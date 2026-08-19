import { useEffect, useState, type FormEvent } from "react";
import type { Server, ServerCreate, ServerUpdate } from "../api/client";

interface ServerFormProps {
  mode: "create" | "edit";
  initialServer: Server | null;
  submitting: boolean;
  error: string | null;
  onSubmit: (values: ServerCreate | ServerUpdate) => void;
  onCancel: () => void;
}

function parseInteger(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "" || !/^-?\d+$/.test(trimmed)) {
    return null;
  }
  return Number(trimmed);
}

export default function ServerForm({ mode, initialServer, submitting, error, onSubmit, onCancel }: ServerFormProps) {
  const [id, setId] = useState("");
  const [cpu, setCpu] = useState("");
  const [mem, setMem] = useState("");
  const [rate, setRate] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  useEffect(() => {
    if (mode === "edit" && initialServer) {
      setId(initialServer.id);
      setCpu(String(initialServer.cpu_units_per_tick));
      setMem(String(initialServer.mem_mb));
      setRate(String(initialServer.rate_limit_per_sec));
    } else {
      setId("");
      setCpu("");
      setMem("");
      setRate("");
    }
    setLocalError(null);
  }, [mode, initialServer]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLocalError(null);

    const trimmedId = id.trim();
    if (mode === "create" && trimmedId === "") {
      setLocalError("Server ID is required and cannot be whitespace-only.");
      return;
    }

    const cpuValue = parseInteger(cpu);
    if (cpuValue === null || cpuValue <= 0) {
      setLocalError("CPU units per tick must be a positive whole number.");
      return;
    }

    const memValue = parseInteger(mem);
    if (memValue === null || memValue < 0) {
      setLocalError("Memory (MB) must be a non-negative whole number.");
      return;
    }

    const rateValue = parseInteger(rate);
    if (rateValue === null || rateValue < 0) {
      setLocalError("Rate limit per second must be a non-negative whole number.");
      return;
    }

    if (mode === "create") {
      onSubmit({ id: trimmedId, cpu_units_per_tick: cpuValue, mem_mb: memValue, rate_limit_per_sec: rateValue });
    } else {
      onSubmit({ cpu_units_per_tick: cpuValue, mem_mb: memValue, rate_limit_per_sec: rateValue });
    }
  }

  const displayedError = localError ?? error;

  return (
    <form
      className="server-form"
      onSubmit={handleSubmit}
      noValidate
      aria-label={mode === "create" ? "Add server" : `Edit server ${initialServer?.id ?? ""}`}
    >
      {mode === "create" ? (
        <div className="field">
          <label htmlFor="server-id">Server ID</label>
          <input
            id="server-id"
            type="text"
            value={id}
            onChange={(e) => setId(e.target.value)}
            disabled={submitting}
          />
        </div>
      ) : (
        <div className="field">
          <span className="field-label">Server ID</span>
          <span className="readonly-id">{initialServer?.id}</span>
        </div>
      )}

      <div className="field">
        <label htmlFor="server-cpu">CPU units per tick</label>
        <input
          id="server-cpu"
          type="number"
          min={1}
          step={1}
          value={cpu}
          onChange={(e) => setCpu(e.target.value)}
          disabled={submitting}
        />
      </div>

      <div className="field">
        <label htmlFor="server-mem">Memory (MB)</label>
        <input
          id="server-mem"
          type="number"
          min={0}
          step={1}
          value={mem}
          onChange={(e) => setMem(e.target.value)}
          disabled={submitting}
        />
      </div>

      <div className="field">
        <label htmlFor="server-rate">Rate limit per second</label>
        <input
          id="server-rate"
          type="number"
          min={0}
          step={1}
          value={rate}
          onChange={(e) => setRate(e.target.value)}
          disabled={submitting}
        />
      </div>

      {displayedError ? (
        <p role="alert" className="form-error">
          {displayedError}
        </p>
      ) : null}

      <div className="form-actions">
        <button type="submit" disabled={submitting}>
          {submitting ? "Saving…" : mode === "create" ? "Add server" : "Save changes"}
        </button>
        <button type="button" onClick={onCancel} disabled={submitting}>
          Cancel
        </button>
      </div>
    </form>
  );
}
