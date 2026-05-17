local M = {}

M.defaults = {
  base_url = "http://127.0.0.1:5000",

  reviewed_style = "line",
  reviewed_sign_text = "▎",
  reviewed_hl = "AuditviewReviewed",

  note_sign_text = "■",
  note_sign_hl = "AuditviewNoteSign",
  todo_sign_text = "◆",
  todo_sign_hl = "AuditviewTodoSign",

  note_virt_text = "cursor",
  note_virt_text_max_width = 60,
  note_virt_text_hl = "AuditviewNoteVirtText",
  todo_virt_text_hl = "AuditviewTodoVirtText",

  hover = {
    auto = true,
    border = "rounded",
    max_width = 80,
  },
  keymaps = {
    mark = "<leader>am",
    unmark = "<leader>au",
    note = "<leader>an",
    todo = "<leader>at",
    note_show = "<leader>aN",
    note_detail = "<leader>ao",
    note_delete = "<leader>aD",
    notes_list = "<leader>al",
    next_unreviewed = "]r",
    prev_unreviewed = "[r",
  },
  auto_keymaps = true,
}

M.options = vim.deepcopy(M.defaults)

function M.setup(opts)
  M.options = vim.tbl_deep_extend("force", M.defaults, opts or {})
end

return M
