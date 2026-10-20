import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List

import git
import json
import networkx as nx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from parser import extract_repo, extract_from_in_memory_files, SUPPORTED_EXTENSIONS
from graph_builder import build_graph, graph_to_json
from git_utils import (
    get_function_history,
    get_repo_change_frequency,
    get_repo_commits,
    get_temporal_coupling,
    parse_github_owner_repo,
    fetch_github_in_memory,
)
from llm import ask_gemini
from retrieval import build_repo_index, retrieve_and_answer, retrieve_and_answer_stream
from database import (
    find_cached_repo,
    save_repository_analysis,
    get_repository_analysis,
    get_all_symbols,
    get_symbol_details as db_get_symbol_details,
    save_qa_thread,
    get_qa_threads,
    safe_delete_tree,
)

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


def generate_architectural_context(
    extracted: Dict[str, Any],
    file_change_freq: Dict[str, int],
    repo_name: str,
    temporal_couplings: Optional[Dict[str, Any]] = None,
    keystones: Optional[List[Dict[str, Any]]] = None,
    circular_cycles: Optional[List[Any]] = None,
) -> str:
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
        f"- **Files Parsed**: {len(files)} files",
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

    if keystones:
        lines.extend([
            "",
            "## 3. Architectural Keystones (PageRank Hubs)",
            "Key functions and classes that form the core backbone of this repository:",
        ])
        for k in keystones[:5]:
            lines.append(f"- **`{k.get('label')}`** (Centrality Score: `{k.get('score')}`)")

    if circular_cycles:
        lines.extend([
            "",
            "## 4. Circular Dependency Warnings (Tarjan Cycle Detection)",
            "Detected circular dependency loops across module boundaries:",
        ])
        for cyc in circular_cycles[:4]:
            lines.append(f"- `{' ⇄ '.join(cyc)}`")

    if temporal_couplings:
        lines.extend([
            "",
            "## 5. Temporal Co-Change Coupling (CodeScene Forensics)",
            "Files that frequently change together in the same commits:",
        ])
        for src_f, couples in list(temporal_couplings.items())[:6]:
            couple_strs = [f"`{c['file']}` ({c['strength_pct']}%)" for c in couples[:2]]
            lines.append(f"- `{src_f}` &harr; {', '.join(couple_strs)}")

    lines.extend([
        "",
        "## 6. Core Classes & Hierarchies",
    ])

    if classes:
        for cls in classes[:15]:
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
        "## 7. API Endpoints & Handlers",
    ])

    if routes:
        for r in routes[:15]:
            decs = ", ".join(r.get("decorators", []))
            lines.append(f"- **`{r['name']}()`** (`{r['file']}:{r['start_line']}`): `{decs}`")
    else:
        lines.append("_No route decorators detected._")

    lines.extend([
        "",
        "## 8. Cross-Module Dependencies & Imports",
    ])

    unique_imports = set()
    for imp in imports[:30]:
        unique_imports.add(f"- `{imp['file']}`: `{imp['text']}`")

    lines.extend(sorted(list(unique_imports))[:20])

    return "\n".join(lines)


def _reconstruct_networkx(graph_data: Dict[str, Any]) -> nx.DiGraph:
    G = nx.DiGraph()
    for n in graph_data.get("nodes", []):
        G.add_node(n["id"], **n)
    for e in graph_data.get("edges", []):
        G.add_edge(e["source"], e["target"], type=e.get("type", "calls"), weight=e.get("weight", 1))
    return G


