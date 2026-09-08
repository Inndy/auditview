#!/usr/bin/env python3
"""Test the RECOMMENDED path: tsserver-family server + @vue/typescript-plugin.

The Vue language server advertises definitionProvider/referencesProvider but
only CSS and JSON stand behind them -- TS-level definition/references for a
.vue file are served by vtsls/ts_ls with @vue/typescript-plugin loaded, as a
server in its own right. No tsserver/request relay involved.
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lspspike import Client, CLIENT_CAPS, uri, summarize_locations

HERE = Path(__file__).parent
ROOT = Path(os.environ.get("SPIKE_ROOT") or HERE / "fixtures" / "fixture-vue")

# Both tools are expected on PATH (or overridden), matching how auditview itself
# locates language servers. VUE_LS must be the *real* directory of the
# @vue/language-server package -- under pnpm the node_modules entry is a symlink
# into .pnpm/, and the tsserver plugin loader needs the resolved path.
VTSLS = os.environ.get("VTSLS_BIN") or shutil.which("vtsls") or "vtsls"
_vue_ls_env = os.environ.get("VUE_LS_DIR")
VUE_LS = Path(_vue_ls_env).resolve() if _vue_ls_env else Path("@vue/language-server")

VUE_PLUGIN = {
    "name": "@vue/typescript-plugin",
    "location": str(VUE_LS),
    "languages": ["vue"],
    "configNamespace": "typescript",
}
_TSSERVER = {"globalPlugins": [VUE_PLUGIN], "useSyntaxServer": "never"}
SETTINGS = {
    "vtsls": {"tsserver": _TSSERVER},
    "typescript": {"tsserver": _TSSERVER},
    "javascript": {},
}

# Anchored to content, not line numbers: these files get edited, and a pinned
# line silently starts testing whatever moved into its place.
#   (relpath, substring identifying the line, symbol to point at, label)
_FIXTURE_QUERIES = [
    ("src/Counter.vue", "{{ count }}", "count", "template `count` -> script decl"),
    ("src/Counter.vue", '@click="increment"', "increment", "template `increment` -> script fn"),
    ("src/Counter.vue", "const count = ref(0)", "count", "script `count` decl -> refs incl. template"),
]
_UI_QUERIES = [
    ("src/components/LineRow.vue", "import LineGutter from", "LineGutter", "import of a .vue component"),
    ("src/components/CodeViewer.vue", "import { getFile }", "getFile", "import of a named JS export"),
    ("src/components/LineRow.vue", '@mousedown.prevent="onMouseDown"', "onMouseDown", "template -> Options API methods"),
]
# SPIKE_QUERIES=ui uses the known-good positions for this repo's ui/ directory;
# otherwise the bundled fixture's own set is used.
QUERIES = _UI_QUERIES if os.environ.get("SPIKE_QUERIES") == "ui" else _FIXTURE_QUERIES

def locate(path, needle, symbol):
    """1-based (line, col) of `symbol` on the first line containing `needle`."""
    for i, text in enumerate(path.read_text().splitlines(), start=1):
        if needle in text:
            col = text.index(symbol, text.index(needle)) + 1
            return i, col
    return None


caps = json.loads(json.dumps(CLIENT_CAPS))
caps["textDocument"]["definition"].pop("linkSupport", None)  # plain Location[]

def main():
    argv = [VTSLS, "--stdio"]
    print("=== vtsls + @vue/typescript-plugin ===")
    print(f"vtsls           = {VTSLS}")
    print(f"plugin location = {VUE_LS}")
    if not VUE_LS.is_dir():
        sys.exit(
            "VUE_LS_DIR must point at the real @vue/language-server directory.\n"
            "  pnpm add vtsls typescript@5 @vue/language-server   # in a tools dir\n"
            "  export VUE_LS_DIR=$(readlink -f node_modules/@vue/language-server)"
        )
    print(f"root            = {ROOT}")
    c = Client(argv, cwd=str(ROOT))
    c.settings = SETTINGS
    t0 = time.time()
    r = c.request("initialize", {
        "processId": os.getpid(),
        "rootUri": uri(ROOT),
        "workspaceFolders": [{"uri": uri(ROOT), "name": "fixture"}],
        "capabilities": caps,
        "initializationOptions": {"plugins": [VUE_PLUGIN], **SETTINGS},
    }, timeout=90)
    if "error" in r:
        print(f"INITIALIZE FAILED: {r['error']}")
        return
    sc = r["result"]["capabilities"]
    print(f"serverInfo: {r['result'].get('serverInfo')}  ({time.time()-t0:.1f}s)")
    for k in ("definitionProvider", "referencesProvider", "documentSymbolProvider"):
        print(f"  {k}: {bool(sc.get(k))}")
    c.notify("initialized", {})
    c.notify("workspace/didChangeConfiguration", {"settings": SETTINGS})

    # languageId MUST be "vue" here, and the plugin entry MUST carry
    # languages: ["vue"] -- set one without the other and every query is empty.
    for p in {q[0] for q in QUERIES}:
        f = ROOT / p
        c.notify("textDocument/didOpen", {"textDocument": {
            "uri": uri(f), "languageId": "vue" if f.suffix == ".vue" else "javascript",
            "version": 1, "text": f.read_text()}})
    time.sleep(6)

    for rel, needle, symbol, label in QUERIES:
        target = ROOT / rel
        found = locate(target, needle, symbol)
        if found is None:
            print(f"\n--- {label}  ({rel}) --- SKIP: {needle!r} not found")
            continue
        line, col = found
        tdoc = {"uri": uri(target)}
        print(f"\n--- {label}  ({rel} {line}:{col}) ---")
        print(f"  source: {target.read_text().splitlines()[line-1].strip()!r}")
        pos = {"line": line - 1, "character": col - 1}
        d = c.request("textDocument/definition",
                      {"textDocument": tdoc, "position": pos}, timeout=45)
        print("  definition:" if "error" not in d else f"  definition ERROR: {d['error']}")
        if "error" not in d:
            for l in summarize_locations(d.get("result"), ROOT):
                print(l)
        rf = c.request("textDocument/references", {
            "textDocument": tdoc, "position": pos,
            "context": {"includeDeclaration": True}}, timeout=45)
        if "error" in rf:
            print(f"  references ERROR: {rf['error']}")
        else:
            res = rf.get("result")
            print(f"  references: {len(res) if isinstance(res, list) else res}")
            for l in summarize_locations(res, ROOT):
                print(l)

    ds = c.request("textDocument/documentSymbol",
                   {"textDocument": {"uri": uri(ROOT / QUERIES[0][0])}})
    syms = ds.get("result") or [] if "error" not in ds else []
    print(f"\ndocumentSymbol: {len(syms)} -> {[s.get('name') for s in syms][:10]}")
    print(f"server->client requests: {sorted(set(c._inbound))}")
    c.proc.terminate()

if __name__ == "__main__":
    main()
