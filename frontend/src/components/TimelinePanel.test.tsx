import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import TimelinePanel from "./TimelinePanel";
import type { TimelineResponse } from "../api/client";

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// The complete, exact canonical persisted event sequence (matches
// backend/tests/test_timeline.py's SAMPLE_EVENTS / the real engine's D-007
// phase order for the provided sample) — not a truncated stub. Requests,
// intervals, total_requests, duration, and queue_depth are all consistent
// with this exact 12-event list.
const CANONICAL_EVENTS = [
  { sequence: 0, tick: 0, event_type: "REQUEST_ARRIVED", request_id: "r1", server_id: null },
  { sequence: 1, tick: 0, event_type: "REQUEST_ARRIVED", request_id: "r2", server_id: null },
  { sequence: 2, tick: 0, event_type: "REQUEST_STARTED", request_id: "r1", server_id: "s1" },
  { sequence: 3, tick: 0, event_type: "REQUEST_STARTED", request_id: "r2", server_id: "s2" },
  { sequence: 4, tick: 1, event_type: "REQUEST_ARRIVED", request_id: "r3", server_id: null },
  { sequence: 5, tick: 2, event_type: "REQUEST_FINISHED", request_id: "r1", server_id: "s1" },
  { sequence: 6, tick: 2, event_type: "REQUEST_FINISHED", request_id: "r2", server_id: "s2" },
  { sequence: 7, tick: 2, event_type: "REQUEST_ARRIVED", request_id: "r4", server_id: null },
  { sequence: 8, tick: 2, event_type: "REQUEST_STARTED", request_id: "r3", server_id: "s1" },
  { sequence: 9, tick: 2, event_type: "REQUEST_STARTED", request_id: "r4", server_id: "s2" },
  { sequence: 10, tick: 3, event_type: "REQUEST_FINISHED", request_id: "r4", server_id: "s2" },
  { sequence: 11, tick: 4, event_type: "REQUEST_FINISHED", request_id: "r3", server_id: "s1" },
];

const CANONICAL_TIMELINE: TimelineResponse = {
  context_available: true,
  strategy_used: "fastest_finish",
  total_requests: 4,
  start_tick: 0,
  end_tick: 4,
  duration_ticks: 4,
  requests: [
    { request_id: "r1", arrival_tick: 0, server_id: "s1", start_tick: 0, finish_tick: 2, dropped_tick: null, status: "finished", wait_ticks: 0 },
    { request_id: "r2", arrival_tick: 0, server_id: "s2", start_tick: 0, finish_tick: 2, dropped_tick: null, status: "finished", wait_ticks: 0 },
    { request_id: "r3", arrival_tick: 1, server_id: "s1", start_tick: 2, finish_tick: 4, dropped_tick: null, status: "finished", wait_ticks: 1 },
    { request_id: "r4", arrival_tick: 2, server_id: "s2", start_tick: 2, finish_tick: 3, dropped_tick: null, status: "finished", wait_ticks: 0 },
  ],
  servers: [
    { server_id: "s1", cpu_units_per_tick: 10, intervals: [{ request_id: "r1", start_tick: 0, finish_tick: 2 }, { request_id: "r3", start_tick: 2, finish_tick: 4 }] },
    { server_id: "s2", cpu_units_per_tick: 5, intervals: [{ request_id: "r2", start_tick: 0, finish_tick: 2 }, { request_id: "r4", start_tick: 2, finish_tick: 3 }] },
  ],
  events: CANONICAL_EVENTS,
  queue_depth: [
    { tick: 0, depth: 0 },
    { tick: 1, depth: 1 },
    { tick: 2, depth: 0 },
  ],
};

const DEGRADED_TIMELINE: TimelineResponse = {
  ...CANONICAL_TIMELINE,
  context_available: false,
  strategy_used: null,
  servers: CANONICAL_TIMELINE.servers.map((s) => ({ ...s, cpu_units_per_tick: null })),
};

// Memory-incompatible request (mirrors backend/tests/test_autoscale.py's
// srv("s1", cpu=10, mem=100) + req(mem=500) scenario): a verified context
// containing the one configured server produces an idle lane for it (empty
// intervals), since the request was dropped before ever reaching a server.
const DROPPED_TIMELINE: TimelineResponse = {
  context_available: true,
  strategy_used: "fastest_finish",
  total_requests: 1,
  start_tick: 0,
  end_tick: 0,
  duration_ticks: 0,
  requests: [
    { request_id: "r1", arrival_tick: 0, server_id: null, start_tick: null, finish_tick: null, dropped_tick: 0, status: "dropped", wait_ticks: null },
  ],
  servers: [{ server_id: "s1", cpu_units_per_tick: 10, intervals: [] }],
  events: [
    { sequence: 0, tick: 0, event_type: "REQUEST_ARRIVED", request_id: "r1", server_id: null },
    { sequence: 1, tick: 0, event_type: "REQUEST_DROPPED", request_id: "r1", server_id: null },
  ],
  queue_depth: [{ tick: 0, depth: 0 }],
};

