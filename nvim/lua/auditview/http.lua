local config = require("auditview.config")

local M = {}

local function url_encode_segment(s)
  return (s:gsub("([^%w%-%._~/])", function(c)
    return string.format("%%%02X", string.byte(c))
  end))
end

function M.url(path)
  return config.options.base_url .. path
end

function M.encode_path(rel_path)
  return url_encode_segment(rel_path)
end

local function run(args)
  local result = vim.system(args, { text = true }):wait()
  if result.code ~= 0 then
    return nil, string.format("curl failed (%d): %s", result.code, result.stderr or "")
  end
  local ok, decoded = pcall(vim.json.decode, result.stdout)
  if not ok then
    return nil, "invalid JSON from server: " .. (result.stdout or ""):sub(1, 200)
  end
  return decoded, nil
end

function M.get(path)
  return run({ "curl", "-sS", "-X", "GET", M.url(path) })
end

function M.post(path, body)
  return run({
    "curl", "-sS", "-X", "POST",
    "-H", "Content-Type: application/json",
    "--data", vim.json.encode(body),
    M.url(path),
  })
end

function M.delete(path)
  return run({ "curl", "-sS", "-X", "DELETE", M.url(path) })
end

return M