@app.post("/api/analyze")
def process_repo_analysis(raw_url: str, requested_branch: Optional[str] = None, progress_cb=None) -> Dict[str, Any]:
    raw_url = raw_url.strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="Repository URL is required.")

    # Normalize GitHub URL if entered as owner/repo
    if not raw_url.startswith("http://") and not raw_url.startswith("https://") and not raw_url.startswith("git@"):
        clean_name = raw_url.strip("/")
        if len(clean_name.split("/")) == 2:
            raw_url = f"https://github.com/{clean_name}.git"

    repo_name = parse_github_owner_repo(raw_url) or raw_url.split("/")[-1].replace(".git", "")
    clean_branch = requested_branch.strip() if requested_branch and requested_branch.strip() else None

    # ── 1. Check SQLite Cache First (Instant 2ms Load) ──
    cached = find_cached_repo(raw_url, clean_branch)
    if cached:
        cached_id = cached["repo_id"]
        if progress_cb:
            progress_cb(1, "cached", f"Found {repo_name} in SQLite database! Loading instantaneously...", 40)
            progress_cb(4, "graph", "Restoring cached dependency graph & metrics...", 80)
            progress_cb(7, "complete", "Excavation loaded from database!", 100)

        # Restore in memory for active session
        G = _reconstruct_networkx(cached["graph"])
        STORE[cached_id] = {
            "workdir": "",
            "graph": G,
            "symbols_by_id": {},  # Will load on demand from SQLite
            "functions_by_id": {},
            "classes_by_id": {},
            "files": [],
            "file_change_freq": {},
            "repo_index": {"files": [], "classes": [], "functions": [], "constants": [], "imports": [], "routes": []},
            "commits": cached.get("commits", []),
            "architectural_context": cached.get("architectural_context", ""),
            "repo_url": cached.get("repo_url", raw_url),
            "repo_name": cached.get("repo_name", repo_name),
            "branch": cached.get("branch", "main"),
        }
        return cached

    # ── 2. Cloud-Native Zero-Disk Ingestion (In-Memory Tarball Stream) ──
    repo_id = str(uuid.uuid4())[:8]
    workdir_obj = None
    extracted = None
    commits = []
    file_change_freq = {}
    active_branch = clean_branch or "main"
    temporal_couplings = {}

    # Attempt zero-disk in-memory streaming if GitHub URL
    owner_repo = parse_github_owner_repo(raw_url)
    if owner_repo:
        try:
            if progress_cb:
                progress_cb(1, "streaming", f"Streaming {repo_name} source tarball from GitHub CDN into RAM...", 20)

            files_dict, gh_commits, gh_freq, gh_name, gh_branch = fetch_github_in_memory(raw_url, clean_branch)
            repo_name = gh_name
            active_branch = gh_branch
            commits = gh_commits
            file_change_freq = gh_freq

            if progress_cb:
                progress_cb(2, "parsing_ast", f"Extracting syntax trees across {len(files_dict)} files in RAM...", 50)

            extracted = extract_from_in_memory_files(files_dict)
        except Exception as e_stream:
            print(f"In-memory streaming fallback due to: {e_stream}")
            extracted = None

    # Fallback to shallow clone depth=15 if in-memory streaming failed or non-GitHub URL
    if not extracted:
        workdir_obj = Path(tempfile.gettempdir()) / "code-archaeologist" / repo_id
        workdir_obj.mkdir(parents=True, exist_ok=True)
        CLONE_DEPTH = 15
        clone_opts = ["--single-branch", "--no-tags"]

        if progress_cb:
            progress_cb(1, "cloning", f"Cloning {repo_name} from git (depth={CLONE_DEPTH})...", 20)

        try:
            if clean_branch:
                git_repo = git.Repo.clone_from(raw_url, workdir_obj, branch=clean_branch, depth=CLONE_DEPTH, multi_options=clone_opts)
                active_branch = clean_branch
            else:
                git_repo = git.Repo.clone_from(raw_url, workdir_obj, depth=CLONE_DEPTH, multi_options=clone_opts)
                active_branch = git_repo.active_branch.name if not git_repo.head.is_detached else "master"
        except Exception as e_clone:
            safe_delete_tree(workdir_obj)
            raise HTTPException(status_code=400, detail=f"Could not clone repository: {str(e_clone)}")

        if progress_cb:
            progress_cb(2, "scanning", f"Parsing syntax trees ({active_branch} branch)...", 50)

        extracted = extract_repo(str(workdir_obj), extensions=SUPPORTED_EXTENSIONS)
        file_change_freq = get_repo_change_frequency(str(workdir_obj))
        temporal_couplings = get_temporal_coupling(str(workdir_obj), limit_commits=CLONE_DEPTH)
        commits = get_repo_commits(str(workdir_obj), repo_url=raw_url, limit=CLONE_DEPTH)

    if not extracted or (not extracted.get("functions") and not extracted.get("classes")):
        if workdir_obj:
            safe_delete_tree(workdir_obj)
        raise HTTPException(
            status_code=400,
            detail="No classes or functions found. Only Python and JavaScript/TypeScript repositories are currently supported.",
        )

    num_files = len(extracted["files"])
    num_fns = len(extracted["functions"])
    num_classes = len(extracted["classes"])

    # ── 3. Graph Construction with PyCG Call Resolution & Keystones ──
    G, unresolved, graph_metadata = build_graph(extracted)

    if progress_cb:
        progress_cb(4, "graph", f"Constructed call graph ({G.number_of_nodes()} nodes, {G.number_of_edges()} edges)...", 75)

    for _, node_attrs in G.nodes(data=True):
        f = node_attrs.get("file", "")
        node_attrs["change_frequency"] = file_change_freq.get(f, 0)

    # Pre-mine blame history for top hotspot & complex functions (up to 40)
    top_candidates = sorted(
        extracted["functions"],
        key=lambda fn: (file_change_freq.get(fn.get("file", ""), 0) * 10 + fn.get("complexity", 1)),
        reverse=True,
    )[:40]
    top_candidate_ids = {fn["id"] for fn in top_candidates}

    for fn in extracted["functions"]:
        if fn["id"] in top_candidate_ids and workdir_obj:
            try:
                fn["history"] = get_function_history(str(workdir_obj), fn["file"], fn["start_line"], fn["end_line"], limit=4)
            except Exception:
                fn["history"] = []
        else:
            fn["history"] = []

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

    if progress_cb:
        progress_cb(5, "git", f"Mined Git commit history and computed CodeScene hotspots...", 88)

    if not commits and workdir_obj:
        commits = get_repo_commits(str(workdir_obj), repo_url=raw_url, limit=15)

    if progress_cb:
        progress_cb(6, "indexing", "Synthesizing architectural context summary and persisting to SQLite...", 95)

    arch_context = generate_architectural_context(
        extracted,
        file_change_freq,
        repo_name,
        temporal_couplings=temporal_couplings,
        keystones=graph_metadata.get("keystones"),
        circular_cycles=graph_metadata.get("circular_dependencies"),
    )

    repo_index = build_repo_index(extracted, G, extracted["files"], file_change_freq)
    graph_data = graph_to_json(G)

    # ── 6. Ingest into SQLite Database (Extract & Evaporate) ──
    try:
        save_repository_analysis(
            repo_id=repo_id,
            repo_url=raw_url,
            repo_name=repo_name,
            branch=active_branch,
            graph_data=graph_data,
            extracted=extracted,
            file_change_freq=file_change_freq,
            commits=commits,
            architectural_context=arch_context,
            symbols_by_id=symbols_by_id,
            unresolved_count=len(unresolved),
        )
    except Exception as dbe:
        print(f"Warning: SQLite persistence failed: {dbe}")

    # ── 7. EVAPORATE: If fallback clone was used, purge folder immediately from disk! ──
    if workdir_obj:
        safe_delete_tree(workdir_obj)

    # In-memory session cache
    STORE[repo_id] = {
        "workdir": "",
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
        "keystones": graph_metadata.get("keystones", []),
        "circular_dependencies": graph_metadata.get("circular_dependencies", []),
    }

    result = {
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
        "keystones": graph_metadata.get("keystones", []),
        "circular_dependencies": graph_metadata.get("circular_dependencies", []),
    }

    if progress_cb:
        progress_cb(7, "complete", "Excavation complete! Disk storage reclaimed.", 100)

    return result


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    return process_repo_analysis(req.repo_url, req.branch)


