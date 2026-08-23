import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, getLatestTimeline, type TimelineResponse } from "../api/client";

type TimelineState =
  | { status: "loading" }
  | { status: "none" }
  | { status: "error"; message: string }
  | { status: "ready"; timeline: TimelineResponse };

// Fixed intrinsic SVG dimensions — proportional positioning within a bounded
// canvas, never width = f(end_tick). A huge or sparse max tick compresses
// features; it never grows the SVG. The overflow-x:auto wrapper (index.css)
// still gives narrow screens something meaningful to scroll for legibility.
const SVG_WIDTH = 900;
const MARGIN_LEFT = 90;
const MARGIN_RIGHT = 20;
const MARGIN_TOP = 12;
const MARGIN_BOTTOM = 24;
const LANE_HEIGHT = 22;
const LANE_GAP = 6;

const EVENT_TYPES = ["REQUEST_ARRIVED", "REQUEST_STARTED", "REQUEST_FINISHED", "REQUEST_DROPPED"] as const;

function tickToX(tick: number, startTick: number, durationTicks: number): number {
  const innerWidth = SVG_WIDTH - MARGIN_LEFT - MARGIN_RIGHT;
  if (durationTicks <= 0) return MARGIN_LEFT;
  return MARGIN_LEFT + ((tick - startTick) / durationTicks) * innerWidth;
}

function axisTicks(startTick: number, durationTicks: number): number[] {
  const count = Math.min(10, durationTicks + 1);
  if (count <= 1) return [startTick];
  const ticks: number[] = [];
  for (let i = 0; i < count; i++) {
    ticks.push(Math.round(startTick + (i * durationTicks) / (count - 1)));
  }
  return Array.from(new Set(ticks));
}

function Axis({ startTick, durationTicks, height }: { startTick: number; durationTicks: number; height: number }) {
  return (
    <>
      {axisTicks(startTick, durationTicks).map((t) => {
        const x = tickToX(t, startTick, durationTicks);
        return (
          <g key={t}>
            <line x1={x} x2={x} y1={MARGIN_TOP - 4} y2={height - MARGIN_BOTTOM} className="timeline-gridline" />
            <text x={x} y={height - 6} textAnchor="middle" className="timeline-axis-label">
              {t}
            </text>
          </g>
        );
      })}
    </>
  );
}

function ServerLaneChart({ timeline }: { timeline: TimelineResponse }) {
  const { start_tick, end_tick, duration_ticks, servers } = timeline;
  const height = MARGIN_TOP + Math.max(servers.length, 1) * (LANE_HEIGHT + LANE_GAP) + MARGIN_BOTTOM;
  const label = `Server execution timeline, ticks ${start_tick} to ${end_tick}, ${servers.length} server lane(s).`;
  const description =
    "Each row is one server. A solid bar marks the ticks during which that server was actively running one " +
    "request; gaps are idle time. Exact start and finish ticks for every interval are listed in the requests " +
    "table below.";
  return (
    <svg role="img" aria-label={label} viewBox={`0 0 ${SVG_WIDTH} ${height}`} className="timeline-svg">
      <title>{label}</title>
      <desc>{description}</desc>
      <Axis startTick={start_tick} durationTicks={duration_ticks} height={height} />
      {servers.map((lane, i) => {
        const y = MARGIN_TOP + i * (LANE_HEIGHT + LANE_GAP);
        return (
          <g key={lane.server_id}>
            <text x={4} y={y + LANE_HEIGHT / 2 + 4} className="timeline-lane-label">
              {lane.server_id}
            </text>
            {lane.intervals.map((iv) => {
              const x1 = tickToX(iv.start_tick, start_tick, duration_ticks);
              const x2 = tickToX(iv.finish_tick, start_tick, duration_ticks);
              return (
                <rect
                  key={iv.request_id}
                  x={x1}
                  y={y}
                  width={Math.max(x2 - x1, 1)}
                  height={LANE_HEIGHT}
                  className="timeline-running-rect"
                />
              );
            })}
          </g>
        );
      })}
    </svg>
  );
}

const WAITING_PATTERN_ID = "timeline-waiting-pattern";

function LifecycleDefs() {
  return (
    <defs>
      {/* Diagonal-stripe texture for "waiting" — a genuine shape/texture
          distinction from the solid "running" fill, not a color-only one. */}
      <pattern id={WAITING_PATTERN_ID} width={6} height={6} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width={6} height={6} className="timeline-waiting-pattern-bg" />
        <line x1={0} y1={0} x2={0} y2={6} className="timeline-waiting-pattern-stroke" strokeWidth={2} />
      </pattern>
    </defs>
  );
}

