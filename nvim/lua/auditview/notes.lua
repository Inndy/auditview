local config = require("auditview.config")
local http = require("auditview.http")
local session = require("auditview.session")
local buffer = require("auditview.buffer")

local M = {}

local function visual_range()
  local mode = vim.fn.mode()
  if mode == "v" or mode == "V" or mode == "\22" then
    vim.cmd('normal! \27')
  end
  local s = vim.fn.getpos("'<")[2]
  local e = vim.fn.getpos("'>")[2]
  if s == 0 or e == 0 then
    local cur = vim.api.nvim_win_get_cursor(0)[1]
    return cur, cur
  end
  if s > e then s, e = e, s end
  return s, e
end

local function ensure_ready(bufnr, cb)
  if vim.bo[bufnr].modified then
    vim.notify("auditview: buffer has unsaved changes — :w first", vim.log.levels.WARN)
    return
  end
  buffer.ensure(bufnr, function(cached, err)
    if not cached then
      vim.notify("auditview: " .. (err or "no cache"), vim.log.levels.ERROR)
      return
    end
    cb(cached)
  end)
end

local function submit(bufnr, start_line, end_line, content, is_todo)
  ensure_ready(bufnr, function(cached)
    local sess = session.current()
    local resp, http_err = http.post(
      "/api/sessions/" .. sess.id .. "/notes",
      {
        file_path = cached.rel_path,
        start_line = start_line,
        end_line = end_line,
        content = content,
        is_todo = is_todo,
      }
    )
    if http_err then
      vim.notify("auditview: " .. http_err, vim.log.levels.ERROR)
      return
    end
    if resp.error then
      vim.notify("auditview: " .. resp.error, vim.log.levels.ERROR)
      return
    end
    buffer.refresh(bufnr)
  end)
end

local function ask_and_submit(bufnr, start_line, end_line, is_todo, preset)
  if preset and preset ~= "" then
    submit(bufnr, start_line, end_line, preset, is_todo)
    return
  end
  local label = is_todo and "TODO" or "Note"
  local range_label = (start_line == end_line)
    and ("line " .. start_line)
    or ("lines " .. start_line .. "-" .. end_line)
  vim.ui.input({ prompt = label .. " (" .. range_label .. "): " },
    function(input)
      if not input or input == "" then return end
      submit(bufnr, start_line, end_line, input, is_todo)
    end
  )
end

function M.add_current(is_todo, content)
  local bufnr = vim.api.nvim_get_current_buf()
  local ln = vim.api.nvim_win_get_cursor(0)[1]
  ask_and_submit(bufnr, ln, ln, is_todo, content)
end

function M.add_visual(is_todo, content)
  local bufnr = vim.api.nvim_get_current_buf()
  local s, e = visual_range()
  ask_and_submit(bufnr, s, e, is_todo, content)
end

local function format_note_line(note)
  local tag = note.is_todo and "TODO" or "NOTE"
  if note.is_orphaned then tag = tag .. ",ORPHAN" end
  local first = (note.content or ""):gsub("\n.*", "")
  return string.format("[%s] L%d-%d: %s", tag, note.start_line, note.end_line, first)
end

function M.show_at_cursor(opts)
  opts = opts or {}
  local silent = opts.silent
  local bufnr = vim.api.nvim_get_current_buf()
  local ln = vim.api.nvim_win_get_cursor(0)[1]
  local hits = buffer.notes_at_line(bufnr, ln)
  if #hits == 0 then
    if not silent then
      vim.notify("auditview: no note at line " .. ln, vim.log.levels.WARN)
    end
    return
  end
  local lines = {}
  for i, note in ipairs(hits) do
    if i > 1 then table.insert(lines, "---") end
    local tag = note.is_todo and "TODO" or "NOTE"
    table.insert(lines, string.format(
      "[%s #%d] L%d-%d", tag, note.id, note.start_line, note.end_line))
    for _, content_line in ipairs(vim.split(note.content or "", "\n", { plain = true })) do
      table.insert(lines, content_line)
    end
  end
  vim.lsp.util.open_floating_preview(lines, "markdown", {
    border = config.options.hover.border,
    max_width = config.options.hover.max_width,
    focus = false,
    focusable = false,
  })
end

local function present(v)
  if v == nil or v == vim.NIL then return nil end
  return v
end

