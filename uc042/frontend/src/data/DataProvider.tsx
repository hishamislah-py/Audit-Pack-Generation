// Chooses the data source once, explicitly. The real FastAPI adapter is the default. The mock adapter is used only when
// VITE_DATA_SOURCE=mock in a DEVELOPMENT build; it is imported dynamically under a build-time condition, so production
// bundles contain neither the mock code nor the captured data. There is never an automatic fallback between sources.
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { createApiSource } from "./apiSource";
import type { DataSource } from "./DataSource";

const DataContext = createContext<DataSource | null>(null);

export const MOCK_REQUESTED = import.meta.env.DEV && import.meta.env.VITE_DATA_SOURCE === "mock";

export async function createConfiguredSource(): Promise<DataSource> {
  if (import.meta.env.DEV && import.meta.env.VITE_DATA_SOURCE === "mock") {
    const { MockDataSource } = await import("./mock/MockDataSource");
    return new MockDataSource();
  }
  return createApiSource();
}

export function DataProvider({ source, children }: { source?: DataSource; children: ReactNode }) {
  const [value, setValue] = useState<DataSource | null>(source ?? (MOCK_REQUESTED ? null : createApiSource()));
  useEffect(() => {
    if (source) { setValue(source); return; }
    if (!MOCK_REQUESTED) return;
    let live = true;
    createConfiguredSource().then((s) => live && setValue(s));
    return () => { live = false; };
  }, [source]);
  if (!value) return null;
  return <DataContext.Provider value={value}>{children}</DataContext.Provider>;
}

export function useData(): DataSource {
  const ds = useContext(DataContext);
  if (!ds) throw new Error("useData must be used inside <DataProvider>");
  return ds;
}
