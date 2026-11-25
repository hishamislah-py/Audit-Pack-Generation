// Display formatting only. Amounts are decimal strings from the engine: they are formatted, never recalculated.
const DATE = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
const DATETIME = new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit",
  minute: "2-digit", timeZone: "Europe/London", timeZoneName: "short" });

/** "-812.40" + "GBP" -> "-£812.40". Grouping is added for readability; digits and sign are the engine's. */
export function money(amount: string | null | undefined, currency?: string | null): string {
  if (amount === null || amount === undefined || amount === "") return "—";
  const m = /^(-)?(\d+)(\.\d+)?$/.exec(String(amount).trim());
  if (!m) return String(amount);
  const grouped = m[2].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const symbol = currency ? ({ GBP: "£", EUR: "€", USD: "$" } as Record<string, string>)[currency] : undefined;
  const body = `${grouped}${m[3] ?? ""}`;
  return `${m[1] ?? ""}${symbol ?? ""}${body}${!symbol && currency ? ` ${currency}` : ""}`;
}

export function isNonZero(amount: string | null | undefined): boolean {
  return !!amount && /[1-9]/.test(amount);
}

export function date(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T00:00:00Z` : iso);
  return Number.isNaN(d.getTime()) ? iso : DATE.format(d);
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : DATETIME.format(d);
}

export function shortHash(sha: string | null | undefined, n = 12): string {
  return sha ? sha.slice(0, n) : "—";
}

export function humanize(code: string | null | undefined): string {
  if (!code) return "—";
  return code.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase());
}
