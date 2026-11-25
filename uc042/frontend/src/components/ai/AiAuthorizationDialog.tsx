// The analyst's explicit authorisation of one paid AI operation (an AI investigation of one exception, or the AI closing
// summary of a final review). Nothing is sent until the analyst ticks the statement and confirms; Cancel sends nothing.
// The backend records the authorisation (provider, model, analyst, time) before the job that calls the model is started.
import { useState, type ReactNode } from "react";
import { errorMessage } from "../../api/client";
import type { AiConfiguration, AiConfirmation } from "../../api/types";
import { useData } from "../../data/DataProvider";
import { useApi } from "../../hooks/useApi";
import { KeyValue, Loading, Modal, Notice } from "../common";

export type AiOperation = "INVESTIGATION" | "CLOSING_SUMMARY";

const TITLE: Record<AiOperation, string> = {
  INVESTIGATION: "Authorise an AI investigation",
  CLOSING_SUMMARY: "Authorise the AI closing summary",
};

export function AiAuthorizationDialog({ operation, context, onConfirm, onCancel }: {
  operation: AiOperation;
  /** What is being authorised: period, pack, exception or selected investigations (shown as label / value rows). */
  context: Array<[string, ReactNode]>;
  onConfirm: (authorization: AiConfirmation) => Promise<void>;
  onCancel: () => void;
}) {
  const data = useData();
  const config = useApi(() => data.aiConfiguration(), [data]);
  const [accepted, setAccepted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const c: AiConfiguration | undefined = config.data;
  // Without a configured provider an investigation is refused; a closing summary is then UNAVAILABLE (no model call).
  const blocked = !!c && !c.provider_configured && operation === "INVESTIGATION";
  const confirm = async () => {
    if (!c) return;
    setBusy(true);
    setError(undefined);
    try {
      await onConfirm({ confirmed: true, provider: c.provider, model: c.model });
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  };
  return (
    <Modal title={TITLE[operation]} wide onClose={() => !busy && onCancel()} footer={<>
      <button className="btn btn--ghost" onClick={onCancel} disabled={busy}>Cancel</button>
      <button className="btn btn--primary" onClick={confirm} disabled={busy || !c || !accepted || blocked}>
        {busy ? "Starting…" : operation === "INVESTIGATION" ? "Authorise and run" : "Authorise and generate"}</button>
    </>}>
      {config.loading ? <Loading label="Reading the AI configuration…" /> : !c ? <Notice tone="bad">{errorMessage(config.error)}</Notice> : (
        <div className="stack stack--sm">
          <KeyValue items={[...context,
            ["Provider and model", <span className="mono">{c.provider} · {c.model}{c.reasoning_effort ? ` · reasoning ${c.reasoning_effort}` : ""}</span>],
            ["Provider configured", c.provider_configured ? "Yes" : "No"]]} />
          {!c.provider_configured && (operation === "INVESTIGATION"
            ? <Notice tone="bad" title="The AI provider is not configured">The backend refuses the investigation until a provider is configured. {c.configuration_problem ?? ""}</Notice>
            : <Notice tone="warn" title="The AI provider is not configured">No model is called: the preview is built with the closing summary UNAVAILABLE, and GENERATE then needs a second acknowledgement.</Notice>)}
          <Notice tone="warn" title="Live API calls may incur charges">{c.charges_notice}</Notice>
          <ul className="small">
            {operation === "INVESTIGATION" ? <>
              <li>The AI uses only the approved evidence sources of this deterministic pack (hash-verified source records; never answer keys or verification material).</li>
              <li>Limits: {c.tool_limits.max_tool_calls ?? "–"} tool calls, {c.tool_limits.max_rounds ?? "–"} rounds, {c.tool_limits.total_timeout ?? "–"} s.</li>
              <li>It cannot resolve the exception, change the deterministic results or approve the audit.</li>
            </> : <>
              <li>The summary is written from the deterministic pack and the selected investigations only.</li>
              <li>It does not resolve exceptions, approve the audit or certify compliance.</li>
            </>}
          </ul>
          <label className="check"><input type="checkbox" checked={accepted} disabled={blocked} onChange={(e) => setAccepted(e.target.checked)} />
            <span>{c.statements[operation]}</span></label>
          {error !== undefined && <Notice tone="bad" title="The request was refused">{errorMessage(error)}</Notice>}
          <p className="xsmall muted">The authorisation is recorded (provider, model, analyst, time) before anything is run, and stays linked to the job.</p>
        </div>
      )}
    </Modal>
  );
}
