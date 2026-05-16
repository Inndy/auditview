# auditview.nvim (v0)

A minimal Lua client for the auditview HTTP API: mark/unmark lines as
reviewed and see file progress without leaving nvim. The auditview server
stays the single source of truth; the web UI sees nvim's marks live via SSE.

## Requirements

- Neovim 0.10+ (for `vim.system`, `vim.fs.normalize`, `vim.json`)
- `curl` on `$PATH`
- A running `auditview` server (default `http://127.0.0.1:5000`)

## Install

Symlink or point your plugin manager at this directory.

**lazy.nvim** (local path):
```lua
{ dir = "/path/to/auditview-nvim/nvim", name = "auditview.nvim",
  config = function() require("auditview").setup() end }
```

**Manual**:
```bash
ln -s /path/to/auditview-nvim/nvim ~/.config/nvim/pack/auditview/start/auditview.nvim
```

## Usage

1. Start the server: `uv run auditview /path/to/project`
2. Create a session in the web UI at `http://127.0.0.1:5000`
   (sessions can't be created from nvim yet).
3. `cd /path/to/project` and open nvim. The plugin auto-picks the session
   whose `root_path` matches your cwd; if multiple match (or none), it
   prompts via `vim.ui.select`.
4. Open a file. Reviewed lines show with a sign in the sign column.

### Keymaps (defaults)

| Mode    | Key          | Action                       |
| ------- | ------------ | ---------------------------- |
| Normal  | `<leader>am` | mark current line reviewed   |
| Visual  | `<leader>am` | mark selected lines reviewed |
| Normal  | `<leader>au` | unmark current line          |
| Visual  | `<leader>au` | unmark selected lines        |

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

## Configuration

```lua
require("auditview").setup({
  base_url = "http://127.0.0.1:5000",
  sign_text = "▎",
  sign_hl = "AuditviewReviewed",   -- linked to DiffAdd by default
  auto_keymaps = true,
  keymaps = { mark = "<leader>am", unmark = "<leader>au" },
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

## Out of scope for v0

- Notes / TODOs / issues
- SSE consumption (no live update when the web UI marks)
- Creating sessions from nvim
