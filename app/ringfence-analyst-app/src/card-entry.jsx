/* Design-system card entry. Compiles this React app (src/app) into the design system's
   components/bundle.js as window.Ringfence.AnalystApp, so the live "Analyst application" card
   runs this source. The card always uses the MOCK data service (no backend in the design viewer).
   tokens.css and ringfence.css are already loaded there as the design system stylesheet. */
import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './app/App.jsx';
import { createStore } from './app/store.js';
import { createMockService } from './services/mockService.js';
import appCss from './styles/app.css';
import screensCss from './styles/app-screens.css';
import caseBCss from './styles/app-case-b.css';
import caseCCss from './styles/app-case-c.css';
import caseDCss from './styles/app-case-d.css';

function injectCss() {
  if (document.getElementById('rf-analyst-app-css')) return;
  const s = document.createElement('style');
  s.id = 'rf-analyst-app-css';
  s.textContent = [appCss, screensCss, caseBCss, caseCCss, caseDCss].join('\n');
  document.head.appendChild(s);
}

export function mount(el, opts) {
  const o = Object.assign({ routing: 'memory', start: 'queue', signIn: true }, opts || {});
  injectCss();
  const svc = createMockService();
  const store = createStore(svc, { routing: o.routing, start: o.start });
  if (o.signIn) store.signIn();
  const root = createRoot(el);
  root.render(<App store={store} />);
  return { store, unmount: () => { root.unmount(); svc.mock.dispose(); } };
}
export const version = '0.1.0';
