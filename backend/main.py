import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List

import git
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from parser import extract_repo
from graph_builder import build_graph, graph_to_json
from git_utils import (
    get_function_history,
    get_repo_change_frequency,
    get_repo_commits,
    parse_github_owner_repo,
)
from llm import ask_gemini
from retrieval import build_repo_index, retrieve_and_answer

app = FastAPI(title="Code Archaeologist API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STORE: Dict[str, Dict[str, Any]] = {}


class AnalyzeRequest(BaseModel):
    repo_url: str
    branch: Optional[str] = None


class AskRequest(BaseModel):
    question: str


def generate_architectural_context(extracted: Dict[str, Any], file_change_freq: Dict[str, int], repo_name: str) -> str:
    """Generate a high-density architectural context markdown summary for LLMs and developers."""
    files = extracted.get("files", [])
    classes = extracted.get("classes", [])
    functions = extracted.get("functions", [])
    imports = extracted.get("imports", [])

    # Sort files by churn
    hotspots = sorted(
        [(f, file_change_freq.get(f, 0)) for f in files],
        key=lambda x: x[1],
        reverse=True,
    )

    routes = [fn for fn in functions if fn.get("is_route")]
    methods = [fn for fn in functions if fn.get("kind") == "method"]
    standalone_functions = [fn for fn in functions if fn.get("kind") == "function"]

    lines = [
        f"# Architectural Context: `{repo_name}`",
        "",
        "## 1. System Overview",
        f"- **Files Parsed**: {len(files)} Python files",
        f"- **Classes**: {len(classes)}",
        f"- **Methods**: {len(methods)}",
        f"- **Standalone Functions**: {len(standalone_functions)}",
        f"- **API Endpoints / Routes**: {len(routes)}",
        "",
        "## 2. Git Churn Hotspots (Change Frequency)",
        "Files with the most frequent historical modifications:",
    ]

    for f, count in hotspots[:8]:
        lines.append(f"- `{f}`: **{count}** commits")

    lines.extend([
        "",
        "## 3. Core Classes & Hierarchies",
    ])

    if classes:
        for cls in classes:
            bases_str = f" inherits `{', '.join(cls['bases'])}`" if cls.get("bases") else ""
            methods_count = len(cls.get("methods", []))
            lines.append(
                f"- **`{cls['name']}`** (`{cls['file']}`): {methods_count} methods{bases_str}"
            )
            if cls.get("docstring"):
                first_line = cls['docstring'].strip().split("\n")[0]
                lines.append(f"  > _{first_line}_")
    else:
        lines.append("_No explicit class definitions found._")

    lines.extend([
        "",
        "## 4. API Endpoints & Handlers",
    ])

    if routes:
        for r in routes:
            decs = ", ".join(r.get("decorators", []))
            lines.append(f"- **`{r['name']}()`** (`{r['file']}:{r['start_line']}`): `{decs}`")
    else:
        lines.append("_No route decorators detected._")

    lines.extend([
        "",
        "## 5. Cross-Module Dependencies & Imports",
    ])

    unique_imports = set()
    for imp in imports[:30]:
        unique_imports.add(f"- `{imp['file']}`: `{imp['text']}`")

    lines.extend(sorted(list(unique_imports))[:20])

    return "\n".join(lines)


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    raw_url = req.repo_url.strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="Repository URL is required.")

    # Normalize GitHub URL if entered as owner/repo
    if not raw_url.startswith("http://") and not raw_url.startswith("https://") and not raw_url.startswith("git@"):
        clean_name = raw_url.strip("/")
        if len(clean_name.split("/")) == 2:
            raw_url = f"https://github.com/{clean_name}.git"

    repo_name = parse_github_owner_repo(raw_url) or raw_url.split("/")[-1].replace(".git", "")

    repo_id = str(uuid.uuid4())[:8]
    workdir = Path(tempfile.gettempdir()) / "code-archaeologist" / repo_id
    workdir.mkdir(parents=True, exist_ok=True)

    clone_kwargs: Dict[str, Any] = {"depth": 100}
    if req.branch:
        clone_kwargs["branch"] = req.branch

    try:
        git_repo = git.Repo.clone_from(raw_url, workdir, **clone_kwargs)
        active_branch = req.branch or (git_repo.active_branch.name if not git_repo.head.is_detached else "main")
    except Exception as e:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=f"Could not clone repository: {str(e)}")

    extracted = extract_repo(str(workdir), extensions=(".py",))
    if not extracted["functions"] and not extracted["classes"]:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(
            status_code=400,
            detail="No Python classes or functions found. Only Python repositories are currently supported.",
        )

    G, unresolved = build_graph(extracted)

    # Calculate change frequencies
    file_change_freq = get_repo_change_frequency(str(workdir))
    for _, node_attrs in G.nodes(data=True):
        f = node_attrs.get("file", "")
        node_attrs["change_frequency"] = file_change_freq.get(f, 0)

    # Map symbols by ID and aliases
    symbols_by_id: Dict[str, Dict[str, Any]] = {}
    for cls in extracted["classes"]:
        cls["change_frequency"] = file_change_freq.get(cls["file"], 0)
        symbols_by_id[cls["id"]] = cls
        if cls.get("raw_id"):
            symbols_by_id[cls["raw_id"]] = cls

    for fn in extracted["functions"]:
        fn["change_frequency"] = file_change_freq.get(fn["file"], 0)
        symbols_by_id[fn["id"]] = fn
        if fn.get("raw_id"):
            symbols_by_id[fn["raw_id"]] = fn
        if fn.get("legacy_id"):
            symbols_by_id[fn["legacy_id"]] = fn

    # Retrieve commit log
    commits = get_repo_commits(str(workdir), repo_url=raw_url, limit=50)

    # Generate architectural context summary markdown
    arch_context = generate_architectural_context(extracted, file_change_freq, repo_name)

    # Build Stage 0 structural index for retrieval LLM
    repo_index = build_repo_index(extracted, G, extracted["files"], file_change_freq)

    STORE[repo_id] = {
        "workdir": str(workdir),
        "graph": G,
        "symbols_by_id": symbols_by_id,
        "functions_by_id": {fn["id"]: fn for fn in extracted["functions"]},
        "classes_by_id": {cls["id"]: cls for cls in extracted["classes"]},
        "files": extracted["files"],
        "file_change_freq": file_change_freq,
        "repo_index": repo_index,
        "commits": commits,
        "architectural_context": arch_context,
        "repo_url": raw_url,
        "repo_name": repo_name,
        "branch": active_branch,
    }

    graph_data = graph_to_json(G)

    return {
        "repo_id": repo_id,
        "repo_url": raw_url,
        "repo_name": repo_name,
        "branch": active_branch,
        "graph": graph_data,
        "num_files": len(extracted["files"]),
        "num_functions": len(extracted["functions"]),
        "num_classes": len(extracted["classes"]),
        "unresolved_calls": len(unresolved),
        "commits": commits,
        "architectural_context": arch_context,
    }


