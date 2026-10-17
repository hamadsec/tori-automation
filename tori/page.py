"""JavaScript helpers that pierce shadow DOM.

Tori's create-listing form renders its controls inside shadow roots, so
``document.querySelector`` finds nothing. Every helper here walks shadow roots
recursively. Inject ``PRELUDE`` at the top of an IIFE and the ``__find`` /
``__all`` / ``__setNative`` / ``__setSelectByText`` / ``__clickText`` helpers
become available.
"""

PRELUDE = r"""
const __seen = new Set();
function __find(pred, root, depth) {
  root = root || document; depth = depth || 0;
  if (depth > 9) return null;
  let n; try { n = root.querySelectorAll('*'); } catch (e) { return null; }
  for (const el of n) {
    if (el.shadowRoot && !__seen.has(el)) {
      __seen.add(el);
      const r = __find(pred, el.shadowRoot, depth + 1);
      if (r) return r;
    }
    if (pred(el)) return el;
  }
  return null;
}
function __all(pred) {
  const seen = new Set(); const out = [];
  (function walk(root, depth) {
    if (depth > 9) return;
    let n; try { n = root.querySelectorAll('*'); } catch (e) { return; }
    for (const el of n) {
      if (el.shadowRoot && !seen.has(el)) { seen.add(el); walk(el.shadowRoot, depth + 1); }
      if (pred(el)) out.push(el);
    }
  })(document, 0);
  return out;
}
function __setNative(el, value) {
  const proto = el.tagName === 'SELECT' ? HTMLSelectElement.prototype
              : el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype
              : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(el, value);
  el.dispatchEvent(new InputEvent('input', {bubbles: true, composed: true}));
  el.dispatchEvent(new Event('change', {bubbles: true, composed: true}));
}
function __setSelectByText(text, prefix) {
  const sels = __all(el => el.tagName === 'SELECT' && el.getBoundingClientRect().width > 0);
  for (const s of sels) {
    // exact match first, then a prefix match ("Vaatteet" -> "Vaatteet, kosmetiikka ja asusteet")
    const o = [...s.options].find(o => o.text.trim() === text)
           || [...s.options].find(o => o.text.trim().indexOf(text) === 0);
    if (o) { __setNative(s, o.value); return {ok: true, set: o.text.trim(), value: o.value}; }
  }
  return {ok: false, reason: 'option not found: ' + text,
          available: sels.map(s => [...s.options].map(o => o.text.trim()))};
}
function __numberField(label) {
  // Tori's numeric inputs are <w-textfield> custom elements whose visible
  // label lives on the HOST's label attribute, not on a <label for=...>.
  // Addressing them by index breaks the moment a category adds extra numeric
  // fields (Korkeus/Leveys/Syvyys), so address them by label instead.
  const hosts = __all(e => (e.tagName === 'W-TEXTFIELD')
                        && (e.getAttribute('label') || '').trim() === label);
  for (const h of hosts) {
    const inp = h.shadowRoot ? h.shadowRoot.querySelector('input')
                             : h.querySelector('input');
    if (inp) return inp;
  }
  return null;
}
function __numberFieldLabels() {
  return __all(e => e.tagName === 'W-TEXTFIELD')
    .filter(h => h.shadowRoot && h.shadowRoot.querySelector('input[type=number]'))
    .map(h => (h.getAttribute('label') || '').trim());
}
function __clickText(text) {
  const el = __find(e => {
    const t = (e.innerText || '').trim();
    return t === text && (e.tagName === 'BUTTON' || e.tagName === 'A' ||
                          e.getAttribute('role') === 'button');
  });
  if (!el) return {ok: false, reason: 'no clickable with text ' + text};
  el.click();
  return {ok: true, clicked: text};
}
function __selects() {
  return __all(el => el.tagName === 'SELECT' && el.getBoundingClientRect().width > 0)
    .map(s => ({value: s.value, options: [...s.options].map(o => ({v: o.value, t: o.text.trim()}))}));
}
"""


def wrap(body: str) -> str:
    """Wrap a JS body (use ``return`` for the value) as a self-contained IIFE."""
    return "(() => { " + PRELUDE + body + " })()"


def find(expression: str) -> str:
    """Evaluate ``expression`` in the page, returning a DOM node (objectId)."""
    return "(() => { " + PRELUDE + f"return __find({expression}); }})()"
