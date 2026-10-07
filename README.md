# Code Archaeologist

Paste a GitHub URL for a small Python repo and get back a clickable call graph, source-on-click, git-blame history per function, a change-frequency "hotspot" overlay on the graph itself, forward tracing from any function/route, and natural-language Q&A that's grounded in both the code **and** its commit history — so it can answer "why" questions, not just "what" ones — answered by Gemini.

## Introduction

Code Archaeologist is an interactive tool that helps developers understand and explore unfamiliar Python codebases by combining code structure, visual relationships, source code, and Git history in one interface.
 
## Problem Statement

Understanding an unfamiliar codebase can be difficult because developers need to manually navigate through files, functions, relationships, and Git history. Code Archaeologist makes this process easier through an interactive code exploration interface.

## Objectives

- Visualize relationships between functions and routes.
- Inspect source code directly from graph nodes.
- View Git blame and commit history.
- Identify frequently changed code using hotspot information.
- Trace downstream function relationships.
- Ask natural-language questions about the codebase using code and Git history.

## Team Members

- Shivang Kumar
- Raghav

## Setup

### 1. Backend

cd backend python3 -m venv venv source venv/bin/activate       # Windows: venv\Scripts\activate pip install -r requirements.txt  cp .env.example .env # edit .env and paste a free key from [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)  uvicorn main:app --reload --port 8000

Backend now running at [http://localhost:8000](http://localhost:8000) (check [http://localhost:8000/api/health](http://localhost:8000/api/health)).

### 2. Frontend

In a second terminal:

cd frontend npm install npm run dev

Frontend runs at [http://localhost:5173](http://localhost:5173) and proxies `/api` calls to the backend.

## Using it

1. Open [http://localhost:5173](http://localhost:5173)
2. Paste a small Python repo URL (Flask/FastAPI toy apps work best — they have clear route decorators to demo tracing on, and ideally some real commit history so the hotspot overlay and history Q&A have something to show)
3. Click "Analyze repo" — this clones it, parses it, builds the graph, and computes change-frequency per file from the full commit history
4. Notice which nodes have a thicker, redder border — those are the functions that have changed the most across the repo's history
5. Click any node to see its source, its change-frequency badge, and its git blame history
6. Click "Trace from here" on a route handler to highlight its downstream call chain
7. Ask a "why" question like "why does this validation logic look the way it does?" — Gemini answers using the retrieved functions' source *and* their commit history, and highlights the functions it used