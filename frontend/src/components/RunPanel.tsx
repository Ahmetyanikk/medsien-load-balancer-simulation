import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getLatestSimulation, runSimulation, type RunSummary } from "../api/client";

type LatestState =
  | { status: "loading" }
  | { status: "none" }
  | { status: "error"; message: string }
  | { status: "ready"; summary: RunSummary };

function formatWait(value: number | null): string {
  return value === null ? "N/A" : String(value);
}

interface RunPanelProps {
  /** Monotonic counter App bumps after ANY successful run, whether started
   * from this panel's own button or from StrategySelector. Refetching on
   * change keeps this panel in sync with runs triggered elsewhere. */
  runVersion: number;
  /** Notify App that this panel's own run succeeded, so sibling panels
   * (MetricsPanel, StrategySelector) can refresh too. */
  onRunCompleted: () => void;
}

export default function RunPanel({ runVersion, onRunCompleted }: RunPanelProps) {
  const [latest, setLatest] = useState<LatestState>({ status: "loading" });
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  // Monotonic generation token shared by loadLatest() and handleRun(): whichever
  // call incremented it *last* owns the right to write `latest`. Any call whose
  // captured token no longer matches the current value is stale — from a
  // superseded StrictMode double-invocation, an effect that has since been
  // cleaned up, or a GET that lost a race against a POST — and its result is
  // discarded instead of applied, regardless of resolution order. Plain refs
  // (not state) so bumping one never itself triggers a re-render.
  const generationRef = useRef(0);

  const loadLatest = useCallback(async () => {
    const token = ++generationRef.current;
    setLatest({ status: "loading" });
    try {
      const summary = await getLatestSimulation();
      if (token !== generationRef.current) return; // superseded — do not apply
      setLatest({ status: "ready", summary });
    } catch (err) {
      if (token !== generationRef.current) return; // superseded — do not apply
      if (err instanceof ApiError && err.status === 404) {
        setLatest({ status: "none" });
        return;
      }
      const message = err instanceof ApiError ? err.message : "Unable to load the latest simulation.";
      setLatest({ status: "error", message });
    }
  }, []);

  useEffect(() => {
    void loadLatest();
    return () => {
      // Invalidate this effect invocation's in-flight request on cleanup
      // (real unmount, or the synthetic unmount StrictMode performs to verify
      // effects tolerate being run twice) so a response arriving afterward can
      // never apply itself.
      generationRef.current += 1;
    };
    // runVersion in the dependency array covers both the initial mount fetch
    // (runVersion's initial value) and every subsequent successful run
    // triggered anywhere (this panel's own button or StrategySelector) — one
    // effect, no separate mount-only effect needed.
  }, [loadLatest, runVersion]);

  async function handleRun() {
    const token = ++generationRef.current;
    setRunning(true);
    setRunError(null);
    try {
      const summary = await runSimulation();
      if (token === generationRef.current) {
        setLatest({ status: "ready", summary });
        onRunCompleted();
      }
    } catch (err) {
      if (token === generationRef.current) {
        const message = err instanceof ApiError ? err.message : "Unable to run the simulation.";
        setRunError(message);
        // Deliberately do not touch `latest` here — a failed run preserves the
        // last successful summary, mirroring the backend's own atomic-publish
        // guarantee (a failed run never replaces the previous run.jsonl).
      }
    } finally {
      setRunning(false);
    }
  }

  const summary = latest.status === "ready" ? latest.summary : null;
  const initialLoadPending = latest.status === "loading";

  return (
    <section className="panel" aria-labelledby="run-heading">
      <div className="panel-header">
        <h2 id="run-heading">Simulation</h2>
        <button type="button" onClick={handleRun} disabled={running || initialLoadPending}>
          {running ? "Running…" : "Run simulation"}
        </button>
      </div>

      {runError ? (
        <p role="alert" className="form-error">
          {runError}
        </p>
      ) : null}

      {latest.status === "loading" ? <p>Loading latest simulation…</p> : null}
      {latest.status === "none" ? <p>No simulation has been run yet.</p> : null}
      {latest.status === "error" ? <p role="alert">{latest.message}</p> : null}

      {summary ? (
        <div aria-live="polite">
          <dl className="summary-grid">
            <div className="summary-card">
              <dt>Total</dt>
              <dd>{summary.total_requests}</dd>
            </div>
            <div className="summary-card">
              <dt>Started</dt>
              <dd>{summary.started}</dd>
            </div>
            <div className="summary-card">
              <dt>Finished</dt>
              <dd>{summary.finished}</dd>
            </div>
            <div className="summary-card">
              <dt>Dropped</dt>
              <dd>{summary.dropped}</dd>
            </div>
            <div className="summary-card">
              <dt>Avg wait</dt>
              <dd>{formatWait(summary.avg_wait_ticks)}</dd>
            </div>
            <div className="summary-card">
              <dt>P50 wait</dt>
              <dd>{formatWait(summary.p50_wait_ticks)}</dd>
            </div>
            <div className="summary-card">
              <dt>P95 wait</dt>
              <dd>{formatWait(summary.p95_wait_ticks)}</dd>
            </div>
            <div className="summary-card">
              <dt>Max wait</dt>
              <dd>{formatWait(summary.max_wait_ticks)}</dd>
            </div>
          </dl>
          <a className="download-link" href="/api/simulations/latest/download">
            Download run.jsonl
          </a>
        </div>
      ) : null}
    </section>
  );
}
