import { Link, Outlet } from "react-router-dom";

// Shared shell: a slim top bar + the routed page underneath.
export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <Link to="/" className="brand">
          ✍️ Blog Automation <span className="brand-sub">· tester</span>
        </Link>
        <nav className="topbar-nav">
          <Link to="/">Generatore</Link>
          <Link to="/policies">📋 Policy</Link>
          <Link to="/feedback">📈 Feedback</Link>
        </nav>
        <span className="topbar-hint">NorthLedger Finance pipeline</span>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
