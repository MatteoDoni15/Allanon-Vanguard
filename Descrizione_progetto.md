# Automatizzare la Creazione di 700 Blog al Mese — Design Document

**Automazione di contenuti FinTech — progettazione end-to-end, implementazione e proposte Gen-AI/ML**

Questo è il documento di consegna per l'assignment. Copre tutte e quattro le parti:
il workflow (Parte 1), ciò che è implementato nel codice (Parte 2), i metodi di
Generative-AI / ML usati per valutare e migliorare la qualità dei contenuti
(Parte 3), e come i componenti si collegano in un unico flusso scalabile (Parte 4).
È accompagnato da un progetto Python funzionante (`README.md` per come eseguirlo)
e da un report tecnico di implementazione (`report.md`).

In tutto il documento viene tracciata una linea netta tra **ciò che gira come
codice oggi** e **ciò che è una proposta con relativi costi** per la produzione —
quest'ultima principalmente dove serve un'API/modello gestito o dati di produzione
reali che un prototipo locale non può onestamente sostituire.

---

## 0. Inquadramento del problema

Un'azienda FinTech deve pubblicare ~700 blog post/mese (~23/giorno), ciascuno
**pertinente, ottimizzato SEO, on-brand e conforme**, con la pubblicazione
automatizzata end-to-end. In un dominio regolamentato, "automatizzato" non può
significare "non supervisionato per tutto": il design deve auto-pubblicare la
maggioranza sicura instradando la minoranza genuinamente rischiosa a un umano,
senza una persona nel loop per ogni singolo post.

Tre forze plasmano ogni decisione qui sotto:

1. **Scala** — 700/mese esclude qualsiasi cosa con un lavoro manuale per-post
   significativo o un SaaS costoso a chiamata dove basta un calcolo locale.
2. **Rischio di compliance** — le regole sulla promozione finanziaria (nessun
   rendimento garantito, niente "risk-free", nessuna urgenza indebita, claim
   accurati su commissioni/tassi) rendono inaccettabile un puro loop
   "genera-e-pubblica".
3. **Qualità su volume** — 700 post quasi identici sarebbero un danno SEO e
   un'evidente "impronta AI"; varietà e de-duplicazione sono priorità di prima
   classe, non rifinitura.

---

## Parte 1 — Passi chiave del workflow

La pipeline è il seguente insieme ordinato di passi. Ciascuno è implementato come
un nodo in una macchina a stati LangGraph (Parte 4).

| # | Passo | Ruolo | Requisiti tecnici |
|---|------|------|------------------------|
| 0 | **Input keyword & tagging** | Accetta la keyword target; tagga l'*importanza* del topic (standard/alta) e assegna un *profilo di voce dello scrittore* interno. | Sorgente keyword (calendario contenuti / coda); una lista di tag di sensibilità o tag curati da umani; assegnazione deterministica della voce. |
| 1 | **Ricerca web** | Recupera contesto fresco e reale (cifre e fatti recenti) per la keyword così che la bozza non sia puramente memoria del modello. | API di ricerca web (DuckDuckGo qui, senza chiave); gestione del budget di token del contesto recuperato. |
| 2 | **Generazione contenuti** | Produce una bozza Markdown strutturata, on-brand e SEO-aware a partire dalla keyword. | Provider LLM (Claude/GPT/locale); prompt che porta brand voice, regole di compliance, target strutturali; controllo del budget di token in input. |
| 3 | **Ottimizzazione SEO** | Valuta e arricchisce la bozza: leggibilità, densità di keyword, headings, meta title/description, slug. | Libreria di leggibilità (textstat), libreria slug; scoring deterministico; suggerimenti di fix concreti reinseriti al retry. |
| 4 | **Internal linking** (il "plus") | Inserisce link contestuali dal nuovo post a contenuti esistenti del sito per migliorare SEO e navigazione. | Similarità su un catalogo di contenuti CMS (TF-IDF/coseno); inserimento sicuro nel testo che evita headings/link. |
| 5 | **Validazione & compliance** | Verifica la bozza rispetto alle linee guida scritte dell'azienda e alle policy aziendali prima che possa essere pubblicata. | LLM-as-judge; un indice RAG sui documenti di policy aziendali; controlli deterministici di frasi vietate. |
| 6 | **Quality gate & routing** | Una sola decisione: auto-pubblica, retry-con-feedback, o escala a un umano. | Soglie nella config; loop di retry limitato; override sul tier di rischio. |
| 7 | **Automazione pubblicazione** | Converte in HTML, allega metadati SEO/canonical/disclosure, programma e pubblica (o scrive un pacchetto di review). | API CMS (esempio WordPress REST); finestra di scheduling; AI-disclosure; modalità dry-run per i test. |

