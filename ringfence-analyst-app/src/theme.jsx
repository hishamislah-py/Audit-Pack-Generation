/* Light / Dark theme controller. The DEFAULT theme comes from the backend (GET /api/ui/config -> default_theme, set by
   the server's --default-theme). A user's own choice is kept in localStorage ("ds-theme") and overrides it; choosing the
   option that equals the backend default clears the stored choice, so that user follows the backend again.
   The last default seen is cached ("ds-theme-default") so the first paint does not flash the wrong theme.
   The resolved theme is written to <html data-theme>. */
import React from 'react';

const THEMES = ['light', 'dark'];
const KEY = 'ds-theme';
const DEFAULT_KEY = 'ds-theme-default';
const FALLBACK = 'light';
const listeners = new Set();

const valid = (v) => THEMES.includes(v);
function read(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }       // storage blocked
function write(key, v) { try { if (v == null) localStorage.removeItem(key); else localStorage.setItem(key, v); } catch (e) { /* storage blocked */ } }

let serverDefault = valid(read(DEFAULT_KEY)) ? read(DEFAULT_KEY) : FALLBACK;

/** The user's own choice ('light' | 'dark'), or null when they follow the backend default. */
export function getPreference() {
  const v = read(KEY);
  return valid(v) ? v : null;
}
/** The theme actually shown. */
export function getTheme() { return getPreference() || serverDefault; }

function apply() {
  const theme = getTheme();
  const root = document.documentElement;
  if (root.getAttribute('data-theme') !== theme) {
    root.classList.add('ds-theme-switching');
    root.setAttribute('data-theme', theme);
    requestAnimationFrame(() => requestAnimationFrame(() => root.classList.remove('ds-theme-switching')));
  }
  listeners.forEach((fn) => fn(theme));
}

export function setPreference(theme) {
  if (!valid(theme)) return;
  write(KEY, theme === serverDefault ? null : theme);
  apply();
}

/** Apply the theme before the first render, then ask the backend for its default (when a backend is in use). */
export function initTheme({ baseUrl = '', fetchDefault = true } = {}) {
  apply();
  addEventListener('storage', (e) => { if (e.key === KEY || e.key === DEFAULT_KEY) apply(); });
  if (!fetchDefault || typeof fetch !== 'function') return Promise.resolve(serverDefault);
  return fetch(baseUrl + '/api/ui/config', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
    .then((r) => (r.ok ? r.json() : null))
    .then((cfg) => {
      if (cfg && valid(cfg.default_theme)) {
        serverDefault = cfg.default_theme;
        write(DEFAULT_KEY, serverDefault);
        if (getPreference() === serverDefault) write(KEY, null);   // an explicit choice equal to the default is redundant
        apply();
      }
      return serverDefault;
    })
    .catch(() => serverDefault);                                    // backend unreachable: keep the cached default
}

export function ThemeSwitch({ className }) {
  const [theme, setTheme] = React.useState(getTheme());
  React.useEffect(() => { listeners.add(setTheme); return () => listeners.delete(setTheme); }, []);
  return <div className={'theme-switch' + (className ? ' ' + className : '')} role="group" aria-label="Colour theme">
    {[['light', 'Light'], ['dark', 'Dark']].map(([v, l]) =>
      <button key={v} type="button" aria-pressed={theme === v} onClick={() => setPreference(v)}>{l}</button>)}
  </div>;
}
