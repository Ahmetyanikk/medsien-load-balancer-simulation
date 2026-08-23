import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getLatestAutoscaling, type AutoScaleResponse } from "../api/client";

type AutoScaleState =
  | { status: "loading" }
  | { status: "none" }
  | { status: "error"; message: string }
  | { status: "ready"; autoscale: AutoScaleResponse };

function formatNumber(value: number | null): string {
  return value === null ? "N/A" : String(value);
}

function formatRatio(value: number | null): string {
  return value === null ? "N/A" : `${(value * 100).toFixed(1)}%`;
}

function formatIdleServers(value: string[] | null): string {
  if (value === null) return "N/A";
  if (value.length === 0) return "None";
  return value.join(", ");
}

function actionBadge(action: AutoScaleResponse["action"]): { icon: string; text: string } {
  switch (action) {
    case "scale_up":
      return { icon: "▲", text: "Scale up" };
    case "scale_down":
      return { icon: "▼", text: "Scale down" };
    case "no_change":
      return { icon: "—", text: "No change" };
    default:
      return { icon: "?", text: "Unknown" };
  }
}

interface AutoScalePanelProps {
  /** Bumped by App after any successful run, wherever it was started. */
  runVersion: number;
}

export default function AutoScalePanel({ runVersion }: AutoScalePanelProps) {
  const [state, setState] = useState<AutoScaleState>({ status: "loading" });

  // Same monotonic generation-token pattern as RunPanel/MetricsPanel/TimelinePanel.
  const generationRef = useRef(0);

  const loadAutoscaling = useCallback(async () => {
    const token = ++generationRef.current;
    setState({ status: "loading" });
    try {
      const autoscale = await getLatestAutoscaling();
      if (token !== generationRef.current) return;
      setState({ status: "ready", autoscale });
    } catch (err) {
      if (token !== generationRef.current) return;
      if (err instanceof ApiError && err.status === 404) {
        setState({ status: "none" });
        return;
      }
      const message = err instanceof ApiError ? err.message : "Unable to load the auto-scaling recommendation.";
      setState({ status: "error", message });
    }
  }, []);

  useEffect(() => {
    void loadAutoscaling();
    return () => {
      generationRef.current += 1;
    };
  }, [loadAutoscaling, runVersion]);

  const autoscale = state.status === "ready" ? state.autoscale : null;
  const badge = autoscale?.recommendation_available ? actionBadge(autoscale.action) : null;

  return (
    <section className="panel" aria-labelledby="autoscale-heading">
      <div className="panel-header">
        <h2 id="autoscale-heading">Auto-scaling recommendation</h2>
      </div>

      {state.status === "loading" ? <p>Loading recommendation…</p> : null}
      {state.status === "none" ? <p>No simulation has been run yet.</p> : null}
      {state.status === "error" ? <p role="alert">{state.message}</p> : null}

      {autoscale ? (
        <div aria-live="polite">
          {autoscale.recommendation_available ? (
            <p className="autoscale-badge-row">
              <span className={`autoscale-badge autoscale-badge-${autoscale.action}`}>
                <span aria-hidden="true">{badge!.icon}</span> {badge!.text}
              </span>
            </p>
          ) : (
            <p className="autoscale-badge-row">
              <span className="autoscale-badge autoscale-badge-unavailable">Recommendation unavailable</span>
            </p>
          )}

          <p>{autoscale.explanation}</p>

          <dl className="summary-grid">
            <div className="summary-card">
              <dt>Total requests</dt>
              <dd>{autoscale.observed.total_requests}</dd>
            </div>
            <div className="summary-card">
              <dt>Dropped</dt>
              <dd>{autoscale.observed.dropped}</dd>
            </div>
            <div className="summary-card">
              <dt>Dropped rate (proxy)</dt>
              <dd>{formatRatio(autoscale.observed.dropped_rate)}</dd>
            </div>
            <div className="summary-card">
              <dt>Peak queue depth</dt>
              <dd>{autoscale.observed.peak_queue_depth}</dd>
            </div>
            <div className="summary-card">
              <dt>Avg queue depth</dt>
              <dd>{formatNumber(autoscale.observed.avg_queue_depth)}</dd>
            </div>
            <div className="summary-card">
              <dt>Cluster occupancy (proxy)</dt>
              <dd>{formatRatio(autoscale.observed.avg_cluster_busy_ratio)}</dd>
            </div>
            <div className="summary-card">
              <dt>Configured servers</dt>
              <dd>{formatNumber(autoscale.observed.configured_server_count)}</dd>
            </div>
            <div className="summary-card">
              <dt>Idle configured servers</dt>
              <dd>{formatIdleServers(autoscale.observed.idle_configured_server_ids)}</dd>
            </div>
          </dl>

          <p className="metrics-context-note">
            "Dropped rate" and "cluster occupancy" above are proxies, not literal application error rate or CPU
            utilization — see the limitations below.
          </p>

          {autoscale.suggested_server_delta !== null ? (
            <p>
              Suggested change: <strong>{autoscale.suggested_server_delta > 0 ? "+1 server" : "-1 server"}</strong>
            </p>
          ) : null}

          {autoscale.removal_candidate_server_ids ? (
            <p>
              Removal candidates (choose at most one): <strong>{autoscale.removal_candidate_server_ids.join(", ")}</strong>
            </p>
          ) : null}

          <p className="metrics-context-note">
            Recommendations are not applied automatically. To change server configuration for future runs, use the
            Servers panel.
          </p>

          <ul className="autoscale-limitations">
            {autoscale.limitations.map((limitation) => (
              <li key={limitation}>{limitation}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
