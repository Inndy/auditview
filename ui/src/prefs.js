const NS = 'auditview:'

export function getPref(key, defaultValue = null) {
  const raw = localStorage.getItem(NS + key)
  return raw !== null ? raw : defaultValue
}

export function setPref(key, value) {
  localStorage.setItem(NS + key, String(value))
}

export function getBoolPref(key, defaultValue = false) {
  const raw = localStorage.getItem(NS + key)
  if (raw === null) return defaultValue
  return raw === 'true' || raw === '1'
}

export function setBoolPref(key, value) {
  localStorage.setItem(NS + key, value ? 'true' : 'false')
}
