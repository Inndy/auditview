local http = require("auditview.http")
local session = require("auditview.session")
local buffer = require("auditview.buffer")
local utils = require("auditview.utils")

local M = {}

local function send(bufnr, start_line, end_line, reviewed)
  if vim.bo[bufnr].modified then
    vim.notify("auditview: buffer has unsaved changes — :w first", vim.log.levels.WARN)
    return
  end
  buffer.ensure(bufnr, function(cached, err)
    if not cached then
      vim.notify("auditview: " .. (err or "no cache"), vim.log.levels.ERROR)
      return
    end
    local lines = {}
    for ln = start_line, end_line do
      local entry = cached.lines[ln]
      if entry then
        table.insert(lines, {
          line_no = ln,
          line_hash = entry.line_hash,
          context_hash = entry.context_hash,
        })
      end
    end
    if #lines == 0 then
      vim.notify("auditview: no hashable lines in range", vim.log.levels.WARN)
      return
    end
    local sess = session.current()
    local resp, http_err = http.post(
      "/api/sessions/" .. sess.id .. "/lines/mark",
      { file_path = cached.rel_path, reviewed = reviewed, lines = lines }
    )
    if http_err then
      vim.notify("auditview: " .. http_err, vim.log.levels.ERROR)
      return
    end
    if resp.error then
      vim.notify("auditview: " .. resp.error, vim.log.levels.ERROR)
      return
    end
    local n_rej = #(resp.rejected or {})
    if n_rej > 0 then
      vim.notify(string.format(
        "auditview: %d/%d rejected (%s) — refetching",
        n_rej, #lines, resp.rejected[1].reason or "unknown"
      ), vim.log.levels.WARN)
    end
    buffer.refresh(bufnr)
    pcall(function()
      require("auditview.integrations.nvim_tree").maybe_refresh()
    end)
  end)
end

function M.mark_current()
  local bufnr = vim.api.nvim_get_current_buf()
  local ln = vim.api.nvim_win_get_cursor(0)[1]
  send(bufnr, ln, ln, true)
end

function M.unmark_current()
  local bufnr = vim.api.nvim_get_current_buf()
  local ln = vim.api.nvim_win_get_cursor(0)[1]
  send(bufnr, ln, ln, false)
end

function M.mark_visual()
  local bufnr = vim.api.nvim_get_current_buf()
  local s, e = utils.visual_range()
  send(bufnr, s, e, true)
end

function M.unmark_visual()
  local bufnr = vim.api.nvim_get_current_buf()
  local s, e = utils.visual_range()
  send(bufnr, s, e, false)
end

return M
