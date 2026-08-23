import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AutoScalePanel from "./AutoScalePanel";
import type { AutoScaleResponse } from "../api/client";

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

const LIMITATIONS = [
  "No work_units or memory-demand evidence is available to this recommendation.",
  "avg_cluster_busy_ratio is an occupancy/CPU-pressure proxy, not literal CPU utilization.",
  "dropped_rate is a dropped-request/error-pressure proxy, not a true application error rate.",
  "Only a single-step +1 or -1 recommendation is supported; there is no magnitude model.",
  "Thresholds are simple, explainable, uncalibrated heuristic defaults for this case study, not derived from production telemetry.",
  "Recommendations are never applied automatically.",
];

const NO_CHANGE_RESPONSE: AutoScaleResponse = {
  context_available: true,
  recommendation_available: true,
  action: "no_change",
  reason_codes: ["steady_state"],
  explanation: "No scaling signal was triggered; the cluster appears to be operating in a steady state.",
  suggested_server_delta: null,
  removal_candidate_server_ids: null,
  observed: {
    total_requests: 4,
    dropped: 0,
    dropped_rate: 0.0,
    peak_queue_depth: 1,
    avg_queue_depth: 0.25,
    avg_cluster_busy_ratio: 0.875,
    configured_server_count: 2,
    idle_configured_server_ids: [],
  },
  limitations: LIMITATIONS,
};

const SCALE_UP_RESPONSE: AutoScaleResponse = {
  ...NO_CHANGE_RESPONSE,
  action: "scale_up",
  reason_codes: ["dropped_requests"],
  explanation: "At least one request was dropped, which may indicate an incompatible capacity profile.",
  suggested_server_delta: 1,
  removal_candidate_server_ids: null,
  observed: { ...NO_CHANGE_RESPONSE.observed, dropped: 1, dropped_rate: 0.25 },
};

// Policy-coherent: scale-down requires dropped_rate 0, peak_queue_depth 0
// (compute_metrics can never show queue pressure alongside a scale-down
// recommendation — see domain/autoscale.py's low_occupancy branch), low
// occupancy, more than one configured server, and a non-empty, sorted idle
// server list.
const SCALE_DOWN_RESPONSE: AutoScaleResponse = {
  ...NO_CHANGE_RESPONSE,
  action: "scale_down",
  reason_codes: ["low_occupancy_idle_capacity"],
  explanation: "Average cluster occupancy is below the low-utilization threshold. Choose at most one candidate.",
  suggested_server_delta: -1,
  removal_candidate_server_ids: ["s2"],
  observed: {
    ...NO_CHANGE_RESPONSE.observed,
    total_requests: 2,
    dropped: 0,
    dropped_rate: 0,
    peak_queue_depth: 0,
    avg_queue_depth: 0,
    avg_cluster_busy_ratio: 0.01,
    idle_configured_server_ids: ["s2"],
  },
};

const UNAVAILABLE_RESPONSE: AutoScaleResponse = {
  context_available: false,
  recommendation_available: false,
  action: null,
  reason_codes: ["context_unavailable"],
  explanation: "Configured-server context is unavailable or unverified.",
  suggested_server_delta: null,
  removal_candidate_server_ids: null,
  observed: {
    total_requests: 4,
    dropped: 0,
    dropped_rate: 0.0,
    peak_queue_depth: 1,
    avg_queue_depth: 0.25,
    avg_cluster_busy_ratio: null,
    configured_server_count: null,
    idle_configured_server_ids: null,
  },
  limitations: LIMITATIONS,
};

