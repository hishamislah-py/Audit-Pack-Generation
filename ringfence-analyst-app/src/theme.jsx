/* Light / Dark / System theme controller (Money20/20 theme kit, theme.js). The choice is kept in localStorage
   ("ds-theme"); System follows the operating system. The resolved theme is written to <html data-theme>. */
import React from 'react';

const KEY = 'ds-theme';
const media = typeof matchMedia === 'function' ? matchMedia('(prefers-color-scheme: light)') : { matches: true, addEventListener() {} };
const listeners = new Set();

export function getPreference() {
  try { const v = localStorage.getItem(KEY); if (v === 'light' || v === 'dark') return v; } catch (e) { /* storage blocked */ }
  return 'system';
}
function apply(pref) {
  const theme = pref === 'system' ? (media.matches ? 'light' : 'dark') : pref;
  const root = document.documentElement;
  if (root.getAttribute('data-theme') !== theme) {
    root.classList.add('ds-theme-switching');
    root.setAttribute('data-theme', theme);
    requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove('ds-theme-switching')));
  }
  listeners.forEach((fn) => fn(pref));
}
export function setPreference(pref) {
  try { if (pref === 'system') localStorage.removeItem(KEY); else localStorage.setItem(KEY, pref); } catch (e) { /* storage blocked */ }
  apply(pref);
}
export function initTheme() {
  apply(getPreference());
  media.addEventListener('change', () => { if (getPreference() === 'system') apply('system'); });
  addEventListener('storage', (e) => { if (e.key === KEY) apply(getPreference()); });
}

export function ThemeSwitch({ className }) {
  const [pref, setPref] = React.useState(getPreference());
  React.useEffect(() => { listeners.add(setPref); return () => listeners.delete(setPref); }, []);
  return <div className={'theme-switch' + (className ? ' ' + className : '')} role="group" aria-label="Colour theme">
    {[['light', 'Light'], ['dark', 'Dark'], ['system', 'System']].map(([v, l]) =>
      <button key={v} type="button" aria-pressed={pref === v} onClick={() => setPreference(v)}>{l}</button>)}
  </div>;
}
