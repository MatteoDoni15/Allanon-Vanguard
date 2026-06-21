// Thin client around the FastAPI backend. All paths go through the Vite proxy
// (/api -> http://localhost:8000) so there is a single origin in dev.

export async function fetchProviders() {
  const res = await fetch("/api/providers");
  if (!res.ok) throw new Error("Impossibile leggere i provider");
  return res.json();
}

export async function startGeneration(body) {
  const res = await fetch("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || "Avvio generazione fallito");
  }
  return res.json(); // { job_id }
}

export async function fetchBlogs() {
  const res = await fetch("/api/blogs");
  if (!res.ok) throw new Error("Impossibile leggere i blog");
  return (await res.json()).blogs;
}

export async function fetchBlog(id) {
  const res = await fetch(`/api/blogs/${id}`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("Impossibile leggere il blog");
  return res.json();
}

export async function deleteBlog(id) {
  const res = await fetch(`/api/blogs/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Eliminazione fallita");
  return res.json();
}

export async function approveBlog(id) {
  const res = await fetch(`/api/blogs/${id}/approve`, { method: "POST" });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || "Approvazione fallita");
  }
  return res.json();
}

export async function fetchPolicies() {
  const res = await fetch("/api/policies");
  if (!res.ok) throw new Error("Impossibile leggere le policy");
  return (await res.json()).policies;
}

export async function addPolicy(body) {
  const res = await fetch("/api/policies", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || "Creazione policy fallita");
  }
  return res.json();
}

export async function deletePolicy(docId) {
  const res = await fetch(`/api/policies/${encodeURIComponent(docId)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Eliminazione policy fallita");
  return res.json();
}

// --- Feedback loop (Part 3, proposal 3) ---

export async function submitFeedback(body) {
  const res = await fetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || "Invio metriche fallito");
  }
  return res.json();
}

export async function fetchFeedback() {
  const res = await fetch("/api/feedback");
  if (!res.ok) throw new Error("Impossibile leggere il feedback");
  return (await res.json()).feedback;
}

export async function fetchKeywordPriorities(candidates) {
  const res = await fetch("/api/keyword-priorities", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ candidates }),
  });
  if (!res.ok) throw new Error("Calcolo priorità fallito");
  return res.json(); // { priorities, history_posts_with_engagement }
}

// Open the SSE stream for a job. Calls onEvent(payload) for every event and
// returns the EventSource so the caller can close it.
export function openJobStream(jobId, onEvent, onDone) {
  const es = new EventSource(`/api/jobs/${jobId}/stream`);
  es.onmessage = (e) => {
    try {
      onEvent(JSON.parse(e.data));
    } catch {
      /* ignore keep-alive / malformed frames */
    }
  };
  es.addEventListener("end", () => {
    es.close();
    if (onDone) onDone();
  });
  es.onerror = () => {
    es.close();
    if (onDone) onDone();
  };
  return es;
}