> **Nota di scope sul Passo 0 — *scoperta* di keyword vs *input* di keyword.** Il
> prototipo prende la keyword target come **input** (file / CLI / coda) e il loop
> di feedback (Parte 3, Proposta 3) *ri-classifica* un insieme di candidati
> esistente in base all'engagement passato. **Non** *scopre* attivamente nuovi
> topic. La scoperta attiva — far emergere topic FinTech di tendenza da una
> **ricerca di notizie (Brave Search API)** o tramite **scraping di fonti
> attendibili note** — è una proposta deliberata e con relativi costi (vedi
> Appendice C.1), lasciata fuori dal codice in esecuzione per ragioni di
> costo/stabilità, non di difficoltà. Questo è l'unico passo della Parte 1 senza
> una controparte attiva nel codice, ed è segnalato qui esplicitamente piuttosto
> che lasciato implicito.

---

## Parte 2 — Cosa è implementato in Python

L'assignment chiede che almeno i primi tre passi siano codificati, con
l'internal linking come plus. **Tutti i passi 1–7 sono implementati ed
eseguibili.** Il progetto gira end-to-end con **zero setup e zero costo API** in
modalità `mock` (un generatore di contenuti deterministico), così che l'intero
flusso — generazione → SEO → linking → compliance → gate → pubblicazione — possa
essere esercitato e testato unitariamente senza alcuna chiave. 36 unit test
coprono SEO, linking, parsing della compliance, l'indice vettoriale, il budgeting
dei token e la logica di routing.

Moduli chiave (tabella completa in `README.md`, approfondimento in `report.md`):

- **Generazione contenuti** — `src/content_generator.py`, con un'interfaccia
  `LLMProvider` plug-in (`src/llm_providers.py`): Anthropic (default), OpenAI,
  Ollama (locale, routing del modello per-task) e Mock. Cambiare provider è una
  modifica di config, non di codice.
- **SEO** — `src/seo_optimizer.py`: SEO **on-page** puramente in Python
  (leggibilità, densità di keyword, struttura degli heading, meta
  title/description, slug) — nessun SaaS SEO a pagamento, quindi costa zero per
  post a 700/mese. Deliberatamente **non** copre i fattori off-page / SERP
  (volume di ricerca, gap rispetto ai competitor, backlink): quelli appartengono
  al layer di scoperta delle keyword (Appendice C.1), non allo scoring per-post.
- **Internal linking** — `src/internal_linking.py`: TF-IDF + similarità del
  coseno (scikit-learn) contro `data/existing_site_content.json`.
- **Compliance & fact-check** — `src/compliance_judge.py`,
  `src/policy_fact_check.py`, `src/vector_index.py` (Parte 3, sotto).
- **Pubblicazione** — `src/publisher.py`: target API WordPress REST, il `dry_run`
  di default scrive HTML + un manifest di metadati in `outputs/`.
- **Orchestrazione** — `src/pipeline_graph.py` (Parte 4, sotto).

La scelta di rendere `mock` il default è deliberata: permette di **verificare il
design come sistema**, non solo di leggerlo, e mantiene onesta la logica di
SEO/linking/routing perché gira contro Markdown realmente generato.

---

## Parte 3 — Metodi Generative-AI / ML per valutare e migliorare la qualità