// Internally coherent large/sparse-tick fixture: one request that arrives
// and starts at tick 0, finishes at tick 1,000,000 — matching server
// interval, events, and a single all-zero queue-depth point (it never
// waits, so depth never leaves zero). Exercises the fixed-viewBox behavior
// with a genuinely huge duration rather than just relabeling the canonical
// sample's aggregate fields while leaving its (much smaller) events/intervals
// unchanged.
const HUGE_TICK_TIMELINE: TimelineResponse = {
  context_available: true,
  strategy_used: "fastest_finish",
  total_requests: 1,
  start_tick: 0,
  end_tick: 1_000_000,
  duration_ticks: 1_000_000,
  requests: [
    { request_id: "r1", arrival_tick: 0, server_id: "s1", start_tick: 0, finish_tick: 1_000_000, dropped_tick: null, status: "finished", wait_ticks: 0 },
  ],
  servers: [{ server_id: "s1", cpu_units_per_tick: 1, intervals: [{ request_id: "r1", start_tick: 0, finish_tick: 1_000_000 }] }],
  events: [
    { sequence: 0, tick: 0, event_type: "REQUEST_ARRIVED", request_id: "r1", server_id: null },
    { sequence: 1, tick: 0, event_type: "REQUEST_STARTED", request_id: "r1", server_id: "s1" },
    { sequence: 2, tick: 1_000_000, event_type: "REQUEST_FINISHED", request_id: "r1", server_id: "s1" },
  ],
  queue_depth: [{ tick: 0, depth: 0 }],
};

function lifecycleGroup(container: HTMLElement, requestId: string): HTMLElement {
  const g = container.querySelector(`g[data-request-id="${requestId}"]`);
  if (!g) throw new Error(`no lifecycle group found for request ${requestId}`);
  return g as unknown as HTMLElement;
}

