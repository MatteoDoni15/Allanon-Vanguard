"""
FastAPI backend for the React blog-tester UI.

Responsibilities
----------------
1. Kick off a pipeline run for a keyword with a user-chosen LLM provider/model
   (POST /api/generate -> returns a job_id).
2. Stream that run node-by-node to the browser over Server-Sent Events
   (GET /api/jobs/{job_id}/stream), so the UI can draw a live progress timeline.
3. Persist every finished post to a local SQLite DB and expose it at a stable
   id the frontend renders as /blog_1, /blog_2, ... (GET /api/blogs[/{id}]).

Why a background thread + a lock
--------------------------------
The pipeline nodes read the active provider from the *global* ``settings``
singleton (config.py), so a request picks its provider by mutating that
singleton just before running. To keep two concurrent requests from stepping
on each other's provider choice, generation is serialised with a single lock:
fine for a local testing tool, and it keeps the provider switch race-free.

Run it:
    pip install -r requirements.txt
    uvicorn server.app:app --reload --port 8000
(run from the blog_automation/ directory)
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import sys
import threading
import uuid
from typing import Any

# Make the project root (blog_automation/) importable when uvicorn is launched
# from elsewhere, so `config` and `src` resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import settings
from src.logging_config import configure_logging, get_logger
from server import db
from src import policy_store
from src.vector_index import reset_knowledge_base_index
from src.keyword_priority import compute_keyword_priorities
from src.pipeline_graph import NODE_LABELS, NODE_ORDER, stream_for_keyword

configure_logging()
logger = get_logger("server")

app = FastAPI(title="Blog Automation API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local testing tool; the Vite dev server lives on :8080
    allow_methods=["*"],
    allow_headers=["*"],
)

# job_id -> queue of SSE event dicts (a None item signals end-of-stream)
_JOBS: dict[str, "queue.Queue[dict | None]"] = {}
# Only one pipeline runs at a time (it mutates the global provider settings).
_GEN_LOCK = threading.Lock()

PROVIDERS = {
    "mock": {"label": "Mock (no key, deterministic)", "needs_key": False,
             "default_model": ""},
    "ollama": {"label": "Ollama (local models)", "needs_key": False,
               "default_model": settings.ollama_content_model},
    "anthropic": {"label": "Anthropic (Claude API)", "needs_key": True,
                  "default_model": settings.anthropic_model},
    "openai": {"label": "OpenAI (GPT API)", "needs_key": True,
               "default_model": settings.openai_model},
}


class GenerateRequest(BaseModel):
    keyword: str
    provider: str = "mock"
    model: str | None = None
    api_key: str | None = None
    ollama_url: str | None = None
    target_audience: str = "general retail banking customers"


class PolicyRequest(BaseModel):
    title: str
    text: str


class FeedbackRequest(BaseModel):
    blog_id: int
    impressions: int = 0
    clicks: int = 0
    avg_time_sec: float = 0.0
    conversions: int = 0


class PriorityRequest(BaseModel):
    candidates: list[str]


def _apply_provider(req: GenerateRequest) -> None:
    """Point the global settings (and API-key env vars) at the chosen provider."""
    logger.info(f"Applying provider configuration: {req.provider}")
    settings.llm_provider = req.provider
    if req.provider == "ollama":
        if req.ollama_url:
            logger.info(f"Setting Ollama base URL: {req.ollama_url}")
            settings.ollama_base_url = req.ollama_url
        if req.model:
            logger.info(f"Setting Ollama content model: {req.model}")
            settings.ollama_content_model = req.model
    elif req.provider == "anthropic":
        if req.model:
            logger.info(f"Setting Anthropic model: {req.model}")
            settings.anthropic_model = req.model
        if req.api_key:
            logger.info("Setting Anthropic API key from request")
            os.environ["ANTHROPIC_API_KEY"] = req.api_key
    elif req.provider == "openai":
        if req.model:
            logger.info(f"Setting OpenAI model: {req.model}")
            settings.openai_model = req.model
        if req.api_key:
            logger.info("Setting OpenAI API key from request")
            os.environ["OPENAI_API_KEY"] = req.api_key


def _node_event(node: str, update: dict, state: dict) -> dict:
    """Shape one finished-node update into an SSE payload for the timeline."""
    payload: dict[str, Any] = {
        "type": "node",
        "node": node,
        "label": NODE_LABELS.get(node, node),
        "update_keys": list(update.keys()),
    }
    if node in NODE_ORDER:
        idx = NODE_ORDER.index(node) + 1
        payload["index"] = idx
        payload["total"] = len(NODE_ORDER)
        payload["progress"] = round(idx / len(NODE_ORDER) * 100)
    # Surface a pass/fail hint for the check nodes so the UI can colour them.
    for key in ("compliance", "fact_check", "web_fact_check", "duplicate_check", "quality"):
        if isinstance(update.get(key), dict) and "passed" in update[key]:
            payload["passed"] = update[key]["passed"]
            payload["reasons"] = update[key].get("reasons", [])
    if node == "increment_retries":
        payload["retries"] = state.get("retries")
    return payload


def _run_job(job_id: str, req: GenerateRequest) -> None:
    q = _JOBS[job_id]
    logger.info(f"Job {job_id}: Starting generation for keyword '{req.keyword}'")
    try:
        with _GEN_LOCK:
            _apply_provider(req)
            q.put({"type": "start", "keyword": req.keyword,
                   "provider": req.provider,
                   "model": req.model or PROVIDERS.get(req.provider, {}).get("default_model", ""),
                   "total": len(NODE_ORDER)})

            def on_node(node: str, update: dict, state: dict) -> None:
                logger.info(f"Job {job_id}: Node '{node}' completed")
                q.put(_node_event(node, update, state))

            logger.info(f"Job {job_id}: Starting pipeline execution")
            state = stream_for_keyword(
                req.keyword, target_audience=req.target_audience, on_node=on_node
            )
            blog_id = db.save_blog(state, provider=req.provider, model=req.model)
            status = state.get("status")
            logger.info(f"Job {job_id}: Pipeline complete - status={status}, blog_id={blog_id}")
            q.put({
                "type": "done",
                "blog_id": blog_id,
                "url": f"/blog_{blog_id}",
                "status": status,
                "title": state.get("title"),
                "seo_score": (state.get("seo_report") or {}).get("score"),
            })
    except Exception as exc:
        logger.error(f"Job {job_id}: Error during generation - {str(exc)}", exc_info=True)
        q.put({"type": "error", "message": str(exc)})
    finally:
        q.put(None)


@app.get("/api/providers")
def get_providers() -> dict:
    logger.info("API: Fetching available providers")
    return {"providers": PROVIDERS, "current": settings.llm_provider}


@app.post("/api/generate")
def generate(req: GenerateRequest) -> dict:
    if req.provider not in PROVIDERS:
        logger.warning(f"API: Invalid provider requested: {req.provider}")
        raise HTTPException(400, f"Unknown provider '{req.provider}'")
    if not req.keyword.strip():
        logger.warning("API: Empty keyword provided")
        raise HTTPException(400, "Keyword is required")
    job_id = uuid.uuid4().hex
    logger.info(f"API: Creating job {job_id} for keyword '{req.keyword}' with provider={req.provider}")
    _JOBS[job_id] = queue.Queue()
    threading.Thread(target=_run_job, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}/stream")
async def stream_job(job_id: str) -> StreamingResponse:
    q = _JOBS.get(job_id)
    if q is None:
        raise HTTPException(404, "Unknown job id")

    async def event_gen():
        try:
            while True:
                try:
                    item = q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.1)
                    continue
                if item is None:  # end-of-stream sentinel
                    yield "event: end\ndata: {}\n\n"
                    break
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            _JOBS.pop(job_id, None)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/blogs")
def get_blogs() -> dict:
    logger.info("API: Fetching all blogs")
    return {"blogs": db.list_blogs()}


@app.get("/api/blogs/{blog_id}")
def get_blog(blog_id: int) -> dict:
    logger.info(f"API: Fetching blog {blog_id}")
    blog = db.get_blog(blog_id)
    if blog is None:
        logger.warning(f"API: Blog {blog_id} not found")
        raise HTTPException(404, "Blog not found")
    return blog


@app.post("/api/blogs/{blog_id}/approve")
def approve_blog(blog_id: int) -> dict:
    """Human-in-the-loop sign-off: a reviewer approves a needs_review post."""
    logger.info(f"API: Approving (human review) blog {blog_id}")
    if not db.approve_blog(blog_id):
        logger.warning(f"API: Blog {blog_id} not found or not awaiting review")
        raise HTTPException(409, "Blog non trovato o non in attesa di revisione")
    logger.info(f"API: Blog {blog_id} approved -> published")
    return {"approved": blog_id, "status": "published"}


@app.delete("/api/blogs/{blog_id}")
def remove_blog(blog_id: int) -> dict:
    logger.info(f"API: Deleting blog {blog_id}")
    if not db.delete_blog(blog_id):
        logger.warning(f"API: Blog {blog_id} not found for deletion")
        raise HTTPException(404, "Blog not found")
    logger.info(f"API: Successfully deleted blog {blog_id}")
    return {"deleted": blog_id}


@app.get("/api/policies")
def get_policies() -> dict:
    logger.info("API: Fetching company policies")
    return {"policies": policy_store.list_policies()}


@app.post("/api/policies")
def create_policy(req: PolicyRequest) -> dict:
    if not req.title.strip() or not req.text.strip():
        logger.warning("API: Policy title or text missing")
        raise HTTPException(400, "Sia il titolo che il testo della policy sono obbligatori")
    doc = policy_store.add_policy(req.title, req.text)
    # The new policy must enter the vector space: refit on next pipeline run.
    reset_knowledge_base_index()
    logger.info("API: Vector index reset -- will rebuild with new policy on next run")
    return doc


@app.delete("/api/policies/{doc_id}")
def remove_policy(doc_id: str) -> dict:
    logger.info(f"API: Deleting policy {doc_id}")
    if not policy_store.delete_policy(doc_id):
        raise HTTPException(404, "Policy non trovata")
    reset_knowledge_base_index()
    logger.info("API: Vector index reset -- will rebuild without the policy on next run")
    return {"deleted": doc_id}


# --- Feedback loop (Part 3, proposal 3) --------------------------------------

@app.post("/api/feedback")
def submit_feedback(req: FeedbackRequest) -> dict:
    if db.get_blog(req.blog_id) is None:
        logger.warning(f"API: Feedback for unknown blog {req.blog_id}")
        raise HTTPException(404, "Blog non trovato")
    fid = db.save_feedback(
        req.blog_id, req.impressions, req.clicks, req.avg_time_sec, req.conversions
    )
    logger.info(
        f"API: Stored feedback {fid} for blog {req.blog_id} "
        f"(impressions={req.impressions}, clicks={req.clicks})"
    )
    return {"feedback_id": fid, "blog_id": req.blog_id}


@app.get("/api/feedback")
def get_feedback() -> dict:
    logger.info("API: Fetching engagement feedback")
    return {"feedback": db.list_feedback()}


@app.post("/api/keyword-priorities")
def keyword_priorities(req: PriorityRequest) -> dict:
    logger.info(f"API: Computing keyword priorities for {len(req.candidates)} candidate(s)")
    history = db.history_for_priority()
    ranked = compute_keyword_priorities(req.candidates, history)
    posts_with_data = sum(1 for h in history if h.get("metrics"))
    return {"priorities": ranked, "history_posts_with_engagement": posts_with_data}


@app.on_event("startup")
def _startup() -> None:
    logger.info("Server: Initializing database")
    db.init_db()
    logger.info("Server: Application startup complete")