Qui è andato la maggior parte dello sforzo di design. Cinque proposte; **tutte e
cinque hanno ora codice in esecuzione** — il loop di feedback come meccanismo
minimo-ma-reale, le altre quattro più complete. Quelle implementate sono
deliberatamente oneste su dove i sostituti locali del prototipo differiscono dai
componenti di produzione raccomandati, e su cosa ciascuna prova e cosa *non*
prova.

### Proposta 1 — Validazione contenuti & compliance (LLM-as-judge) — IMPLEMENTATA

`src/compliance_judge.py` è un nodo del grafo che chiede all'LLM configurato di
valutare la bozza **solo** rispetto alle `compliance_guidelines` scritte
(config.py) e di restituire un JSON stretto `{"passed": bool, "reasons": [...]}`.

- **Perché LLM-as-judge, non un classificatore addestrato:** non esiste ancora un
  corpus etichettato di post storici "conformi / segnalati" su cui addestrare, e
  un judge funziona immediatamente a partire dalle linee guida scritte
  restituendo al contempo *ragioni* che rientrano direttamente nel loop di
  retry-con-feedback (Proposta 4).
- **Fail-closed:** una risposta del judge non parsabile è trattata come *necessita
  review*, mai passata silenziosamente — il default corretto in un dominio
  regolamentato.
- **Token-safe:** una bozza fuori budget viene *suddivisa in chunk e giudicata
  chunk-per-chunk*, mai riassunta (un riassunto potrebbe eliminare la frase esatta
  che il controllo esiste per intercettare); i verdetti si fondono con un AND
  logico.
- **Upgrade di produzione:** fine-tuning di un classificatore più piccolo una
  volta che esistono abbastanza esiti etichettati da umani, usando il judge per
  fare bootstrap delle etichette; mantenere l'LLM judge come seconda opinione in
  caso di disaccordo.

### Proposta 2 — Fact-checking via RAG — IMPLEMENTATA (leggera)

`src/policy_fact_check.py` + `src/vector_index.py` + `src/embeddings.py`. I claim
numerici/assoluti della bozza (un tasso, una commissione, "garantito", "FDIC",
"protezione dei depositi") vengono estratti e ciascuno è verificato contro un
**indice vettoriale Qdrant** di documenti di policy aziendali
(`data/company_policies.json`). Un claim è segnalato se (a) non recupera nulla,
(b) è sotto una similarità minima di grounding, oppure (c) **contraddice** una
policy recuperata (segnali di negazione espliciti, ad es. un claim "garantito"
contro una policy "non garantito").

- **Cosa gira:** retrieval-and-check reale, end to end, su un corpus di policy
  reale (a contenuto mock).
- **Gap onesto — embeddings:** il prototipo fa embedding con **TF-IDF + Truncated
  SVD (LSA, scikit-learn)**, non un modello neurale. È una tecnica reale che
  cattura *un po'* di similarità latente oltre la sovrapposizione di parole,
  completamente offline, e usa una dipendenza che il progetto ha già. **Non** è
  accurata quanto un embedding neurale, e il codice lo dichiara.
- **Upgrade di produzione:** **Voyage AI `voyage-finance-2`** (partner di
  embedding raccomandato da Anthropic, tarato sulla finanza) per il retrieval, e
  **IBM Granite Guardian** per lo step di groundedness/entailment — che può
  distinguere *supportato* da *contraddetto* da *meramente non correlato*, dove la
  sola similarità non può. **Docling** per ingerire veri PDF di policy invece di
  un JSON curato.
- **Perché un vector DB del tutto (Appendice A):** vedi sotto.

### Proposta 3 — Loop di feedback dai risultati dei blog pubblicati — IMPLEMENTATA (meccanismo minimo)

La leva a minor rischio del loop è ora **codice in esecuzione**:
`src/keyword_priority.py` + una tabella `feedback` (`server/db.py`) + due endpoint
(`POST /api/feedback`, `POST /api/keyword-priorities`) + una pagina frontend
(`web/src/pages/FeedbackPage.jsx`).

