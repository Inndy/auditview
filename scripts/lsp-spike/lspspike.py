#!/usr/bin/env python3
"""Minimal LSP client spike: can a non-editor client get definition/references?

Deliberately ~200 lines and dependency-free, to find out what the real
auditview LspService would have to handle. Nothing here is production code.

Usage:
  lspspike.py --root DIR --file FILE --line N --col N -- CMD [ARGS...]

Positions are 1-based on the command line (as a user sees them) and converted
to LSP's 0-based on the wire.
"""
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path


def uri(path):
    return Path(path).resolve().as_uri()


class Client:
    def __init__(self, argv, cwd=None, env=None, verbose=False):
        self.verbose = verbose
        self.proc = subprocess.Popen(
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, cwd=cwd, env=env,
        )
        self._id = 0
        self._pending = {}          # id -> queue for the response
        self._inbound = []          # server->client requests we answered
        self._notes = []            # server->client notifications
        self._handlers = {}         # method -> callable(params)
        self._lock = threading.Lock()
        threading.Thread(target=self._read_loop, daemon=True).start()
        threading.Thread(target=self._stderr_loop, daemon=True).start()

    # --- framing ---------------------------------------------------------
    def _send(self, msg):
        body = json.dumps(msg).encode()
        self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        self.proc.stdin.flush()
        if self.verbose:
            print(f"  -> {msg.get('method', 'response')}", file=sys.stderr)

    def _read_loop(self):
        f = self.proc.stdout
        while True:
            headers = {}
            while True:
                line = f.readline()
                if not line:
                    return
                line = line.strip()
                if not line:
                    break
                k, _, v = line.decode(errors="replace").partition(":")
                headers[k.lower()] = v.strip()
            n = int(headers.get("content-length", 0))
            if not n:
                continue
            msg = json.loads(f.read(n))
            self._dispatch(msg)

    def _stderr_loop(self):
        for line in self.proc.stderr:
            if self.verbose:
                print(f"  [stderr] {line.decode(errors='replace').rstrip()}",
                      file=sys.stderr)

    def _dispatch(self, msg):
        if "id" in msg and "method" not in msg:          # response to us
            with self._lock:
                q = self._pending.pop(msg["id"], None)
            if q:
                q.put(msg)
            return
        if "id" in msg and "method" in msg:              # REQUEST from server
            # The trap: fail to answer these and the server may never proceed.
            self._inbound.append(msg["method"])
            m = msg["method"]
            if m == "workspace/configuration":
                # Real clients answer per requested section; vtsls needs this
                # to ever see globalPlugins.
                items = msg.get("params", {}).get("items", [{}])
                result = [self._section(i.get("section")) for i in items]
            elif m == "workspace/workspaceFolders":
                result = None
            elif m in ("window/workDoneProgress/create",
                       "client/registerCapability",
                       "client/unregisterCapability"):
                result = None
            else:
                result = None
            self._send({"jsonrpc": "2.0", "id": msg["id"], "result": result})
            return
        method = msg.get("method")                       # notification
        self._notes.append(method)
        h = self._handlers.get(method)
        if h:
            # Run off the reader thread: a handler may itself block on I/O
            # (the tsserver relay does) and must not stall reading.
            threading.Thread(target=h, args=(msg.get("params"),),
                             daemon=True).start()

    # --- rpc -------------------------------------------------------------
    def request(self, method, params, timeout=60):
        with self._lock:
            self._id += 1
            rid = self._id
            q = queue.Queue()
            self._pending[rid] = q
        self._send({"jsonrpc": "2.0", "id": rid, "method": method,
                    "params": params})
        try:
            msg = q.get(timeout=timeout)
        except queue.Empty:
            return {"error": {"message": f"TIMEOUT after {timeout}s"}}
        return msg

    def _section(self, section):
        node = getattr(self, "settings", None) or {}
        if not section:
            return node
        for part in section.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def on_notification(self, method, fn):
        self._handlers[method] = fn

    def notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})


CLIENT_CAPS = {
    "general": {"positionEncodings": ["utf-16"]},
    "workspace": {
        "workspaceFolders": True,
        "configuration": True,
        "symbol": {"dynamicRegistration": False},
    },
    "textDocument": {
        "synchronization": {"dynamicRegistration": False, "didSave": False},
        "definition": {"dynamicRegistration": False, "linkSupport": True},
        "references": {"dynamicRegistration": False},
        "documentSymbol": {
            "dynamicRegistration": False,
            "hierarchicalDocumentSymbolSupport": True,
        },
        "hover": {"contentFormat": ["plaintext"]},
    },
}


