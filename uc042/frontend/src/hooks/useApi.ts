// Load data from the backend with explicit loading / error states. No caching layer and no mock fallback: an error is
// shown as an error.
import { useCallback, useEffect, useRef, useState } from "react";

export interface ApiState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => void;
}

export function useApi<T>(load: () => Promise<T>, deps: ReadonlyArray<unknown>): ApiState<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(undefined);
    loadRef.current().then(
      (d) => { if (live) { setData(d); setLoading(false); } },
      (e) => { if (live) { setError(e); setLoading(false); } },
    );
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload };
}