- **Cosa fa, end to end:**
  1. Le metriche di engagement (impressioni, click, dwell time, conversioni)
     vengono collegate a un post pubblicato via `POST /api/feedback` e salvate nel
     DB.
  2. `engagement_score()` le combina in un unico valore (dominato dal CTR).
  3. Gli score dei post passati vengono **centrati sulla media** — sopra la media
     → peso positivo, sotto la media → negativo.
  4. La priorità di una keyword candidata è la **somma pesata per similarità** di
     quei pesi (TF-IDF + coseno, la *stessa* macchina dell'internal linking —
     nessun nuovo modello). I candidati simili ai vincenti salgono; quelli simili
     ai perdenti scendono. Ogni risultato porta una motivazione in linguaggio
     naturale.
- **Testata con dati finti** (non esiste ancora traffico reale): seminando un post
  "savings" ad alto engagement, uno "budgeting" mediocre e uno "crypto" scarso, le
  keyword future vengono classificate esattamente come previsto — i topic savings
  in cima, crypto in fondo. Questo prova il **meccanismo**, ed è esplicito sul
  fatto che *non* prova un reale aumento di engagement (che richiede dati di
  produzione).
- **Guardrail:** il loop regola *cosa scrivere dopo*, **mai la compliance**. Le
  soglie di compliance restano di proprietà umana; una metrica di click-through
  non è mai autorizzata a convincere il sistema ad accettare un claim più
  rischioso.
- **Pezzo mancante — ingestione automatica delle metriche:** le metriche di
  engagement sono **inserite a mano** (via UI / `POST /api/feedback`), non recuperate
  automaticamente. **Non c'è alcuna integrazione che ingerisce impressioni/click
  reali da Google Analytics (GA4), Google Search Console (GSC) o dal CMS** — ed è
  anche per questo che oggi può essere testata solo su dati finti. Il *meccanismo
  di apprendimento* è reale; l'*ingestione automatica di metriche reali* è il
  pezzo mancante. Per un deployment serio / di produzione aggiungerei un connettore
  schedulato che importa metriche reali da **GA4 / GSC / il CMS** nella tabella
  `feedback`, chiudendo il loop senza alcun passo manuale — solo allora prova un
  reale aumento di engagement piuttosto che solo la correttezza del meccanismo.
- **Altre due leve, ancora proposte** (servono più dati / cablaggio di produzione):
  - **Tuning delle soglie** — sostituire valori fissi a intuito (la finestra di
    pubblicazione in `config.py`, la soglia SEO) con valori appresi e testati in
    A/B.
  - **Guida alla generazione** — restituire quali profili di voce / strutture
    correlano con l'engagement come preferenze *morbide* di prompt (mai regole
    rigide che ri-omogeneizzerebbero l'output).
- **Perché il DB conta oltre a questo:** la stessa storia accumulata
  `{post → engagement}` è il dataset che in seguito addestra il classificatore
  economico dell'Appendice C.4 — questa feature lo sta già raccogliendo.

### Proposta 4 — Gate di pubblicazione a tier di rischio (human-in-the-loop) — IMPLEMENTATA

`src/quality_gate.py` + `src/importance_tagger.py`. Il gate combina **due assi
indipendenti** in una sola decisione di routing:

1. **Asse qualità** — frasi vietate, score SEO, lunghezza minima, il compliance
   judge, il policy fact-check, il web fact-check e il controllo dei duplicati.
   Qualsiasi fallimento con retry rimanenti torna alla generazione *con le ragioni
   specifiche allegate*; dopo `max_generation_retries`, escala.
2. **Asse importanza** — un topic taggato a importanza **alta** (tasse,
   tassi/commissioni, protezione dei depositi, regolamentare/legale, confronti con
   competitor, notizie di prodotto non annunciate) **instrada sempre** alla review
   umana, *indipendentemente da quanto sia buona la bozza*. Questo non è un
   fallimento di qualità e non innesca mai un retry — una bozza perfetta su un
   topic sensibile necessita comunque di un'approvazione per *ciò che è*, non per
   *come è stata scritta*.

