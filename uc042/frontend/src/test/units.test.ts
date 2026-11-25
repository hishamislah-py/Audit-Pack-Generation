import { describe, expect, it, vi, afterEach } from "vitest";
import { ApiError } from "../api/client";
import type { PackListItem, SourceRecord } from "../api/types";
import { createApiSource } from "../data/apiSource";
import { buildPeriods, periodLabel } from "../data/periods";
import { summarise, groupOf } from "../lib/evidence";
import { money } from "../lib/format";
import { REPORT_SECTIONS } from "../lib/report";
import { checkUpload, illustrativeFileNames } from "../lib/upload";

afterEach(() => vi.unstubAllGlobals());

const pack = (period: string): PackListItem => ({ pack_id: `PACK-X-${period}`, verified: true, problem: null,
  summary: { period_id: period } as PackListItem["summary"] });

describe("reconciliation periods", () => {
  it("lists January to the current month; September scenarios stay in September", () => {
    const packs = Array.from({ length: 9 }, () => pack("PER-2026-09"));
    const periods = buildPeriods(packs, new Date(Date.UTC(2026, 10, 3)));
    expect(periods.map((p) => p.label)).toEqual(["November 2026", "October 2026", "September 2026", "August 2026", "July 2026", "June 2026",
      "May 2026", "April 2026", "March 2026", "February 2026", "January 2026"]);
    expect(periods.map((p) => p.state)).toEqual(["OPEN_FOR_UPLOAD", "NO_DATA", "AVAILABLE", ...Array(8).fill("NO_DATA")]);
    expect(periods.find((p) => p.month === 9)!.packs).toHaveLength(9);
    expect(periods.filter((p) => p.month !== 9).every((p) => p.packs.length === 0)).toBe(true);
    expect(periodLabel("PER-2026-09")).toBe("September 2026");
  });
});

describe("financial formatting and evidence", () => {
  it("formats engine amounts without recalculating them", () => {
    expect(money("2868.50", "GBP")).toBe("£2,868.50");
    expect(money("-812.40", "GBP")).toBe("-£812.40");
    expect(money("0.00", "EUR")).toBe("€0.00");
  });

  it("keeps the recorded debit/credit direction", () => {
    const bank = { evidence_id: "IN-09:BE-GBP-0916-T01", file_id: "IN-09", fields: { amount: "2868.50", dc_indicator: "D", booking_date: "2026-09-16", currency: "GBP", narrative_text: "SB-GBP-20260915" } } as SourceRecord;
    const ledger = { evidence_id: "IN-10:LE-GBP-0915-0005", file_id: "IN-10", fields: { amount: "2868.50", dc_indicator: "C", posted_ts: "2026-09-15T16:00:00+01:00", currency: "GBP", entry_type: "SETTLEMENT_OUT" } } as SourceRecord;
    expect(summarise(bank)).toMatchObject({ dc: "D", amount: "2868.50", date: "2026-09-16" });
    expect(summarise(ledger)).toMatchObject({ dc: "C", amount: "2868.50", date: "2026-09-15" });
    expect([groupOf("IN-09"), groupOf("IN-10"), groupOf("IN-12"), groupOf("IN-99")]).toEqual(["bank", "cashbook", "settlement", "other"]);
  });

  it("maps the 16 Phase 1 report sections with the closing summary last", () => {
    expect(REPORT_SECTIONS).toHaveLength(16);
    expect(REPORT_SECTIONS.at(-1)).toMatchObject({ n: 16, anchor: "closing-summary", title: "AI-Generated Closing Summary", ai: true });
  });
});

describe("upload pre-checks", () => {
  it("accepts a complete set for the month (IN-19 is the previous month's receipt)", () => {
    const names = illustrativeFileNames("PER-2026-11");
    expect(names).toContain("rep027_submission_receipt_2026-10.pdf");
    const s = checkUpload("PER-2026-11", names.map((name) => ({ name, size: 100 })));
    expect([s.recognised, s.problems, s.missing_required.length, s.ready_for_processing]).toEqual([19, 0, 0, true]);
  });

  it("flags duplicates, wrong periods, unknown and unsupported files, and missing categories", () => {
    const s = checkUpload("PER-2026-11", [
      { name: "bank_statement_entries_2026-11.csv", size: 10 }, { name: "bank_statement_entries_2026-11.csv", size: 10 },
      { name: "sga_cashbook_entries_2026-09.csv", size: 10 }, { name: "notes.txt", size: 10 }, { name: "mystery.csv", size: 10 },
      { name: "transactions_2026-11.csv", size: 0 },
    ]);
    expect(s.files.map((f) => f.status)).toEqual(["VALID", "DUPLICATE", "WRONG_PERIOD", "UNSUPPORTED_TYPE", "UNKNOWN_DOCUMENT", "EMPTY_FILE"]);
    expect(s.missing_required.map((d) => d.id)).toContain("IN-10");
    expect(s.missing_required).toHaveLength(16);
    expect(s.ready_for_processing).toBe(false);
  });
});

describe("FastAPI adapter (next phase)", () => {
  it("calls the real endpoint and never falls back to mock data", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ type: "about:blank", title: "x", status: 500, detail: "boom", code: "INTERNAL_ERROR" }),
      { status: 500, headers: { "Content-Type": "application/problem+json" } }));
    vi.stubGlobal("fetch", fetchMock);
    const source = createApiSource();
    const err = (await source.packs().catch((e) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("INTERNAL_ERROR");
    expect(String((fetchMock.mock.calls[0] as unknown[])[0])).toBe("http://127.0.0.1:8000/api/v1/packs");
    expect(source.kind).toBe("api");
  });
});
