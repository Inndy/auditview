local config = require("auditview.config")
local http = require("auditview.http")
local session = require("auditview.session")

local M = {}

local ns_reviewed = vim.api.nvim_create_namespace("auditview")
local ns_notes_sign = vim.api.nvim_create_namespace("auditview-notes-sign")
local ns_notes_vt = vim.api.nvim_create_namespace("auditview-notes-vt")
local cache = {}

local function render_reviewed(bufnr, lines)
  if not vim.api.nvim_buf_is_valid(bufnr) then return end
  vim.api.nvim_buf_clear_namespace(bufnr, ns_reviewed, 0, -1)
  local line_count = vim.api.nvim_buf_line_count(bufnr)
  local style = config.options.reviewed_style
  for line_no, entry in pairs(lines) do
    if entry.is_reviewed and line_no >= 1 and line_no <= line_count then
      local opts
      if style == "sign" then
        opts = {
          sign_text = config.options.reviewed_sign_text,
          sign_hl_group = config.options.reviewed_hl,
        }
      else
        opts = { line_hl_group = config.options.reviewed_hl }
      end
      vim.api.nvim_buf_set_extmark(bufnr, ns_reviewed, line_no - 1, 0, opts)
    end
  end
end

local function present(v)
  if v == nil or v == vim.NIL then return nil end
  return v
end

local function render_note_signs(bufnr, notes)
  if not vim.api.nvim_buf_is_valid(bufnr) then return end
  vim.api.nvim_buf_clear_namespace(bufnr, ns_notes_sign, 0, -1)
  local line_count = vim.api.nvim_buf_line_count(bufnr)
  local severity_map = config.options.severity_sign_hl or {}
  for _, note in ipairs(notes or {}) do
    if not note.is_orphaned
        and note.start_line >= 1
        and note.start_line <= line_count then
      local sign_text = note.is_todo
        and config.options.todo_sign_text
        or config.options.note_sign_text
      local sign_hl = note.is_todo
        and config.options.todo_sign_hl
        or config.options.note_sign_hl
      local severity = present(note.issue_severity)
      if severity and severity_map[severity] then
        sign_hl = severity_map[severity]
      end
      vim.api.nvim_buf_set_extmark(bufnr, ns_notes_sign, note.start_line - 1, 0, {
        sign_text = sign_text,
        sign_hl_group = sign_hl,
      })
    end
  end
end

local function truncate(s, limit)
  s = s:gsub("\n", " ")
  if vim.fn.strdisplaywidth(s) > limit then
    return s:sub(1, limit) .. "…"
  end
  return s
end

local function virt_text_chunk(note)
  local label = note.is_todo and "TODO" or "NOTE"
  local hl = note.is_todo
    and config.options.todo_virt_text_hl
    or config.options.note_virt_text_hl
  local max = config.options.note_virt_text_max_width or 60
  return { string.format(" %s: %s", label, truncate(note.content or "", max)), hl }
end

function M.render_note_virt_text(bufnr)
  if bufnr == 0 then bufnr = vim.api.nvim_get_current_buf() end
  if not vim.api.nvim_buf_is_valid(bufnr) then return end
  vim.api.nvim_buf_clear_namespace(bufnr, ns_notes_vt, 0, -1)
  local mode = config.options.note_virt_text
  if mode == "none" then return end
  local entry = cache[bufnr]
  if not entry or not entry.notes then return end
  local line_count = vim.api.nvim_buf_line_count(bufnr)

  if mode == "all" then
    for _, note in ipairs(entry.notes) do
      if not note.is_orphaned
          and note.start_line >= 1
          and note.start_line <= line_count then
        vim.api.nvim_buf_set_extmark(bufnr, ns_notes_vt, note.start_line - 1, 0, {
          virt_text = { virt_text_chunk(note) },
          virt_text_pos = "eol",
          hl_mode = "combine",
        })
      end
    end
    return
  end

  if mode == "cursor" then
    local win = vim.api.nvim_get_current_win()
    if vim.api.nvim_win_get_buf(win) ~= bufnr then return end
    local cur = vim.api.nvim_win_get_cursor(win)[1]
    if cur < 1 or cur > line_count then return end
    local hits = {}
    for _, note in ipairs(entry.notes) do
      if not note.is_orphaned
          and note.start_line <= cur
          and cur <= note.end_line then
        table.insert(hits, note)
      end
    end
    if #hits == 0 then return end
    local chunks = {}
    for i, note in ipairs(hits) do
      if i > 1 then table.insert(chunks, { " │", "Comment" }) end
      table.insert(chunks, virt_text_chunk(note))
    end
    vim.api.nvim_buf_set_extmark(bufnr, ns_notes_vt, cur - 1, 0, {
      virt_text = chunks,
      virt_text_pos = "eol",
      hl_mode = "combine",
    })
  end
end

function M.get(bufnr)
  return cache[bufnr]
end

function M.unreviewed_chunks(bufnr)
  local entry = cache[bufnr]
  if not entry or not entry.lines then return {} end
  if not vim.api.nvim_buf_is_valid(bufnr) then return {} end
  local line_count = vim.api.nvim_buf_line_count(bufnr)
  local chunks = {}
  local first_countable, last_countable = nil, nil
  for i = 1, line_count do
    local line = entry.lines[i]
    if line and line.is_reviewed then
      if first_countable then
        table.insert(chunks, { start = first_countable, finish = last_countable })
      end
      first_countable, last_countable = nil, nil
    elseif line and line.is_countable then
      first_countable = first_countable or i
      last_countable = i
    end
  end
  if first_countable then
    table.insert(chunks, { start = first_countable, finish = last_countable })
  end
  return chunks
end

function M.notes_at_line(bufnr, line_no)
  local entry = cache[bufnr]
  if not entry or not entry.notes then return {} end
  local hits = {}
  for _, note in ipairs(entry.notes) do
    if not note.is_orphaned
        and note.start_line <= line_no
        and line_no <= note.end_line then
      table.insert(hits, note)
    end
  end
  return hits
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
  local notes = data.notes or {}
  cache[bufnr] = {
    rel_path = rel,
    lines = lines,
    notes = notes,
  }
  render_reviewed(bufnr, lines)
  render_note_signs(bufnr, notes)
  M.render_note_virt_text(bufnr)
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
    vim.api.nvim_buf_clear_namespace(bufnr, ns_reviewed, 0, -1)
    vim.api.nvim_buf_clear_namespace(bufnr, ns_notes_sign, 0, -1)
    vim.api.nvim_buf_clear_namespace(bufnr, ns_notes_vt, 0, -1)
  end
end

function M.ensure(bufnr, cb, opts)
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
  end, opts)
end

return M
