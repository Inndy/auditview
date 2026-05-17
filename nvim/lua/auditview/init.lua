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
  end, { interactive = false })
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

local function jump_unreviewed(direction)
  local bufnr = vim.api.nvim_get_current_buf()
  if not buffer.get(bufnr) then
    vim.notify("auditview: buffer not tracked", vim.log.levels.WARN)
    return
  end
  local chunks = buffer.unreviewed_chunks(bufnr)
  if #chunks == 0 then
    vim.notify("auditview: no unreviewed chunks", vim.log.levels.INFO)
    return
  end
  local count = vim.v.count1
  local cur_pos = vim.api.nvim_win_get_cursor(0)[1]
  local anchor_start, anchor_finish = cur_pos, cur_pos
  for _, c in ipairs(chunks) do
    if c.start <= cur_pos and cur_pos <= c.finish then
      anchor_start, anchor_finish = c.start, c.finish
      break
    end
  end
  local target
  for _ = 1, count do
    local found
    if direction == "next" then
      for _, c in ipairs(chunks) do
        if c.start > anchor_finish then found = c; break end
      end
    else
      if anchor_start < cur_pos and cur_pos <= anchor_finish then
        found = { start = anchor_start, finish = anchor_finish }
      else
        for i = #chunks, 1, -1 do
          if chunks[i].finish < anchor_start then found = chunks[i]; break end
        end
      end
    end
    if not found then break end
    target = found
    anchor_start, anchor_finish = found.start, found.finish
    cur_pos = found.start
  end
  if not target then
    vim.notify(
      direction == "next"
        and "auditview: no more unreviewed chunks below"
        or "auditview: no more unreviewed chunks above",
      vim.log.levels.INFO
    )
    return
  end
  vim.cmd("normal! m'")
  vim.api.nvim_win_set_cursor(0, { target.start, 0 })
end

function M.jump_next_unreviewed() jump_unreviewed("next") end
function M.jump_prev_unreviewed() jump_unreviewed("prev") end

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
