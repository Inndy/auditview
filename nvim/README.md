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
    "AuditviewNote", "AuditviewTodo", "AuditviewNotes",
    "AuditviewNoteShow", "AuditviewNoteDetail", "AuditviewNoteDelete",
    "AuditviewNextUnreviewed", "AuditviewPrevUnreviewed",
  },
  keys = {
    { "<leader>am", mode = { "n", "x" }, desc = "auditview: mark reviewed" },
    { "<leader>au", mode = { "n", "x" }, desc = "auditview: unmark" },
    { "<leader>an", mode = { "n", "x" }, desc = "auditview: add note" },
    { "<leader>at", mode = { "n", "x" }, desc = "auditview: add TODO" },
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
4. Open a file. Reviewed lines get a background tint; note/TODO lines
   get a glyph (`■` / `◆`) in the sign column.

If no `.auditview.db` is found above cwd, the plugin stays dormant on
buffer-open (no prompts). Running `:AuditviewMark` or `:AuditviewProgress`
explicitly will still prompt you to pick from all sessions on the server.

### Keymaps (defaults)

| Mode    | Key          | Action                          |
| ------- | ------------ | ------------------------------- |
| Normal  | `<leader>am` | mark current line reviewed      |
| Visual  | `<leader>am` | mark selected lines reviewed    |
| Normal  | `<leader>au` | unmark current line             |
| Visual  | `<leader>au` | unmark selected lines           |
| Normal  | `<leader>an` | add note on current line        |
| Visual  | `<leader>an` | add note on selected range      |
| Normal  | `<leader>at` | add TODO on current line        |
| Visual  | `<leader>at` | add TODO on selected range      |
| Normal  | `<leader>aN` | show note(s) at cursor (popup)  |
| Normal  | `<leader>ao` | open note detail view (focusable) |
| Normal  | `<leader>aD` | delete note at cursor           |
| Normal  | `<leader>al` | quickfix list notes in buffer   |
| Normal  | `]r`         | jump to next unreviewed chunk   |
| Normal  | `[r`         | jump to previous unreviewed chunk |

Disable with `setup({ auto_keymaps = false })` and bind the `Auditview*`
commands yourself. Override individual keys via `setup({ keymaps = { … } })`;
set a key to `""` to skip just that one.

### Commands

| Command                  | Effect                                                |
| ------------------------ | ----------------------------------------------------- |
| `:AuditviewMark`         | mark current line / range (range-aware)               |
| `:AuditviewUnmark`       | unmark current line / range                           |
| `:AuditviewProgress`     | echo `reviewed/countable (NN%)` for current file      |
| `:AuditviewProgress!`    | quickfix list of every file's coverage                |
| `:AuditviewRefresh`      | refetch current buffer's state from the server        |
| `:AuditviewSessionReset` | drop cached session id (next action re-resolves)      |
| `:AuditviewNote [text]`  | add note on current line / range (prompts if no arg)  |
| `:AuditviewTodo [text]`  | add TODO on current line / range (prompts if no arg)  |
| `:AuditviewNotes`        | quickfix list of notes in current file                |
| `:AuditviewNotes!`       | quickfix list of all notes in the session             |
| `:AuditviewNoteShow`     | floating preview of note(s) covering the cursor       |
| `:AuditviewNoteDetail`   | focusable detail window (prompt if multiple overlap)  |
| `:AuditviewNoteDelete`   | delete note at cursor (prompt if multiple overlap)    |
| `:AuditviewNextUnreviewed` | jump to next unreviewed chunk (accepts a count)     |
| `:AuditviewPrevUnreviewed` | jump to previous unreviewed chunk (accepts a count) |

## Configuration

```lua
require("auditview").setup({
  base_url = "http://127.0.0.1:5000",

  -- reviewed lines: full-line background tint (the sign column is reserved
  -- for note/todo markers so they don't fight for that one column).
  -- Set reviewed_style = "sign" to switch back to a sign-column glyph.
  reviewed_style = "line",
  reviewed_sign_text = "▎",                  -- only when reviewed_style == "sign"
  reviewed_hl = "AuditviewReviewed",         -- linked to DiffAdd by default

  note_sign_text = "■",
  note_sign_hl = "AuditviewNoteSign",        -- linked to Identifier
  todo_sign_text = "◆",
  todo_sign_hl = "AuditviewTodoSign",        -- linked to Todo

  -- EOL virtual text label for notes: "none" | "cursor" | "all"
  --   none   — never show
  --   cursor — show on the current cursor line when it's covered by a note
  --   all    — always show on each note's start line
  note_virt_text = "cursor",
  note_virt_text_max_width = 60,
  note_virt_text_hl = "AuditviewNoteVirtText",
  todo_virt_text_hl = "AuditviewTodoVirtText",

  hover = {
    auto = true,                             -- floating popup on CursorHold
    border = "rounded",
    max_width = 80,
  },
  auto_keymaps = true,
  keymaps = {
    mark = "<leader>am",
    unmark = "<leader>au",
    note = "<leader>an",
    todo = "<leader>at",
    note_show = "<leader>aN",
    note_detail = "<leader>ao",
    note_delete = "<leader>aD",
    notes_list = "<leader>al",
    next_unreviewed = "]r",
    prev_unreviewed = "[r",
  },
})
```

Hover popup is driven by Neovim's `'updatetime'` (default 4000 ms). Lower it for
snappier popups, e.g. `vim.o.updatetime = 500`. Set `hover.auto = false` to
disable the autocmd and trigger manually with `:AuditviewNoteShow`
(or `<leader>aN`).

### Highlight groups

Buffer indicators (linked to sensible defaults — override with `:hi`):

| Group                  | Default link | Meaning                                |
| ---------------------- | ------------ | -------------------------------------- |
| `AuditviewReviewed`    | `DiffAdd`    | reviewed line (full-line bg by default)|
| `AuditviewNoteSign`    | `Identifier` | note glyph in sign column              |
| `AuditviewTodoSign`    | `Todo`       | TODO glyph in sign column              |
| `AuditviewNoteVirtText`| `Comment`    | EOL inline note label                  |
| `AuditviewTodoVirtText`| `Todo`       | EOL inline TODO label                  |

## Notes

- The plugin caches per-line hashes returned by the server, so it never
  computes SHA-256 itself. The cache is refreshed on `BufReadPost`,
  `BufWritePost`, and after every mark/unmark or note action.
- If you edit a file outside nvim, run `:AuditviewRefresh` (or just
  re-enter the buffer).
- Marking and note creation are blocked while a buffer is `modified` —
  save first so the server hashes match what you see.
- Reviewed lines render as a whole-line background tint (so the sign
  column stays free for notes). Flip back to a sign-column glyph by
  setting `reviewed_style = "sign"`.
- `]r` / `[r` skip past the chunk you're currently inside (gitsigns-style),
  treating blank/comment lines as connective tissue and stopping only at
  reviewed lines or file edges. Accepts a count: `3]r` jumps three chunks.
- Notes appear as signs in the sign column on each note's first line:
  `■` for a regular note, `◆` for a TODO. With `note_virt_text = "cursor"`
  (default) you also get an inline `TODO: …` / `NOTE: …` label at end of
  the cursor line when it sits inside a note's range; set `"all"` to keep
  the label on every note's start line, or `"none"` to disable. Orphaned
  notes (anchor lines changed) are not rendered in the buffer; they still
  show up in `:AuditviewNotes` / `:AuditviewNotes!` for triage.

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

- Issues / linking notes to issues
- Editing existing note content (delete + re-create instead)
- SSE consumption (no live update when the web UI marks or adds notes)
- Creating sessions from nvim
