local http = require("auditview.http")

local M = {}

local state = {
  session = nil,
  files_listed = false,
}

local function normalize(path)
  return vim.fs.normalize(path)
end

local function pick_for_cwd(sessions)
  local cwd = normalize(vim.fn.getcwd())
  local matches = {}
  for _, s in ipairs(sessions) do
    if normalize(s.root_path) == cwd then
      table.insert(matches, s)
    end
  end
  return matches
end

local function choose_interactive(sessions, cb)
  vim.ui.select(sessions, {
    prompt = "auditview: pick session",
    format_item = function(s)
      return string.format("[%d] %s  (%s)", s.id, s.label, s.root_path)
    end,
  }, function(picked)
    if picked then
      state.session = picked
      state.files_listed = false
    end
    cb(picked)
  end)
end

function M.current()
  return state.session
end

function M.resolve(cb)
  if state.session then
    cb(state.session)
    return
  end
  local sessions, err = http.get("/api/sessions")
  if err then
    vim.notify("auditview: " .. err, vim.log.levels.ERROR)
    cb(nil)
    return
  end
  if not sessions or #sessions == 0 then
    vim.notify("auditview: no sessions on server — create one in the web UI", vim.log.levels.WARN)
    cb(nil)
    return
  end
  local matches = pick_for_cwd(sessions)
  if #matches == 1 then
    state.session = matches[1]
    state.files_listed = false
    cb(state.session)
    return
  end
  choose_interactive(#matches > 1 and matches or sessions, cb)
end

function M.ensure_files_listed(cb)
  if state.files_listed then
    cb(true)
    return
  end
  M.resolve(function(session)
    if not session then
      cb(false)
      return
    end
    local _, err = http.get("/api/sessions/" .. session.id .. "/files")
    if err then
      vim.notify("auditview: " .. err, vim.log.levels.ERROR)
      cb(false)
      return
    end
    state.files_listed = true
    cb(true)
  end)
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
  state.files_listed = false
end

return M
