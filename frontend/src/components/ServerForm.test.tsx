import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import ServerForm from "./ServerForm";

const SERVER = { id: "s1", cpu_units_per_tick: 10, mem_mb: 1024, rate_limit_per_sec: 2 };

afterEach(() => {
  vi.restoreAllMocks();
});

async function fillAndSubmit(
  user: ReturnType<typeof userEvent.setup>,
  values: { id?: string; cpu?: string; mem?: string; rate?: string },
) {
  if (values.id !== undefined) {
    await user.type(screen.getByLabelText(/server id/i), values.id);
  }
  if (values.cpu !== undefined) {
    await user.type(screen.getByLabelText(/cpu units per tick/i), values.cpu);
  }
  if (values.mem !== undefined) {
    await user.type(screen.getByLabelText(/memory/i), values.mem);
  }
  if (values.rate !== undefined) {
    await user.type(screen.getByLabelText(/rate limit/i), values.rate);
  }
  await user.click(screen.getByRole("button", { name: /add server|save changes/i }));
}

describe("ServerForm", () => {
  it("shows an editable ID field in create mode", () => {
    render(
      <ServerForm mode="create" initialServer={null} submitting={false} error={null} onSubmit={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByLabelText(/server id/i)).toBeInTheDocument();
  });

  it("shows the ID as read-only text in edit mode and never as an input", () => {
    render(
      <ServerForm mode="edit" initialServer={SERVER} submitting={false} error={null} onSubmit={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByText("s1")).toBeInTheDocument();
    expect(screen.queryByLabelText(/server id/i)).not.toBeInTheDocument();
  });

  it("resets form values when the edited server prop changes", () => {
    const { rerender } = render(
      <ServerForm mode="edit" initialServer={SERVER} submitting={false} error={null} onSubmit={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByLabelText(/cpu units per tick/i)).toHaveValue(10);

    const other = { id: "s2", cpu_units_per_tick: 5, mem_mb: 512, rate_limit_per_sec: 1 };
    rerender(
      <ServerForm mode="edit" initialServer={other} submitting={false} error={null} onSubmit={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByLabelText(/cpu units per tick/i)).toHaveValue(5);
    expect(screen.getByText("s2")).toBeInTheDocument();
  });

  it("rejects a non-positive CPU value", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <ServerForm mode="create" initialServer={null} submitting={false} error={null} onSubmit={onSubmit} onCancel={vi.fn()} />,
    );
    await fillAndSubmit(user, { id: "s3", cpu: "0", mem: "10", rate: "1" });
    expect(await screen.findByRole("alert")).toHaveTextContent(/positive whole number/i);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects a negative memory value", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <ServerForm mode="create" initialServer={null} submitting={false} error={null} onSubmit={onSubmit} onCancel={vi.fn()} />,
    );
    await fillAndSubmit(user, { id: "s3", cpu: "1", mem: "-1", rate: "1" });
    expect(await screen.findByRole("alert")).toHaveTextContent(/non-negative whole number/i);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects a negative rate limit value", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <ServerForm mode="create" initialServer={null} submitting={false} error={null} onSubmit={onSubmit} onCancel={vi.fn()} />,
    );
    await fillAndSubmit(user, { id: "s3", cpu: "1", mem: "1", rate: "-1" });
    expect(await screen.findByRole("alert")).toHaveTextContent(/non-negative whole number/i);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects an empty CPU value", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <ServerForm mode="create" initialServer={null} submitting={false} error={null} onSubmit={onSubmit} onCancel={vi.fn()} />,
    );
    await fillAndSubmit(user, { id: "s3", mem: "1", rate: "1" });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects a non-numeric CPU value", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <ServerForm mode="create" initialServer={null} submitting={false} error={null} onSubmit={onSubmit} onCancel={vi.fn()} />,
    );
    await fillAndSubmit(user, { id: "s3", cpu: "NaN", mem: "1", rate: "1" });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects a fractional CPU value", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <ServerForm mode="create" initialServer={null} submitting={false} error={null} onSubmit={onSubmit} onCancel={vi.fn()} />,
    );
    await fillAndSubmit(user, { id: "s3", cpu: "1.5", mem: "1", rate: "1" });
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("rejects a whitespace-only ID", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <ServerForm mode="create" initialServer={null} submitting={false} error={null} onSubmit={onSubmit} onCancel={vi.fn()} />,
    );
    await fillAndSubmit(user, { id: "   ", cpu: "1", mem: "1", rate: "1" });
    expect(await screen.findByRole("alert")).toHaveTextContent(/id is required/i);
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("disables submission while a request is pending", () => {
    render(
      <ServerForm mode="create" initialServer={null} submitting={true} error={null} onSubmit={vi.fn()} onCancel={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: /saving/i })).toBeDisabled();
  });

  it("displays a string API error", () => {
    render(
      <ServerForm
        mode="create"
        initialServer={null}
        submitting={false}
        error="server id already exists: s1"
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("server id already exists: s1");
  });

  it("renders a parent-supplied error string (already normalized by the caller)", () => {
    // This only proves ServerForm renders whatever string it's given via the
    // `error` prop — it does NOT exercise client.ts's real 422-array
    // normalization (extractDetail is private to client.ts and not exported
    // for testing). The real end-to-end normalization test, which goes
    // through createServer() -> request() -> extractDetail() for real, lives
    // in ServerList.test.tsx: "normalizes a real FastAPI 422 detail array
    // through client.ts and displays both messages".
    render(
      <ServerForm
        mode="create"
        initialServer={null}
        submitting={false}
        error="Field required; Input should be a valid integer"
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Field required; Input should be a valid integer");
  });
});
