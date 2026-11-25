// The single HTTP client for the UC-042 backend. Every request goes through `request`: base URL, JSON parsing, problem-
// details errors and timeouts live here and nowhere else. It never substitutes mock data for a failed request.
import type { Problem } from "./types";

const env = import.meta.env;
export const API_BASE_URL: string = String(env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
const DEFAULT_TIMEOUT_MS = Number(env.VITE_API_TIMEOUT_MS) || 30_000;
export const LONG_TIMEOUT_MS = 180_000; // GENERATE assembles, renders and publishes synchronously

/** An error from the backend (problem details) or from the network, in one shape the UI can display. */
export class ApiError extends Error {
  readonly status: number; // 0 = network failure or timeout
  readonly code: string;
  readonly detail: string;
  readonly problem: Problem | null;

  constructor(status: number, code: string, detail: string, problem: Problem | null = null) {
    super(`${code}: ${detail}`);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.problem = problem;
  }

  /** Extra problem fields such as `blockers`, `job_id` or `final_pack_id`. */
  get extra(): Record<string, unknown> {
    return (this.problem ?? {}) as Record<string, unknown>;
  }
}

export function apiUrl(path: string): string {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

type Body = Record<string, unknown> | Array<unknown> | FormData | undefined;

interface Options {
  method?: "GET" | "POST" | "PATCH";
  body?: Body;
  timeoutMs?: number;
  as?: "json" | "text" | "blob";
  signal?: AbortSignal;
}

export async function request<T>(path: string, options: Options = {}): Promise<T> {
  const { method = "GET", body, timeoutMs = DEFAULT_TIMEOUT_MS, as = "json" } = options;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), timeoutMs);
  const forward = () => controller.abort(options.signal?.reason);
  options.signal?.addEventListener("abort", forward);
  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      method,
      // FormData (file upload) sets its own multipart Content-Type with the boundary.
      headers: body === undefined || body instanceof FormData ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : body instanceof FormData ? body : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (e) {
    if (options.signal?.aborted) throw e;
    const timedOut = controller.signal.aborted;
    throw new ApiError(0, timedOut ? "TIMEOUT" : "NETWORK_ERROR",
      timedOut ? `The backend did not respond within ${Math.round(timeoutMs / 1000)} s.`
        : `The backend at ${API_BASE_URL} cannot be reached. Is it running (python -m uc042app)?`);
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", forward);
  }
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  if (as === "text") return (await response.text()) as T;
  if (as === "blob") return (await response.blob()) as T;
  return (await response.json()) as T;
}

async function toApiError(response: Response): Promise<ApiError> {
  let problem: Problem | null = null;
  try {
    const data = await response.json();
    if (data && typeof data === "object" && "code" in data) problem = data as Problem;
  } catch {
    /* not JSON */
  }
  if (problem) return new ApiError(response.status, problem.code, problem.detail || problem.title, problem);
  return new ApiError(response.status, `HTTP_${response.status}`, response.statusText || "The backend returned an error.");
}

/** A user-facing message for any thrown value. */
export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.detail;
  if (e instanceof Error) return e.message;
  return String(e);
}
