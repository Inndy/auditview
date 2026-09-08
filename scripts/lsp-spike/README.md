# LSP spike

Throwaway-quality but **empirically validated** LSP clients, kept because they
are the reference implementation for `auditview/core/lsp.py` and the only record
of a working `.vue` configuration. Nothing here is imported by the application.

- `lspspike.py` — a generic, dependency-free LSP client. Spawns any server,
  performs the handshake, `didOpen`s a file, and reports `documentSymbol`,
  `definition`, `typeDefinition` and `references`, tagging each result location
  as in-root / out-of-root / non-file.
- `vtslsspike.py` — the validated `.vue` path: `vtsls` with
  `@vue/typescript-plugin` loaded, driven through `workspace/configuration`.

## Running

```bash
# generic: any server, any position (1-based line/col, as a user sees them)
python3 scripts/lsp-spike/lspspike.py \
  --root . --file auditview/api/files.py --line 458 --col 21 --settle 20 \
  -- basedpyright-langserver --stdio

python3 scripts/lsp-spike/lspspike.py \
  --root scripts/lsp-spike/fixtures/fixture-go --file main.go --line 9 --col 7 \
  -- gopls -mode=stdio
```

For the Vue path, install the trio into any tools directory and point the script
at it. **`typescript` must be 5.x** (see below), and `VUE_LS_DIR` must be the
*resolved* package directory — under pnpm the `node_modules` entry is a symlink
into `.pnpm/`, and the tsserver plugin loader needs the real path.

```bash
mkdir -p ~/tools/lsp && cd ~/tools/lsp
pnpm add vtsls typescript@5 @vue/language-server
export PATH="$PWD/node_modules/.bin:$PATH"
export VUE_LS_DIR=$(readlink -f node_modules/@vue/language-server)
```

`vtsls` resolves `typescript` from **its own** install location, so a plain-JS
project needs no TypeScript dependency of its own.

Then either target this repo's UI, which is the more useful check because its
`node_modules` is already populated:

```bash
cd /path/to/auditview
SPIKE_ROOT=./ui SPIKE_QUERIES=ui python3 scripts/lsp-spike/vtslsspike.py
```

…or the bundled fixture, which **needs its own `vue` installed first**:

```bash
cd scripts/lsp-spike/fixtures/fixture-vue && pnpm add vue && cd -
python3 scripts/lsp-spike/vtslsspike.py
```

Without that install, `import { ref } from 'vue'` does not resolve, the script
half of the SFC cannot be checked, and every *template* position silently returns
an empty list while script positions still work — a compact demonstration of how
this toolchain fails: quietly and partially, never with an error.

## Known-good positions

All were observed, not inferred. `vtslsspike.py` finds these by **searching for
the line content** rather than by line number, because these files get edited and
a pinned line quietly starts testing whatever moved into its place — which is
exactly what happened once during development.

| Root | Symbol, on the line containing… | Expected target |
|---|---|---|
| `ui/` | `LineGutter` in `import LineGutter from './LineGutter.vue'` | `LineGutter.vue:1` |
| `ui/` | `getFile` in `import { getFile } from '../api/files.js'` | `api/files.js:15` |
| `ui/` | `onMouseDown` in `@mousedown.prevent="onMouseDown"` | `LineRow.vue:51` (Options API template→methods) |
| repo root | `safe_path` in `full_path = safe_path(root_path, fpath)` | `auditview/api/util.py:4` |
| `fixtures/fixture-go` | `makeHandler` in `h := makeHandler("hello")` | `handler.go:5` |

The `lspspike.py` examples above still take explicit `--line/--col`; only the Vue
script self-locates.

## What the spike established

**`.vue` definition/references come from `vtsls` + `@vue/typescript-plugin`, not
from `@vue/language-server`.** Volar registers only the `docCommentTemplate` and
`syntactic` TypeScript plugins; the semantic one that implements
`provideDefinition`/`provideReferences` is not registered. Only CSS and JSON
stand behind the `definitionProvider: true` it advertises — **the capability
handshake lies for `.vue`**, so a client that routes by capability gets `[]`
forever with no warning.

