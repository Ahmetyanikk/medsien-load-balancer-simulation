import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StrategySelector from "./StrategySelector";

const STRATEGIES = {
  strategies: [
    { id: "fastest_finish", label: "Fastest finish", default: true },
    { id: "lowest_id", label: "Lowest server ID", default: false },
  ],
};

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("StrategySelector", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows a loading state before the strategy list resolves", () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));
    render(<StrategySelector onRunCompleted={vi.fn()} />);
    expect(screen.getByText(/loading strategies/i)).toBeInTheDocument();
  });

  it("defaults the selection to the backend-declared default strategy", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(200, STRATEGIES));
    render(<StrategySelector onRunCompleted={vi.fn()} />);
    const select = (await screen.findByLabelText("Strategy")) as HTMLSelectElement;
    expect(select.value).toBe("fastest_finish");
  });

  it("shows an error if the strategy list fails to load", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce(jsonResponse(500, { detail: "boom" }));
    render(<StrategySelector onRunCompleted={vi.fn()} />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/boom/i);
  });

  it("triggers POST /run with the selected strategy and notifies onRunCompleted on success", async () => {
    const user = userEvent.setup();
    const onRunCompleted = vi.fn();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch
      .mockResolvedValueOnce(jsonResponse(200, STRATEGIES))
      .mockResolvedValueOnce(jsonResponse(200, { status: "completed" }));

    render(<StrategySelector onRunCompleted={onRunCompleted} />);
    const select = (await screen.findByLabelText("Strategy")) as HTMLSelectElement;
    await user.selectOptions(select, "lowest_id");
    await user.click(screen.getByRole("button", { name: /run with selected strategy/i }));

    await waitFor(() => expect(onRunCompleted).toHaveBeenCalledTimes(1));
    expect(mockedFetch.mock.calls[1][0]).toBe("/api/simulations/run?strategy=lowest_id");
    expect(mockedFetch.mock.calls[1][1]?.method).toBe("POST");
  });

  it("disables controls while a run is in progress", async () => {
    const user = userEvent.setup();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, STRATEGIES));
    mockedFetch.mockReturnValueOnce(new Promise(() => {}));

    render(<StrategySelector onRunCompleted={vi.fn()} />);
    await screen.findByLabelText("Strategy");
    await user.click(screen.getByRole("button", { name: /run with selected strategy/i }));

    expect(await screen.findByRole("button", { name: /running/i })).toBeDisabled();
    expect(screen.getByLabelText("Strategy")).toBeDisabled();
  });

  it("displays a 422 unknown-strategy error clearly and does not call onRunCompleted", async () => {
    const user = userEvent.setup();
    const onRunCompleted = vi.fn();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch
      .mockResolvedValueOnce(jsonResponse(200, STRATEGIES))
      .mockResolvedValueOnce(jsonResponse(422, { detail: [{ msg: "unknown strategy" }] }));

    render(<StrategySelector onRunCompleted={onRunCompleted} />);
    await screen.findByLabelText("Strategy");
    await user.click(screen.getByRole("button", { name: /run with selected strategy/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/unknown strategy/i);
    expect(onRunCompleted).not.toHaveBeenCalled();
  });

  it("displays a 409 already-running error clearly", async () => {
    const user = userEvent.setup();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch
      .mockResolvedValueOnce(jsonResponse(200, STRATEGIES))
      .mockResolvedValueOnce(jsonResponse(409, { detail: "a simulation is already running" }));

    render(<StrategySelector onRunCompleted={vi.fn()} />);
    await screen.findByLabelText("Strategy");
    await user.click(screen.getByRole("button", { name: /run with selected strategy/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already running/i);
  });

  it("displays a network error clearly", async () => {
    const user = userEvent.setup();
    const mockedFetch = fetch as unknown as ReturnType<typeof vi.fn>;
    mockedFetch.mockResolvedValueOnce(jsonResponse(200, STRATEGIES)).mockRejectedValueOnce(new TypeError("failed to fetch"));

    render(<StrategySelector onRunCompleted={vi.fn()} />);
    await screen.findByLabelText("Strategy");
    await user.click(screen.getByRole("button", { name: /run with selected strategy/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/network error/i);
  });
});
