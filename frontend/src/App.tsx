import ServerList from "./components/ServerList";
import RunPanel from "./components/RunPanel";

export default function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1>Medsien Load Balancer Dashboard</h1>
        <p className="app-subtitle">Server configuration and simulation control</p>
      </header>
      <main className="app-main">
        <ServerList />
        <RunPanel />
      </main>
    </div>
  );
}
