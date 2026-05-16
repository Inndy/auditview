if vim.g.loaded_auditview then return end
vim.g.loaded_auditview = true

local auditview = require("auditview")
local config = require("auditview.config")

vim.api.nvim_set_hl(0, "AuditviewReviewed", { link = "DiffAdd", default = true })

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

vim.api.nvim_create_user_command("AuditviewRefresh", auditview.refresh, {})
vim.api.nvim_create_user_command("AuditviewSessionReset", auditview.session_reset, {})

local group = vim.api.nvim_create_augroup("auditview", { clear = true })

vim.api.nvim_create_autocmd({ "BufReadPost", "BufWritePost" }, {
  group = group,
  callback = function(args) auditview.on_buf_read(args.buf) end,
})

vim.api.nvim_create_autocmd("BufUnload", {
  group = group,
  callback = function(args) auditview.on_buf_unload(args.buf) end,
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
end
