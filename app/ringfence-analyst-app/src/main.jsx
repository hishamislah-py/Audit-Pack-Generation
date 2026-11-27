/* Vite entry. Data service: ?service=http|mock, else VITE_DATA_SERVICE, else mock. */
import React from 'react';
import { createRoot } from 'react-dom/client';
import './styles/index.css';
import { initTheme } from './theme.jsx';
import App from './app/App.jsx';
import { createStore } from './app/store.js';
import { createDataService } from './services/index.js';

const kind = new URLSearchParams(location.search).get('service') || import.meta.env.VITE_DATA_SERVICE || 'mock';
const baseUrl = import.meta.env.VITE_API_BASE || '';
// Light / Dark, applied before the first render; the default theme comes from the backend (/api/ui/config).
initTheme({ baseUrl, fetchDefault: kind === 'http' });
const service = createDataService(kind, { baseUrl });
const store = createStore(service, { routing: 'hash', start: 'login' });
createRoot(document.getElementById('root')).render(<React.StrictMode><App store={store} /></React.StrictMode>);
