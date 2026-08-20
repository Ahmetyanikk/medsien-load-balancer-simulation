import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getStrategies, runSimulation, type StrategyInfo } from "../api/client";

type StrategiesState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; strategies: StrategyInfo[] };

interface StrategySelectorProps {
  /** Notify App that a run succeeded, so sibling panels refresh. */
  onRunCompleted: () => void;
}

export default function StrategySelector({ onRunCompleted }: StrategySelectorProps) {
  const [state, setState] = useState<StrategiesState>({ status: "loading" });
  const [selected, setSelected] = useState("");
  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  // Same shared-generation-token pattern as RunPanel/ServerList: whichever
  // call incremented it last owns the right to apply its result; a call
  // whose captured token no longer matches the current value is stale and
  // is discarded regardless of resolution order.
  const generationRef = useRef(0);

  const loadStrategies = useCallback(async () => {
    const token = ++generationRef.current;
    setState({ status: "loading" });
    try {
      const response = await getStrategies();
      if (token !== generationRef.current) return;
      setState({ status: "ready", strategies: response.strategies });
      // Default selection must be the backend-declared default, never a
      // hardcoded id here — this panel doesn't own scheduling knowledge.
      setSelected((current) => {
        if (current) return current;
        const defaultEntry = response.strategies.find((s) => s.default);
        return defaultEntry?.id ?? response.strategies[0]?.id ?? "";
      });
    } catch (err) {
      if (token !== generationRef.current) return;
      const message = err instanceof ApiError ? err.message : "Unable to load scheduling strategies.";
      setState({ status: "error", message });
    }
  }, []);

  useEffect(() => {
    void loadStrategies();
    return () => {
      generationRef.current += 1;
    };
  }, [loadStrategies]);

  async function handleRun() {
    if (!selected) return;
    const token = ++generationRef.current;
    setRunning(true);
    setRunError(null);
    try {
      await runSimulation(selected);
      if (token === generationRef.current) {
        onRunCompleted();
      }
    } catch (err) {
      if (token === generationRef.current) {
        const message = err instanceof ApiError ? err.message : "Unable to run the simulation.";
        setRunError(message);
      }
    } finally {
      if (token === generationRef.current) {
        setRunning(false);
      }
    }
  }

  const strategies = state.status === "ready" ? state.strategies : [];
  const controlsDisabled = running || state.status !== "ready" || !selected;

  return (
    <section className="panel" aria-labelledby="strategy-heading">
      <div className="panel-header">
        <h2 id="strategy-heading">Scheduling strategy</h2>
      </div>

      {state.status === "loading" ? <p>Loading strategies…</p> : null}
      {state.status === "error" ? <p role="alert">{state.message}</p> : null}

      {state.status === "ready" ? (
        <div className="strategy-controls">
          <div className="field">
            <label htmlFor="strategy-select">Strategy</label>
            <select
              id="strategy-select"
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
              disabled={running}
            >
              {strategies.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.label}
                  {s.default ? " (default)" : ""}
                </option>
              ))}
            </select>
          </div>
          <button type="button" onClick={handleRun} disabled={controlsDisabled}>
            {running ? "Running…" : "Run with selected strategy"}
          </button>
        </div>
      ) : null}

      {runError ? (
        <p role="alert" className="form-error">
          {runError}
        </p>
      ) : null}
    </section>
  );
}
