import { StrictMode } from "react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ServerList from "./ServerList";

const SERVERS = [
  { id: "s1", cpu_units_per_tick: 10, mem_mb: 1024, rate_limit_per_sec: 2 },
  { id: "s2", cpu_units_per_tick: 5, mem_mb: 512, rate_limit_per_sec: 1 },
];

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

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function emptyResponse(status: number) {
  return new Response(null, { status });
}

describe("ServerList", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows a loading state before the initial fetch resolves", () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
    render(<ServerList />);
    expect(screen.getByText(/loading servers/i)).toBeInTheDocument();
  });

  it("shows an empty state when no servers are configured", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, []));
    render(<ServerList />);
    expect(await screen.findByText(/no servers configured/i)).toBeInTheDocument();
  });

  it("renders fetched server rows", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, SERVERS));
    render(<ServerList />);
    expect(await screen.findByText("s1")).toBeInTheDocument();
    expect(screen.getByText("s2")).toBeInTheDocument();
  });

  it("shows a readable error when the initial fetch fails", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(500, { detail: "server exploded" }));
    render(<ServerList />);
    expect(await screen.findByText("server exploded")).toBeInTheDocument();
  });

  it("re-fetches the authoritative list after a successful create", async () => {
    const user = userEvent.setup();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch
      .mockResolvedValueOnce(jsonResponse(200, []))
      .mockResolvedValueOnce(jsonResponse(201, { id: "s3", cpu_units_per_tick: 3, mem_mb: 50, rate_limit_per_sec: 1 }))
      .mockResolvedValueOnce(jsonResponse(200, [{ id: "s3", cpu_units_per_tick: 3, mem_mb: 50, rate_limit_per_sec: 1 }]));

    render(<ServerList />);
    await screen.findByText(/no servers configured/i);

    await user.click(screen.getByRole("button", { name: /add server/i }));
    await user.type(screen.getByLabelText(/server id/i), "s3");
    await user.type(screen.getByLabelText(/cpu units per tick/i), "3");
    await user.type(screen.getByLabelText(/memory/i), "50");
    await user.type(screen.getByLabelText(/rate limit/i), "1");
    await user.click(screen.getByRole("button", { name: /^add server$/i }));

    await screen.findByText("s3");
    expect(mockedFetch).toHaveBeenCalledTimes(3);
    const createCall = mockedFetch.mock.calls[1];
    expect(createCall[0]).toBe("/api/servers");
    expect(createCall[1]?.method).toBe("POST");
  });

  it("sends PUT without an id and re-fetches after a successful edit", async () => {
    const user = userEvent.setup();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch
      .mockResolvedValueOnce(jsonResponse(200, SERVERS))
      .mockResolvedValueOnce(jsonResponse(200, { id: "s1", cpu_units_per_tick: 99, mem_mb: 1024, rate_limit_per_sec: 2 }))
      .mockResolvedValueOnce(jsonResponse(200, [{ ...SERVERS[0], cpu_units_per_tick: 99 }, SERVERS[1]]));

    render(<ServerList />);
    await screen.findByText("s1");

    const row = screen.getByText("s1").closest("tr");
    if (!row) throw new Error("row not found");
    await user.click(within(row).getByRole("button", { name: /edit/i }));

    const cpuInput = screen.getByLabelText(/cpu units per tick/i);
    await user.clear(cpuInput);
    await user.type(cpuInput, "99");
    await user.click(screen.getByRole("button", { name: /save changes/i }));

    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(3));
    const updateCall = mockedFetch.mock.calls[1];
    expect(updateCall[0]).toBe("/api/servers/s1");
    expect(updateCall[1]?.method).toBe("PUT");
    const sentBody = JSON.parse(updateCall[1]?.body as string);
    expect(sentBody).not.toHaveProperty("id");
  });

  it("sends DELETE and re-fetches when delete confirmation is accepted", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch
      .mockResolvedValueOnce(jsonResponse(200, SERVERS))
      .mockResolvedValueOnce(emptyResponse(204))
      .mockResolvedValueOnce(jsonResponse(200, [SERVERS[1]]));

    render(<ServerList />);
    await screen.findByText("s1");

    const row = screen.getByText("s1").closest("tr");
    if (!row) throw new Error("row not found");
    await user.click(within(row).getByRole("button", { name: /delete/i }));

    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(3));
    expect(mockedFetch.mock.calls[1][0]).toBe("/api/servers/s1");
    expect(mockedFetch.mock.calls[1][1]?.method).toBe("DELETE");
  });

  it("sends no DELETE when delete confirmation is cancelled", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, SERVERS));

    render(<ServerList />);
    await screen.findByText("s1");

    const row = screen.getByText("s1").closest("tr");
    if (!row) throw new Error("row not found");
    await user.click(within(row).getByRole("button", { name: /delete/i }));

    expect(mockedFetch).toHaveBeenCalledTimes(1);
  });

  it("keeps mutation errors visible", async () => {
    const user = userEvent.setup();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch
      .mockResolvedValueOnce(jsonResponse(200, SERVERS))
      .mockResolvedValueOnce(jsonResponse(409, { detail: "server id already exists: s1" }));

    render(<ServerList />);
    await screen.findByText("s1");

    await user.click(screen.getByRole("button", { name: /add server/i }));
    await user.type(screen.getByLabelText(/server id/i), "s1");
    await user.type(screen.getByLabelText(/cpu units per tick/i), "1");
    await user.type(screen.getByLabelText(/memory/i), "1");
    await user.type(screen.getByLabelText(/rate limit/i), "1");
    await user.click(screen.getByRole("button", { name: /^add server$/i }));

    expect(await screen.findByText(/server id already exists/i)).toBeInTheDocument();
  });

  it("ignores an older overlapping list response when a newer one resolves first", async () => {
    const first = createDeferred<Response>();
    const second = createDeferred<Response>();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);

    render(
      <StrictMode>
        <ServerList />
      </StrictMode>,
    );

    // StrictMode double-invokes the mount effect in development, producing two
    // overlapping GET /api/servers calls from this one mount.
    await waitFor(() => expect(mockedFetch).toHaveBeenCalledTimes(2));

    // Resolve out of order: the newer (second) call settles first...
    await act(async () => {
      second.resolve(jsonResponse(200, SERVERS));
    });
    expect(screen.getByText("s1")).toBeInTheDocument();

    // ...then the stale first call resolves afterward with a DIFFERENT
    // (empty) result. It must not replace the newer list already showing.
    await act(async () => {
      first.resolve(jsonResponse(200, []));
    });
    expect(screen.getByText("s1")).toBeInTheDocument();
    expect(screen.queryByText(/no servers configured/i)).not.toBeInTheDocument();
  });

  it("normalizes a real FastAPI 422 detail array through client.ts and displays both messages", async () => {
    // Unlike ServerForm.test.tsx's "renders a parent-supplied error string"
    // case, this goes through the real createServer() -> request() ->
    // extractDetail() path in client.ts — nothing here is pre-normalized.
    const user = userEvent.setup();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch
      .mockResolvedValueOnce(jsonResponse(200, SERVERS))
      .mockResolvedValueOnce(
        jsonResponse(422, {
          detail: [
            { loc: ["body", "cpu_units_per_tick"], msg: "Input should be greater than 0", type: "greater_than" },
            { loc: ["body", "mem_mb"], msg: "Input should be a valid integer", type: "int_parsing" },
          ],
        }),
      );

    render(<ServerList />);
    await screen.findByText("s1");

    await user.click(screen.getByRole("button", { name: /add server/i }));
    await user.type(screen.getByLabelText(/server id/i), "s3");
    await user.type(screen.getByLabelText(/cpu units per tick/i), "1");
    await user.type(screen.getByLabelText(/memory/i), "1");
    await user.type(screen.getByLabelText(/rate limit/i), "1");
    await user.click(screen.getByRole("button", { name: /^add server$/i }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Input should be greater than 0");
    expect(alert).toHaveTextContent("Input should be a valid integer");
  });
});
