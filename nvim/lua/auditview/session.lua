local http = require("auditview.http")

local M = {}

local state = {
  session = nil,
  files_scanned = false,
  project_root = nil,
  project_root_searched = false,
  resolving = false,
  resolve_pending = {},
  files_scanning = false,
  files_scanning_pending = {},
}

local function normalize(path)
  return vim.fs.normalize(path)
end

local function discover_project_root(start_dir)
  local found = vim.fs.find(".auditview.db", {
    path = start_dir or vim.fn.getcwd(),
    upward = true,
    type = "file",
  })
  if found and found[1] then
    return normalize(vim.fs.dirname(found[1]))
  end
  return nil
end

local function pick_for_path(sessions, target)
  if not target then return {} end
  local norm = normalize(target)
  local matches = {}
  for _, s in ipairs(sessions) do
    if normalize(s.root_path) == norm then
      table.insert(matches, s)
    end
  end
  return matches
end

local function has_ui_select_override()
  local info = debug.getinfo(vim.ui.select, "S")
  return info and info.source and not info.source:find("/lua/vim/ui%.lua$")
end

local function float_select(sessions, cb)
  local lines = {}
  for _, s in ipairs(sessions) do
    table.insert(lines, string.format("  [%d] %-24s %s", s.id, s.label, s.root_path))
  end

  local width = 0
  for _, l in ipairs(lines) do width = math.max(width, #l) end
  width = math.min(width + 2, vim.o.columns - 4)

  local buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  vim.bo[buf].modifiable = false

  local row = math.floor((vim.o.lines - #lines) / 2) - 1
  local col = math.floor((vim.o.columns - width) / 2)
  local win = vim.api.nvim_open_win(buf, true, {
    relative = "editor",
    row = row, col = col,
    width = width, height = #lines,
    style = "minimal",
    border = "rounded",
    title = " auditview: pick session ",
    title_pos = "center",
  })
  vim.wo[win].cursorline = true

  local function close(idx)
    if vim.api.nvim_win_is_valid(win) then
      vim.api.nvim_win_close(win, true)
    end
    local picked = idx and sessions[idx] or nil
    if picked then
      state.session = picked
      state.files_scanned = false
    end
    cb(picked)
  end

  local ko = { nowait = true, noremap = true, silent = true, buffer = buf }
  vim.keymap.set("n", "<CR>", function()
    close(vim.api.nvim_win_get_cursor(win)[1])
  end, ko)
  vim.keymap.set("n", "q",     function() close(nil) end, ko)
  vim.keymap.set("n", "<Esc>", function() close(nil) end, ko)
  vim.api.nvim_create_autocmd("BufLeave", {
    buffer = buf, once = true,
    callback = function() close(nil) end,
  })
end

local function choose_interactive(sessions, cb)
  if has_ui_select_override() then
    vim.ui.select(sessions, {
      prompt = "auditview: pick session",
      format_item = function(s)
        return string.format("[%d] %-24s %s", s.id, s.label, s.root_path)
      end,
    }, function(picked)
      if picked then
        state.session = picked
        state.files_scanned = false
      end
      cb(picked)
    end)
  else
    float_select(sessions, cb)
  end
end

function M.current()
  return state.session
end

function M.project_root()
  if not state.project_root_searched then
    state.project_root = discover_project_root()
    state.project_root_searched = true
  end
  return state.project_root
end

---@param cb fun(session: table|nil)
---@param opts? { interactive?: boolean } interactive=false means never prompt; default true
function M.resolve(cb, opts)
  opts = opts or {}
  local interactive = opts.interactive ~= false

  if state.session then
    cb(state.session)
    return
  end

  if state.resolving then
    table.insert(state.resolve_pending, cb)
    return
  end

  local root = M.project_root()
  if not root and not interactive then
    cb(nil)
    return
  end

  state.resolving = true

  local function finish(sess)
    state.resolving = false
    local pending = state.resolve_pending
    state.resolve_pending = {}
    cb(sess)
    for _, pcb in ipairs(pending) do
      pcb(sess)
    end
  end

  local sessions, err = http.get("/api/sessions")
  if err then
    if interactive then vim.notify("auditview: " .. err, vim.log.levels.ERROR) end
    finish(nil)
    return
  end
  if not sessions or #sessions == 0 then
    if interactive then
      vim.notify("auditview: no sessions on server — create one in the web UI", vim.log.levels.WARN)
    end
    finish(nil)
    return
  end

  local matches = pick_for_path(sessions, root or vim.fn.getcwd())
  if #matches == 1 then
    state.session = matches[1]
    state.files_scanned = false
    finish(state.session)
    return
  end

  if not interactive then
    finish(nil)
    return
  end

  if #matches == 0 and root then
    vim.notify(
      "auditview: no session matches " .. root .. " — pick manually",
      vim.log.levels.WARN
    )
  end
  -- choose_interactive is async (UI picker); wrap its callback through finish
  choose_interactive(#matches > 1 and matches or sessions, function(picked)
    finish(picked)
  end)
end

--- Sync the server's file table with the disk, and return the file list.
---
--- POST /rescan is the only endpoint that adopts a file created since the last
--- scan; GET /files is read-only (API.md), so listing it can never make an
--- untracked file fetchable. Unforced is cheap — the server serves a cached
--- scan and only re-walks the tree once a watchdog event has invalidated it.
--- force=1 re-walks regardless, which is what picks up an edited .gitignore or
--- a changed exclusion_patterns.
---@param opts? { force?: boolean }
---@return table|nil files, string|nil err
function M.rescan(opts)
  local sess = state.session
  if not sess then return nil, "no session resolved" end
  local qs = (opts or {}).force and "?force=1" or ""
  local files, err = http.post(
    "/api/sessions/" .. sess.id .. "/rescan" .. qs, vim.empty_dict()
  )
  if err then return nil, err end
  state.files_scanned = true
  return files, nil
end

---@param cb fun(ok: boolean)
---@param opts? { interactive?: boolean }
function M.ensure_files_scanned(cb, opts)
  if state.files_scanned then
    cb(true)
    return
  end

  if state.files_scanning then
    table.insert(state.files_scanning_pending, cb)
    return
  end

  state.files_scanning = true

  local function finish(ok)
    state.files_scanning = false
    local pending = state.files_scanning_pending
    state.files_scanning_pending = {}
    cb(ok)
    for _, pcb in ipairs(pending) do
      pcb(ok)
    end
  end

  M.resolve(function(session)
    if not session then
      finish(false)
      return
    end
    local _, err = M.rescan()
    if err then
      if (opts or {}).interactive ~= false then
        vim.notify("auditview: " .. err, vim.log.levels.ERROR)
      end
      finish(false)
      return
    end
    finish(true)
  end, opts)
end

function M.rel_path(bufnr)
  local session = state.session
  if not session then return nil end
  local abs = vim.api.nvim_buf_get_name(bufnr)
  if abs == "" then return nil end
  local norm_abs = normalize(abs)
  local norm_root = normalize(session.root_path)
  if norm_root:sub(-1) ~= "/" then norm_root = norm_root .. "/" end
  if norm_abs:sub(1, #norm_root) ~= norm_root then
    return nil
  end
  return norm_abs:sub(#norm_root + 1)
end

function M.reset()
  state.session = nil
  state.files_scanned = false
  state.project_root = nil
  state.project_root_searched = false
  state.resolving = false
  state.resolve_pending = {}
  state.files_scanning = false
  state.files_scanning_pending = {}
end

return M
