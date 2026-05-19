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
  local raw = result.stdout or ""
  local last_nl = raw:find("\n[^\n]*$")
  local body_str, status_str
  if last_nl then
    body_str = raw:sub(1, last_nl - 1)
    status_str = raw:sub(last_nl + 1)
  else
    body_str = raw
    status_str = ""
  end
  local status = tonumber(status_str) or 0
  local ok, decoded = pcall(vim.json.decode, body_str)
  if not ok then
    return nil, string.format("invalid JSON from server (HTTP %d): %s", status, body_str:sub(1, 200))
  end
  if status < 200 or status >= 300 then
    local msg = (type(decoded) == "table" and decoded.error) or body_str:sub(1, 200)
    return nil, string.format("HTTP %d: %s", status, msg)
  end
  return decoded, nil
end

function M.get(path)
  return run({ "curl", "-sS", "-X", "GET", "-w", "\n%{http_code}", M.url(path) })
end

function M.post(path, body)
  return run({
    "curl", "-sS", "-X", "POST",
    "-H", "Content-Type: application/json",
    "--data", vim.json.encode(body),
    "-w", "\n%{http_code}",
    M.url(path),
  })
end

function M.delete(path)
  return run({ "curl", "-sS", "-X", "DELETE", "-w", "\n%{http_code}", M.url(path) })
end

return M