local function open_detail_window(note)
  local lines = {}
  local tag = note.is_todo and "TODO" or "NOTE"
  if note.is_orphaned then tag = tag .. " · ORPHANED" end
  table.insert(lines, string.format("# %s #%d", tag, note.id))
  if note.start_line == note.end_line then
    table.insert(lines, string.format("Line:    %d", note.start_line))
  else
    table.insert(lines, string.format("Lines:   %d-%d", note.start_line, note.end_line))
  end
  local created_at = present(note.created_at)
  if created_at then
    table.insert(lines, "Created: " .. created_at)
  end
  local issue_id = present(note.issue_id)
  if issue_id then
    local severity = present(note.issue_severity)
    local sev = severity and (" [" .. severity .. "]") or ""
    table.insert(lines, string.format("Issue:   #%d%s", issue_id, sev))
  end
  table.insert(lines, "")
  for _, content_line in ipairs(vim.split(note.content or "", "\n", { plain = true })) do
    table.insert(lines, content_line)
  end
  local snapshot_text = present(note.snapshot_text)
  if note.is_orphaned and snapshot_text and snapshot_text ~= "" then
    table.insert(lines, "")
    table.insert(lines, "---")
    table.insert(lines, "Anchor snapshot:")
    for _, snap_line in ipairs(vim.split(snapshot_text, "\n", { plain = true })) do
      table.insert(lines, "  " .. snap_line)
    end
  end

  local buf = vim.api.nvim_create_buf(false, true)
  vim.api.nvim_buf_set_lines(buf, 0, -1, false, lines)
  vim.bo[buf].filetype = "markdown"
  vim.bo[buf].modifiable = false
  vim.bo[buf].bufhidden = "wipe"

  local max_width = config.options.hover.max_width or 80
  local width = math.min(max_width, math.max(40, vim.o.columns - 4))
  local content_height = #lines
  for _, l in ipairs(lines) do
    local extra = math.floor(vim.fn.strdisplaywidth(l) / width)
    content_height = content_height + extra
  end
  local height = math.min(content_height, math.floor(vim.o.lines * 0.6))
  if height < 1 then height = 1 end

  local win = vim.api.nvim_open_win(buf, true, {
    relative = "editor",
    width = width,
    height = height,
    row = math.floor((vim.o.lines - height) / 2) - 1,
    col = math.floor((vim.o.columns - width) / 2),
    border = config.options.hover.border or "rounded",
    title = " Note Detail ",
    title_pos = "center",
    style = "minimal",
  })
  vim.wo[win].wrap = true
  vim.wo[win].linebreak = true
  vim.wo[win].conceallevel = 2

  local function close()
    if vim.api.nvim_win_is_valid(win) then
      vim.api.nvim_win_close(win, true)
    end
  end
  vim.keymap.set("n", "q", close, { buffer = buf, nowait = true, silent = true })
  vim.keymap.set("n", "<Esc>", close, { buffer = buf, nowait = true, silent = true })
end

function M.detail_at_cursor()
  local bufnr = vim.api.nvim_get_current_buf()
  local ln = vim.api.nvim_win_get_cursor(0)[1]
  local hits = buffer.notes_at_line(bufnr, ln)
  if #hits == 0 then
    vim.notify("auditview: no note at line " .. ln, vim.log.levels.WARN)
    return
  end
  if #hits == 1 then
    open_detail_window(hits[1])
    return
  end
  vim.ui.select(hits, {
    prompt = "auditview: open detail of which note?",
    format_item = format_note_line,
  }, function(picked)
    if picked then open_detail_window(picked) end
  end)
end

function M.delete_at_cursor()
  local bufnr = vim.api.nvim_get_current_buf()
  local ln = vim.api.nvim_win_get_cursor(0)[1]
  local hits = buffer.notes_at_line(bufnr, ln)
  if #hits == 0 then
    vim.notify("auditview: no note at line " .. ln, vim.log.levels.WARN)
    return
  end
  local function do_delete(note)
    local sess = session.current()
    local resp, http_err = http.delete(
      "/api/sessions/" .. sess.id .. "/notes/" .. note.id
    )
    if http_err then
      vim.notify("auditview: " .. http_err, vim.log.levels.ERROR)
      return
    end
    if resp and resp.error then
      vim.notify("auditview: " .. resp.error, vim.log.levels.ERROR)
      return
    end
    buffer.refresh(bufnr)
  end
  if #hits == 1 then
    do_delete(hits[1])
    return
  end
  vim.ui.select(hits, {
    prompt = "auditview: delete which note?",
    format_item = format_note_line,
  }, function(picked)
    if picked then do_delete(picked) end
  end)
end

function M.list_in_buffer()
  local bufnr = vim.api.nvim_get_current_buf()
  local cached = buffer.get(bufnr)
  if not cached then
    vim.notify("auditview: buffer not loaded", vim.log.levels.WARN)
    return
  end
  local notes = cached.notes or {}
  if #notes == 0 then
    vim.notify("auditview: no notes in " .. cached.rel_path)
    return
  end
  local items = {}
  for _, n in ipairs(notes) do
    table.insert(items, {
      bufnr = bufnr,
      lnum = n.start_line,
      end_lnum = n.end_line,
      text = format_note_line(n),
    })
  end
  vim.fn.setqflist({}, " ", {
    title = "auditview notes: " .. cached.rel_path,
    items = items,
  })
  vim.cmd("copen")
end

function M.list_all()
  session.resolve(function(sess)
    if not sess then return end
    local notes, err = http.get("/api/sessions/" .. sess.id .. "/notes")
    if err then
      vim.notify("auditview: " .. err, vim.log.levels.ERROR)
      return
    end
    if notes.error then
      vim.notify("auditview: " .. notes.error, vim.log.levels.ERROR)
      return
    end
    if #notes == 0 then
      vim.notify("auditview: no notes in this session")
      return
    end
    local items = {}
    for _, n in ipairs(notes) do
      table.insert(items, {
        filename = sess.root_path .. "/" .. n.file_path,
        lnum = n.start_line,
        end_lnum = n.end_line,
        text = format_note_line(n),
      })
    end
    vim.fn.setqflist({}, " ", { title = "auditview: all notes", items = items })
    vim.cmd("copen")
  end)
end

return M
