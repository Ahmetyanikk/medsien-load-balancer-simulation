import { StrictMode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import RunPanel from "./RunPanel";

/** Deferred promise: lets a test control exactly when a mocked fetch call
 * resolves, so ordering races can be reproduced deterministically — no
 * setTimeout, no sleep, no timing assumptions. */
function createDeferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const SUMMARY = {
  status: "completed" as const,
  total_requests: 7,
  started: 6,
  finished: 5,
  dropped: 1,
  avg_wait_ticks: 2.5,
  p50_wait_ticks: 2,
  p95_wait_ticks: 4,
  max_wait_ticks: 9,
};

const NULL_SUMMARY = {
  status: "completed" as const,
  total_requests: 3,
  started: 0,
  finished: 0,
  dropped: 3,
  avg_wait_ticks: null,
  p50_wait_ticks: null,
  p95_wait_ticks: null,
  max_wait_ticks: null,
};

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("RunPanel", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows a loading state before the initial fetch resolves", () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
    render(<RunPanel />);
    expect(screen.getByText(/loading latest simulation/i)).toBeInTheDocument();
  });

  it("treats a 404 on latest as the normal empty state", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(404, { detail: "no simulation has been run yet" }));
    render(<RunPanel />);
    expect(await screen.findByText(/no simulation has been run yet/i)).toBeInTheDocument();
  });

  it("renders the summary when latest returns 200", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, SUMMARY));
    render(<RunPanel />);
    expect(await screen.findByText("7")).toBeInTheDocument();
  });

  it("sends a POST when the run button is clicked", async () => {
    const user = userEvent.setup();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch.mockResolvedValueOnce(jsonResponse(404, { detail: "none" })).mockResolvedValueOnce(jsonResponse(200, SUMMARY));

    render(<RunPanel />);
    await screen.findByText(/no simulation has been run yet/i);

    await user.click(screen.getByRole("button", { name: /run simulation/i }));

    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(2));
    expect(mockedFetch.mock.calls[1][0]).toBe("/api/simulations/run");
    expect(mockedFetch.mock.calls[1][1]?.method).toBe("POST");
  });

  it("disables the run button while the request is pending", async () => {
    const user = userEvent.setup();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch.mockResolvedValueOnce(jsonResponse(404, { detail: "none" }));
    mockedFetch.mockReturnValueOnce(new Promise(() => {}));

    render(<RunPanel />);
    await screen.findByText(/no simulation has been run yet/i);

    await user.click(screen.getByRole("button", { name: /run simulation/i }));

    expect(await screen.findByRole("button", { name: /running/i })).toBeDisabled();
  });

  it("updates the summary after a successful run", async () => {
    const user = userEvent.setup();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch.mockResolvedValueOnce(jsonResponse(404, { detail: "none" })).mockResolvedValueOnce(jsonResponse(200, SUMMARY));

    render(<RunPanel />);
    await screen.findByText(/no simulation has been run yet/i);
    await user.click(screen.getByRole("button", { name: /run simulation/i }));

    expect(await screen.findByText("7")).toBeInTheDocument();
  });

  it("preserves a previously successful summary when a later run fails", async () => {
    const user = userEvent.setup();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch
      .mockResolvedValueOnce(jsonResponse(200, SUMMARY))
      .mockResolvedValueOnce(jsonResponse(409, { detail: "a simulation is already running" }));

    render(<RunPanel />);
    await screen.findByText("7");

    await user.click(screen.getByRole("button", { name: /run simulation/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already running/i);
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("displays a 400 error clearly", async () => {
    const user = userEvent.setup();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch
      .mockResolvedValueOnce(jsonResponse(404, { detail: "none" }))
      .mockResolvedValueOnce(jsonResponse(400, { detail: "no servers configured" }));

    render(<RunPanel />);
    await screen.findByText(/no simulation has been run yet/i);
    await user.click(screen.getByRole("button", { name: /run simulation/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/no servers configured/i);
  });

  it("displays a 409 error clearly", async () => {
    const user = userEvent.setup();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch
      .mockResolvedValueOnce(jsonResponse(404, { detail: "none" }))
      .mockResolvedValueOnce(jsonResponse(409, { detail: "a simulation is already running" }));

    render(<RunPanel />);
    await screen.findByText(/no simulation has been run yet/i);
    await user.click(screen.getByRole("button", { name: /run simulation/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already running/i);
  });

  it("renders null wait metrics as N/A", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, NULL_SUMMARY));
    render(<RunPanel />);
    const naValues = await screen.findAllByText("N/A");
    expect(naValues).toHaveLength(4);
  });

  it("shows the download link only when a summary exists", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(404, { detail: "none" }));
    render(<RunPanel />);
    await screen.findByText(/no simulation has been run yet/i);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders the download link with the exact expected href once a summary exists", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, SUMMARY));
    render(<RunPanel />);
    const link = await screen.findByRole("link", { name: /download/i });
    expect(link).toHaveAttribute("href", "/api/simulations/latest/download");
  });

  it("under StrictMode, an older latest response resolving after a newer one does not win", async () => {
    const first = createDeferred<Response>();
    const second = createDeferred<Response>();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    render(
      <StrictMode>
        <RunPanel />
      </StrictMode>,
    );

    // StrictMode double-invokes the mount effect in development, producing two
    // overlapping GET /api/simulations/latest calls from this one mount.
    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(2));

    // Resolve out of order: the newer (second) call settles first...
    await act(async () => {
      second.resolve(jsonResponse(200, SUMMARY));
    });
    expect(screen.getByText("7")).toBeInTheDocument();

    // ...then the stale first call resolves afterward. Its result must not
    // replace the newer one that's already showing.
    await act(async () => {
      first.resolve(jsonResponse(404, { detail: "none" }));
    });
    expect(screen.getByText("7")).toBeInTheDocument();
    expect(screen.queryByText(/no simulation has been run yet/i)).not.toBeInTheDocument();
  });

  it("disables the run button while the authoritative initial latest request is pending", () => {
    const deferred = createDeferred<Response>();
    (fetch as unknown as ReturnType<typeof vi.fn>).mockReturnValue(deferred.promise);
    render(<RunPanel />);
    expect(screen.getByRole("button", { name: /run simulation/i })).toBeDisabled();
  });
});
