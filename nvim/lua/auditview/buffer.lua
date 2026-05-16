local config = require("auditview.config")
local http = require("auditview.http")
local session = require("auditview.session")

local M = {}

local ns = vim.api.nvim_create_namespace("auditview")
local cache = {}

local function render_signs(bufnr, lines)
  if not vim.api.nvim_buf_is_valid(bufnr) then return end
  vim.api.nvim_buf_clear_namespace(bufnr, ns, 0, -1)
  local line_count = vim.api.nvim_buf_line_count(bufnr)
  for line_no, entry in pairs(lines) do
    if entry.is_reviewed and line_no >= 1 and line_no <= line_count then
      vim.api.nvim_buf_set_extmark(bufnr, ns, line_no - 1, 0, {
        sign_text = config.options.sign_text,
        sign_hl_group = config.options.sign_hl,
      })
    end
  end
end

function M.get(bufnr)
  return cache[bufnr]
end

function M.fetch(bufnr, cb)
  cb = cb or function() end
  local rel = session.rel_path(bufnr)
  if not rel then
    cb(nil, "buffer is not inside session root")
    return
  end
  local sess = session.current()
  local data, err = http.get(
    "/api/sessions/" .. sess.id .. "/files/" .. http.encode_path(rel)
  )
  if err then
    cb(nil, err)
    return
  end
  if data.error then
    cb(nil, data.error)
    return
  end
  local lines = {}
  for _, line in ipairs(data.lines or {}) do
    lines[line.line_no] = {
      line_hash = line.line_hash,
      context_hash = line.context_hash,
      is_reviewed = line.is_reviewed,
      is_countable = line.is_countable,
    }
  end
  cache[bufnr] = {
    rel_path = rel,
    lines = lines,
    fetched_at = os.time(),
  }
  render_signs(bufnr, lines)
  cb(cache[bufnr])
end

function M.refresh(bufnr)
  M.fetch(bufnr, function(_, err)
    if err then
      vim.notify("auditview: refresh failed — " .. err, vim.log.levels.WARN)
    end
  end)
end

function M.invalidate(bufnr)
  cache[bufnr] = nil
  if vim.api.nvim_buf_is_valid(bufnr) then
    vim.api.nvim_buf_clear_namespace(bufnr, ns, 0, -1)
  end
end

function M.ensure(bufnr, cb)
  if cache[bufnr] then
    cb(cache[bufnr])
    return
  end
  session.ensure_files_listed(function(ok)
    if not ok then
      cb(nil, "session not resolved")
      return
    end
    M.fetch(bufnr, cb)
  end)
end

return M
