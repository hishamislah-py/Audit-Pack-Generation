import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { PACKS, confirmAi, mockSource, renderApp } from "./support";

const T = { timeout: 8000 };
const row = (id: string) => screen.getAllByText(id).find((el) => el.tagName === "TD")!.closest("tr")!;

describe("Dashboard and monthly periods", () => {
  it("shows January to November 2026 with September's nine test scenarios", async () => {
    renderApp("/");
    const rows = await screen.findAllByRole("row", { name: /2026/ }, T);
    expect(rows.map((r) => within(r).getAllByRole("cell")[0].textContent)).toEqual(expect.arrayContaining(["November 2026", "October 2026", "September 2026", "January 2026"]));
    expect(await screen.findByText(/9 demonstration scenarios for September 2026/, undefined, T)).toBeInTheDocument();
    expect(screen.getByText(/test scenarios of the same month, not\s+different months/)).toBeInTheDocument();
    expect(await screen.findByText(/^Scenario SC2 · /, undefined, T)).toBeInTheDocument();
    expect(screen.getByText("MOCK DATA · SIMULATED ACTIONS")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Exceptions", { selector: ".kpi__label" }).closest(".kpi")).toHaveTextContent("Exceptions3030 unresolved"), T);
  });

  it("shows empty states for months without data and the upload entry for the current month", async () => {
    renderApp("/?period=PER-2026-10");
    expect(await screen.findByText("No reconciliation data for October 2026", undefined, T)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("row", { name: /November 2026/ }));
    expect(await screen.findByText("November 2026 is open for upload")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upload financial documents" })).toHaveAttribute("href", "/upload?period=PER-2026-11");
  });

  it("navigates dashboard → pack → workspace → review through the workflow", async () => {
    const { source } = renderApp("/");
    await userEvent.click(await screen.findByText(/^Scenario SC2 · /, undefined, T));
    expect(await screen.findByRole("heading", { name: PACKS.SC2 }, T)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Investigate exceptions" }));
    expect(await screen.findByRole("heading", { name: /EXC-SC2-01/ }, T)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: /02\s*Reconciliation pack/ }));
    expect(await screen.findByRole("heading", { name: PACKS.SC2 }, T)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Open final review" }));
    // Navigating to the review URL is read-only: no session exists until the explicit action.
    await userEvent.click(await screen.findByRole("button", { name: "Open a new final review" }, T));
    expect(await screen.findByRole("heading", { name: "Final audit pack review" }, T)).toBeInTheDocument();
    expect((await source.reviews({ packId: PACKS.SC2 })).length).toBe(1);
  });
});

describe("Reconciliation pack details", () => {
  it("shows accounts, the 19-document source inventory, both reconciliation views and the exception register", async () => {
    renderApp(`/packs/${PACKS.SC2}`);
    expect(await screen.findByText("recon_calendar_2026-09.csv", undefined, T)).toBeInTheDocument();
    expect(screen.getByText("rep027_submission_receipt_2026-08.pdf")).toBeInTheDocument();
    expect(screen.getAllByRole("row").filter((r) => /^IN-\d\d/.test(r.textContent ?? "")).length).toBeGreaterThanOrEqual(19);
    expect(screen.getByText(/The firm's ledger balance vs the bank balance/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /Reconciliation differences/ }));
    const diff = await screen.findByText("External (ledger vs bank)");
    expect(within(diff.closest("tr")!).getByText("£2,868.50")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /Internal reconciliation/ }));
    expect(screen.getByText(/Safeguarding requirement vs safeguarding resources/)).toBeInTheDocument();
    const exc = screen.getByText("EXC-SC2-01").closest("tr")!;
    expect(within(exc).getByText("Unresolved")).toBeInTheDocument();
    expect(within(exc).getByText("£2,868.50")).toBeInTheDocument();
  });
});

describe("Exception and investigation workspace", () => {
  it("shows EXC-SC2-01 with bank debit 16 Sept and cashbook credit 15 Sept, findings and citations", async () => {
    renderApp(`/packs/${PACKS.SC2}/workspace/EXC-SC2-01`);
    expect(await screen.findByText("Bank records", { exact: false }, T)).toBeInTheDocument();
    const bank = row("IN-09:BE-GBP-0916-T01");
    expect(within(bank).getByText("D")).toHaveAttribute("title", "Debit");
    expect(within(bank).getByText("16 Sept 2026")).toBeInTheDocument();
    const ledger = row("IN-10:LE-GBP-0915-0005");
    expect(within(ledger).getByText("C")).toHaveAttribute("title", "Credit");
    expect(within(ledger).getByText("15 Sept 2026")).toBeInTheDocument();
    expect(screen.getAllByText("£2,868.50").length).toBeGreaterThan(1);
    expect(screen.getByText("INELIGIBLE")).toBeInTheDocument(); // both SC2 investigations fail current rule C-01
    await userEvent.click(screen.getByRole("tab", { name: /Observations/ }));
    expect(screen.getAllByText("Relevance to the discrepancy").length).toBeGreaterThan(0);
    const cite = screen.getAllByRole("button", { name: "IN-09:BE-GBP-0916-T01" })[0];
    await userEvent.click(cite);
    expect(await screen.findByLabelText("Citation IN-09:BE-GBP-0916-T01")).toBeInTheDocument();
    expect(screen.getByText("Source record · Engine retrieval (no AI)")).toBeInTheDocument(); // the record's origin is named
    expect(row("IN-09:BE-GBP-0916-T01")).toHaveClass("is-highlight");
    await userEvent.click(screen.getByRole("tab", { name: /Hypotheses/ }));
    expect(screen.getByText("No hypotheses were proposed.")).toBeInTheDocument(); // the tools-mode record has none
    await userEvent.selectOptions(screen.getByLabelText("Investigation record"), "INV-EXC-SC2-01-eb2021ac50e9");
    expect(await screen.findByText("Hypothesis · not established", undefined, T)).toBeInTheDocument();
  });

  it("simulates a run: completes to the captured investigation, or fails when none exists", async () => {
    renderApp(`/packs/${PACKS.SC2}/workspace/EXC-SC2-01`);
    await userEvent.click(await screen.findByRole("button", { name: "Run investigation" }, T));
    await confirmAi("Authorise an AI investigation");
    expect(await screen.findByText("Investigation complete", undefined, T)).toBeInTheDocument();
    expect(screen.getByText(/Simulated run: no AI call was made/)).toBeInTheDocument();

    renderApp(`/packs/${PACKS.SC3B}/workspace/EXC-SC3B-01`);
    expect(await screen.findByText("No investigation results", undefined, T)).toBeInTheDocument();
    await userEvent.click(screen.getAllByRole("button", { name: "Run investigation" }).at(-1)!);
    await confirmAi("Authorise an AI investigation");
    expect(await screen.findByText(/SIMULATED: AI investigations run on the backend/, undefined, T)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry investigation" })).toBeInTheDocument();
  });

  it("shows an error, not an endless 'Loading findings…', when the investigation cannot be loaded", async () => {
    // found in the report 19 end-to-end validation: a failed findings request left the panel loading for ever
    const source = mockSource();
    source.findings = () => Promise.reject(new Error("findings unavailable"));
    renderApp(`/packs/${PACKS.SC2}/workspace/EXC-SC2-01`, source);
    expect(await screen.findByText("The investigation could not be loaded", undefined, T)).toBeInTheDocument();
    expect(screen.queryByText("Loading findings…")).not.toBeInTheDocument();
  });
});

describe("Final audit-pack review", () => {
  async function openPreview(pack: string) {
    const view = renderApp(`/packs/${pack}/review`);
    await userEvent.click(await screen.findByRole("button", { name: "Open a new final review" }, T)); // explicit: never on page load
    await userEvent.click(await screen.findByRole("button", { name: "Generate closing summary and preview" }, T));
    await confirmAi("Authorise the AI closing summary");
    const frame = await screen.findByTitle("Final audit-pack preview", undefined, T);
    return { view, frame };
  }

  it("previews the real 16-section report with the AI closing summary last", async () => {
    const { frame } = await openPreview(PACKS.S05);
    expect(frame.getAttribute("srcdoc")).toContain("16. AI-Generated Closing Summary");
    expect(frame.getAttribute("sandbox")).toBe("allow-same-origin");
    const toc = screen.getByRole("navigation", { name: "Report sections" });
    const items = within(toc).getAllByRole("button");
    expect(items).toHaveLength(16);
    expect(items.at(-1)).toHaveTextContent("AI-Generated Closing Summary");
    expect(await screen.findByText("GENERATED · gpt", { exact: false }).catch(() => null)).toBeNull();
    expect(screen.getAllByText("GENERATED").length).toBeGreaterThan(0); // closing summary status of the live S05 preview
    await userEvent.click(screen.getByRole("tab", { name: "JSON" }));
    expect(await screen.findByLabelText("Canonical JSON")).toHaveTextContent("uc042-final-pack/1.0");
  });

  it("HOLD needs a reason and publishes nothing; GENERATE needs the acknowledgement and opens the simulated pack", async () => {
    await openPreview(PACKS.S05);
    await userEvent.click(screen.getByRole("button", { name: "HOLD" }));
    const hold = await screen.findByRole("dialog", { name: "Save decision: HOLD" });
    expect(within(hold).getByRole("button", { name: "SAVE HOLD" })).toBeDisabled();
    await userEvent.type(within(hold).getByRole("textbox"), "Awaiting the bank's payment trace.");
    await userEvent.click(within(hold).getByRole("button", { name: "SAVE HOLD" }));
    expect(await screen.findByText(/Decision saved: HOLD/, undefined, T)).toBeInTheDocument();
    expect(screen.getByText("Preview required")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Generate closing summary and preview" }));
    await confirmAi("Authorise the AI closing summary");
    await screen.findByTitle("Final audit-pack preview", undefined, T);
    const generate = screen.getByRole("button", { name: "GENERATE" });
    expect(generate).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /does not resolve any exception/ }));
    expect(generate).toBeEnabled();
    await userEvent.click(generate);
    const modal = await screen.findByRole("dialog", { name: "Authorise final audit-pack assembly" });
    expect(within(modal).getByText(/does/)).toHaveTextContent(/not resolve exceptions/);
    await userEvent.click(within(modal).getByRole("button", { name: "GENERATE PACK" }));
    expect(await screen.findByRole("heading", { name: /SIM-FAP-S05-PER-2026-09-v1/ }, T)).toBeInTheDocument();
    expect(screen.getAllByText("Integrity: not verified (simulated pack)").length).toBeGreaterThan(0);
    expect((await screen.findAllByText("INV-EXC-S05-01-65bd05498b9e", undefined, T)).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("tab", { name: /Version history/ }));
    expect(await screen.findByRole("cell", { name: "v1" })).toBeInTheDocument();
  });

  it("requires acknowledging an unavailable closing summary, and selection changes invalidate the preview", async () => {
    await openPreview(PACKS.SC2);
    expect(screen.getAllByText(/closing summary could not be generated/).length).toBeGreaterThan(0);
    await userEvent.click(screen.getByRole("checkbox", { name: /does not resolve any exception/ }));
    expect(screen.getByRole("button", { name: "GENERATE" })).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: /closing summary is unavailable/ }));
    expect(screen.getByRole("button", { name: "GENERATE" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog", { name: "Investigation selections" });
    await userEvent.selectOptions(within(dialog).getByLabelText("Inclusion for EXC-SC2-01"), "EXCLUDED_BY_ANALYST");
    await userEvent.type(within(dialog).getByLabelText("Exclusion reason for EXC-SC2-01"), "Both investigations fail current rules.");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save selections" }));
    expect(await screen.findByText("Preview required")).toBeInTheDocument();
  });
});

describe("Upload workflow (design only)", () => {
  it("classifies an illustrative set and keeps processing unavailable", async () => {
    renderApp("/upload?period=PER-2026-11");
    await userEvent.click(await screen.findByRole("button", { name: "Load illustrative file set" }, T));
    expect(await screen.findByText("19 / 19")).toBeInTheDocument();
    expect(screen.getByText(/Every required document is present once/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "5. Start processing" })).toBeDisabled();
    expect(screen.getByText(/the backend has no ingestion endpoint/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Remove sga_cashbook_entries_2026-11.csv" }));
    expect(await screen.findByText("Missing expected documents")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText(/IN-10 · Safeguarding-account cash book/)).toBeInTheDocument());
  });
});
