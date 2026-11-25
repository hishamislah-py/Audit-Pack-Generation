// Loads the captured fixtures (frontend/public/mock-data, produced by scripts/capture_mock_data.py from the real backend).
// A missing fixture is reported exactly like a backend 404; nothing is invented to fill the gap.
import { ApiError } from "../../api/client";

export interface FixtureLoader {
  json<T>(path: string): Promise<T>;
  text(path: string): Promise<string>;
  blob(path: string): Promise<Blob>;
}

export function fetchLoader(base = `${import.meta.env.BASE_URL}mock-data/`): FixtureLoader {
  const get = async (path: string): Promise<Response> => {
    const r = await fetch(`${base}${path}`);
    if (!r.ok) throw new ApiError(404, "NOT_FOUND", `not found in the mock data set (${path})`);
    return r;
  };
  return {
    json: async <T,>(path: string) => {
      const r = await get(`${path}.json`);
      const type = r.headers.get("content-type") ?? "";
      if (!type.includes("json")) throw new ApiError(404, "NOT_FOUND", `not found in the mock data set (${path})`); // dev-server HTML fallback
      return (await r.json()) as T;
    },
    text: async (path: string) => (await get(path)).text(),
    blob: async (path: string) => (await get(path)).blob(),
  };
}
