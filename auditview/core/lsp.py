"""LSP client: one language-server subprocess per (server, resolved root).

auditview never edits files, which removes the hardest part of being an LSP
client: there is no incremental sync, no version vector, no dirty-buffer
reconciliation. `didOpen` with the content on disk is the whole document story.

Positions on this module's public surface are LSP-native: 0-based line, 0-based
`character` in **UTF-16 code units**. Every server observed either declares
`positionEncoding: utf-16` or omits it (which means the same), and a column
computed in a browser from a DOM text node is already in those units -- so it is
passed straight through and must never be converted to a byte offset. The API
layer converts auditview's 1-based line numbers at its boundary.

See `scripts/lsp-spike/README.md` for the empirical findings this encodes.
"""

import asyncio
import json
import logging
import os
import shutil
import time
from urllib.parse import unquote, urlparse

from pathspec import PathSpec

logger = logging.getLogger("auditview")

_INIT_TIMEOUT = 90.0
_REQUEST_TIMEOUT = 30.0
_IDLE_TTL = 600.0
_REAP_INTERVAL = 60.0
# Bounded so a long session cannot grow it without limit; only paths the servers
# actually returned are ever previewable.
_PREVIEW_MAX = 1024

# Vue's TS semantics come from vtsls with @vue/typescript-plugin loaded, NOT from
# @vue/language-server -- which advertises definitionProvider: true and cannot
# answer it for script or template positions. Running it would also require
# implementing its tsserver/request bridge, whose promise has no timeout and
# deadlocks every request if unanswered. See the spike README.
DEFAULT_SERVERS = (
    {
        "name": "vtsls",
        "cmd": ["vtsls", "--stdio"],
        "match": ["**/*.vue", "**/*.js", "**/*.jsx", "**/*.mjs", "**/*.cjs",
                  "**/*.ts", "**/*.tsx"],
        "roots": ["jsconfig.json", "tsconfig.json", "package.json"],
        "language_ids": {".vue": "vue"},
    },
    {
        "name": "basedpyright",
        "cmd": ["basedpyright-langserver", "--stdio"],
        "match": ["**/*.py", "**/*.pyi"],
        "roots": ["pyproject.toml", "setup.py", "setup.cfg"],
        "language_ids": {},
    },
    {
        "name": "gopls",
        "cmd": ["gopls", "-mode=stdio"],
        "match": ["**/*.go"],
        "roots": ["go.work", "go.mod"],
        # An audited tree is not trusted: do not let analysis mutate go.mod or
        # reach the network to fetch modules.
        "env": {"GOFLAGS": "-mod=readonly", "GOPROXY": "off"},
        "language_ids": {},
    },
)

_LANGUAGE_IDS = {
    ".js": "javascript", ".jsx": "javascriptreact", ".mjs": "javascript",
    ".cjs": "javascript", ".ts": "typescript", ".tsx": "typescriptreact",
    ".vue": "vue", ".py": "python", ".go": "go",
}

CLIENT_CAPABILITIES = {
    "general": {"positionEncodings": ["utf-16"]},
    "workspace": {
        "workspaceFolders": True,
        # Declared because vtsls only ever learns about the Vue plugin through
        # our workspace/configuration reply. Declaring it obliges us to answer
        # it -- an unanswered request is another way to hang a server.
        "configuration": True,
    },
    "textDocument": {
        "synchronization": {"dynamicRegistration": False, "didSave": False},
        # linkSupport is deliberately NOT declared: plain Location[] is simpler
        # and the server-side downgrade is lossless for our purposes.
        "definition": {"dynamicRegistration": False},
        "documentSymbol": {"dynamicRegistration": False},
    },
}


def path_to_uri(path):
    from pathlib import Path
    return Path(path).as_uri()


def uri_to_path(uri):
    """Convert a file: URI to a filesystem path, undoing percent-encoding.

    Servers return percent-encoded URIs (`typescript%405.9.3` was observed for a
    `typescript@5.9.3` directory). Skipping the unquote makes every downstream
    containment check silently compare the wrong string.
    """
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return None
    return unquote(parsed.path)