Il ramo `needs_review` scrive un vero **pacchetto di review** (`*.review.html` +
`*.review.manifest.json`) con il proprio template di AI-disclosure — dando a una
coda umana qualcosa di concreto su cui agire, non solo un flag di stato. Un
revisore poi **approva** il post dalla UI (`POST /api/blogs/{id}/approve`,
"✅ Approva e pubblica"), il che porta il suo stato a `published` e timbra chi ha
approvato e quando — chiudendo l'human-in-the-loop. Questo è anche il punto
naturale dove in seguito aggiungere `interrupt()` di LangGraph per una vera pausa
di approvazione in-graph.

### Proposta 5 — Rilevamento di duplicati semantici su scala — IMPLEMENTATA

`src/semantic_duplicate_check.py`. L'evoluzione scalabile dell'internal linking:
la *stessa* similarità di embedding, a una soglia *più alta* (0.90), contro una
seconda collection Qdrant (`published_posts`) seminata dal catalogo di contenuti
esistente e fatta crescere **incrementalmente** man mano che ogni post viene
pubblicato. Segnala i probabili quasi-duplicati prima che possano essere
pubblicati — critico a 700/mese, dove la generazione su template altrimenti
deriva verso l'uniformità (un problema che abbiamo incontrato e risolto
onestamente nel generatore mock invece di nasconderlo alzando la soglia).

---

## Parte 4 — Il workflow integrato

### Perché LangGraph, non uno script lineare

Due requisiti **non sono lineari**, e uno `StateGraph` li modella nativamente dove
una catena di funzioni richiederebbe while-loop fatti a mano:

1. **Retry-con-feedback** è un *ciclo*: `quality_gate → increment_retries →
   generate_content`, limitato da `max_generation_retries`, con le ragioni di
   rifiuto portate nello stato condiviso.
2. **Human-in-the-loop** è un *ramo terminale condizionale*: `needs_review`,
   raggiungibile sia all'esaurimento dei retry sia direttamente su un tag di
   importanza alta.

### Il flusso (Input → Processing → Output)

```
INPUT
  keyword  ─►  tag importanza + profilo voce

PROCESSING  (LangGraph StateGraph, PipelineState condiviso)
  web_research ─► generate_content ─► seo_optimize ─► internal_linking
        ▲                                                   │
        │ retry (+ ragioni)                                 ▼
        │                                            compliance_judge
        │                                                   │
        └──────────── quality_gate ◄── duplicate_check ◄── web_fact_check ◄── policy_fact_check
                          │
            ┌─────────────┼─────────────┐
            ▼             ▼             ▼
         publish     needs_review    (retry)
            │             │
OUTPUT      ▼             ▼
   CMS / outputs/    pacchetto review + coda umana
   + index in published_posts (per dedup futura)
```

### Scalare a 700 post/mese

L'unità di lavoro è una chiamata `run_for_keyword()`. Per scalare:

- **Fan-out:** una coda (SQS / Pub-Sub), un messaggio per keyword approvata,
  consumato da **N processi worker** ciascuno che esegue questo stesso grafo. A
  ~23/giorno, 5–10 worker smaltiscono il volume con margine per i retry.
- **Scheduling/orchestrazione a livello di flotta:** Airflow o Prefect per
  innescare i batch, gestire retry/backfill e far emergere i fallimenti.
- **Stato & dati:** il Qdrant in-process diventa un **Qdrant gestito/self-hosted**
  condiviso tra i worker (cambio del client di una riga — vedi Appendice A); i
  post generati vanno al **CMS** invece che in `outputs/`; una **coda di review
  umana** nel CMS gestisce tutto ciò che è instradato a `needs_review`.
- **Controllo dei costi:** SEO puramente in Python e un embedder locale fanno sì
  che l'unica chiamata a pagamento per-post sia la generazione LLM (e l'eventuale
  judge) — tutto il resto è calcolo gratuito, il che conta molto a questo volume.

---

## Appendice A — Scelta del Vector DB (modalità locale ora, gestita dopo)

