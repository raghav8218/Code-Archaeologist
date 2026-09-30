import shutil
import tempfile
import uuid
from pathlib import Path

import git
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from parser import extract_repo
from graph_builder import build_graph, graph_to_json
from git_utils import get_function_history, get_repo_change_frequency
from llm import ask_gemini
from retrieval import build_repo_index, retrieve_and_answer

app = FastAPI(title="Code Archaeologist API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store: fine for a single-session class demo.
# Would move to a real cache/DB if this went further than that.
STORE = {}


class AnalyzeRequest(BaseModel):
    repo_url: str


class AskRequest(BaseModel):
    question: str


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    repo_id = str(uuid.uuid4())[:8]
    workdir = Path(tempfile.gettempdir()) / "code-archaeologist" / repo_id
    workdir.mkdir(parents=True, exist_ok=True)

    try:
        # Shallow-ish clone: enough history for blame, not the whole repo.
        git.Repo.clone_from(req.repo_url, workdir, depth=200)
    except Exception as e:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Could not clone repo: {e}")

    extracted = extract_repo(str(workdir), extensions=(".py",))
    if not extracted["functions"]:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(
            status_code=400,
            detail="No Python functions found. This MVP currently only supports Python repos.",
        )

    G, unresolved = build_graph(extracted)
    functions_by_id = {fn["id"]: fn for fn in extracted["functions"]}

    # Repo-wide change frequency, attached to every node — this is what makes
    # the graph itself carry a history signal instead of just structure.
    file_change_freq = get_repo_change_frequency(str(workdir))
    for _, node_attrs in G.nodes(data=True):
        node_attrs["change_frequency"] = file_change_freq.get(node_attrs.get("file", ""), 0)

    # Stage 0: build a compact structural index for the retrieval pipeline.
    # Contains names, files, line ranges, and relationships but NO source
    # code — designed to be cheap to send to the Stage 1 LLM.
    repo_index = build_repo_index(extracted, G, extracted["files"], file_change_freq)

    STORE[repo_id] = {
        "workdir": str(workdir),
        "graph": G,
        "functions_by_id": functions_by_id,
        "files": extracted["files"],
        "file_change_freq": file_change_freq,
        "repo_index": repo_index,
    }

    return {
        "repo_id": repo_id,
        "graph": graph_to_json(G),
        "num_files": len(extracted["files"]),
        "num_functions": len(extracted["functions"]),
        "unresolved_calls": len(unresolved),
    }


def _get_repo(repo_id):
    if repo_id not in STORE:
        raise HTTPException(status_code=404, detail="Unknown repo_id — re-run analyze.")
    return STORE[repo_id]


@app.get("/api/graph/{repo_id}")
def get_graph(repo_id: str):
    data = _get_repo(repo_id)
    return graph_to_json(data["graph"])


@app.get("/api/function/{repo_id}")
def get_function(repo_id: str, id: str):
    data = _get_repo(repo_id)
    fn = data["functions_by_id"].get(id)
    if not fn:
        raise HTTPException(status_code=404, detail="Function not found")
    history = get_function_history(data["workdir"], fn["file"], fn["start_line"], fn["end_line"])
    change_frequency = data["file_change_freq"].get(fn["file"], 0)
    return {**fn, "history": history, "change_frequency": change_frequency}


@app.get("/api/trace/{repo_id}")
def trace(repo_id: str, start_id: str, depth: int = 6):
    """BFS forward from a function/route to show its downstream call path."""
    data = _get_repo(repo_id)
    G = data["graph"]
    if start_id not in G:
        raise HTTPException(status_code=404, detail="Starting function not found in graph")

    visited = {start_id}
    frontier = [start_id]
    path_edges = []

    for _ in range(depth):
        next_frontier = []
        for node in frontier:
            for _, target in G.out_edges(node):
                path_edges.append({"source": node, "target": target})
                if target not in visited:
                    visited.add(target)
                    next_frontier.append(target)
        frontier = next_frontier
        if not frontier:
            break

    return {"nodes": list(visited), "edges": path_edges}


@app.post("/api/ask/{repo_id}")
def ask(repo_id: str, req: AskRequest):
    data = _get_repo(repo_id)

    try:
        answer, highlighted_ids = retrieve_and_answer(req.question, data)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"answer": answer, "highlighted_ids": highlighted_ids}


@app.get("/api/health")
def health():
    return {"status": "ok"}
