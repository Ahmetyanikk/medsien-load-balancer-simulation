import { useCallback, useState } from "react";
import ServerList from "./components/ServerList";
import RunPanel from "./components/RunPanel";
import StrategySelector from "./components/StrategySelector";
import MetricsPanel from "./components/MetricsPanel";
import TimelinePanel from "./components/TimelinePanel";
import AutoScalePanel from "./components/AutoScalePanel";

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
      <main className="app-content">
        <div className="app-primary-grid">
          <ServerList />
          <div className="app-controls-stack">
            <RunPanel runVersion={runVersion} onRunCompleted={handleRunCompleted} />
            <StrategySelector onRunCompleted={handleRunCompleted} />
          </div>
        </div>
        <div className="app-analysis-grid">
          <MetricsPanel runVersion={runVersion} />
          <AutoScalePanel runVersion={runVersion} />
        </div>
        <div className="app-timeline">
          <TimelinePanel runVersion={runVersion} />
        </div>
      </main>
    </div>
  );
}