Il fact-check RAG e il rilevatore di duplicati necessitano entrambi di ricerca
vettoriale. Il prototipo usa **Qdrant in modalità locale**
(`QdrantClient(":memory:")`) — un client in-process, nessun server da far girare,
adatto fino a ~20k vettori (molti di più di quanti ne serva a ciascuna delle due
collection qui).

È una scelta deliberata, non un segnaposto: la **stessa API `QdrantClient`**
funziona identicamente contro un'istanza gestita o self-hosted, quindi il
passaggio alla produzione è `QdrantClient(":memory:")` → `QdrantClient(url=...)`
— una riga, non una riscrittura. L'embedder viene fittato una volta per processo
(lo step costoso) e cachato come singleton; quando il set di policy cambia,
l'indice viene ricostruito così che il vocabolario di una nuova policy entri
davvero nello spazio vettoriale (`reset_knowledge_base_index`).

Un embedder neurale (Voyage) elimina del tutto la necessità di *fittare* (l'API fa
embedding direttamente), il che elimina anche il caso limite del "vettore
degenere" di LSA da cui il prototipo deve difendersi per testi molto corti o fuori
tema.

---

## Appendice B — Limitazioni oneste del prototipo

- **Gli embeddings sono LSA, non neurali** — vedi Proposta 2. Il pattern è reale;
  l'accuratezza non è di livello produzione.
- **Nessun dato di engagement reale** — il loop di feedback (Proposta 3) è
  implementato come meccanismo minimo-ma-reale (ri-classificazione delle keyword),
  ma è **testato solo su metriche finte**: prova il meccanismo, non un reale
  aumento di engagement, che richiede traffico di produzione.
- **Corpus di policy mock** — `company_policies.json` è illustrativo; la produzione
  necessita di documenti reali (ingestione Docling).
- **Indice in-process** — va bene per un prototipo / singolo batch; la produzione
  necessita di un'istanza gestita condivisa per il fan-out multi-worker.
- **Generazione a lock singolo nel web server** — l'API serializza la generazione
  perché i nodi leggono un'impostazione di provider globale; corretto per uno
  strumento di test locale, sostituito da isolamento per-worker su scala.

Queste cose sono dichiarate in apertura perché, in un contesto di compliance,
sapere esattamente dove finiscono le garanzie di un sistema è esso stesso parte
del design.

---

## Appendice C — Scelte pragmatiche di prototipazione e i loro delta di produzione

Ogni scelta qui sotto è stata fatta per mantenere il prototipo **gratuito, locale
ed eseguibile con zero setup**. Ciascuna è la scelta *giusta* per un prototipo
take-home e quella *sbagliata* per un deployment aziendale — quindi ciascuna è
accompagnata da ciò che farei davvero in produzione. Dichiarare il delta
esplicitamente è il punto: niente qui è un'assunzione nascosta.

### C.1 Ricerca web & scoperta keyword — DuckDuckGo ora, news search / scraping in prod

- **Prototipo:** la ricerca web e il web fact-check usano il client Python di
  **DuckDuckGo** (`ddgs`) perché è un servizio funzionante, **gratuito e
  senza chiave** — sufficiente a provare il pattern di retrieval-and-inject end to
  end.