def language_id_for(path, overrides=None):
    ext = os.path.splitext(path)[1].lower()
    if overrides and ext in overrides:
        return overrides[ext]
    return _LANGUAGE_IDS.get(ext, "plaintext")


def discover_vue_plugin(cmd_path):
    """Locate the @vue/language-server directory that holds @vue/typescript-plugin.

    `location` must be the *resolved* directory: under pnpm the node_modules
    entry is a symlink into .pnpm/ and the tsserver plugin loader needs the real
    path. Explicit env var wins; otherwise look in the node_modules that the
    vtsls binary itself lives in, which is the layout the README documents.
    """
    env = os.environ.get("AUDITVIEW_VUE_LS_DIR")
    if env and os.path.isdir(env):
        return os.path.realpath(env)
    if not cmd_path:
        return None
    # .../node_modules/.bin/vtsls -> .../node_modules/@vue/language-server
    node_modules = os.path.dirname(os.path.dirname(os.path.abspath(cmd_path)))
    candidate = os.path.join(node_modules, "@vue", "language-server")
    if os.path.isdir(candidate):
        return os.path.realpath(candidate)
    return None


def resolve_root(abs_file, session_root, markers):
    """Nearest ancestor of abs_file containing a root marker, bounded by session_root.

    Keyed per (server, root) rather than per extension because a Vue project's
    .js and .vue files share one jsconfig.json -- splitting them by glob would
    hand the two halves inconsistent type views.
    """
    session_root = os.path.realpath(session_root)
    cur = os.path.dirname(os.path.realpath(abs_file))
    best = session_root
    while True:
        if any(os.path.exists(os.path.join(cur, m)) for m in markers):
            best = cur
            break
        if cur == session_root or len(cur) <= len(session_root):
            break
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return best


