export function debounce(fn, wait) {
  let t = null;
  let lastArgs = null;
  const wrapped = (...args) => {
    lastArgs = args;
    if (t !== null) clearTimeout(t);
    t = setTimeout(() => { t = null; fn(...lastArgs); }, wait);
  };
  wrapped.cancel = () => {
    if (t !== null) { clearTimeout(t); t = null; }
  };
  wrapped.flush = () => {
    if (t !== null) { clearTimeout(t); t = null; fn(...(lastArgs || [])); }
  };
  return wrapped;
}
