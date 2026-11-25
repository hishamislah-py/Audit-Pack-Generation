// Poll a job through the active DataSource until it reaches a terminal status (COMPLETED, FAILED, INTERRUPTED).
import { useEffect, useRef, useState } from "react";
import type { Job } from "../api/types";
import { useData } from "../data/DataProvider";

export const TERMINAL: ReadonlyArray<Job["status"]> = ["COMPLETED", "FAILED", "INTERRUPTED"];
export const POLL_INTERVAL_MS = 1000;

export function isActive(job: Job | null | undefined): boolean {
  return !!job && !TERMINAL.includes(job.status);
}

export function useJobPoller(jobId: string | null | undefined, onDone?: (job: Job) => void, intervalMs = POLL_INTERVAL_MS) {
  const data = useData();
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<unknown>();
  const doneRef = useRef(onDone);
  doneRef.current = onDone;

  useEffect(() => {
    setJob(null);
    setError(undefined);
    if (!jobId) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const tick = async () => {
      try {
        const j = await data.job(jobId);
        if (!live) return;
        setJob(j);
        if (TERMINAL.includes(j.status)) {
          doneRef.current?.(j);
          return;
        }
      } catch (e) {
        if (!live) return;
        setError(e); // keep polling through a transient error
      }
      timer = setTimeout(tick, intervalMs);
    };
    tick();
    return () => { live = false; if (timer) clearTimeout(timer); };
  }, [jobId, intervalMs, data]);

  return { job, error };
}
