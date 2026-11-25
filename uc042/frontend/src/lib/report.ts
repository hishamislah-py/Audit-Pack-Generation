// The 16 sections of the Phase 1 final audit pack, with the anchor IDs the backend renderer writes
// (uc042lib/final_pack/report.py SECTIONS). The AI-Generated Closing Summary is the final narrative section.
export interface ReportSection { n: number; anchor: string; title: string; ai: boolean }

export const REPORT_SECTIONS: ReportSection[] = [
  ["overview", "Audit overview", false], ["executive", "Executive summary", false], ["sources", "Source data inventory", false],
  ["reconciliation", "Deterministic reconciliation results", false], ["exceptions", "Exception register", false],
  ["evidence", "Supporting evidence", false], ["ai-summary", "AI investigation summary", true],
  ["ai-assessments", "AI investigative assessments", true], ["observations", "Confirmed observations", true],
  ["hypotheses", "Hypotheses (not established)", true], ["gaps", "Evidence gaps and conflicts", true],
  ["next-steps", "Suggested next steps", true], ["review", "Human review record", false],
  ["limitations", "Limitations and exclusions", false], ["provenance", "Audit trail and provenance", false],
  ["closing-summary", "AI-Generated Closing Summary", true],
].map(([anchor, title, ai], i) => ({ n: i + 1, anchor: anchor as string, title: title as string, ai: ai as boolean }));
