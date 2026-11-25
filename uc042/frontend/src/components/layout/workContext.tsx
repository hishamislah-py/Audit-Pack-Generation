// The analyst's current working context (selected reporting period, pack, exception, review, final pack) so the topbar,
// sidebar and numbered workflow navigation agree on where they are. Pages declare their context and breadcrumbs; nothing
// here fetches data. There is no default month: the period comes from the route (/reports/PER-YYYY-MM), from the pack or
// final pack being viewed (their identifiers carry the period), or, before anything is selected, from the backend's own
// period list (TopBar picks the newest period with data).
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { periodFromFinalPackId, periodFromPackId } from "../../data/periods";

export interface WorkContext {
  periodId?: string;
  packId?: string;
  exceptionId?: string;
  reviewId?: string;
  finalPackId?: string;
}

export type Crumb = { label: string; to?: string };

interface Ctx {
  work: WorkContext;
  setWork: (patch: Partial<WorkContext>) => void;
  crumbs: Crumb[];
  setCrumbs: (c: Crumb[]) => void;
}

const WorkCtx = createContext<Ctx | null>(null);

/** A pack or final pack always belongs to the period in its identifier, so selecting one selects its period. */
function withPeriod(patch: Partial<WorkContext>): Partial<WorkContext> {
  if (patch.periodId) return patch;
  const derived = periodFromPackId(patch.packId) ?? periodFromFinalPackId(patch.finalPackId);
  return derived ? { ...patch, periodId: derived } : patch;
}

export function WorkProvider({ children, initial = {} }: { children: ReactNode; initial?: WorkContext }) {
  const [work, setWorkState] = useState<WorkContext>(initial);
  const [crumbs, setCrumbs] = useState<Crumb[]>([]);
  const setWork = (patch: Partial<WorkContext>) => setWorkState((w) => {
    const p = withPeriod(patch);
    // Changing to another month clears the pack-level context of the previous month.
    const next = p.periodId && w.periodId && p.periodId !== w.periodId && !p.packId
      ? { periodId: p.periodId, ...p } as WorkContext : { ...w, ...p };
    return JSON.stringify(next) === JSON.stringify(w) ? w : next;
  });
  return <WorkCtx.Provider value={{ work, setWork, crumbs, setCrumbs }}>{children}</WorkCtx.Provider>;
}

export function useWork(): Ctx {
  const c = useContext(WorkCtx);
  if (!c) throw new Error("useWork must be used inside <WorkProvider>");
  return c;
}

/** Declare this page's breadcrumb trail and working context. */
export function usePage(crumbs: Crumb[], work: Partial<WorkContext> = {}) {
  const { setCrumbs, setWork } = useWork();
  const ck = JSON.stringify(crumbs);
  const wk = JSON.stringify(work);
  useEffect(() => { setCrumbs(JSON.parse(ck)); }, [ck]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setWork(JSON.parse(wk)); }, [wk]); // eslint-disable-line react-hooks/exhaustive-deps
}
