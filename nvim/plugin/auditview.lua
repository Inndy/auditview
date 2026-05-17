if vim.g.loaded_auditview then return end
vim.g.loaded_auditview = true

local auditview = require("auditview")
local config = require("auditview.config")

vim.api.nvim_set_hl(0, "AuditviewReviewed", { link = "DiffAdd", default = true })
vim.api.nvim_set_hl(0, "AuditviewNoteSign", { link = "Identifier", default = true })
vim.api.nvim_set_hl(0, "AuditviewTodoSign", { link = "Todo", default = true })
vim.api.nvim_set_hl(0, "AuditviewNoteVirtText", { link = "Comment", default = true })
vim.api.nvim_set_hl(0, "AuditviewTodoVirtText", { link = "Todo", default = true })
vim.api.nvim_set_hl(0, "AuditviewSeverityP0", { link = "DiagnosticError", default = true })
vim.api.nvim_set_hl(0, "AuditviewSeverityP1", { link = "DiagnosticWarn", default = true })
vim.api.nvim_set_hl(0, "AuditviewSeverityP2", { link = "DiagnosticInfo", default = true })
vim.api.nvim_set_hl(0, "AuditviewTreeReviewed", { link = "DiffAdd", default = true })
vim.api.nvim_set_hl(0, "AuditviewTreePartial", { link = "DiffChange", default = true })
vim.api.nvim_set_hl(0, "AuditviewTreeNotViewed", { link = "Comment", default = true })

vim.api.nvim_create_user_command("AuditviewMark", function(opts)
  if opts.range == 2 then
    require("auditview.marks").mark_visual()
  else
    auditview.mark()
  end
end, { range = true })

vim.api.nvim_create_user_command("AuditviewUnmark", function(opts)
  if opts.range == 2 then
    require("auditview.marks").unmark_visual()
  else
    auditview.unmark()
  end
end, { range = true })

vim.api.nvim_create_user_command("AuditviewProgress", function(opts)
  auditview.progress(opts.bang)
end, { bang = true })

vim.api.nvim_create_user_command("AuditviewNextUnreviewed",
  auditview.jump_next_unreviewed, { count = true })
vim.api.nvim_create_user_command("AuditviewPrevUnreviewed",
  auditview.jump_prev_unreviewed, { count = true })

vim.api.nvim_create_user_command("AuditviewRefresh", auditview.refresh, {})
vim.api.nvim_create_user_command("AuditviewSessionReset", auditview.session_reset, {})

vim.api.nvim_create_user_command("AuditviewNote", function(opts)
  local content = opts.args ~= "" and opts.args or nil
  if opts.range == 2 then
    require("auditview.notes").add_visual(false, content)
  else
    require("auditview.notes").add_current(false, content)
  end
end, { range = true, nargs = "?" })

vim.api.nvim_create_user_command("AuditviewTodo", function(opts)
  local content = opts.args ~= "" and opts.args or nil
  if opts.range == 2 then
    require("auditview.notes").add_visual(true, content)
  else
    require("auditview.notes").add_current(true, content)
  end
end, { range = true, nargs = "?" })

vim.api.nvim_create_user_command("AuditviewNoteShow", auditview.note_show, {})
vim.api.nvim_create_user_command("AuditviewNoteDetail", auditview.note_detail, {})
vim.api.nvim_create_user_command("AuditviewNoteDelete", auditview.note_delete, {})
vim.api.nvim_create_user_command("AuditviewNotes", function(opts)
  auditview.notes_list(opts.bang)
end, { bang = true })

local group = vim.api.nvim_create_augroup("auditview", { clear = true })

vim.api.nvim_create_autocmd({ "BufReadPost", "BufWritePost" }, {
  group = group,
  callback = function(args) auditview.on_buf_read(args.buf) end,
})

vim.api.nvim_create_autocmd("BufUnload", {
  group = group,
  callback = function(args) auditview.on_buf_unload(args.buf) end,
})

if config.options.hover and config.options.hover.auto then
  vim.api.nvim_create_autocmd("CursorHold", {
    group = group,
    callback = function(args)
      if vim.bo[args.buf].buftype ~= "" then return end
      require("auditview.notes").show_at_cursor({ silent = true })
    end,
  })
end

vim.api.nvim_create_autocmd("CursorMoved", {
  group = group,
  callback = function(args)
    if config.options.note_virt_text ~= "cursor" then return end
    if vim.bo[args.buf].buftype ~= "" then return end
    local buffer = require("auditview.buffer")
    if not buffer.get(args.buf) then return end
    buffer.render_note_virt_text(args.buf)
  end,
})

if config.options.auto_keymaps then
  local km = config.options.keymaps
  if km.mark and km.mark ~= "" then
    vim.keymap.set("n", km.mark, auditview.mark, { desc = "auditview: mark line reviewed" })
    vim.keymap.set("x", km.mark, ":<C-u>lua require('auditview.marks').mark_visual()<CR>",
      { desc = "auditview: mark range reviewed", silent = true })
  end
  if km.unmark and km.unmark ~= "" then
    vim.keymap.set("n", km.unmark, auditview.unmark, { desc = "auditview: unmark line" })
    vim.keymap.set("x", km.unmark, ":<C-u>lua require('auditview.marks').unmark_visual()<CR>",
      { desc = "auditview: unmark range", silent = true })
  end
  if km.note and km.note ~= "" then
    vim.keymap.set("n", km.note, auditview.note, { desc = "auditview: add note" })
    vim.keymap.set("x", km.note, ":<C-u>lua require('auditview.notes').add_visual(false)<CR>",
      { desc = "auditview: add note (range)", silent = true })
  end
  if km.todo and km.todo ~= "" then
    vim.keymap.set("n", km.todo, auditview.todo, { desc = "auditview: add TODO" })
    vim.keymap.set("x", km.todo, ":<C-u>lua require('auditview.notes').add_visual(true)<CR>",
      { desc = "auditview: add TODO (range)", silent = true })
  end
  if km.note_show and km.note_show ~= "" then
    vim.keymap.set("n", km.note_show, auditview.note_show,
      { desc = "auditview: show note at cursor" })
  end
  if km.note_detail and km.note_detail ~= "" then
    vim.keymap.set("n", km.note_detail, auditview.note_detail,
      { desc = "auditview: open note detail view" })
  end
  if km.note_delete and km.note_delete ~= "" then
    vim.keymap.set("n", km.note_delete, auditview.note_delete,
      { desc = "auditview: delete note at cursor" })
  end
  if km.notes_list and km.notes_list ~= "" then
    vim.keymap.set("n", km.notes_list, function() auditview.notes_list(false) end,
      { desc = "auditview: list notes in buffer" })
  end
  if km.next_unreviewed and km.next_unreviewed ~= "" then
    vim.keymap.set("n", km.next_unreviewed, auditview.jump_next_unreviewed,
      { desc = "auditview: jump to next unreviewed chunk" })
  end
  if km.prev_unreviewed and km.prev_unreviewed ~= "" then
    vim.keymap.set("n", km.prev_unreviewed, auditview.jump_prev_unreviewed,
      { desc = "auditview: jump to previous unreviewed chunk" })
  end
end