**Do not run `@vue/language-server` for this.** Since 3.0 its hybrid mode is
mandatory and the bridge is the client's job: it sends a `tsserver/request`
notification and awaits `tsserver/response` on a promise with **no timeout**,
immune to `$/cancelRequest`. A client that ignores it hangs on *every* request —
observed: four queries, all timing out at 45s, `documentSymbol` included. It is
not a degradation, it is a deadlock. Running only `vtsls` removes the bridge, the
hang class, and the two-server startup ordering problem.

**TypeScript 7 cannot serve `.vue`.** TS 7 (`typescript@7.x`, the Go port) ships
its own LSP server — `<native>/lib/tsc --lsp --stdio`, `serverInfo:
typescript-go` — which is excellent for plain `.ts`/`.js` and is the only server
observed to declare `positionEncoding` explicitly. But it has no plugin mechanism
at all (no `globalPlugins`/`pluginProbeLocations`/`allowLocalPluginLoads` strings
exist in the binary) and dies on a `.vue` file with
`panic: ScriptKind must be specified when parsing source file`. Volar 3.3.11 is
also incompatible with it (`ts.server.protocol` is undefined under TS 7). Pin
typescript 5.x wherever `.vue` is involved.

**The first query after spawn is answered wrongly unless the syntax server is
disabled.** vtsls runs *two* tsserver instances -- `<syntax>` and `<semantic>`
(visible in `window/logMessage` at startup) -- and there is **no readiness
signal**: no `$/progress`, no `workDoneProgress`, only log text. The syntax
server answers immediately and syntactically, so a `definition` issued right
after `didOpen` comes back pointing at the *import specifier's own position*
instead of the target. Measured on `ui/src/components/LineRow.vue` 29:8:

| | first query | later queries |
|---|---|---|
| default | 0.44s, **wrong** (`LineRow.vue:29`) | 0.01s, correct |
| `useSyntaxServer: "never"` | 1.14s, correct | 0.00s, correct |

So set `typescript.tsserver.useSyntaxServer` (and the `vtsls` mirror) to
`"never"`. It trades ~0.7s on the first query for an answer that is right, and
it is a root-cause fix rather than a sleep or a retry. This was the single most
dangerous behaviour found: not an empty result, a confident wrong one.

**Two config keys are load-bearing and fail silently.** The plugin entry needs
`languages: ["vue"]` *and* the `didOpen` must use `languageId: "vue"`. Set one
without the other and every query returns an empty list.

**Servers send requests to the client.** All of `gopls`, `basedpyright`, `vtsls`
and TS 7 native issue `workspace/configuration`; TS 7 native also issues
`client/registerCapability`. `vtsls` only ever learns about the Vue plugin
through the client's `workspace/configuration` reply, so answering it per
requested `section` is mandatory, not optional.

## Result hygiene the caller must apply

Straight from observed output:

- **URIs are percent-encoded** — `typescript%405.9.3` for `typescript@5.9.3`.
  URL-decode before any path containment check.
- **Duplicates occur** — the Options API case returned the same location twice.
  Dedupe by `(uri, range)`.
- **Stdlib noise** — `definition` on an `async` function was observed returning
  the real `api/files.js:15` *plus five* hits inside TypeScript's own
  `lib.es*.d.ts`. It does not happen on every run (it depends on how the
  project's TypeScript gets resolved), which is precisely why the caller must
  handle it rather than assume a single result: rank in-root first and treat the
  rest as preview material.
- **Stale in-tree copies** — `basedpyright` on this repo returned 15 references
  for `safe_path`, six of them in `build/lib/auditview/...`. Filter through the
  session's `is_excluded()`.
- **`documentSymbol` returns 0 for `.vue`** — no outline is available for Vue
  files from `vtsls`.
- **`positionEncoding` is UTF-16.** JavaScript string offsets *are* UTF-16 code
  units, so a column computed in the browser is already correct. Never convert
  it to a byte offset.
