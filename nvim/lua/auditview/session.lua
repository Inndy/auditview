local http = require("auditview.http")

local M = {}

local state = {
  session = nil,
  files_listed = false,
  project_root = nil,
  project_root_searched = false,
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

  local root = M.project_root()
  if not root and not interactive then
    cb(nil)
    return
  end

  local sessions, err = http.get("/api/sessions")
  if err then
    if interactive then vim.notify("auditview: " .. err, vim.log.levels.ERROR) end
    cb(nil)
    return
  end
  if not sessions or #sessions == 0 then
    if interactive then
      vim.notify("auditview: no sessions on server — create one in the web UI", vim.log.levels.WARN)
    end
    cb(nil)
    return
  end

  local matches = pick_for_path(sessions, root or vim.fn.getcwd())
  if #matches == 1 then
    state.session = matches[1]
    state.files_listed = false
    cb(state.session)
    return
  end

  if not interactive then
    cb(nil)
    return
  end

  if #matches == 0 and root then
    vim.notify(
      "auditview: no session matches " .. root .. " — pick manually",
      vim.log.levels.WARN
    )
  end
  choose_interactive(#matches > 1 and matches or sessions, cb)
end

---@param cb fun(ok: boolean)
---@param opts? { interactive?: boolean }
function M.ensure_files_listed(cb, opts)
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
      if (opts or {}).interactive ~= false then
        vim.notify("auditview: " .. err, vim.log.levels.ERROR)
      end
      cb(false)
      return
    end
    state.files_listed = true
    cb(true)
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
  state.files_listed = false
  state.project_root = nil
  state.project_root_searched = false
end

return M