class _Server:
    """One language-server subprocess, plus the JSON-RPC plumbing around it."""

    def __init__(self, spec, root, settings=None, init_options=None):
        self.spec = spec
        self.name = spec["name"]
        self.root = root
        self.settings = settings or {}
        self.init_options = init_options or spec.get("init_options") or {}
        self.state = "spawning"
        self.detail = None
        self.capabilities = {}
        self.proc = None
        self.last_used = time.monotonic()
        self._id = 0
        self._pending = {}
        self._reader = None
        self._stderr_reader = None
        self._opened = {}          # uri -> mtime we opened it with
        self._start_lock = asyncio.Lock()

    # --- framing ---------------------------------------------------------
    def _write(self, msg):
        if self.proc is None or self.proc.stdin is None:
            return
        body = json.dumps(msg).encode()
        try:
            self.proc.stdin.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
        except (BrokenPipeError, ConnectionResetError):
            self.state = "crashed"
            self.detail = "stdin closed"

    async def _read_loop(self):
        stdout = self.proc.stdout
        while True:
            headers = {}
            while True:
                line = await stdout.readline()
                if not line:
                    self._fail_pending("server exited")
                    return
                line = line.strip()
                if not line:
                    break
                key, _, value = line.decode("utf-8", "replace").partition(":")
                headers[key.lower()] = value.strip()
            try:
                length = int(headers.get("content-length", 0))
            except ValueError:
                continue
            if not length:
                continue
            try:
                payload = await stdout.readexactly(length)
            except asyncio.IncompleteReadError:
                self._fail_pending("server exited mid-message")
                return
            try:
                self._dispatch(json.loads(payload))
            except Exception:
                logger.exception("lsp: %s: failed to dispatch message", self.name)

    async def _drain_stderr(self):
        while True:
            line = await self.proc.stderr.readline()
            if not line:
                return
            logger.debug("lsp: %s: %s", self.name,
                         line.decode("utf-8", "replace").rstrip())

    def _fail_pending(self, reason):
        if self.state != "stopped":
            self.state = "crashed"
            self.detail = reason
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(LspError(f"{self.name}: {reason}"))
        self._pending.clear()

    def _dispatch(self, msg):
        if "id" in msg and "method" not in msg:
            fut = self._pending.pop(msg["id"], None)
            if fut is not None and not fut.done():
                fut.set_result(msg)
            return
        if "id" in msg and "method" in msg:
            self._answer(msg)
            return
        # Notifications (diagnostics, progress, logs) are not used by phase 1.

    def _answer(self, msg):
        """Answer a server->client request.

        Not optional. Every server observed issues workspace/configuration, and
        vtsls only learns about the Vue plugin from the reply.
        """
        method = msg.get("method")
        if method == "workspace/configuration":
            items = (msg.get("params") or {}).get("items") or [{}]
            result = [self._section(i.get("section")) for i in items]
        elif method == "workspace/workspaceFolders":
            result = [{"uri": path_to_uri(self.root), "name": os.path.basename(self.root)}]
        else:
            # registerCapability, workDoneProgress/create, and anything else we
            # do not model: acknowledge so the server proceeds.
            result = None
        self._write({"jsonrpc": "2.0", "id": msg["id"], "result": result})

    def _section(self, section):
        node = self.settings
        if not section:
            return node
        for part in section.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    # --- rpc -------------------------------------------------------------
    async def request(self, method, params, timeout=_REQUEST_TIMEOUT):
        if self.proc is None or self.proc.returncode is not None:
            raise LspError(f"{self.name}: not running")
        self._id += 1
        rid = self._id
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        try:
            msg = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            raise LspError(f"{self.name}: {method} timed out after {timeout:.0f}s")
        if "error" in msg:
            raise LspError(f"{self.name}: {msg['error'].get('message', 'error')}")
        return msg.get("result")

    def notify(self, method, params):
        self._write({"jsonrpc": "2.0", "method": method, "params": params})

    # --- lifecycle -------------------------------------------------------
    async def ensure_started(self):
        async with self._start_lock:
            if self.state == "ready":
                return
            if self.state == "crashed":
                raise LspError(f"{self.name}: {self.detail or 'crashed'}")
            await self._start()

    async def _start(self):
        cmd = list(self.spec["cmd"])
        env = dict(os.environ)
        env.update(self.spec.get("env") or {})
        self.state = "warming"
        try:
            self.proc = await asyncio.create_subprocess_exec(
                *cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=self.root, env=env,
            )
        except (FileNotFoundError, PermissionError) as exc:
            self.state = "missing"
            self.detail = str(exc)
            raise LspError(f"{self.name}: {exc}") from exc

        self._reader = asyncio.create_task(self._read_loop())
        self._stderr_reader = asyncio.create_task(self._drain_stderr())

        root_uri = path_to_uri(self.root)
        result = await self.request("initialize", {
            "processId": os.getpid(),
            "rootUri": root_uri,
            "workspaceFolders": [{"uri": root_uri, "name": os.path.basename(self.root)}],
            "capabilities": CLIENT_CAPABILITIES,
            "initializationOptions": self.init_options,
        }, timeout=_INIT_TIMEOUT)
        self.capabilities = (result or {}).get("capabilities") or {}
        self.notify("initialized", {})
        self.notify("workspace/didChangeConfiguration", {"settings": self.settings})
        self.state = "ready"
        logger.info("lsp: %s ready at %s", self.name, self.root)

    async def stop(self):
        self.state = "stopped"
        if self.proc is None:
            return
        try:
            if self.proc.returncode is None:
                await asyncio.wait_for(self.request("shutdown", {}, timeout=2.0), 2.5)
                self.notify("exit", {})
        except (LspError, asyncio.TimeoutError, asyncio.CancelledError):
            pass
        for task in (self._reader, self._stderr_reader):
            if task is not None:
                task.cancel()
        try:
            if self.proc.returncode is None:
                self.proc.terminate()
                await asyncio.wait_for(self.proc.wait(), 3.0)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass

    # --- documents -------------------------------------------------------
    async def sync_document(self, abs_path):
        """didOpen the file, or re-open it if it changed on disk since we did.

        Cheap because auditview is read-only: the document is always exactly the
        bytes on disk, so there is nothing to reconcile -- only to refresh.
        """
        uri = path_to_uri(abs_path)
        try:
            mtime = os.path.getmtime(abs_path)
        except OSError as exc:
            raise LspError(f"could not stat {abs_path}") from exc
        known = self._opened.get(uri)
        if known == mtime:
            return uri
        text = await asyncio.to_thread(_read_text, abs_path)
        if known is not None:
            self.notify("textDocument/didClose", {"textDocument": {"uri": uri}})
        self.notify("textDocument/didOpen", {"textDocument": {
            "uri": uri,
            "languageId": language_id_for(abs_path, self.spec.get("language_ids")),
            "version": 1,
            "text": text,
        }})
        self._opened[uri] = mtime
        return uri


