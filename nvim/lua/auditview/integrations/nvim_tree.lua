local http = require("auditview.http")
local session = require("auditview.session")

local M = {}

local status_map = {}
local enabled = false

local HL_BY_STATUS = {
  reviewed = "AuditviewTreeReviewed",
  partial = "AuditviewTreePartial",
  not_viewed = "AuditviewTreeNotViewed",
  empty = nil,
}

local function abs_to_rel(abs_path, root_path)
  local norm_abs = vim.fs.normalize(abs_path)
  local norm_root = vim.fs.normalize(root_path)
  if norm_root:sub(-1) ~= "/" then norm_root = norm_root .. "/" end
  if norm_abs:sub(1, #norm_root) ~= norm_root then return nil end
  return norm_abs:sub(#norm_root + 1)
end

function M.refresh()
  if not enabled then return end
  session.resolve(function(sess)
    if not sess then return end
    local files, err = http.get("/api/sessions/" .. sess.id .. "/files")
    if err or not files then return end
    local new_map = {}
    for _, f in ipairs(files) do
      new_map[f.rel_path] = f.status
    end
    status_map = new_map
    local ok, nt_api = pcall(require, "nvim-tree.api")
    if ok then pcall(nt_api.tree.reload) end
  end)
end

function M.maybe_refresh()
  if enabled then M.refresh() end
end

local function build_decorator()
  local ok, nt_api = pcall(require, "nvim-tree.api")
  if not ok then return nil end

  local Decorator = nt_api.Decorator:extend()

  function Decorator:new()
    self.enabled = true
    self.highlight_range = "name"
    self.icon_placement = "none"
  end

  function Decorator:highlight_group(node)
    if node.type ~= "file" then return nil end
    local sess = session.current()
    if not sess then return nil end
    local rel = abs_to_rel(node.absolute_path, sess.root_path)
    if not rel then return nil end
    return HL_BY_STATUS[status_map[rel] or ""]
  end

  return Decorator
end

function M.setup()
  local Decorator = build_decorator()
  if not Decorator then
    vim.notify("auditview: nvim-tree not available", vim.log.levels.WARN)
    return nil
  end

  enabled = true

  local ok, nt_api = pcall(require, "nvim-tree.api")
  if ok and nt_api.events and nt_api.events.subscribe then
    pcall(function()
      nt_api.events.subscribe(nt_api.events.Event.TreeOpen, M.refresh)
    end)
  end

  return Decorator
end

return M
