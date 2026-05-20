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
    local rejected = resp.rejected or {}
    local n_rej = #rejected
    if n_rej > 0 then
      local reason_counts = {}
      local order = {}
      for _, r in ipairs(rejected) do
        local reason = r.reason or "unknown"
        if reason_counts[reason] == nil then
          table.insert(order, reason)
        end
        reason_counts[reason] = (reason_counts[reason] or 0) + 1
      end
      local parts = {}
      for _, reason in ipairs(order) do
        table.insert(parts, string.format("%dx %s", reason_counts[reason], reason))
      end
      local detail = table.concat(parts, "; ")
      local sample = {}
      for i = 1, math.min(3, n_rej) do
        table.insert(sample, tostring(rejected[i].line_no or "?"))
      end
      local lines_str = table.concat(sample, ",")
      if n_rej > #sample then lines_str = lines_str .. ",…" end
      vim.notify(string.format(
        "auditview: %d/%d rejected at L%s — %s — refetching",
        n_rej, #lines, lines_str, detail
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