def _get_repo(repo_id: str):
    if repo_id not in STORE:
        workdir = Path(tempfile.gettempdir()) / "code-archaeologist" / repo_id
        if workdir.exists():
            extracted = extract_repo(str(workdir), extensions=(".py",))
            G, unresolved = build_graph(extracted)
            file_change_freq = get_repo_change_frequency(str(workdir))
            for _, node_attrs in G.nodes(data=True):
                f = node_attrs.get("file", "")
                node_attrs["change_frequency"] = file_change_freq.get(f, 0)

            symbols_by_id: Dict[str, Dict[str, Any]] = {}
            for cls in extracted["classes"]:
                cls["change_frequency"] = file_change_freq.get(cls["file"], 0)
                symbols_by_id[cls["id"]] = cls
                if cls.get("raw_id"):
                    symbols_by_id[cls["raw_id"]] = cls

            for fn in extracted["functions"]:
                fn["change_frequency"] = file_change_freq.get(fn["file"], 0)
                symbols_by_id[fn["id"]] = fn
                if fn.get("raw_id"):
                    symbols_by_id[fn["raw_id"]] = fn
                if fn.get("legacy_id"):
                    symbols_by_id[fn["legacy_id"]] = fn

            STORE[repo_id] = {
                "workdir": str(workdir),
                "graph": G,
                "symbols_by_id": symbols_by_id,
                "functions_by_id": {fn["id"]: fn for fn in extracted["functions"]},
                "classes_by_id": {cls["id"]: cls for cls in extracted["classes"]},
                "files": extracted["files"],
                "file_change_freq": file_change_freq,
                "repo_index": build_repo_index(extracted, G, extracted["files"], file_change_freq),
                "commits": get_repo_commits(str(workdir), limit=50),
                "architectural_context": "",
                "repo_url": "",
                "repo_name": repo_id,
                "branch": "main",
            }
            return STORE[repo_id]
        raise HTTPException(status_code=404, detail="Session expired or unknown repo_id. Please re-analyze.")
    return STORE[repo_id]


