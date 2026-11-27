/* React bindings for the store (store.js). */
import React from 'react';

export const StoreContext = React.createContext(null);
export const useStoreApi = () => React.useContext(StoreContext);
export function useAppState() { const s = useStoreApi(); return React.useSyncExternalStore(s.subscribe, s.getState, s.getState); }

/* useQuery(key, fetcher, { poll, enabled, focus })
   key: a string; case-scoped keys MUST contain the case ref (e.g. 'run:RF-2026-10-004:RUN-…') so they
   refetch when the case revision changes. fetcher: (svc) => Promise. poll: ms or null (re-evaluated each render).
   Returns { data, error, loading (no data yet), refreshing, reload }. */
export function useQuery(key, fetcher, opts) {
  const o = opts || {};
  const store = useStoreApi();
  const enabled = !!key && o.enabled !== false;
  const get = () => (enabled ? store.getQuery(key) : EMPTY);
  const snap = React.useSyncExternalStore(store.subscribe, get, get);
  const ref = React.useRef(fetcher); ref.current = fetcher;
  React.useEffect(() => { if (!enabled) return undefined; return store.mountQuery(key, (svc) => ref.current(svc)); }, [key, enabled]);
  const poll = enabled ? o.poll || null : null;
  React.useEffect(() => { if (!poll) return undefined; const t = setInterval(() => store.refetch(key), poll); return () => clearInterval(t); }, [key, poll]);
  React.useEffect(() => { if (!enabled || !o.focus) return undefined; const f = () => store.refetch(key); window.addEventListener('focus', f); return () => window.removeEventListener('focus', f); }, [key, enabled, o.focus]);
  return { data: snap.data, error: snap.error, loading: enabled && snap.data === undefined && !snap.error, refreshing: snap.loading, reload: () => store.refetch(key) };
}
const EMPTY = Object.freeze({ data: undefined, error: null, loading: false, at: 0 });

/* useMutation(): { run(fn, opts) → Promise<result|null>, busy, error (message), code, reset }
   fn: (svc) => Promise. opts: { success: text|fn, inline: true (show the error in place, no toast), key }.
   Never throws. Refetches every mounted query after the call (contract §5). */
export function useMutation() {
  const store = useStoreApi();
  const [st, setSt] = React.useState({ busy: false, error: null, code: null });
  const alive = React.useRef(true);
  React.useEffect(() => () => { alive.current = false; }, []);
  const run = React.useCallback(async (fn, opts) => {
    setSt({ busy: true, error: null, code: null });
    const r = await store.mutate(fn, opts);
    if (alive.current) setSt({ busy: false, error: r.ok ? null : r.error.message, code: r.ok ? null : r.error.error });
    return r.ok ? (r.data == null ? true : r.data) : null;
  }, [store]);
  return { run, busy: st.busy, error: st.error, code: st.code, reset: () => setSt({ busy: false, error: null, code: null }) };
}