def summarize_locations(result, root):
    """Report each location's URI, flagging out-of-root and non-file URIs."""
    if result is None:
        return ["(null)"]
    if isinstance(result, dict):
        result = [result]
    out = []
    root = str(Path(root).resolve())
    for loc in result:
        u = loc.get("uri") or loc.get("targetUri") or "?"
        rng = loc.get("range") or loc.get("targetSelectionRange") or {}
        line = rng.get("start", {}).get("line")
        tag = "file" if u.startswith("file://") else "NON-FILE"
        if u.startswith("file://"):
            p = u[len("file://"):]
            tag = "in-root" if p.startswith(root) else "OUT-OF-ROOT"
            if ".vue.ts" in p or "volar" in p:
                tag = "VIRTUAL?"
        out.append(f"    [{tag}] {u} :{(line + 1) if line is not None else '?'}")
    return out or ["    (empty list)"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--line", type=int, default=1)
    ap.add_argument("--col", type=int, default=1)
    ap.add_argument("--init-options", default=None,
                    help="JSON for initializationOptions")
    ap.add_argument("--also-open", action="append", default=[],
                    help="extra file to didOpen before querying")
    ap.add_argument("--settings", default=None,
                    help="JSON answered to workspace/configuration")
    ap.add_argument("--settle", type=float, default=3.0)
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    argv = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    if not argv:
        sys.exit("no server command given")

    init_opts = json.loads(a.init_options) if a.init_options else {}
    langmap = {".vue": "vue", ".ts": "typescript", ".js": "javascript",
               ".go": "go", ".py": "python"}

    print(f"=== {' '.join(argv[:2])} ===")
    print(f"root={a.root}")
    t0 = time.time()
    c = Client(argv, cwd=a.root, verbose=a.verbose)
    if a.settings:
        c.settings = json.loads(a.settings)

    r = c.request("initialize", {
        "processId": os.getpid(),
        "rootUri": uri(a.root),
        "rootPath": str(Path(a.root).resolve()),
        "workspaceFolders": [{"uri": uri(a.root), "name": "root"}],
        "capabilities": CLIENT_CAPS,
        "initializationOptions": init_opts,
    }, timeout=90)
    if "error" in r:
        print(f"  INITIALIZE FAILED: {r['error']}")
        print(f"  stderr tail: {c.proc.stderr.read(2000)[:2000]!r}"
              if c.proc.poll() is not None else "")
        return
    caps = r.get("result", {}).get("capabilities", {})
    info = r.get("result", {}).get("serverInfo", {})
    print(f"  serverInfo: {info}")
    print(f"  init took {time.time() - t0:.1f}s")
    for k in ("positionEncoding",):
        print(f"  {k}: {caps.get(k, '(absent -> utf-16 default)')}")
    for k in ("definitionProvider", "referencesProvider",
              "documentSymbolProvider", "semanticTokensProvider",
              "hoverProvider"):
        v = caps.get(k)
        print(f"  {k}: {'yes' if v else repr(v)}"
              + (" (options)" if isinstance(v, dict) else ""))

    c.notify("initialized", {})
    c.notify("workspace/didChangeConfiguration",
             {"settings": getattr(c, "settings", {})})

    for extra in a.also_open:
        p = Path(a.root) / extra if not os.path.isabs(extra) else Path(extra)
        c.notify("textDocument/didOpen", {"textDocument": {
            "uri": uri(p), "languageId": langmap.get(p.suffix, "plaintext"),
            "version": 1, "text": p.read_text()}})

    target = Path(a.root) / a.file if not os.path.isabs(a.file) else Path(a.file)
    text = target.read_text()
    c.notify("textDocument/didOpen", {"textDocument": {
        "uri": uri(target), "languageId": langmap.get(target.suffix, "plaintext"),
        "version": 1, "text": text}})

    time.sleep(a.settle)  # crude stand-in for real indexing readiness
    tdoc = {"uri": uri(target)}
    pos = {"line": a.line - 1, "character": a.col - 1}
    src_line = text.splitlines()[a.line - 1] if a.line - 1 < len(text.splitlines()) else ""
    print(f"  query at {a.line}:{a.col} -> {src_line.strip()[:70]!r}")

    ds = c.request("textDocument/documentSymbol", {"textDocument": tdoc})
    if "error" in ds:
        print(f"  documentSymbol: ERROR {ds['error']}")
    else:
        syms = ds.get("result") or []
        names = [s.get("name") for s in syms][:12]
        print(f"  documentSymbol: {len(syms)} top-level {names}")

    for method in ("textDocument/definition", "textDocument/typeDefinition"):
        r = c.request(method, {"textDocument": tdoc, "position": pos})
        if "error" in r:
            print(f"  {method.split('/')[1]}: ERROR {r['error']}")
        else:
            print(f"  {method.split('/')[1]}:")
            for l in summarize_locations(r.get("result"), a.root):
                print(l)

    r = c.request("textDocument/references", {
        "textDocument": tdoc, "position": pos,
        "context": {"includeDeclaration": True}})
    if "error" in r:
        print(f"  references: ERROR {r['error']}")
    else:
        res = r.get("result")
        print(f"  references: {len(res) if isinstance(res, list) else res}")
        for l in summarize_locations(res, a.root):
            print(l)

    print(f"  server->client requests seen: {sorted(set(c._inbound)) or 'none'}")
    print(f"  total {time.time() - t0:.1f}s")
    c.request("shutdown", {}, timeout=5)
    c.notify("exit", {})
    c.proc.terminate()


if __name__ == "__main__":
    main()
