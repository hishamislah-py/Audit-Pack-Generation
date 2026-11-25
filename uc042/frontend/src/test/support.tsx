// TEST-ONLY helpers: the MockDataSource reading the captured fixtures straight from public/mock-data on disk, with a
// fixed clock (3 Nov 2026) and fast simulated timings, rendered inside the real app routes.
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ApiError } from "../api/client";
import { AppRoutes } from "../App";
import type { DataSource } from "../data/DataSource";
import { DataProvider } from "../data/DataProvider";
import type { FixtureLoader } from "../data/mock/fixtures";
import { MockDataSource } from "../data/mock/MockDataSource";

const ROOT = join(__dirname, "..", "..", "dev-fixtures", "mock-data");

export const diskLoader: FixtureLoader = {
  json: async <T,>(path: string) => {
    try { return JSON.parse(await readFile(join(ROOT, `${path}.json`), "utf-8")) as T; } catch { throw new ApiError(404, "NOT_FOUND", `not found in the mock data set (${path})`); }
  },
  text: async (path) => readFile(join(ROOT, path), "utf-8"),
  blob: async (path) => new Blob([await readFile(join(ROOT, path))]),
};

export const NOW = Date.UTC(2026, 10, 3, 10, 0, 0);
export const FAST = { queuedMs: 5, investigationMs: 40, previewMs: 40, generateMs: 5 };

const START = Date.now();

/** A fresh mock source whose clock starts at 3 Nov 2026 and advances in real time (simulated jobs progress). */
export function mockSource(): MockDataSource {
  return new MockDataSource(diskLoader, FAST, () => NOW + (Date.now() - START));
}

export function renderApp(path: string, source: DataSource = mockSource()) {
  const view = render(<DataProvider source={source}><MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter></DataProvider>);
  return { ...view, source };
}

export const PACKS = {
  S05: "PACK-S05-PER-2026-09-ddd0fdc8b731",
  SC2: "PACK-SC2-PER-2026-09-aaca8a8b7194",
  SC3B: "PACK-SC3B-PER-2026-09-137351796028",
  S01: "PACK-S01-PER-2026-09-577b06a1d894",
};

/** Confirm the AI authorisation dialog (tick the statement, then confirm): the only way a paid AI operation starts. */
export async function confirmAi(title: "Authorise an AI investigation" | "Authorise the AI closing summary") {
  const dialog = await screen.findByRole("dialog", { name: title }, { timeout: 15000 });
  await userEvent.click(await within(dialog).findByRole("checkbox", undefined, { timeout: 15000 }));
  await userEvent.click(within(dialog).getByRole("button", { name: /^Authorise and / }));
}