describe("AutoScalePanel", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows a loading state before the initial fetch resolves", () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
    render(<AutoScalePanel runVersion={0} />);
    expect(screen.getByText(/loading recommendation/i)).toBeInTheDocument();
  });

  it("treats a 404 as the normal no-run state", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(404, { detail: "none" }));
    render(<AutoScalePanel runVersion={0} />);
    expect(await screen.findByText(/no simulation has been run yet/i)).toBeInTheDocument();
  });

  it("shows a generic error message on an unexpected failure", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(500, { detail: "boom" }));
    render(<AutoScalePanel runVersion={0} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/boom/i);
  });

  it("renders 'Recommendation unavailable', never 'No change', when recommendation_available is false", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, UNAVAILABLE_RESPONSE));
    render(<AutoScalePanel runVersion={0} />);

    expect(await screen.findByText(/recommendation unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/^no change$/i)).not.toBeInTheDocument();
  });

  it("renders the scale-up badge with icon and text", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, SCALE_UP_RESPONSE));
    render(<AutoScalePanel runVersion={0} />);

    const badge = await screen.findByText(/scale up/i);
    expect(badge).toBeInTheDocument();
    expect(badge.closest(".autoscale-badge")).toHaveTextContent("▲");
  });

  it("renders the scale-down badge with icon, text, and removal candidates", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, SCALE_DOWN_RESPONSE));
    render(<AutoScalePanel runVersion={0} />);

    const badge = await screen.findByText(/scale down/i);
    expect(badge.closest(".autoscale-badge")).toHaveTextContent("▼");
    expect(await screen.findByText(/removal candidates/i)).toHaveTextContent("s2");
    // Scale-down is only ever reachable with zero queue pressure.
    expect(SCALE_DOWN_RESPONSE.observed.peak_queue_depth).toBe(0);
  });

  it("renders idle configured servers as 'None' for the canonical (empty-list) response", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, NO_CHANGE_RESPONSE));
    render(<AutoScalePanel runVersion={0} />);
    await screen.findByText(/^no change$/i);

    const idleDt = screen.getByText("Idle configured servers");
    expect(idleDt.nextElementSibling).toHaveTextContent("None");
  });

  it("renders idle configured servers as 'N/A' for the unavailable (null) response", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, UNAVAILABLE_RESPONSE));
    render(<AutoScalePanel runVersion={0} />);
    await screen.findByText(/recommendation unavailable/i);

    const idleDt = screen.getByText("Idle configured servers");
    expect(idleDt.nextElementSibling).toHaveTextContent("N/A");
  });

  it("renders 's2' in the observed idle-servers card independently of the removal-candidates paragraph", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, SCALE_DOWN_RESPONSE));
    render(<AutoScalePanel runVersion={0} />);
    await screen.findByText(/scale down/i);

    // Two independently scoped assertions on two different DOM nodes — a
    // bug that removed either the idle-servers card or the candidates
    // paragraph (while "s2" still appeared once, in the other) would fail
    // exactly one of these, unlike a single unscoped getAllByText("s2").
    const idleDt = screen.getByText("Idle configured servers");
    expect(idleDt.nextElementSibling).toHaveTextContent("s2");

    const candidatesParagraph = screen.getByText(/removal candidates/i);
    expect(candidatesParagraph).toHaveTextContent("s2");
  });

  it("renders the no-change badge with icon and text", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, NO_CHANGE_RESPONSE));
    render(<AutoScalePanel runVersion={0} />);

    const badge = await screen.findByText(/^no change$/i);
    expect(badge.closest(".autoscale-badge")).toHaveTextContent("—");
  });

  it("renders null observed values as N/A", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, UNAVAILABLE_RESPONSE));
    render(<AutoScalePanel runVersion={0} />);

    await screen.findByText(/recommendation unavailable/i);
    const naValues = screen.getAllByText("N/A");
    expect(naValues.length).toBeGreaterThan(0);
  });

  it("explains the occupancy and dropped-rate proxy meanings", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, NO_CHANGE_RESPONSE));
    render(<AutoScalePanel runVersion={0} />);

    expect(await screen.findByText(/proxies, not literal application error rate or cpu utilization/i)).toBeInTheDocument();
  });

  it("renders the fixed limitations list", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, NO_CHANGE_RESPONSE));
    render(<AutoScalePanel runVersion={0} />);

    await screen.findByText(/^no change$/i);
    for (const limitation of LIMITATIONS) {
      expect(screen.getByText(limitation)).toBeInTheDocument();
    }
  });

  it("unconditionally states recommendations are not applied automatically", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, NO_CHANGE_RESPONSE));
    render(<AutoScalePanel runVersion={0} />);

    expect(await screen.findByText(/not applied automatically/i)).toBeInTheDocument();
    expect(screen.getByText(/servers panel/i)).toBeInTheDocument();
  });

  it("omits removal candidates when null", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, NO_CHANGE_RESPONSE));
    render(<AutoScalePanel runVersion={0} />);

    await screen.findByText(/^no change$/i);
    expect(screen.queryByText(/removal candidates/i)).not.toBeInTheDocument();
  });

  it("never renders an Apply button", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, SCALE_DOWN_RESPONSE));
    render(<AutoScalePanel runVersion={0} />);

    await screen.findByText(/scale down/i);
    expect(screen.queryByRole("button", { name: /apply/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("refetches when runVersion changes", async () => {
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch
      .mockResolvedValueOnce(jsonResponse(404, { detail: "none" }))
      .mockResolvedValueOnce(jsonResponse(200, NO_CHANGE_RESPONSE));

    const { rerender } = render(<AutoScalePanel runVersion={0} />);
    await screen.findByText(/no simulation has been run yet/i);

    rerender(<AutoScalePanel runVersion={1} />);

    expect(await screen.findByText(/^no change$/i)).toBeInTheDocument();
    expect(mockedFetch).toHaveBeenCalledTimes(2);
  });

  it("does not let a stale response overwrite a newer one", async () => {
    const first = createDeferred<Response>();
    const second = createDeferred<Response>();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    const { rerender } = render(<AutoScalePanel runVersion={0} />);
    rerender(<AutoScalePanel runVersion={1} />);
    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(2));

    await act(async () => {
      second.resolve(jsonResponse(200, NO_CHANGE_RESPONSE));
    });
    expect(await screen.findByText(/^no change$/i)).toBeInTheDocument();

    await act(async () => {
      first.resolve(jsonResponse(404, { detail: "none" }));
    });
    expect(screen.queryByText(/no simulation has been run yet/i)).not.toBeInTheDocument();
    expect(screen.getByText(/^no change$/i)).toBeInTheDocument();
  });
});
