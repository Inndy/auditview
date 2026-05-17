local M = {}

M.defaults = {
  base_url = "http://127.0.0.1:5000",
  sign_text = "▎",
  sign_hl = "AuditviewReviewed",
  keymaps = {
    mark = "<leader>am",
    unmark = "<leader>au",
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
