# Code Archaeologist

Paste a GitHub URL for a small Python repo and get back a clickable call
graph, source-on-click, git-blame history per function, a change-frequency
"hotspot" overlay on the graph itself, forward tracing from any
function/route, and natural-language Q&A that's grounded in both the code
**and** its commit history — so it can answer "why" questions, not just
"what" ones — answered by Gemini.

## What's built vs. what's future work

**Built (MVP, Python-only):**
- tree-sitter parsing of functions, classes, calls, imports, route decorators
- Heuristic (name-based) call graph via networkx
- Interactive graph UI (react-flow) — click a node to see source
- Git blame per function ("who wrote this and why")
- Repo-wide change-frequency, rendered as a hotspot overlay directly on the
  graph (thicker, redder border = changed more often) — the graph carries a
  history signal, not just structure
- History-grounded Q&A: when you ask a question, the retrieved functions'
  commit history is passed to Gemini alongside their source, so "why does
  this exist" questions get answered from real commit messages instead of
  guessed from code alone
- Forward trace from any function (e.g. a route) through its call chain

**Explicitly not built (documented as scoping, not a gap):**
- Multi-language support (only Python — tree-sitter grammar is swappable later)
- True type-aware call resolution (name-matching is a heuristic; documented
  in `graph_builder.py`)
- Embedding-based semantic retrieval (current retrieval is keyword-overlap —
  works at this repo scale, but is a known simplification)
- Large repos (tested/intended for small-to-medium demo repos, not 100k+ LOC)

## Setup

### 1. Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate       # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and paste a free key from https://aistudio.google.com/apikey

uvicorn main:app --reload --port 8000
```

Backend now running at http://localhost:8000 (check http://localhost:8000/api/health).

### 2. Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at http://localhost:5173 and proxies `/api` calls to the backend.

## Using it

1. Open http://localhost:5173
2. Paste a small Python repo URL (Flask/FastAPI toy apps work best — they
   have clear route decorators to demo tracing on, and ideally some real
   commit history so the hotspot overlay and history Q&A have something to
   show)
3. Click "Analyze repo" — this clones it, parses it, builds the graph, and
   computes change-frequency per file from the full commit history
4. Notice which nodes have a thicker, redder border — those are the
   functions that have changed the most across the repo's history
5. Click any node to see its source, its change-frequency badge, and its
   git blame history
6. Click "Trace from here" on a route handler to highlight its downstream
   call chain
7. Ask a "why" question like "why does this validation logic look the way
   it does?" — Gemini answers using the retrieved functions' source *and*
   their commit history, and highlights the functions it used

## Good test repos to demo on

Small (a few hundred to low thousands of lines), pure Python, with clear
routes — e.g. small Flask tutorial apps or FastAPI example projects. Avoid
huge repos and repos that are mostly non-Python (JS frontends, notebooks) —
this MVP only parses `.py` files.

## Project structure

```
backend/
  main.py             FastAPI app + all API endpoints
  parser.py           tree-sitter extraction (functions/calls/imports/routes)
  graph_builder.py     networkx graph construction + call resolution
  git_utils.py         git blame + repo-wide change-frequency
  llm.py                Gemini API wrapper (history-grounded prompts)
  requirements.txt
  .env.example

frontend/
  src/
    App.jsx                     main layout + state
    components/GraphView.jsx     react-flow graph canvas + hotspot styling
    components/CodePanel.jsx     source + change-frequency + blame panel
    utils/layout.js              dagre auto-layout + hotspot border scaling
    index.css
```

## Known limitations (say these out loud, don't hide them)

- Call resolution is name-based, not type-aware — it can mis-link two
  same-named functions in different classes. Documented in `graph_builder.py`.
- Retrieval for Q&A is keyword-overlap, not embeddings — good enough for a
  small demo repo, would need upgrading for anything larger.
- Frontend has been built and reasoned through but should be visually
  verified in a real browser before a live demo.
- Gemini output quality is unverified without a live API key configured —
  the exact prompt sent has been checked, but not the model's actual answer.
