import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";

import { fetchBlog } from "../api.js";

// The route matches the whole segment (":slug"); we accept /blog_1 and parse
// the trailing number. Anything that isn't blog_<n> is treated as not found.
function parseId(slug) {
  const m = /^blog_(\d+)$/.exec(slug || "");
  return m ? Number(m[1]) : null;
}

export default function BlogPage() {
  const { slug } = useParams();
  const id = parseId(slug);
  const [blog, setBlog] = useState(undefined); // undefined=loading, null=not found
  const [error, setError] = useState("");

  useEffect(() => {
    if (id === null) {
      setBlog(null);
      return;
    }
    fetchBlog(id)
      .then(setBlog)
      .catch((e) => setError(e.message));
  }, [id]);

  if (id === null || blog === null) {
    return (
      <div className="panel single">
        <p className="muted">Blog non trovato per “{slug}”.</p>
        <Link to="/">← Torna al generatore</Link>
      </div>
    );
  }
  if (error) return <div className="panel single alert error">⚠ {error}</div>;
  if (blog === undefined) return <div className="panel single muted">Caricamento…</div>;

  const state = blog.state || {};
  const seo = state.seo_report || {};
  const checks = [
    ["Compliance Judge", state.compliance],
    ["Policy Fact-Check", state.fact_check],
    ["Web Fact-Check", state.web_fact_check],
    ["Duplicate Check", state.duplicate_check],
    ["Quality Gate", state.quality],
  ];
  const links = state.internal_links || [];

  return (
    <div className="blog-detail">
      <article className="panel single">
        <Link to="/" className="muted">← generatore</Link>
        <h1>{blog.title || blog.keyword}</h1>
        <p className="muted">
          /blog_{blog.id} · keyword: <code>{blog.keyword}</code> · {blog.provider}
          {blog.model ? ` (${blog.model})` : ""} · creato {blog.created_at?.slice(0, 16)}
        </p>
        <div
          className="blog-body"
          dangerouslySetInnerHTML={{ __html: blog.html || "" }}
        />
      </article>

      <aside className="panel side">
        <h3>Stato</h3>
        <span className={"badge " + (blog.status === "published" ? "green" : "yellow")}>
          {blog.status}
        </span>

        <h3>SEO</h3>
        <ul className="kv">
          <li><span>Score</span><b>{seo.score ?? "—"}/100</b></li>
          <li><span>Parole</span><b>{seo.word_count ?? "—"}</b></li>
          <li><span>Flesch</span><b>{fmt(seo.flesch_reading_ease)}</b></li>
          <li><span>KW density</span><b>{fmt(seo.keyword_density_pct)}%</b></li>
          <li><span>Slug</span><b>{seo.slug ?? "—"}</b></li>
        </ul>

        <h3>Controlli</h3>
        <ul className="checks">
          {checks.map(([label, res]) => {
            const passed = res ? res.passed !== false : true;
            return (
              <li key={label} className={passed ? "pass" : "fail"}>
                {passed ? "✅" : "❌"} {label}
                {!passed && res?.reasons?.length > 0 && (
                  <ul className="node-reasons">
                    {res.reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>

        <h3>Link interni ({links.length})</h3>
        {links.length === 0 && <p className="muted">Nessuno.</p>}
        <ul className="checks">
          {links.map((lk, i) => (
            <li key={i}>
              <b>{lk.anchor_text}</b> → <code>{lk.target_url}</code>
            </li>
          ))}
        </ul>

        {state.voice_profile && (
          <p className="muted">
            voice: <code>{state.voice_profile}</code> · importance:{" "}
            <code>{state.importance_tier}</code> · retry: {state.retries ?? 0}
          </p>
        )}
      </aside>
    </div>
  );
}

function fmt(v) {
  return typeof v === "number" ? v.toFixed(1) : "—";
}
