# Blog Automation — Report Tecnico

Pipeline automatizzata per la generazione, validazione, controllo di compliance
e pubblicazione di articoli di blog in ambito FinTech (brand di esempio:
*NorthLedger Finance*). Questo documento descrive l'architettura, le librerie
usate e l'orchestrazione passo per passo.

---

## 1. Panoramica dell'architettura

Il sistema è composto da tre strati:

| Strato | Cartella | Tecnologia | Ruolo |
|--------|----------|-----------|-------|
| **Pipeline** | `src/` | LangGraph | Orchestrazione dei nodi di generazione e controllo |
| **Backend API** | `server/` | FastAPI + Uvicorn | Espone la pipeline via HTTP/SSE, persiste i risultati |
| **Frontend** | `web/` | React + Vite | UI per generare, ispezionare i blog e gestire le policy |

Esistono due entry point alla pipeline:

- **CLI** — `main.py`, per esecuzioni batch da terminale (es. uno scheduler che
  processa N keyword/giorno).
- **API/Web** — `server/app.py`, che esegue la stessa pipeline ma in streaming
  nodo-per-nodo verso il browser.

Entrambi chiamano le stesse funzioni in `src/pipeline_graph.py`
(`run_for_keyword` / `stream_for_keyword`), quindi non esiste logica duplicata
tra CLI e Web.

---

## 2. Stack tecnologico (librerie)

### Orchestrazione
- **LangGraph** (`langgraph>=0.2.0`, con `langchain-core`) — definisce la
  pipeline come un grafo a stati con cicli (retry) ed edge condizionali. È la
  scelta centrale del progetto: vedi §4.

### LLM
- **anthropic** (`anthropic>=0.40.0`) — SDK ufficiale Claude, provider di
  default.
- **openai** *(opzionale)* — caricato solo se `LLM_PROVIDER=openai`.
- **Ollama** — chiamato via HTTP (`requests`), nessun SDK dedicato; per modelli
  locali.
- **Mock** — generatore deterministico interno, nessuna rete né API key.

### SEO e testo
- **textstat** — indice di leggibilità (Flesch Reading Ease).
- **python-slugify** — slug URL-safe.
- **markdown** — rendering Markdown → HTML.

### Similarità ed embedding
- **scikit-learn** (`scikit-learn>=1.4.0`) — `TfidfVectorizer` +
  `cosine_similarity` per l'internal linking; `TfidfVectorizer` +
  `TruncatedSVD` (LSA) come embedder per il vector index.
- **qdrant-client** (`qdrant-client>=1.18.0`) — vector store in *local mode*
  (`:memory:`), nessun server da avviare.
- **numpy** — operazioni vettoriali (norme, normalizzazione coseno).

> **Nota sull'embedder**: NON si usa LangChain per gli embedding. L'embedder è
> LSA = **TF-IDF + Truncated SVD di scikit-learn**. È la scelta "free/offline":
> nessun download di pesi, nessuna API key. In produzione l'astrazione
> `EmbeddingProvider` permette di sostituirlo con un modello neurale (lo stub
> `VoyageEmbeddingProvider` mostra la forma della chiamata).

### Ricerca web
- **ddgs** (`ddgs==9.14.4`) — ricerca DuckDuckGo (ex `duckduckgo-search`), senza
  API key. Usata per la web research e il web fact-check.

### Web / persistenza
- **fastapi** + **uvicorn** — backend API e server ASGI con auto-reload.
- **sqlite3** (stdlib) — persistenza dei blog generati.
- **React 18 + react-router-dom + Vite** — frontend SPA.

### Configurazione
- **python-dotenv** — carica `.env`; tutti i parametri tunabili stanno in
  `config.py` (`Settings`).

---

## 3. Configurazione (`config.py`)

Tutta la configurazione è centralizzata nella dataclass `Settings`, con override
via variabili d'ambiente. Parametri principali:

- **LLM**: `llm_provider`, `anthropic_model`, `max_tokens`, `temperature`.
- **Budget input-token**: `max_input_tokens`, `max_context_tokens`,
  `max_compliance_draft_tokens` (vedi §6).
- **Requisiti di contenuto**: `min/max_word_count`, densità keyword target,
  Flesch minimo, range di link interni.
- **Quality gate**: `min_seo_score_to_publish`, `max_generation_retries`,
  `banned_phrases`, `compliance_guidelines`.
- **Pubblicazione**: finestra di pubblicazione (giorni/ora), WordPress REST,
  `dry_run_publish` (default `True`).

---

## 4. Orchestrazione con LangGraph (`src/pipeline_graph.py`)

