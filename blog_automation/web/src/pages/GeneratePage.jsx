import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

import {
  fetchProviders,
  startGeneration,
  openJobStream,
  fetchBlogs,
  deleteBlog,
} from "../api.js";

export default function GeneratePage() {
  const [providers, setProviders] = useState({});
  const [provider, setProvider] = useState("mock");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [ollamaUrl, setOllamaUrl] = useState("http://localhost:11434");
  const [keyword, setKeyword] = useState("");

  const [events, setEvents] = useState([]); // node timeline for the current run
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null); // { blog_id, url, status, title }
  const [error, setError] = useState("");
  const [blogs, setBlogs] = useState([]);
  const esRef = useRef(null);

  // Load provider list + existing blogs once.
  useEffect(() => {
    fetchProviders()
      .then((d) => {
        setProviders(d.providers || {});
        setProvider(d.current && d.providers[d.current] ? d.current : "mock");
      })
      .catch(() => {});
    refreshBlogs();
    return () => esRef.current?.close();
  }, []);

  // When the provider changes, prefill the model placeholder with its default.
  useEffect(() => {
    setModel("");
  }, [provider]);

  function refreshBlogs() {
    fetchBlogs().then(setBlogs).catch(() => {});
  }

  async function onSubmit(e) {
    e.preventDefault();
    if (!keyword.trim() || running) return;
    setError("");
    setResult(null);
    setEvents([]);
    setRunning(true);

    try {
      const { job_id } = await startGeneration({
        keyword: keyword.trim(),
        provider,
        model: model.trim() || null,
        api_key: apiKey.trim() || null,
        ollama_url: provider === "ollama" ? ollamaUrl.trim() : null,
      });

      esRef.current = openJobStream(
        job_id,
        (ev) => {
          if (ev.type === "node") {
            setEvents((prev) => [...prev, ev]);
          } else if (ev.type === "done") {
            setResult(ev);
            refreshBlogs();
          } else if (ev.type === "error") {
            setError(ev.message);
          } else if (ev.type === "start") {
            setEvents([]);
          }
        },
        () => setRunning(false)
      );
    } catch (err) {
      setError(err.message);
      setRunning(false);
    }
  }

  async function onDelete(id) {
    await deleteBlog(id).catch(() => {});
    refreshBlogs();
  }

  const needsKey = providers[provider]?.needs_key;
  const defaultModel = providers[provider]?.default_model;
  const lastProgress = events.length ? events[events.length - 1].progress : 0;

  return (
    <div className="layout">
      {/* ── left: the "chatbot" controls ─────────────────────────────── */}
      <section className="panel">
        <h2>Genera un blog</h2>
        <form onSubmit={onSubmit} className="gen-form">
          <label className="field">
            <span>Modello / Provider</span>
            <select value={provider} onChange={(e) => setProvider(e.target.value)}>
              {Object.entries(providers).map(([key, p]) => (
                <option key={key} value={key}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>Modello specifico {defaultModel ? `(default: ${defaultModel})` : ""}</span>
            <input
              type="text"
              placeholder={defaultModel || "—"}
              value={model}
              onChange={(e) => setModel(e.target.value)}
            />
          </label>

          {provider === "ollama" && (
            <label className="field">
              <span>Ollama base URL</span>
              <input
                type="text"
                value={ollamaUrl}
                onChange={(e) => setOllamaUrl(e.target.value)}
              />
            </label>
          )}

          {needsKey && (
            <label className="field">
              <span>API key</span>
              <input
                type="password"
                placeholder="Incolla la API key (resta solo in locale)"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </label>
          )}

          <label className="field">
            <span>Keyword / argomento</span>
            <textarea
              rows={2}
              placeholder="es. how to start investing"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
            />
          </label>

          <button type="submit" className="primary" disabled={running || !keyword.trim()}>
            {running ? "Generazione in corso…" : "▶ Genera blog"}
          </button>
        </form>

        {error && <div className="alert error">⚠ {error}</div>}
      </section>

      {/* ── middle: live node-by-node timeline ───────────────────────── */}
      <section className="panel">
        <h2>Produzione nodo per nodo</h2>
        {events.length === 0 && !running && !result && (
          <p className="muted">La pipeline mostrerà qui ogni nodo man mano che viene eseguito.</p>
        )}

        {(running || events.length > 0) && (
          <div className="progress-track">
            <div className="progress-bar" style={{ width: `${lastProgress}%` }} />
          </div>
        )}

        <ol className="timeline">
          {events.map((ev, i) => (
            <li
              key={i}
              className={
                "node " +
                (ev.passed === false ? "fail" : ev.passed === true ? "pass" : "ok")
              }
            >
              <span className="node-label">{ev.label}</span>
              {typeof ev.progress === "number" && (
                <span className="node-pct">{ev.progress}%</span>
              )}
              {ev.passed === false && ev.reasons?.length > 0 && (
                <ul className="node-reasons">
                  {ev.reasons.map((r, j) => (
                    <li key={j}>{r}</li>
                  ))}
                </ul>
              )}
              {ev.node === "increment_retries" && (
                <span className="node-pct">retry #{ev.retries}</span>
              )}
            </li>
          ))}
          {running && <li className="node pending">⏳ …</li>}
        </ol>

        {result && (
          <div className={"alert " + (result.status === "published" ? "success" : "warn")}>
            <strong>
              {result.status === "published" ? "🟢 Pubblicato" : "🟡 Da revisionare"}
            </strong>{" "}
            — {result.title}
            <div>
              SEO score: {result.seo_score ?? "—"}/100 ·{" "}
              <Link to={result.url}>Apri {result.url}</Link>
            </div>
          </div>
        )}
      </section>

      {/* ── right: saved blogs (the /blog_N list) ────────────────────── */}
      <section className="panel">
        <h2>Blog salvati</h2>
        {blogs.length === 0 && <p className="muted">Ancora nessun blog generato.</p>}
        <ul className="blog-list">
          {blogs.map((b) => (
            <li key={b.id}>
              <Link to={`/blog_${b.id}`} className="blog-link">
                <span className={"dot " + (b.status === "published" ? "green" : "yellow")} />
                <span className="blog-title">{b.title || b.keyword}</span>
                <span className="blog-meta">
                  /blog_{b.id} · {b.provider} · SEO {b.seo_score ?? "—"}
                </span>
              </Link>
              <button className="link-btn" onClick={() => onDelete(b.id)} title="Elimina">
                ✕
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