- **Produzione — due upgrade complementari, entrambi deliberatamente lasciati
  fuori dal prototipo per ragioni di costo/stabilità, non di difficoltà:**
  - **Scoperta keyword guidata dalle notizie.** Oggi la pipeline prende le keyword
    come input (file / CLI / coda) e il loop di feedback si limita a
    *ri-classificare* un insieme di candidati esistente; non *scopre* topic
    freschi. In produzione alimenterei l'insieme di candidati da una **ricerca di
    notizie via Brave Search API** (un'API a pagamento, stabile, in regola con i
    ToS, con rate limit adeguati e qualità dei risultati — il default a basso
    rischio per un'azienda), facendo emergere topic FinTech di tendenza degni di
    essere scritti prima che vengano classificati dal loop di feedback.
  - **Scraping a pagina intera per il grounding.** Invece di snippet, **crawl e
    parsing di pagine intere** — sia dai risultati di ricerca aperti sia da una
    lista curata di fonti note e attendibili — usando uno **scraping in stile
    OpenClaw** con `ddgs`: il suo tool **`web`**
    ([docs.openclaw.ai/it/tools/web](https://docs.openclaw.ai/it/tools/web)) per il
    recupero, e il tool **`browser`** più aggressivo
    ([docs.openclaw.ai/it/tools/browser](https://docs.openclaw.ai/it/tools/browser))
    per le pagine che richiedono rendering / interazione (open source, quindi la
    produzione è "aggiungi la dipendenza e collegala", non una riscrittura). Questo
    àncora la bozza a materiale di origine molto più ricco e fresco di quanto gli
    snippet permettano.
- **Perché è una proposta e non codice qui:** il percorso di scraping è stato
  prototipato ma **non committato**. Lo scraping in stile OpenClaw, specie con il
  tool `browser` più aggressivo, richiede un **modello vision** per leggere e
  interpretare le pagine renderizzate, e **non avevo un modello vision abbastanza
  forte da farlo girare sul mio PC, che è troppo debole**: ho provato con
  **gemma4 e2b (via Ollama)**, ma mi andava in errore. Quindi, invece di
  consegnare codice che non potevo davvero eseguire end to end, l'ho lasciato come
  proposta con relativi costi. Il principio vale in tutta questa consegna:
  **nessun codice non testato nel repo.** Brave Search è similmente un'API a
  pagamento per cui non volevo inserire una chiave per un take-home.
- **Perché conta:** la qualità dei fatti basati sul web — e della selezione stessa
  dei topic — è limitata dal layer di search/crawl; gli snippet di DuckDuckGo sono
  il pavimento, non il soffitto.

### C.2 LLM — testato localmente con un solo modello piccolo

- **Prototipo:** la generazione reale è stata validata **solo con `qwen2.5:1.5b`
  via Ollama**, perché è l'unico modello di *qualità soddisfacente che gira sulla
  mia macchina locale*. La pipeline **non** è stata esercitata contro modelli API
  hosted (Claude / GPT) in questa consegna — anche se l'astrazione di provider
  (`src/llm_providers.py`) rende ciò un cambio di config, non di codice, e il
  provider `mock` deterministico di default copre la logica nei test.
- **Produzione:** usare un modello hosted di capacità superiore (Claude come
  default) per i contenuti e il compliance judge, dove la qualità dell'output e
  l'aderenza alle istruzioni sono materialmente migliori. Il piccolo modello
  locale è una comodità di sviluppo, non lo scrittore di produzione.


### C.3 Embeddings — scikit-learn (LSA) ora, mai in produzione

- **Prototipo:** l'indice vettoriale fa embedding con **TF-IDF + Truncated SVD
  (LSA), scikit-learn** — deliberatamente, per **evitare di aggiungere un altro
  modello** (nessun download di pesi, niente torch, nessun servizio extra) sopra
  un prototipo già ricco di dipendenze.
- **Produzione:** con un **corpus di policy molto più grande**, **non** userei
  **mai** LSA. LSA deve essere rifittato sull'intero corpus e degrada al crescere
  del vocabolario; un embedder neurale appropriato (**Voyage `voyage-finance-2`**,
  o un modello sentence self-hosted) fa embedding direttamente, scala e cattura
  vera similarità semantica.

### C.4 Nessun modello di classificazione ancora — per scelta, perché i dati vengono prima

- **Prototipo:** compliance/qualità usano un **LLM-as-judge**, non un
  classificatore addestrato, perché **un buon classificatore necessita di molti
  dati etichettati** che non esistono al giorno zero.
- **Il piano, e perché il DB conta:** ogni post generato è **persistito in un
  database** (`server/db.py`, incluso lo stato completo della pipeline). Quello
  store non è solo output — è il **dataset storico** che, una volta abbastanza
  grande, ci permette di addestrare un classificatore (pass/fail di compliance,
  scoring di qualità) che è **sia più accurato sia molto più economico per
  chiamata di un LLM**. L'LLM judge fa bootstrap delle etichette; la storia
  accumulata fa diplomare il modello economico.


---