### Perché un grafo e non uno script lineare

Due requisiti rendono il flusso **non lineare**:

1. **Retry con feedback** — se la quality gate boccia una bozza, il flusso deve
   tornare alla generazione del contenuto *passando le motivazioni del rifiuto*,
   non semplicemente fallire. È un **ciclo** nel grafo.
2. **Human-in-the-loop** — dopo N retry falliti, *oppure* se il topic è marcato
   ad alta importanza, il flusso va a un nodo terminale `needs_review` invece di
   pubblicare.

LangGraph supporta nativamente cicli ed edge condizionali
(`add_conditional_edges`), cosa che uno script con chiamate in sequenza non
permette senza while-loop scritti a mano.

### Il grafo

```
keyword_input (tag importance_tier + voice_profile)
      │
      ▼
web_research        (snippet DuckDuckGo — solo alla prima esecuzione)
      │
      ▼
generate_content  ◄──────────────┐
      │                          │ retry (feedback allegato)
      ▼                          │
seo_optimize                     │
      │                          │
      ▼                          │
internal_linking                 │
      │                          │
      ▼                          │
compliance_judge                 │
      │                          │
      ▼                          │
policy_fact_check  (RAG sulle policy aziendali)
      │                          │
      ▼                          │
web_fact_check     (verifica claim via DuckDuckGo)
      │                          │
      ▼                          │
duplicate_check    (vs published_posts)
      │                          │
      ▼                          │
quality_gate ───── quality fail ─┘
   │        \      & retry disponibili
pass│         \
& imp.│        ▼
std  │     needs_review  ◄── raggiunto direttamente anche quando
     ▼                       importance_tier == "high"
  publish
(poi indicizza il post in published_posts
 per i futuri controlli di duplicazione)
```

### Stato condiviso (`src/state.py`)

LangGraph passa un unico oggetto di stato (`PipelineState`, un `TypedDict`) tra i
nodi. Ogni nodo legge i campi che gli servono e restituisce un dict parziale di
update che LangGraph fonde nello stato. Definirlo esplicitamente rende il
contratto di ogni nodo ovvio e il grafo facile da estendere.

### Nodi speciali

- `_increment_retries` — incrementa `retries` sul ramo di retry.
- `_needs_review` — scrive il "review packet" e imposta `status=needs_review`.
- `_publish_and_index` — pubblica e indicizza il post nei `published_posts`.

### Routing condizionale (`route_after_quality_gate`)

```python
if not quality_passed:
    if retries < max_generation_retries: return "retry"
    return "needs_review"
if importance_tier == "high":        return "needs_review"
return "publish"
```

### Recursion limit

`_recursion_limit()` calcola un budget di passi dal numero di retry configurati
`(max_generation_retries + 1) * 10 + 5`, così che una bozza che non passerà mai
la quality gate termini pulita in `needs_review` invece di crashare con
`GRAPH_RECURSION_LIMIT`.

### Streaming (`stream_for_keyword`)

Per il frontend si usa `app.stream(..., stream_mode="updates")`, che emette
`{nome_nodo: update_parziale}` dopo ogni nodo. Una callback `on_node` inoltra
ogni update come evento SSE, ed è esattamente la granularità che serve alla UI
per disegnare la timeline nodo-per-nodo.

---

## 5. I passaggi della pipeline in dettaglio

### 5.0 Keyword input — tagging
- `importance_tagger.tag_importance_from_keyword` — assegna
  `importance_tier` = `standard`/`high` in base a una lista di trigger sensibili
  (tasse, FDIC, tassi, frodi, confronti con competitor…).
- `voice_profiles.assign_voice_profile` — assegna in modo **deterministico**
  (hash stabile della keyword) uno di 4 profili di voce (`analytical`,
  `conversational`, `structured`, `narrative`), così da non lasciare un'unica
  "impronta AI" su tutti i post. Resta fisso tra i retry.

### 5.1 Web research (`src/web_research.py`)
Interroga DuckDuckGo (`ddgs`) sulla keyword e raccoglie fino a 5 snippet, salvati
in `web_research_context` e iniettati nel prompt di generazione. **Non
bloccante**: su qualsiasi errore (rete, rate limit) restituisce contesto vuoto e
la pipeline prosegue.

### 5.2 Content generation (`src/content_generator.py`)
Costruisce un prompt SEO-aware (system + user) attorno a keyword, brand voice e
profilo di voce, poi chiama il provider LLM (`task="content"`). Sul ramo di retry,
allega le motivazioni del rifiuto precedente al prompt. Applica il budget di
input-token (§6) al contesto web e al prompt finale. Produce `raw_markdown` e
`title`.

