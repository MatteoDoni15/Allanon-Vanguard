# Blog Automation — React tester

Lightweight React UI to drive the LangGraph blog pipeline: pick a model
(Ollama / Anthropic / OpenAI / mock), send a keyword, watch the pipeline run
node-by-node, and browse the generated posts (saved in a local SQLite DB) at
`/blog_1`, `/blog_2`, ...

## Architecture

```
React (Vite, :8080)  ──/api proxy──▶  FastAPI (:8000)  ──▶  LangGraph pipeline
        │                                   │                       │
   live node timeline              SSE node events          stream_for_keyword()
   /blog_N pages                   SQLite (server/blogs.db)
```

## Run it (two terminals)

**1. Backend** (from `blog_automation/`):

```bash
pip install -r requirements.txt
uvicorn server.app:app --reload --port 8000
```

**2. Frontend** (from `blog_automation/web/`):

```bash
npm install
npm run dev
```

Open <http://localhost:8080>. Generated posts are then at
<http://localhost:8080/blog_1>, `/blog_2`, ...

## Notes

- **Mock** provider needs no API key — good for a first end-to-end test.
- **Ollama** uses your local instance (default `http://localhost:11434`); the
  "specific model" field overrides the content-generation model.
- **Anthropic / OpenAI**: paste an API key in the form (kept only in the local
  backend process for that run) or set `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
  in `.env`.
- Generation runs one job at a time (the pipeline switches a global provider
  setting per run), which is plenty for local testing.