@app.post("/api/analyze/stream")
def analyze_stream(req: AnalyzeRequest):
    def event_stream():
        import queue
        q = queue.Queue()

        def cb(step, stage, message, percent):
            q.put({
                "type": "progress",
                "step": step,
                "stage": stage,
                "message": message,
                "percent": percent,
            })

        import threading

        result_holder = {}
        error_holder = {}

        def worker():
            try:
                res = process_repo_analysis(req.repo_url, req.branch, progress_cb=cb)
                result_holder["res"] = res
            except Exception as ex:
                error_holder["err"] = ex
            finally:
                q.put(None)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        while True:
            item = q.get()
            if item is None:
                break
            yield json.dumps(item) + "\n"

        if "err" in error_holder:
            err = error_holder["err"]
            detail = err.detail if isinstance(err, HTTPException) else str(err)
            yield json.dumps({"type": "error", "detail": detail}) + "\n"
        elif "res" in result_holder:
            yield json.dumps({"type": "complete", "result": result_holder["res"]}) + "\n"

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


def _get_repo(repo_id: str):
    if repo_id not in STORE:
        # Load directly from SQLite database
        db_repo = get_repository_analysis(repo_id)
        if db_repo:
            G = _reconstruct_networkx(db_repo["graph"])
            symbols = get_all_symbols(repo_id)
            symbols_by_id = {}
            functions_by_id = {}
            classes_by_id = {}
            repo_index = {"files": [], "classes": [], "functions": [], "constants": [], "imports": [], "routes": []}
            files_set = set()

            for sym in symbols:
                symbols_by_id[sym["id"]] = sym
                if sym.get("raw_id"):
                    symbols_by_id[sym["raw_id"]] = sym
                if sym.get("kind") == "class":
                    classes_by_id[sym["id"]] = sym
                    repo_index["classes"].append(sym)
                else:
                    functions_by_id[sym["id"]] = sym
                    repo_index["functions"].append(sym)
                    if sym.get("is_route"):
                        decs = sym.get("decorators") or [""]
                        repo_index["routes"].append({
                            "decorator": decs[0] if decs else "",
                            "function_id": sym["id"],
                            "function_name": sym.get("qualified_name", sym.get("name")),
                            "file": sym.get("file", ""),
                        })
                if sym.get("file"):
                    files_set.add(sym["file"])

            repo_index["files"] = [
                {"path": f, "language": "python" if f.endswith(".py") else "javascript"}
                for f in sorted(files_set)
            ]

            STORE[repo_id] = {
                "repo_id": repo_id,
                "workdir": "",
                "graph": G,
                "symbols_by_id": symbols_by_id,
                "functions_by_id": functions_by_id,
                "classes_by_id": classes_by_id,
                "files": list(files_set),
                "file_change_freq": db_repo.get("file_change_freq", {}),
                "repo_index": repo_index,
                "commits": db_repo.get("commits", []),
                "architectural_context": db_repo.get("architectural_context", ""),
                "repo_url": db_repo.get("repo_url", ""),
                "repo_name": db_repo.get("repo_name", repo_id),
                "branch": db_repo.get("branch", "main"),
            }
            return STORE[repo_id]

        raise HTTPException(status_code=404, detail="Repository not found. Please analyze.")
    return STORE[repo_id]