function RequestLifecycleChart({ timeline }: { timeline: TimelineResponse }) {
  const { start_tick, end_tick, duration_ticks, requests } = timeline;
  const height = MARGIN_TOP + Math.max(requests.length, 1) * (LANE_HEIGHT + LANE_GAP) + MARGIN_BOTTOM;
  const label = `Request lifecycle timeline, ticks ${start_tick} to ${end_tick}, ${requests.length} request(s).`;
  const description =
    "Each row is one request. A striped bar marks time spent waiting for a server; a solid bar marks time spent " +
    "running. Circle, triangle, and square markers mark the arrival, start, and finish ticks; a dropped request " +
    "shows an × marker instead, with no bars. Exact tick values are listed in the requests table below.";
  return (
    <svg role="img" aria-label={label} viewBox={`0 0 ${SVG_WIDTH} ${height}`} className="timeline-svg">
      <title>{label}</title>
      <desc>{description}</desc>
      <LifecycleDefs />
      <Axis startTick={start_tick} durationTicks={duration_ticks} height={height} />
      {requests.map((r, i) => {
        const y = MARGIN_TOP + i * (LANE_HEIGHT + LANE_GAP);
        const midY = y + LANE_HEIGHT / 2 + 4;
        if (r.status === "dropped") {
          const x = tickToX(r.dropped_tick ?? r.arrival_tick, start_tick, duration_ticks);
          return (
            <g key={r.request_id} data-request-id={r.request_id}>
              <text x={4} y={midY} className="timeline-lane-label">
                {r.request_id}
              </text>
              <text x={x} y={midY} textAnchor="middle" className="timeline-dropped-marker">
                ×
              </text>
            </g>
          );
        }
        const arrivalX = tickToX(r.arrival_tick, start_tick, duration_ticks);
        const startX = tickToX(r.start_tick as number, start_tick, duration_ticks);
        const finishX = tickToX(r.finish_tick as number, start_tick, duration_ticks);
        return (
          <g key={r.request_id} data-request-id={r.request_id}>
            <text x={4} y={midY} className="timeline-lane-label">
              {r.request_id}
            </text>
            {startX > arrivalX ? (
              <rect
                x={arrivalX}
                y={y}
                width={startX - arrivalX}
                height={LANE_HEIGHT}
                className="timeline-waiting-rect"
                style={{ fill: `url(#${WAITING_PATTERN_ID})` }}
              />
            ) : null}
            <rect
              x={startX}
              y={y}
              width={Math.max(finishX - startX, 1)}
              height={LANE_HEIGHT}
              className="timeline-running-rect"
            />
            {/* Distinct vertical positions (not just midY for all three) so that
                arrival and start remain individually visible even when they
                share the same tick (wait_ticks === 0) and therefore the same x. */}
            <text x={arrivalX} y={y + 8} textAnchor="middle" className="timeline-marker-arrival">
              ●
            </text>
            <text x={startX} y={y + 15} textAnchor="middle" className="timeline-marker-start">
              ▲
            </text>
            <text x={finishX} y={y + 20} textAnchor="middle" className="timeline-marker-finish">
              ■
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function QueueDepthChart({ timeline }: { timeline: TimelineResponse }) {
  const { start_tick, end_tick, duration_ticks, queue_depth } = timeline;
  const height = 120;
  const chartTop = MARGIN_TOP;
  const chartBottom = height - MARGIN_BOTTOM;
  const actualPeak = queue_depth.length > 0 ? Math.max(...queue_depth.map((p) => p.depth)) : 0;
  const scaleMax = Math.max(1, actualPeak); // avoid a 0/0 scale when depth never leaves zero
  const label = `Queue depth over time, ticks ${start_tick} to ${end_tick}, peak depth ${actualPeak}.`;
  const description =
    "Step chart of the number of requests waiting in the queue at each tick. The vertical scale runs from 0 " +
    `(bottom) to the peak depth of ${actualPeak} (top). The exact tick and depth of every change point is listed ` +
    "in the table below.";

  function y(depth: number): number {
    return chartBottom - (depth / scaleMax) * (chartBottom - chartTop);
  }

  const points = queue_depth.length > 0 ? queue_depth : [{ tick: start_tick, depth: 0 }];
  let path = `M ${tickToX(points[0].tick, start_tick, duration_ticks)} ${y(points[0].depth)}`;
  for (let i = 1; i < points.length; i++) {
    const prev = points[i - 1];
    const curr = points[i];
    const x = tickToX(curr.tick, start_tick, duration_ticks);
    path += ` L ${x} ${y(prev.depth)} L ${x} ${y(curr.depth)}`;
  }
  const lastDepth = points[points.length - 1].depth;
  path += ` L ${tickToX(end_tick, start_tick, duration_ticks)} ${y(lastDepth)}`;

  return (
    <svg role="img" aria-label={label} viewBox={`0 0 ${SVG_WIDTH} ${height}`} className="timeline-svg">
      <title>{label}</title>
      <desc>{description}</desc>
      <Axis startTick={start_tick} durationTicks={duration_ticks} height={height} />
      <text x={MARGIN_LEFT - 6} y={y(0) + 3} textAnchor="end" className="timeline-queue-scale-label">
        0
      </text>
      {actualPeak > 0 ? (
        <text x={MARGIN_LEFT - 6} y={y(actualPeak) + 3} textAnchor="end" className="timeline-queue-scale-label">
          {actualPeak}
        </text>
      ) : null}
      <path d={path} className="timeline-queue-path" fill="none" />
    </svg>
  );
}

interface TimelinePanelProps {
  /** Bumped by App after any successful run, wherever it was started. */
  runVersion: number;
}

export default function TimelinePanel({ runVersion }: TimelinePanelProps) {
  const [state, setState] = useState<TimelineState>({ status: "loading" });
  const [requestFilter, setRequestFilter] = useState("");
  const [serverFilter, setServerFilter] = useState("");
  const [eventTypeFilters, setEventTypeFilters] = useState<Set<string>>(new Set(EVENT_TYPES));

  // Same monotonic generation-token pattern as RunPanel/MetricsPanel: a
  // response whose captured token no longer matches the current value is
  // stale and is discarded, regardless of resolution order.
  const generationRef = useRef(0);

  const loadTimeline = useCallback(async () => {
    const token = ++generationRef.current;
    setState({ status: "loading" });
    try {
      const timeline = await getLatestTimeline();
      if (token !== generationRef.current) return;
      setState({ status: "ready", timeline });
    } catch (err) {
      if (token !== generationRef.current) return;
      if (err instanceof ApiError && err.status === 404) {
        setState({ status: "none" });
        return;
      }
      const message = err instanceof ApiError ? err.message : "Unable to load the simulation timeline.";
      setState({ status: "error", message });
    }
  }, []);

  useEffect(() => {
    void loadTimeline();
    return () => {
      generationRef.current += 1;
    };
  }, [loadTimeline, runVersion]);

  const timeline = state.status === "ready" ? state.timeline : null;

  const filteredEvents = useMemo(() => {
    if (!timeline) return [];
    const requestNeedle = requestFilter.trim().toLowerCase();
    return timeline.events.filter((e) => {
      if (requestNeedle && !e.request_id.toLowerCase().includes(requestNeedle)) return false;
      if (serverFilter && e.server_id !== serverFilter) return false;
      if (!eventTypeFilters.has(e.event_type)) return false;
      return true;
    });
  }, [timeline, requestFilter, serverFilter, eventTypeFilters]);

  function toggleEventType(type: string) {
    setEventTypeFilters((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  return (
    <section className="panel timeline-panel" aria-labelledby="timeline-heading">
      <div className="panel-header">
        <h2 id="timeline-heading">Timeline</h2>
      </div>

      {state.status === "loading" ? <p>Loading timeline…</p> : null}
      {state.status === "none" ? <p>No simulation has been run yet.</p> : null}
      {state.status === "error" ? <p role="alert">{state.message}</p> : null}

      {timeline ? (
        <div aria-live="polite">
          {timeline.context_available ? (
            <p className="metrics-context-note">
              Strategy used: <strong>{timeline.strategy_used}</strong>.
            </p>
          ) : (
            <p className="metrics-context-note">
              Strategy context is unavailable for this trace. Server lanes, request lifecycle, and queue depth below
              are still accurate, trace-derived values.
            </p>
          )}

          <ul className="timeline-legend">
            <li>
              <span className="legend-glyph timeline-marker-arrival" aria-hidden="true">
                ●
              </span>{" "}
              Arrived (arrival tick)
            </li>
            <li>
              <span className="legend-glyph timeline-marker-start" aria-hidden="true">
                ▲
              </span>{" "}
              Started (start tick)
            </li>
            <li>
              <span className="legend-glyph timeline-marker-finish" aria-hidden="true">
                ■
              </span>{" "}
              Finished (finish tick)
            </li>
            <li>
              <span className="legend-glyph timeline-dropped-marker" aria-hidden="true">
                ×
              </span>{" "}
              Dropped (dropped tick)
            </li>
            <li>
              <span className="legend-swatch legend-swatch-waiting" aria-hidden="true" /> Waiting — striped, time
              between arrival and start
            </li>
            <li>
              <span className="legend-swatch legend-swatch-running" aria-hidden="true" /> Running — solid, time
              between start and finish
            </li>
          </ul>

          <h3>Server lanes</h3>
          <div className="timeline-scroll">
            <ServerLaneChart timeline={timeline} />
          </div>

          <h3>Request lifecycle</h3>
          <div className="timeline-scroll">
            <RequestLifecycleChart timeline={timeline} />
          </div>

          <h3>Queue depth</h3>
          <div className="timeline-scroll">
            <QueueDepthChart timeline={timeline} />
          </div>
          <table>
            <caption className="sr-only">
              Queue depth over time (tick / depth), ticks {timeline.start_tick} to {timeline.end_tick}. Every row is a
              sparse change point: each listed depth remains active until the next listed tick, and the last row's
              depth remains active through tick {timeline.end_tick} — sufficient to reconstruct the chart above
              exactly, with no row added for every integer tick in between.
            </caption>
            <thead>
              <tr>
                <th scope="col">Tick</th>
                <th scope="col">Depth</th>
              </tr>
            </thead>
            <tbody>
              {timeline.queue_depth.map((p) => (
                <tr key={p.tick}>
                  <td>{p.tick}</td>
                  <td>{p.depth}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <h3>Events</h3>
          <div className="timeline-event-filters">
            <label className="field">
              <span className="field-label">Request ID contains</span>
              <input
                type="text"
                value={requestFilter}
                onChange={(e) => setRequestFilter(e.target.value)}
                aria-label="Filter events by request ID"
              />
            </label>
            <label className="field">
              <span className="field-label">Server</span>
              <select
                value={serverFilter}
                onChange={(e) => setServerFilter(e.target.value)}
                aria-label="Filter events by server"
              >
                <option value="">All servers</option>
                {timeline.servers.map((s) => (
                  <option key={s.server_id} value={s.server_id}>
                    {s.server_id}
                  </option>
                ))}
              </select>
            </label>
            <fieldset className="timeline-event-type-filters">
              <legend className="field-label">Event type</legend>
              {EVENT_TYPES.map((type) => (
                <label key={type}>
                  <input type="checkbox" checked={eventTypeFilters.has(type)} onChange={() => toggleEventType(type)} />
                  {type}
                </label>
              ))}
            </fieldset>
          </div>
          <table>
            <caption className="sr-only">Filterable event list</caption>
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Tick</th>
                <th scope="col">Event</th>
                <th scope="col">Request</th>
                <th scope="col">Server</th>
              </tr>
            </thead>
            <tbody>
              {filteredEvents.map((e) => (
                <tr key={e.sequence}>
                  <td>{e.sequence}</td>
                  <td>{e.tick}</td>
                  <td>{e.event_type}</td>
                  <td>{e.request_id}</td>
                  <td>{e.server_id ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {filteredEvents.length === 0 ? <p>No events match the current filters.</p> : null}

          <h3>Requests</h3>
          <table>
            <caption className="sr-only">
              Request lifecycle detail — accessible fallback for the charts above
            </caption>
            <thead>
              <tr>
                <th scope="col">Request</th>
                <th scope="col">Arrival</th>
                <th scope="col">Wait</th>
                <th scope="col">Start</th>
                <th scope="col">Finish</th>
                <th scope="col">Server</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {timeline.requests.map((r) => (
                <tr key={r.request_id}>
                  <td>{r.request_id}</td>
                  <td>{r.arrival_tick}</td>
                  <td>{r.wait_ticks ?? "N/A"}</td>
                  <td>{r.start_tick ?? "N/A"}</td>
                  <td>{r.status === "dropped" ? `dropped @ ${r.dropped_tick}` : r.finish_tick}</td>
                  <td>{r.server_id ?? "N/A"}</td>
                  <td>{r.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
