# auditview.nvim (v0)

A minimal Lua client for the auditview HTTP API: mark/unmark lines as
reviewed and see file progress without leaving nvim. The auditview server
stays the single source of truth; the web UI sees nvim's marks live via SSE.

## Requirements

- Neovim 0.10+ (for `vim.system`, `vim.fs.normalize`, `vim.json`)
- `curl` on `$PATH`
- A running `auditview` server (default `http://127.0.0.1:5000`)

## Install

**lazy.nvim** (local path, lazy-loaded — only activates when you touch a buffer or run an auditview command):

```lua
{
  dir = "/path/to/auditview-nvim/nvim",
  name = "auditview.nvim",
  event = "BufReadPre",
  cmd = {
    "AuditviewMark", "AuditviewUnmark", "AuditviewProgress",
    "AuditviewRefresh", "AuditviewSessionReset",
    "AuditviewNextUnreviewed", "AuditviewPrevUnreviewed",
  },
  keys = {
    { "<leader>am", mode = { "n", "x" }, desc = "auditview: mark reviewed" },
    { "<leader>au", mode = { "n", "x" }, desc = "auditview: unmark" },
    { "]r", desc = "auditview: next unreviewed chunk" },
    { "[r", desc = "auditview: prev unreviewed chunk" },
  },
  opts = { base_url = "http://127.0.0.1:5000" },
},
```

If you also use nvim-tree, see the [nvim-tree integration](#nvim-tree-integration-optional)
section — declare `dependencies = { "auditview.nvim" }` on the nvim-tree
spec so the integration loads in time.

**Manual**:
```bash
ln -s /path/to/auditview-nvim/nvim ~/.config/nvim/pack/auditview/start/auditview.nvim
```

## Usage

1. Start the server: `uv run auditview /path/to/project` (writes
   `.auditview.db` at the project root).
2. Create a session in the web UI at `http://127.0.0.1:5000`
   (sessions can't be created from nvim yet).
3. Open nvim anywhere inside that project. The plugin walks up from
   cwd looking for `.auditview.db`; if found, it matches the containing
   directory against `session.root_path` from the API. A single match
   is auto-selected silently. Multiple matches prompt via `vim.ui.select`.
4. Open a file. Reviewed lines get a full-line background tint by default
   (set `reviewed_style = "sign"` for a sign-column glyph instead).

If no `.auditview.db` is found above cwd, the plugin stays dormant on
buffer-open (no prompts). Running `:AuditviewMark` or `:AuditviewProgress`
explicitly will still prompt you to pick from all sessions on the server.

### Keymaps (defaults)

| Mode    | Key          | Action                       |
| ------- | ------------ | ---------------------------- |
| Normal  | `<leader>am` | mark current line reviewed   |
| Visual  | `<leader>am` | mark selected lines reviewed |
| Normal  | `<leader>au` | unmark current line          |
| Visual  | `<leader>au` | unmark selected lines        |
| Normal  | `]r`         | jump to next unreviewed chunk |
| Normal  | `[r`         | jump to previous unreviewed chunk |

Disable with `setup({ auto_keymaps = false })` and bind `AuditviewMark` /
`AuditviewUnmark` yourself.

### Commands

| Command                  | Effect                                                |
| ------------------------ | ----------------------------------------------------- |
| `:AuditviewMark`         | mark current line / range (range-aware)               |
| `:AuditviewUnmark`       | unmark current line / range                           |
| `:AuditviewProgress`     | echo `reviewed/countable (NN%)` for current file      |
| `:AuditviewProgress!`    | quickfix list of every file's coverage                |
| `:AuditviewRefresh`      | refetch current buffer's state from the server        |
| `:AuditviewSessionReset` | drop cached session id (next action re-resolves)      |
| `:AuditviewNextUnreviewed` | jump to next unreviewed chunk (accepts a count)     |
| `:AuditviewPrevUnreviewed` | jump to previous unreviewed chunk (accepts a count) |

## Configuration

```lua
require("auditview").setup({
  base_url = "http://127.0.0.1:5000",

  -- reviewed lines: "line" (default, full-line background tint) | "sign"
  -- (sign-column glyph).
  reviewed_style = "line",
  reviewed_sign_text = "▎",                  -- only when reviewed_style == "sign"
  reviewed_hl = "AuditviewReviewed",         -- linked to DiffAdd by default

  auto_keymaps = true,
  keymaps = {
    mark = "<leader>am",
    unmark = "<leader>au",
    next_unreviewed = "]r",
    prev_unreviewed = "[r",
  },
})
```

## Notes

- The plugin caches per-line hashes returned by the server, so it never
  computes SHA-256 itself. The cache is refreshed on `BufReadPost`,
  `BufWritePost`, and after every mark/unmark.
- If you edit a file outside nvim, run `:AuditviewRefresh` (or just
  re-enter the buffer).
- Marking is blocked while a buffer is `modified` — save first so the
  server hashes match what you see.
- Reviewed lines render as a whole-line background tint by default
  (`reviewed_style = "line"`). Set `reviewed_style = "sign"` to use a
  sign-column glyph instead.
- `]r` / `[r` skip past the chunk you're currently inside (gitsigns-style),
  treating blank/comment lines as connective tissue and stopping only at
  reviewed lines or file edges. Accepts a count: `3]r` jumps three chunks.

## nvim-tree integration (optional)

Color file names in the nvim-tree sidebar by review status:

```lua
require("auditview").setup({ base_url = "http://127.0.0.1:5000" })

local AuditviewDecorator = require("auditview.integrations.nvim_tree").setup()

require("nvim-tree").setup({
  renderer = {
    decorators = {
      "Git", "Open", "Hidden", "Modified",
      "Bookmark", "Diagnostics", "Copied",
      AuditviewDecorator,
      "Cut",
    },
  },
})
```

Highlight groups (linked to sensible defaults — override with `:hi`):

| Group                     | Default link | Meaning                |
| ------------------------- | ------------ | ---------------------- |
| `AuditviewTreeReviewed`   | `DiffAdd`    | fully reviewed         |
| `AuditviewTreePartial`    | `DiffChange` | partially reviewed     |
| `AuditviewTreeNotViewed`  | `Comment`    | tracked, no marks yet  |

Refresh is automatic on nvim-tree open and after every mark/unmark from
this plugin. Marks made elsewhere (web UI) won't show until the tree
reopens; run `:lua require("auditview.integrations.nvim_tree").refresh()`
to force a sync.

## Out of scope for v0

- Notes / TODOs / issues
- SSE consumption (no live update when the web UI marks)
- Creating sessions from nvim