def _read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


class LspError(Exception):
    """A language server was unreachable, too slow, or returned an error."""


class LspService:
    """Owns the language-server subprocesses for one served tree.

    Lifecycle mirrors WatcherService: constructed inert, `start(loop)` binds the
    running loop, `run_worker()` is the single long-lived task, `stop()` tears
    down. Unlike the watcher there is no foreign thread -- a subprocess is
    already asyncio-native -- so there is no lock to hold.

    Holds no database connection and issues no queries; the coverage join and
    all path policy live in the API layer.
    """

    def __init__(self, root_path, servers=None):
        self._root_path = root_path
        self._specs = [dict(s) for s in (servers or DEFAULT_SERVERS)]
        self._matchers = {
            s["name"]: PathSpec.from_lines("gitwildmatch", s["match"])
            for s in self._specs
        }
        self._servers = {}          # (name, root) -> _Server
        self._previewable = {}      # session_id -> list[str] (bounded, ordered)
        self._loop = None

    # --- lifecycle -------------------------------------------------------
    def start(self, loop):
        self._loop = loop

    async def run_worker(self):
        """Reap servers idle past the TTL. Never lets an exception escape."""
        while True:
            try:
                await asyncio.sleep(_REAP_INTERVAL)
                await self._reap_idle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("lsp: reaper iteration failed")

    async def _reap_idle(self):
        now = time.monotonic()
        for key, server in list(self._servers.items()):
            if now - server.last_used < _IDLE_TTL:
                continue
            self._servers.pop(key, None)
            logger.info("lsp: reaping idle %s at %s", server.name, server.root)
            await server.stop()

    async def aclose(self):
        """The only teardown path -- `after_serving` is async, so there is no
        need for the sync `stop()` the watcher has, and two paths would just be
        a way to leak subprocesses."""
        servers = list(self._servers.values())
        self._servers.clear()
        for server in servers:
            try:
                await server.stop()
            except Exception:
                logger.exception("lsp: failed to stop %s", server.name)

    # --- routing ---------------------------------------------------------
    def spec_for(self, rel_path):
        for spec in self._specs:
            if self._matchers[spec["name"]].match_file(rel_path):
                return spec
        return None

    def _configure(self, spec):
        """Build (settings, initializationOptions) for a server spec.

        The plugin has to go in BOTH: vtsls spawns its tsserver during
        initialize with the global plugins baked in, so a plugin that only
        arrives later on workspace/configuration is too late -- observed as
        definition returning the query position itself instead of the target.
        """
        if spec["name"] != "vtsls":
            return {}, {}
        cmd_path = shutil.which(spec["cmd"][0])
        plugin_dir = discover_vue_plugin(cmd_path)
        if plugin_dir is None:
            # .js/.ts still work; .vue will return nothing. Say so once, loudly,
            # rather than letting it look like a bug in the feature.
            logger.warning(
                "lsp: @vue/language-server not found next to %s -- .vue files will "
                "return no results. Set AUDITVIEW_VUE_LS_DIR to its real path.",
                cmd_path or spec["cmd"][0])
            return {}, {}
        # Both keys are load-bearing: languages:["vue"] here AND languageId
        # "vue" on didOpen. Either one alone yields silently empty results.
        plugin = {
            "name": "@vue/typescript-plugin",
            "location": plugin_dir,
            "languages": ["vue"],
            "configNamespace": "typescript",
        }
        # useSyntaxServer "never": vtsls otherwise runs a fast syntax-only
        # tsserver alongside the semantic one, and it answers the first
        # definition request before the project has loaded -- with the import
        # specifier's own position rather than the target. A wrong answer, not
        # an empty one. Forcing all requests to the semantic server trades a
        # slower first query for a correct one.
        tsserver = {"globalPlugins": [plugin], "useSyntaxServer": "never"}
        settings = {
            "vtsls": {"tsserver": tsserver},
            "typescript": {"tsserver": tsserver},
            "javascript": {},
        }
        return settings, {"plugins": [plugin], **settings}

    async def _server_for(self, spec, session_root, abs_path):
        root = resolve_root(abs_path, session_root, spec["roots"])
        key = (spec["name"], root)
        server = self._servers.get(key)
        if server is not None and server.state == "crashed":
            self._servers.pop(key, None)
            server = None
        if server is None:
            settings, init_options = self._configure(spec)
            server = _Server(spec, root, settings, init_options)
            self._servers[key] = server
        await server.ensure_started()
        server.last_used = time.monotonic()
        return server

    # --- features --------------------------------------------------------
    async def definition(self, session_root, rel_path, line, character):
        """Raw `textDocument/definition` locations, or None if no server matches.

        `line` and `character` are LSP-native (0-based). Returns a list of
        `{"uri": str, "line": int, "character": int}` with no filtering applied
        -- ranking, de-duplication and path policy belong to the caller.
        """
        spec = self.spec_for(rel_path)
        if spec is None:
            return None
        abs_path = os.path.join(session_root, rel_path)
        server = await self._server_for(spec, session_root, abs_path)
        uri = await server.sync_document(abs_path)
        result = await server.request("textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })
        return _flatten_locations(result)

    def remember_previewable(self, session_id, paths):
        """Record paths a definition query actually returned.

        The preview endpoint serves only these. auditview ships no
        authentication, so an endpoint that read any absolute path handed to it
        would be an arbitrary-file reader reachable by anyone who can reach the
        port.
        """
        allowed = self._previewable.setdefault(session_id, [])
        for path in paths:
            real = os.path.realpath(path)
            if real in allowed:
                continue
            allowed.append(real)
        if len(allowed) > _PREVIEW_MAX:
            del allowed[: len(allowed) - _PREVIEW_MAX]

    def is_previewable(self, session_id, path):
        return os.path.realpath(path) in self._previewable.get(session_id, [])

    def status(self):
        """One row per configured server, plus any running instances."""
        running = {}
        for (name, root), server in self._servers.items():
            running.setdefault(name, []).append({
                "root": root,
                "state": server.state,
                "detail": server.detail,
                "definition_provider": bool(server.capabilities.get("definitionProvider")),
            })
        rows = []
        for spec in self._specs:
            binary = spec["cmd"][0]
            rows.append({
                "name": spec["name"],
                "command": binary,
                "available": shutil.which(binary) is not None,
                "match": list(spec["match"]),
                "instances": running.get(spec["name"], []),
            })
        return rows


def _flatten_locations(result):
    """Normalise Location | Location[] | LocationLink[] into plain dicts."""
    if result is None:
        return []
    if isinstance(result, dict):
        result = [result]
    out = []
    for item in result:
        if not isinstance(item, dict):
            continue
        uri = item.get("uri") or item.get("targetUri")
        rng = item.get("range") or item.get("targetSelectionRange") or item.get("targetRange")
        if not uri or not isinstance(rng, dict):
            continue
        start = rng.get("start") or {}
        out.append({
            "uri": uri,
            "line": start.get("line", 0),
            "character": start.get("character", 0),
        })
    return out