### 5.3 SEO optimization (`src/seo_optimizer.py`)
Analisi SEO **pure-Python** (niente SaaS a pagamento):
- conteggio parole, Flesch (textstat), densità keyword, conteggio H1/H2;
- genera `meta_title`, `meta_description`, `slug` (python-slugify);
- calcola uno `score` 0–100 ed emette `issues`/`suggestions`.
Inietta i metadati come front-matter HTML in testa al markdown.

### 5.4 Internal linking (`src/internal_linking.py`)
TF-IDF + cosine similarity (scikit-learn) tra il nuovo post e il catalogo dei
contenuti esistenti (`data/existing_site_content.json`). Per i match più
rilevanti, inserisce automaticamente link contestuali nel testo (sui tag
dell'articolo target, evitando heading e front-matter). Produce `internal_links`
e `linked_markdown`.

### 5.5 Compliance judge (`src/compliance_judge.py`)
LLM-as-judge (`task="compliance"`): valuta la bozza **solo** rispetto alle
`compliance_guidelines` e restituisce JSON stretto
`{"passed": bool, "reasons": [...]}`. Se la bozza supera il budget token, viene
**chunked** e ogni chunk giudicato separatamente, poi i verdetti si fondono
(fallisce se *un* chunk fallisce) — mai riassunta, perché un riassunto potrebbe
nascondere proprio la frase incriminata. **Fail-closed**: se la risposta non è
parsabile, viene trattata come "needs review".

### 5.6 Policy fact-check (`src/policy_fact_check.py`) — RAG
Estrae dalla bozza le frasi-"claim" (numeri, tassi, termini come *guaranteed*,
*FDIC*…), e per ciascuna interroga il vector index delle policy aziendali
(`query_policies`). Segnala il claim se:
- nessuna policy viene recuperata, o
- la migliore similarità è sotto soglia (`MIN_GROUNDING_SCORE`), o
- la policy recuperata **contraddice** il claim (regole di negazione esplicite,
  es. claim "guaranteed" vs policy "not guaranteed").

### 5.7 Web fact-check (`src/web_fact_check.py`)
Per i primi N claim, interroga DuckDuckGo: un claim che non restituisce alcun
risultato è marcato come "esternamente non verificabile". Non bloccante sugli
errori di rete.

### 5.8 Duplicate check (`src/semantic_duplicate_check.py`)
Confronta semanticamente la bozza con i `published_posts` nel vector index. Sopra
una soglia di similarità alta (0.90) la segnala come quasi-duplicato.

### 5.9 Quality gate (`src/quality_gate.py`)
Combina due assi:
1. **Qualità** — banned phrases, soglia SEO, lunghezza minima, esiti di
   compliance/fact-check/duplicate. Se fallisce e ci sono retry → loop-back.
2. **Importanza** — un topic `high` va sempre a `needs_review`, anche con
   qualità perfetta (non è un fallimento e non scatena retry).

### 5.10 Publish (`src/publisher.py`)
Target di esempio: WordPress REST API. Con `dry_run_publish=True` (default) NON
fa chiamate reali: scrive HTML + un manifest JSON in `outputs/`. Scrive anche
URL canonico, slot di pubblicazione programmato (finestra giorni/ora) e la
**AI-content disclosure** (testo diverso a seconda del ramo: auto-publish vs
review).

---

## 6. Token budgeting (`src/token_budget.py`)

Due input possono crescere senza limiti e sforare la finestra del modello: il
contesto di web research e la bozza data al compliance judge. Il modulo offre:

- `estimate_tokens` — stima offline (chars/4) o esatta via tiktoken se presente.
- `chunk_by_tokens` — split su confini di paragrafo/frase, mai a metà parola.
- `truncate_to_budget` — taglio netto su confine pulito.
- `extractive_summarize` — riassunto deterministico offline (ranking frasi).
- `compress_to_budget` — entry point: se già nel budget lo lascia intatto,
  altrimenti riassume (abstractive via LLM se `summarizer_use_llm`, altrimenti
  extractive). Il Mock provider non riassume mai → fallback extractive.

Distinzione chiave: il **contesto web viene riassunto** (perdere dettaglio è ok),
la **bozza per la compliance viene chunked, mai riassunta** (un riassunto
potrebbe nascondere una violazione).

---

## 7. Astrazioni pluggable

### LLM (`src/llm_providers.py`)
Tutta la pipeline parla con una sola interfaccia `LLMProvider.generate(system,
user)`. Cambiare modello = scrivere un piccolo adapter, zero modifiche ai nodi.
Provider: `anthropic`, `openai`, `ollama` (con routing per-task:
content→gemma, compliance→granite, default→qwen), `mock`.

### Embedding (`src/embeddings.py`)
Interfaccia `EmbeddingProvider.fit/embed`. Implementazioni:
- `LSAEmbeddingProvider` — TF-IDF + TruncatedSVD (in uso, offline).
- `VoyageEmbeddingProvider` — stub per la versione di produzione.

`LSAEmbeddingProvider` include una difesa contro i vettori **degeneri**: un testo
che condivide ≤1 termine col corpus produrrebbe una similarità coseno
ingannevolmente alta; viene azzerato invece di essere considerato un match.

---

## 8. Vector index (`src/vector_index.py`)

Qdrant in *local mode* (`QdrantClient(":memory:")`) con due collezioni:
- `company_policies` — per il fact-check RAG (§5.6).
- `published_posts` — per il duplicate check (§5.8).

`build()` fitta l'embedder **una volta sola** sull'unione dei due corpora (così
policy e post condividono lo stesso spazio vettoriale), poi popola le collezioni.
L'indice è un **singleton** di processo (`get_knowledge_base_index`) perché il
fit è il passo costoso.

`reset_knowledge_base_index()` azzera il singleton: serve quando cambia il set di
policy (vedi §10), perché l'embedder LSA è fit-once e una nuova policy entra nello
spazio vettoriale solo dopo un rebuild (che avviene lazy alla run successiva,
sotto il lock di generazione).

---

## 9. Backend API (`server/app.py`)

FastAPI + Uvicorn. Endpoint principali:

| Metodo | Path | Funzione |
|--------|------|----------|
| GET | `/api/providers` | Lista provider LLM e quello corrente |
| POST | `/api/generate` | Avvia un job di generazione → `{job_id}` |
| GET | `/api/jobs/{id}/stream` | Stream SSE nodo-per-nodo del job |
| GET | `/api/blogs` / `/api/blogs/{id}` | Lista / dettaglio blog |
| DELETE | `/api/blogs/{id}` | Elimina un blog |
| GET/POST | `/api/policies` | Lista / crea policy |
| DELETE | `/api/policies/{doc_id}` | Elimina policy |

**Concorrenza**: i nodi leggono il provider dal `settings` globale, quindi ogni
richiesta imposta il provider su quel singleton appena prima di eseguire. Per
evitare che due richieste si pestino i piedi, la generazione è serializzata con
un singolo `threading.Lock` (`_GEN_LOCK`) — adatto a uno strumento di test
locale.

**Streaming**: `_run_job` gira in un thread di background e pubblica eventi su una
`queue.Queue`; `stream_job` la drena come Server-Sent Events. Tipi di evento:
`start`, `node`, `done`, `error`, più il sentinella di fine stream.

---

## 10. Persistenza

### Blog (`server/db.py`)
SQLite, una tabella `blogs`. Ogni run finita è una riga; l'URL pubblico
`/blog_N` è semplicemente l'`id` intero. Lo **stato completo** della pipeline è
salvato come JSON in `state_json`, così la pagina di dettaglio può mostrare tutto
(SEO, esiti dei check, link, **e gli output intermedi** come il contesto web).

`get_blog` espone anche un campo `steps` costruito *in lettura* da
`_build_pipeline_steps(state)`: appiattisce lo stato in una lista ordinata di
output per-passaggio (ricerca web, bozza grezza, findings SEO, motivazioni dei
fact-check, post simili…), così il frontend può renderizzarli genericamente.
Vantaggio: nessuna migrazione, funziona anche per i blog già salvati (la fonte di
verità resta `state_json`).

### Policy (`src/policy_store.py`)
Le policy vivono in `data/company_policies.json` — lo stesso file che il vector
index già legge. Questo modulo è l'unico write-path (CRUD: `list/add/delete`),
mantiene unici i `doc_id` e coerente lo schema. Dopo ogni mutazione il backend
chiama `reset_knowledge_base_index()` così la nuova policy entra nell'indice
vettoriale alla run successiva.

---

## 11. Frontend (`web/`)

React + Vite, dev server su :8080 con proxy `/api` → :8000.

- **`GeneratePage`** — form (provider, modello, API key, keyword), timeline
  live nodo-per-nodo via SSE, lista dei blog salvati.
- **`BlogPage`** (`/blog_N`) — articolo renderizzato + sidebar (stato, SEO,
  controlli, link interni) + sezione **"Output dei passaggi della pipeline"**
  che mostra tutti gli output intermedi salvati (incluse le info da internet).
- **`PoliciesPage`** (`/policies`) — form per scrivere nuove policy (con esempi
  pronti precompilabili) e lista delle policy attive con eliminazione.

---

## 12. Logging (`src/logging_config.py`)

Logging centralizzato su stdout con formato `[LIVELLO] modulo: messaggio`. Ogni
modulo della pipeline ottiene il proprio logger via `get_logger("nome")` e
registra INFO (avanzamento, decisioni di routing), WARNING (check falliti,
fallback) ed ERROR (eccezioni). Configurato all'avvio sia dalla CLI (`main.py`)
sia dal server (`server/app.py`).

---

## 13. Come eseguire

### Web (consigliato)
```powershell
.\run.ps1 -Install     # prima volta: installa dipendenze Python + npm
.\run.ps1              # avvia backend :8000 e frontend :8080
```
Poi apri http://localhost:8080.

### CLI
```bash
python main.py "how to start investing" "best budgeting apps"
python main.py --file keywords.txt
python main.py                 # esegue le 3 keyword demo
```

Con `LLM_PROVIDER=mock` (default) gira senza API key né rete, esercitando l'intera
pipeline end-to-end. Per generazione reale: `LLM_PROVIDER=anthropic` +
`ANTHROPIC_API_KEY`.

---

## 14. Flusso dati riassuntivo

```
keyword
  → [tagging] importance_tier, voice_profile
  → [web_research] web_research_context        (ddgs)
  → [generate]    raw_markdown, title          (LLM + token budget)
  → [seo]         seo_report, optimized_markdown (textstat, slugify)
  → [linking]     internal_links, linked_markdown (scikit-learn TF-IDF)
  → [compliance]  compliance                   (LLM-as-judge)
  → [policy_fc]   fact_check                   (Qdrant + LSA RAG)
  → [web_fc]      web_fact_check               (ddgs)
  → [dup_check]   duplicate_check              (Qdrant + LSA)
  → [quality]     quality + routing
        ├─ publish      → publish_result, status, canonical_url, disclosure
        └─ needs_review → review packet
  → [persist] SQLite (state_json + steps) → /blog_N
```

---

## 15. Feedback loop sull'engagement (Part 3, proposta 3)

Oltre al *retry-con-feedback* della pipeline (che migliora **lo stesso post**),
esiste un secondo loop, separato, che impara dai **risultati dei post già
pubblicati** per decidere **cosa scrivere dopo**. Componenti:

- **Tabella `feedback`** (`server/db.py`) — una riga per ogni invio di metriche
  (`impressions`, `clicks`, `avg_time_sec`, `conversions`) legata a un blog.
- **Endpoint** — `POST /api/feedback` (salva le metriche), `POST
  /api/keyword-priorities` (ricalcola le priorità).
- **Algoritmo** (`src/keyword_priority.py`) — `engagement_score` (CTR-dominante),
  punteggi **centrati sulla media** (sopra-media → peso positivo, sotto-media →
  negativo), e priorità di ogni keyword candidata = somma pesata per similarità
  (TF-IDF + cosine, la stessa dell'internal linking) verso i post storici. Ogni
  risultato porta una motivazione in linguaggio naturale.
- **Frontend** — `web/src/pages/FeedbackPage.jsx` per inserire metriche e vedere
  le keyword future ri-classificarsi.

**Guardrail**: il loop tara *cosa scrivere dopo*, **mai** le soglie di compliance
(restano umane: un CTR alto non può mai convincere il sistema a un claim più
rischioso).

### ⚠️ Limite attuale e cosa serve in produzione

**Le metriche di engagement sono inserite a mano, non raccolte in automatico.**
Non esiste un'integrazione che tiri giù impressions/click reali da **Google
Analytics (GA4)**, **Google Search Console (GSC)** o dal **CMS**: nel prototipo
(e nella demo) le metriche si digitano via UI/API. Di conseguenza il sistema è
testato **solo su dati fittizi**.

Quello che è reale è il **meccanismo di apprendimento** (lo scoring e il
ri-ranking funzionano e sono testati); quello che **manca** è l'**ingestione
automatica delle metriche reali**. Per un progetto serio / in produzione
andrebbe aggiunto un connettore che, su base schedulata, importi
automaticamente le metriche reali da **GA4 / GSC / CMS** e le scriva nella
tabella `feedback`, chiudendo il loop senza intervento manuale. Solo a quel
punto il loop dimostrerebbe un **aumento reale di engagement** e non solo la
correttezza del meccanismo.
