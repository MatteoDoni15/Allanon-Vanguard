import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  fetchBlogs,
  fetchFeedback,
  submitFeedback,
  fetchKeywordPriorities,
} from "../api.js";

// Part 3, proposal 3 — the feedback loop.
// Left: attach engagement metrics to past posts (fake data is fine — it's how
// you test the mechanism without real traffic). Right: enter candidate keywords
// and see them re-ranked by what actually performed.
export default function FeedbackPage() {
  const [blogs, setBlogs] = useState([]);
  const [feedback, setFeedback] = useState([]);
  const [draft, setDraft] = useState({}); // blog_id -> {impressions, clicks, avg_time_sec, conversions}
  const [candidates, setCandidates] = useState(
    "best high-yield savings accounts\nhow to choose a budgeting app\nis crypto day trading worth it\nemergency fund strategy"
  );
  const [priorities, setPriorities] = useState(null);
  const [postsWithData, setPostsWithData] = useState(0);
  const [error, setError] = useState("");

  useEffect(() => {
    refresh();
  }, []);

  function refresh() {
    fetchBlogs().then(setBlogs).catch((e) => setError(e.message));
    fetchFeedback().then(setFeedback).catch(() => {});
  }

  function setField(blogId, field, value) {
    setDraft((d) => ({ ...d, [blogId]: { ...d[blogId], [field]: value } }));
  }

  async function send(blogId) {
    const m = draft[blogId] || {};
    setError("");
    try {
      await submitFeedback({
        blog_id: blogId,
        impressions: Number(m.impressions) || 0,
        clicks: Number(m.clicks) || 0,
        avg_time_sec: Number(m.avg_time_sec) || 0,
        conversions: Number(m.conversions) || 0,
      });
      refresh();
    } catch (e) {
      setError(e.message);
    }
  }

  async function recompute() {
    setError("");
    const list = candidates
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    try {
      const res = await fetchKeywordPriorities(list);
      setPriorities(res.priorities);
      setPostsWithData(res.history_posts_with_engagement);
    } catch (e) {
      setError(e.message);
    }
  }

  const metricsFor = (blogId) =>
    feedback.find((f) => f.blog_id === blogId);

  return (
    <div className="layout policies-layout">
      {/* ── left: attach engagement to past posts ──────────────────── */}
      <section className="panel">
        <h2>1 · Metriche di engagement</h2>
        <p className="muted">
          Allega metriche (anche di test) ai post pubblicati. È così che il
          sistema impara: dai risultati reali dei blog passati alla scelta delle
          prossime keyword. <Link to="/" className="muted">← generatore</Link>
        </p>

        {error && <div className="alert error">⚠ {error}</div>}
        {blogs.length === 0 && <p className="muted">Nessun blog ancora. Generane uno prima.</p>}

        <ul className="policy-list">
          {blogs.map((b) => {
            const m = metricsFor(b.id);
            const d = draft[b.id] || {};
            return (
              <li key={b.id} className="policy-item">
                <div className="policy-head">
                  <b>#{b.id} · {b.title || b.keyword}</b>
                  {m && (
                    <span className="muted" title="ultime metriche salvate">
                      CTR {((m.clicks / Math.max(m.impressions, 1)) * 100).toFixed(1)}%
                    </span>
                  )}
                </div>
                <code className="policy-id">{b.keyword}</code>
                <div className="metric-grid">
                  <input type="number" placeholder="impressions"
                    value={d.impressions ?? ""} onChange={(e) => setField(b.id, "impressions", e.target.value)} />
                  <input type="number" placeholder="clicks"
                    value={d.clicks ?? ""} onChange={(e) => setField(b.id, "clicks", e.target.value)} />
                  <input type="number" placeholder="avg time (s)"
                    value={d.avg_time_sec ?? ""} onChange={(e) => setField(b.id, "avg_time_sec", e.target.value)} />
                  <input type="number" placeholder="conversions"
                    value={d.conversions ?? ""} onChange={(e) => setField(b.id, "conversions", e.target.value)} />
                  <button className="primary" onClick={() => send(b.id)}>Salva</button>
                </div>
              </li>
            );
          })}
        </ul>
      </section>

      {/* ── right: recomputed keyword priorities ───────────────────── */}
      <section className="panel">
        <h2>2 · Priorità keyword ricalcolate</h2>
        <p className="muted">
          Le keyword candidate vengono riordinate: salgono quelle simili ai post
          andati bene, scendono quelle simili ai post andati male.
        </p>
        <label className="field">
          <span>Keyword candidate (una per riga)</span>
          <textarea rows={5} value={candidates} onChange={(e) => setCandidates(e.target.value)} />
        </label>
        <button className="primary" onClick={recompute}>↻ Ricalcola priorità</button>

        {priorities && (
          <>
            <p className="muted" style={{ marginTop: 12 }}>
              Basato su {postsWithData} post con dati di engagement.
            </p>
            <ul className="priority-list">
              {priorities.map((p) => (
                <li key={p.keyword} className="priority-item">
                  <div className="priority-bar-row">
                    <span className="priority-score">{p.priority.toFixed(0)}</span>
                    <div className="priority-bar">
                      <div className="priority-fill" style={{ width: `${p.priority}%` }} />
                    </div>
                  </div>
                  <b>{p.keyword}</b>
                  <p className="policy-text muted">{p.rationale}</p>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  );
}