describe("TimelinePanel", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows a loading state before the initial fetch resolves", () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
    render(<TimelinePanel runVersion={0} />);
    expect(screen.getByText(/loading timeline/i)).toBeInTheDocument();
  });

  it("treats a 404 as the normal empty state", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(404, { detail: "none" }));
    render(<TimelinePanel runVersion={0} />);
    expect(await screen.findByText(/no simulation has been run yet/i)).toBeInTheDocument();
  });

  it("shows an error message on an unexpected failure", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(500, { detail: "boom" }));
    render(<TimelinePanel runVersion={0} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/boom/i);
  });

  it("renders server lanes, strategy note, and the accessible requests table on success", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, CANONICAL_TIMELINE));
    render(<TimelinePanel runVersion={0} />);

    expect(await screen.findByText(/strategy used/i)).toBeInTheDocument();
    expect(screen.getByText("fastest_finish")).toBeInTheDocument();

    const requestsHeading = screen.getByRole("heading", { name: /^requests$/i });
    const requestsTable = requestsHeading.nextElementSibling as HTMLElement;
    expect(within(requestsTable).getByText("r1")).toBeInTheDocument();
    expect(within(requestsTable).getByText("r3")).toBeInTheDocument();
    // r3 waited 1 tick before starting — visible in the accessible table's
    // Wait column (3rd cell: Request, Arrival, Wait, ...).
    const r3Row = within(requestsTable).getByText("r3").closest("tr")!;
    expect(r3Row.children[2]).toHaveTextContent("1");
  });

  it("renders a degraded note and omits the strategy line when context is unavailable, without hiding trace data", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, DEGRADED_TIMELINE));
    render(<TimelinePanel runVersion={0} />);

    expect(await screen.findByText(/strategy context is unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/strategy used/i)).not.toBeInTheDocument();
    // trace-derived detail must still render (appears in multiple views —
    // event table, requests table, lane labels — so assert presence, not uniqueness)
    expect(screen.getAllByText("r1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("s1").length).toBeGreaterThan(0);
  });

  it("r3 (a queued request) has a positive-width waiting segment and a running segment in its own lifecycle group", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, CANONICAL_TIMELINE));
    render(<TimelinePanel runVersion={0} />);
    await screen.findByText(/strategy used/i);

    const r3Group = lifecycleGroup(document.body, "r3");
    const waitingRect = r3Group.querySelector(".timeline-waiting-rect") as SVGRectElement | null;
    const runningRect = r3Group.querySelector(".timeline-running-rect") as SVGRectElement | null;
    expect(waitingRect).not.toBeNull();
    expect(runningRect).not.toBeNull();
    expect(Number(waitingRect!.getAttribute("width"))).toBeGreaterThan(0);
    expect(Number(runningRect!.getAttribute("width"))).toBeGreaterThan(0);
  });

  it("r1 (arrival == start, no wait) has no waiting segment, and same-tick arrival/start markers don't visually overlap", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, CANONICAL_TIMELINE));
    render(<TimelinePanel runVersion={0} />);
    await screen.findByText(/strategy used/i);

    const r1Group = lifecycleGroup(document.body, "r1");
    expect(r1Group.querySelector(".timeline-waiting-rect")).toBeNull();
    expect(r1Group.querySelector(".timeline-running-rect")).not.toBeNull();

    const arrivalMarker = within(r1Group).getByText("●");
    const startMarker = within(r1Group).getByText("▲");
    const finishMarker = within(r1Group).getByText("■");

    // r1: arrival_tick === start_tick === 0, so both markers share the same
    // tick-derived x — they must NOT also share the same y, or they'd render
    // on top of each other and become individually indistinguishable.
    const arrivalX = Number(arrivalMarker.getAttribute("x"));
    const startX = Number(startMarker.getAttribute("x"));
    const arrivalY = Number(arrivalMarker.getAttribute("y"));
    const startY = Number(startMarker.getAttribute("y"));
    expect(arrivalX).toBe(startX);
    expect(arrivalY).not.toBe(startY);

    // finish_tick (2) is strictly later than start_tick (0) within a 4-tick
    // window — the finish marker must sit at a correspondingly greater x.
    const finishX = Number(finishMarker.getAttribute("x"));
    expect(finishX).toBeGreaterThan(startX);
  });

  it("renders the dropped marker inside the dropped request's own lifecycle group, not merely in the legend", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, DROPPED_TIMELINE));
    render(<TimelinePanel runVersion={0} />);
    await screen.findByText(/dropped @ 0/i);

    const r1Group = lifecycleGroup(document.body, "r1");
    expect(within(r1Group).getByText("×")).toBeInTheDocument();
    expect(r1Group.querySelector(".timeline-running-rect")).toBeNull();
    expect(r1Group.querySelector(".timeline-waiting-rect")).toBeNull();
  });

  it("every SVG has role=img, a non-empty aria-label, and non-empty title/desc content", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, CANONICAL_TIMELINE));
    render(<TimelinePanel runVersion={0} />);
    await screen.findByText(/strategy used/i);

    const images = screen.getAllByRole("img");
    expect(images.length).toBeGreaterThanOrEqual(3); // server lanes, lifecycle, queue depth
    for (const svg of images) {
      expect(svg.getAttribute("aria-label")).toBeTruthy();
      const title = svg.querySelector("title");
      const desc = svg.querySelector("desc");
      expect(title?.textContent?.trim()).toBeTruthy();
      expect(desc?.textContent?.trim()).toBeTruthy();
    }
  });

  it("keeps a fixed SVG viewBox width regardless of a huge/sparse max tick", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, HUGE_TICK_TIMELINE));
    render(<TimelinePanel runVersion={0} />);
    await screen.findByText(/strategy used/i);

    const images = screen.getAllByRole("img");
    for (const svg of images) {
      const viewBox = svg.getAttribute("viewBox")!;
      const width = Number(viewBox.split(" ")[2]);
      expect(width).toBe(900); // SVG_WIDTH constant, independent of end_tick=1_000_000
    }
  });

  it("renders a semantic queue-depth table containing every supplied sparse point", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, CANONICAL_TIMELINE));
    render(<TimelinePanel runVersion={0} />);
    await screen.findByText(/strategy used/i);

    const caption = screen.getByText(/queue depth over time \(tick \/ depth\)/i);
    // Explains the sparse-representation semantics, not just the column names.
    expect(caption).toHaveTextContent(`ticks ${CANONICAL_TIMELINE.start_tick} to ${CANONICAL_TIMELINE.end_tick}`);
    expect(caption).toHaveTextContent(/remains active until the next listed tick/i);
    expect(caption).toHaveTextContent(new RegExp(`remains active through tick ${CANONICAL_TIMELINE.end_tick}`, "i"));

    const table = caption.closest("table") as HTMLElement;
    const rows = within(table).getAllByRole("row").slice(1); // drop header row
    expect(rows).toHaveLength(CANONICAL_TIMELINE.queue_depth.length);
    CANONICAL_TIMELINE.queue_depth.forEach((point, i) => {
      expect(rows[i].children[0]).toHaveTextContent(String(point.tick));
      expect(rows[i].children[1]).toHaveTextContent(String(point.depth));
    });
  });

  it("filters the event table by request ID", async () => {
    const user = userEvent.setup();
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, CANONICAL_TIMELINE));
    render(<TimelinePanel runVersion={0} />);
    await screen.findByText(/strategy used/i);

    const eventsTable = screen.getByText(/filterable event list/i).closest("table") as HTMLElement;
    expect(within(eventsTable).getAllByText("r1").length).toBeGreaterThan(0);
    expect(within(eventsTable).getAllByText("r2").length).toBeGreaterThan(0);

    await user.type(screen.getByLabelText(/filter events by request id/i), "r1");

    expect(within(eventsTable).queryByText("r2")).not.toBeInTheDocument();
    expect(within(eventsTable).getAllByText("r1").length).toBeGreaterThan(0);
  });

  it("independently filters the event table by server", async () => {
    const user = userEvent.setup();
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, CANONICAL_TIMELINE));
    render(<TimelinePanel runVersion={0} />);
    await screen.findByText(/strategy used/i);

    const eventsTable = screen.getByText(/filterable event list/i).closest("table") as HTMLElement;
    // r1/r2 STARTED on s1/s2 respectively — filtering to s2 must drop r1's rows.
    await user.selectOptions(screen.getByLabelText(/filter events by server/i), "s2");

    const remainingRequestCells = within(eventsTable)
      .getAllByRole("row")
      .slice(1)
      .map((row) => row.children[3].textContent);
    expect(remainingRequestCells).not.toContain("r1");
    expect(remainingRequestCells).toContain("r2");
  });

  it("independently filters the event table by event type", async () => {
    const user = userEvent.setup();
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, CANONICAL_TIMELINE));
    render(<TimelinePanel runVersion={0} />);
    await screen.findByText(/strategy used/i);

    const eventsTable = screen.getByText(/filterable event list/i).closest("table") as HTMLElement;
    // Uncheck everything except REQUEST_ARRIVED.
    await user.click(screen.getByRole("checkbox", { name: "REQUEST_STARTED" }));
    await user.click(screen.getByRole("checkbox", { name: "REQUEST_FINISHED" }));
    await user.click(screen.getByRole("checkbox", { name: "REQUEST_DROPPED" }));

    const remainingEventTypes = within(eventsTable)
      .getAllByRole("row")
      .slice(1)
      .map((row) => row.children[2].textContent);
    expect(new Set(remainingEventTypes)).toEqual(new Set(["REQUEST_ARRIVED"]));
  });

  it("renders the event table rows in exactly the response's sequence order", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, CANONICAL_TIMELINE));
    render(<TimelinePanel runVersion={0} />);
    await screen.findByText(/strategy used/i);

    const eventsTable = screen.getByText(/filterable event list/i).closest("table") as HTMLElement;
    const sequenceCells = within(eventsTable)
      .getAllByRole("row")
      .slice(1)
      .map((row) => Number(row.children[0].textContent));
    expect(sequenceCells).toEqual(CANONICAL_EVENTS.map((e) => e.sequence));
  });

  it("renders a semantic requests table unconditionally (accessible fallback, not hover-gated)", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, CANONICAL_TIMELINE));
    render(<TimelinePanel runVersion={0} />);
    await screen.findByText(/strategy used/i);

    const table = screen.getByText(/accessible fallback for the charts above/i).closest("table");
    expect(table).toBeInTheDocument();
    expect(within(table as HTMLElement).getAllByRole("row").length).toBeGreaterThan(1);
  });

  it("provides a horizontal scroll wrapper for the charts", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, CANONICAL_TIMELINE));
    render(<TimelinePanel runVersion={0} />);
    await screen.findByText(/strategy used/i);

    const wrappers = document.querySelectorAll(".timeline-scroll");
    expect(wrappers.length).toBeGreaterThanOrEqual(3);
  });

  it("refetches when runVersion changes", async () => {
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch
      .mockResolvedValueOnce(jsonResponse(404, { detail: "none" }))
      .mockResolvedValueOnce(jsonResponse(200, CANONICAL_TIMELINE));

    const { rerender } = render(<TimelinePanel runVersion={0} />);
    await screen.findByText(/no simulation has been run yet/i);

    rerender(<TimelinePanel runVersion={1} />);

    expect(await screen.findByText(/strategy used/i)).toBeInTheDocument();
    expect(mockedFetch).toHaveBeenCalledTimes(2);
  });

  it("does not let a stale response overwrite a newer one", async () => {
    const first = createDeferred<Response>();
    const second = createDeferred<Response>();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    const { rerender } = render(<TimelinePanel runVersion={0} />);
    rerender(<TimelinePanel runVersion={1} />);
    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(2));

    await act(async () => {
      second.resolve(jsonResponse(200, CANONICAL_TIMELINE));
    });
    expect(await screen.findByText(/strategy used/i)).toBeInTheDocument();

    await act(async () => {
      first.resolve(jsonResponse(404, { detail: "none" }));
    });
    expect(screen.queryByText(/no simulation has been run yet/i)).not.toBeInTheDocument();
    expect(screen.getByText(/strategy used/i)).toBeInTheDocument();
  });
});
