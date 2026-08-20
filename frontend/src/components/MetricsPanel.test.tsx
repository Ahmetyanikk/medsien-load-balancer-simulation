import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MetricsPanel from "./MetricsPanel";

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

const CONTEXT_METRICS = {
  context_available: true,
  strategy_used: "fastest_finish",
  total_requests: 4,
  started: 4,
  finished: 4,
  dropped: 0,
  dropped_rate: 0.0,
  duration_ticks: 4,
  throughput_requests_per_tick: 1.0,
  peak_queue_depth: 1,
  avg_queue_depth: 0.25,
  configured_server_count: 2,
  idle_configured_server_ids: [],
  avg_cluster_busy_ratio: 0.875,
  servers: [
    { server_id: "s1", requests_handled: 2, work_units_total: null, busy_ticks: 4, busy_time_ratio: 1.0, cpu_units_per_tick: 10 },
    { server_id: "s2", requests_handled: 2, work_units_total: null, busy_ticks: 3, busy_time_ratio: 0.75, cpu_units_per_tick: 5 },
  ],
};

const TRACE_ONLY_METRICS = {
  ...CONTEXT_METRICS,
  context_available: false,
  strategy_used: null,
  configured_server_count: null,
  idle_configured_server_ids: null,
  avg_cluster_busy_ratio: null,
  servers: [
    { server_id: "s1", requests_handled: 2, work_units_total: null, busy_ticks: 4, busy_time_ratio: 1.0, cpu_units_per_tick: null },
    { server_id: "s2", requests_handled: 2, work_units_total: null, busy_ticks: 3, busy_time_ratio: 0.75, cpu_units_per_tick: null },
  ],
};

describe("MetricsPanel", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows a loading state before the initial fetch resolves", () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
    render(<MetricsPanel runVersion={0} />);
    expect(screen.getByText(/loading metrics/i)).toBeInTheDocument();
  });

  it("treats a 404 as the normal empty state", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(404, { detail: "none" }));
    render(<MetricsPanel runVersion={0} />);
    expect(await screen.findByText(/no simulation has been run yet/i)).toBeInTheDocument();
  });

  it("shows an error message on an unexpected failure", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(500, { detail: "boom" }));
    render(<MetricsPanel runVersion={0} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/boom/i);
  });

  it("renders trace-only totals plus per-server context detail when context is available", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, CONTEXT_METRICS));
    render(<MetricsPanel runVersion={0} />);

    expect(await screen.findByText(/strategy used/i)).toBeInTheDocument();
    expect(screen.getByText("fastest_finish")).toBeInTheDocument();
    expect(screen.getByText("87.5%")).toBeInTheDocument(); // avg_cluster_busy_ratio
    expect(screen.getByText("s1")).toBeInTheDocument();
    expect(screen.getByText("s2")).toBeInTheDocument();
  });

  it("renders trace-only per-server rows and a clear degraded note when context is unavailable", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, TRACE_ONLY_METRICS));
    render(<MetricsPanel runVersion={0} />);

    expect(await screen.findByText(/configured-server and strategy enrichment/i)).toBeInTheDocument();
    // trace-only totals must still render
    expect(screen.getByText("Duration (ticks)").nextElementSibling).toHaveTextContent("4");
    expect(screen.queryByText(/strategy used/i)).not.toBeInTheDocument();

    // trace-derived per-server rows must remain visible even without context
    expect(screen.getByText("s1")).toBeInTheDocument();
    expect(screen.getByText("s2")).toBeInTheDocument();
    expect(screen.getByText("75.0%")).toBeInTheDocument(); // s2 busy_time_ratio
    expect(screen.queryByText(/^idle configured servers:/i)).not.toBeInTheDocument();
  });

  it("shows a no-observed-server-execution message when metrics.servers is empty", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(200, { ...TRACE_ONLY_METRICS, servers: [] }),
    );
    render(<MetricsPanel runVersion={0} />);
    expect(await screen.findByText(/no server execution was observed/i)).toBeInTheDocument();
  });

  it("lists idle configured servers when present", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      jsonResponse(200, { ...CONTEXT_METRICS, idle_configured_server_ids: ["s3-idle"] }),
    );
    render(<MetricsPanel runVersion={0} />);
    expect(await screen.findByText(/idle configured servers/i)).toHaveTextContent("s3-idle");
  });

  it("refetches when runVersion changes", async () => {
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch
      .mockResolvedValueOnce(jsonResponse(404, { detail: "none" }))
      .mockResolvedValueOnce(jsonResponse(200, CONTEXT_METRICS));

    const { rerender } = render(<MetricsPanel runVersion={0} />);
    await screen.findByText(/no simulation has been run yet/i);

    rerender(<MetricsPanel runVersion={1} />);

    expect(await screen.findByText(/strategy used/i)).toBeInTheDocument();
    expect(mockedFetch).toHaveBeenCalledTimes(2);
  });

  it("does not let a stale response overwrite a newer one", async () => {
    const first = createDeferred<Response>();
    const second = createDeferred<Response>();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    const { rerender } = render(<MetricsPanel runVersion={0} />);
    rerender(<MetricsPanel runVersion={1} />);
    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(2));

    await act(async () => {
      second.resolve(jsonResponse(200, CONTEXT_METRICS));
    });
    expect(await screen.findByText(/strategy used/i)).toBeInTheDocument();

    await act(async () => {
      first.resolve(jsonResponse(404, { detail: "none" }));
    });
    expect(screen.queryByText(/no simulation has been run yet/i)).not.toBeInTheDocument();
    expect(screen.getByText(/strategy used/i)).toBeInTheDocument();
  });
});
