local M = {}

function M.visual_range()
  local bufnr = vim.api.nvim_get_current_buf()
  local mode = vim.fn.mode()
  if mode == "v" or mode == "V" or mode == "\22" then
    vim.cmd('normal! \27')
  end
  local s_pos = vim.fn.getpos("'<")
  local e_pos = vim.fn.getpos("'>")
  -- getpos returns {bufnum, lnum, col, off}; bufnum 0 means current buffer
  local s_buf = s_pos[1]
  local e_buf = e_pos[1]
  local s = s_pos[2]
  local e = e_pos[2]
  if (s_buf ~= 0 and s_buf ~= bufnr) or (e_buf ~= 0 and e_buf ~= bufnr)
      or s == 0 or e == 0 then
    local cur = vim.api.nvim_win_get_cursor(0)[1]
    return cur, cur
  end
  if s > e then s, e = e, s end
  return s, e
end

return M
