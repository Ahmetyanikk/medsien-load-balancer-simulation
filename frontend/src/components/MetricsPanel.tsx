import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getLatestMetrics, type MetricsResponse } from "../api/client";

type MetricsState =
  | { status: "loading" }
  | { status: "none" }
  | { status: "error"; message: string }
  | { status: "ready"; metrics: MetricsResponse };

function formatNumber(value: number | null): string {
  return value === null ? "N/A" : String(value);
}

function formatRatio(value: number | null): string {
  return value === null ? "N/A" : `${(value * 100).toFixed(1)}%`;
}

interface MetricsPanelProps {
  /** Bumped by App after any successful run, wherever it was started. */
  runVersion: number;
}

export default function MetricsPanel({ runVersion }: MetricsPanelProps) {
  const [state, setState] = useState<MetricsState>({ status: "loading" });

  // Same monotonic generation-token pattern as RunPanel: a response whose
  // captured token no longer matches the current value is stale and is
  // discarded, regardless of resolution order.
  const generationRef = useRef(0);

  const loadMetrics = useCallback(async () => {
    const token = ++generationRef.current;
    setState({ status: "loading" });
    try {
      const metrics = await getLatestMetrics();
      if (token !== generationRef.current) return;
      setState({ status: "ready", metrics });
    } catch (err) {
      if (token !== generationRef.current) return;
      if (err instanceof ApiError && err.status === 404) {
        setState({ status: "none" });
        return;
      }
      const message = err instanceof ApiError ? err.message : "Unable to load simulation metrics.";
      setState({ status: "error", message });
    }
  }, []);

  useEffect(() => {
    void loadMetrics();
    return () => {
      generationRef.current += 1;
    };
    // runVersion covers both the initial mount fetch and every subsequent
    // successful run triggered anywhere (RunPanel's button or StrategySelector).
  }, [loadMetrics, runVersion]);

  return (
    <section className="panel" aria-labelledby="metrics-heading">
      <div className="panel-header">
        <h2 id="metrics-heading">Performance metrics</h2>
      </div>

      {state.status === "loading" ? <p>Loading metrics…</p> : null}
      {state.status === "none" ? <p>No simulation has been run yet.</p> : null}
      {state.status === "error" ? <p role="alert">{state.message}</p> : null}

      {state.status === "ready" ? (
        <div aria-live="polite">
          <dl className="summary-grid">
            <div className="summary-card">
              <dt>Duration (ticks)</dt>
              <dd>{state.metrics.duration_ticks}</dd>
            </div>
            <div className="summary-card">
              <dt>Throughput / tick</dt>
              <dd>{formatNumber(state.metrics.throughput_requests_per_tick)}</dd>
            </div>
            <div className="summary-card">
              <dt>Peak queue depth</dt>
              <dd>{state.metrics.peak_queue_depth}</dd>
            </div>
            <div className="summary-card">
              <dt>Avg queue depth</dt>
              <dd>{formatNumber(state.metrics.avg_queue_depth)}</dd>
            </div>
            <div className="summary-card">
              <dt>Dropped rate</dt>
              <dd>{formatRatio(state.metrics.dropped_rate)}</dd>
            </div>
          </dl>

          {state.metrics.context_available ? (
            <p className="metrics-context-note">
              Strategy used: <strong>{state.metrics.strategy_used}</strong>. Cluster busy ratio (occupancy /
              CPU-pressure proxy, not literal CPU utilization):{" "}
              <strong>{formatRatio(state.metrics.avg_cluster_busy_ratio)}</strong>.
            </p>
          ) : (
            <p className="metrics-context-note">
              Configured-server and strategy enrichment (cpu_units_per_tick, idle configured servers, cluster busy
              ratio, which strategy ran) is unavailable for this trace. Per-server totals below are still accurate,
              trace-derived values.
            </p>
          )}

          {/* Trace-derived per-server metrics (server_id, requests_handled, busy_ticks,
              busy_time_ratio) are always returned by the API regardless of
              context_available, and rendered here unconditionally — only the
              context-only columns/fields above depend on context_available. */}
          {state.metrics.servers.length > 0 ? (
            <>
              <table>
                <caption className="sr-only">Per-server metrics</caption>
                <thead>
                  <tr>
                    <th scope="col">Server</th>
                    <th scope="col">Requests handled</th>
                    <th scope="col">Busy ticks</th>
                    <th scope="col">Busy ratio (proxy)</th>
                    {state.metrics.context_available ? <th scope="col">CPU / tick</th> : null}
                  </tr>
                </thead>
                <tbody>
                  {state.metrics.servers.map((s) => (
                    <tr key={s.server_id}>
                      <td>{s.server_id}</td>
                      <td>{s.requests_handled}</td>
                      <td>{s.busy_ticks}</td>
                      <td>{formatRatio(s.busy_time_ratio)}</td>
                      {state.metrics.context_available ? <td>{formatNumber(s.cpu_units_per_tick)}</td> : null}
                    </tr>
                  ))}
                </tbody>
              </table>
              {state.metrics.context_available &&
              state.metrics.idle_configured_server_ids &&
              state.metrics.idle_configured_server_ids.length > 0 ? (
                <p>Idle configured servers: {state.metrics.idle_configured_server_ids.join(", ")}</p>
              ) : null}
            </>
          ) : (
            <p>No server execution was observed in this trace.</p>
          )}
        </div>
      ) : null}
    </section>
  );
}
