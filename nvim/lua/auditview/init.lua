local config = require("auditview.config")
local session = require("auditview.session")
local buffer = require("auditview.buffer")
local marks = require("auditview.marks")
local http = require("auditview.http")

local M = {}

function M.setup(opts)
  config.setup(opts)
end

function M.mark() marks.mark_current() end
function M.unmark() marks.unmark_current() end
function M.mark_visual() marks.mark_visual() end
function M.unmark_visual() marks.unmark_visual() end

function M.on_buf_read(bufnr)
  bufnr = bufnr or vim.api.nvim_get_current_buf()
  if vim.bo[bufnr].buftype ~= "" then return end
  if vim.api.nvim_buf_get_name(bufnr) == "" then return end
  session.ensure_files_listed(function(ok)
    if not ok then return end
    if session.rel_path(bufnr) then
      buffer.fetch(bufnr, function(_, err)
        if err and not err:match("not inside session root") then
          vim.notify("auditview: " .. err, vim.log.levels.DEBUG)
        end
      end)
    end
  end)
end

function M.on_buf_unload(bufnr)
  buffer.invalidate(bufnr)
end

local function current_buffer_progress()
  local bufnr = vim.api.nvim_get_current_buf()
  local cached = buffer.get(bufnr)
  if not cached then
    vim.notify("auditview: buffer not loaded — open a tracked file", vim.log.levels.WARN)
    return
  end
  local reviewed, countable = 0, 0
  for _, line in pairs(cached.lines) do
    if line.is_countable then
      countable = countable + 1
      if line.is_reviewed then reviewed = reviewed + 1 end
    end
  end
  local pct = countable > 0 and math.floor(reviewed * 100 / countable) or 0
  vim.notify(string.format(
    "auditview: %s — %d/%d (%d%%)",
    cached.rel_path, reviewed, countable, pct
  ))
end

local function all_files_progress()
  session.resolve(function(sess)
    if not sess then return end
    local files, err = http.get("/api/sessions/" .. sess.id .. "/files")
    if err then
      vim.notify("auditview: " .. err, vim.log.levels.ERROR)
      return
    end
    local qf = {}
    for _, f in ipairs(files) do
      local pct = f.countable_lines > 0
        and math.floor(f.reviewed_lines * 100 / f.countable_lines) or 0
      table.insert(qf, {
        filename = sess.root_path .. "/" .. f.rel_path,
        lnum = 1,
        text = string.format("[%s] %d/%d (%d%%)  %s",
          f.status, f.reviewed_lines, f.countable_lines, pct, f.rel_path),
      })
    end
    vim.fn.setqflist({}, " ", { title = "auditview progress", items = qf })
    vim.cmd("copen")
  end)
end

function M.progress(bang)
  if bang then all_files_progress() else current_buffer_progress() end
end

function M.refresh()
  local bufnr = vim.api.nvim_get_current_buf()
  buffer.invalidate(bufnr)
  M.on_buf_read(bufnr)
end

function M.session_reset()
  session.reset()
  vim.notify("auditview: session cache cleared")
end

return M