@app.get("/api/graph/{repo_id}")
def get_graph(repo_id: str):
    data = _get_repo(repo_id)
    return graph_to_json(data["graph"])


@app.get("/api/symbol/{repo_id}")
@app.get("/api/function/{repo_id}")
def get_symbol_details(repo_id: str, id: str = Query(...)):
    data = _get_repo(repo_id)
    symbol = data["symbols_by_id"].get(id)
    G: git.Repo = data["graph"]

    if not symbol:
        # Fallback search by label or substring
        for sid, s in data["symbols_by_id"].items():
            if id in (sid, s.get("name"), s.get("qualified_name")):
                symbol = s
                break

    if not symbol:
        # Check node data directly in graph
        if G.has_node(id):
            symbol = dict(G.nodes[id])
        else:
            raise HTTPException(status_code=404, detail=f"Symbol '{id}' not found.")

    start_line = symbol.get("start_line", 1)
    end_line = symbol.get("end_line", start_line)
    file_path = symbol.get("file", "")

    history = []
    if file_path and file_path != "external":
        history = get_function_history(data["workdir"], file_path, start_line, end_line)

    change_freq = data["file_change_freq"].get(file_path, 0)

    # Incoming callers
    incoming = []
    if G.has_node(symbol.get("id", id)):
        node_id = symbol.get("id", id)
        for predecessor in G.predecessors(node_id):
            pdata = G.nodes[predecessor]
            edge_data = G.get_edge_data(predecessor, node_id) or {}
            incoming.append({
                "id": predecessor,
                "label": pdata.get("label", predecessor),
                "kind": pdata.get("kind", "function"),
                "file": pdata.get("file", ""),
                "type": edge_data.get("type", "calls"),
            })

    # Outgoing dependencies
    outgoing = []
    if G.has_node(symbol.get("id", id)):
        node_id = symbol.get("id", id)
        for successor in G.successors(node_id):
            sdata = G.nodes[successor]
            edge_data = G.get_edge_data(node_id, successor) or {}
            outgoing.append({
                "id": successor,
                "label": sdata.get("label", successor),
                "kind": sdata.get("kind", "function"),
                "file": sdata.get("file", ""),
                "type": edge_data.get("type", "calls"),
            })

    return {
        **symbol,
        "history": history,
        "change_frequency": change_freq,
        "incoming_callers": incoming,
        "outgoing_dependencies": outgoing,
    }


@app.get("/api/commits/{repo_id}")
def get_commits(repo_id: str):
    data = _get_repo(repo_id)
    return {
        "commits": data.get("commits", []),
        "file_change_freq": data.get("file_change_freq", {}),
    }


@app.get("/api/context/{repo_id}")
def get_context(repo_id: str):
    data = _get_repo(repo_id)
    return {
        "architectural_context": data.get("architectural_context", ""),
        "repo_name": data.get("repo_name", ""),
        "repo_url": data.get("repo_url", ""),
        "branch": data.get("branch", ""),
    }


@app.get("/api/trace/{repo_id}")
def trace(repo_id: str, start_id: str = Query(...), depth: int = 6):
    """BFS forward along calls, instantiates, and contains edges."""
    data = _get_repo(repo_id)
    G = data["graph"]

    # Match ID
    actual_id = start_id
    if actual_id not in G:
        for node in G.nodes():
            if start_id in (node, G.nodes[node].get("raw_id"), G.nodes[node].get("name")):
                actual_id = node
                break

    if actual_id not in G:
        raise HTTPException(status_code=404, detail="Starting symbol not found in graph")

    visited = {actual_id}
    frontier = [actual_id]
    path_edges = []

    for _ in range(depth):
        next_frontier = []
        for node in frontier:
            for _, target, edge_data in G.out_edges(node, data=True):
                # Follow execution flow edges
                if edge_data.get("type") in ("calls", "instantiates", "contains"):
                    path_edges.append({"source": node, "target": target, "type": edge_data.get("type")})
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