@app.get("/api/graph/{repo_id}")
def get_graph(repo_id: str):
    data = _get_repo(repo_id)
    return graph_to_json(data["graph"])


@app.get("/api/symbol/{repo_id}")
@app.get("/api/function/{repo_id}")
def get_symbol_details(repo_id: str, id: str = Query(...)):
    data = _get_repo(repo_id)
    symbol = data.get("symbols_by_id", {}).get(id)

    if not symbol:
        # Check SQLite database directly!
        symbol = db_get_symbol_details(repo_id, id)

    G = data.get("graph")

    if not symbol and G and G.has_node(id):
        symbol = dict(G.nodes[id])

    if not symbol:
        raise HTTPException(status_code=404, detail=f"Symbol '{id}' not found.")

    node_id = symbol.get("id", id)

    # Compute incoming callers from graph if not present
    if not symbol.get("incoming_callers") and G and G.has_node(node_id):
        incoming = []
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
        symbol["incoming_callers"] = incoming

    # Compute outgoing dependencies from graph if not present
    if not symbol.get("outgoing_dependencies") and G and G.has_node(node_id):
        outgoing = []
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
        symbol["outgoing_dependencies"] = outgoing

    return symbol


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
        "keystones": data.get("keystones", []),
        "circular_dependencies": data.get("circular_dependencies", []),
    }


@app.get("/api/qa/{repo_id}")
def get_qa_history_endpoint(repo_id: str):
    """Returns persistent multi-turn Q&A threads from SQLite."""
    threads = get_qa_threads(repo_id)
    return {"threads": threads}


@app.get("/api/trace/{repo_id}")
def trace(repo_id: str, start_id: str = Query(...), depth: int = 6):
    """BFS forward along calls, instantiates, and contains edges."""
    data = _get_repo(repo_id)
    G = data["graph"]

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
        # Save to SQLite multi-turn chat history
        save_qa_thread(repo_id, req.question, answer, highlighted_ids)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"answer": answer, "highlighted_ids": highlighted_ids}


@app.post("/api/ask/stream/{repo_id}")
def ask_stream(repo_id: str, req: AskRequest):
    """
    Streams Gemini response tokens over ndjson.
    Emits metadata (highlighted symbols) first, followed by incremental token deltas,
    and finishes with a 'done' event, persisting the final conversation thread in SQLite.
    """
    data = _get_repo(repo_id)

    def event_generator():
        accumulated_text = []
        highlighted = []
        try:
            for event in retrieve_and_answer_stream(req.question, data):
                if event.get("type") == "metadata":
                    highlighted = event.get("highlighted_ids", [])
                elif event.get("type") == "token":
                    accumulated_text.append(event.get("delta", ""))
                yield json.dumps(event) + "\n"

            full_answer = "".join(accumulated_text)
            if full_answer:
                try:
                    save_qa_thread(repo_id, req.question, full_answer, highlighted)
                except Exception as save_err:
                    print(f"Failed to persist QA thread to SQLite: {save_err}")
        except Exception as e:
            yield json.dumps({"type": "error", "detail": str(e)}) + "\n"

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


@app.get("/api/health")
def health():
    return {"status": "ok"}
