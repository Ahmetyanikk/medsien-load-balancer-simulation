import { useCallback, useState } from "react";
import ServerList from "./components/ServerList";
import RunPanel from "./components/RunPanel";
import StrategySelector from "./components/StrategySelector";
import MetricsPanel from "./components/MetricsPanel";

export default function App() {
  // Bumped after any successful run, wherever it was started (RunPanel's own
  // button or StrategySelector) — RunPanel and MetricsPanel both refetch
  // whenever this changes, so all panels stay in sync with the latest run.
  const [runVersion, setRunVersion] = useState(0);
  const handleRunCompleted = useCallback(() => setRunVersion((v) => v + 1), []);

  return (
    <div className="app">
      <header className="app-header">
        <h1>Medsien Load Balancer Dashboard</h1>
        <p className="app-subtitle">Server configuration and simulation control</p>
      </header>
      <main className="app-main">
        <ServerList />
        <RunPanel runVersion={runVersion} onRunCompleted={handleRunCompleted} />
      </main>
      <section className="app-bonus" aria-labelledby="bonus-heading">
        <h2 id="bonus-heading" className="sr-only">
          Bonus features
        </h2>
        <div className="app-bonus-grid">
          <StrategySelector onRunCompleted={handleRunCompleted} />
          <MetricsPanel runVersion={runVersion} />
        </div>
      </section>
    </div>
  );
}
