"""
Two-stage retrieval pipeline for Code Archaeologist.

Stage 0  — Build a compact repository structural index during analysis.
Stage 1  — Use an LLM to identify relevant components from the index.
Stage 2  — Resolve actual source code for the selected components.
Stage 2.5— Expand context through the existing NetworkX call graph.
Git      — Attach blame/commit history to selected functions only.
Final    — Assemble a focused prompt and send it to Gemini.

This module deliberately avoids sending the entire repository to the LLM.
The structural index (Stage 0) contains names, files, line ranges, and
relationships — but NO source code — so Stage 1 is cheap and fast.
"""

import re
from collections import OrderedDict

from llm import select_relevant_components, generate_response
from git_utils import get_function_history


# ── Stage 0: Build repository structural index ──────────────────────────
#
# Called once during /api/analyze.  Produces a compact map of the repo
# that is stored alongside the existing graph and functions_by_id.

def build_repo_index(extracted, graph, files, file_change_freq):
    """
    Build a compact structural index of the repository.

    Contains metadata (names, files, line ranges, relationships) but NOT
    full source code — designed to be cheap to send to the retrieval LLM.
    """
    index = {
        "files": [],
        "classes": [],
        "functions": [],
        "constants": [],
        "imports": [],
        "routes": [],
    }

    # ── Files ──
    for f in files:
        lang = "python" if f.endswith(".py") else "unknown"
        index["files"].append({"path": f, "language": lang})

    # ── Classes ──
    for cls in extracted.get("classes", []):
        index["classes"].append({
            "name": cls["name"],
            "file": cls["file"],
            "qualified_name": cls.get("qualified_name", cls["name"]),
        })

    # ── Functions (stripped of source code) ──
    for fn in extracted["functions"]:
        entry = {
            "id": fn["id"],
            "name": fn["name"],
            "qualified_name": fn["qualified_name"],
            "file": fn["file"],
            "start_line": fn["start_line"],
            "end_line": fn["end_line"],
            "class": fn.get("class"),
            "is_route": fn.get("is_route", False),
            "params": fn.get("params", "()"),
        }
        if fn.get("decorators"):
            entry["decorators"] = fn["decorators"]
        index["functions"].append(entry)

    # ── Constants ──
    for const in extracted.get("constants", []):
        index["constants"].append({
            "name": const["name"],
            "file": const["file"],
            "line": const["line"],
            "source": const.get("source", ""),
        })

    # ── Imports ──
    for imp in extracted.get("imports", []):
        index["imports"].append({
            "text": imp["text"],
            "file": imp.get("file", ""),
            "line": imp.get("line", 0),
        })

    # ── Routes (pulled from functions that have route decorators) ──
    route_markers = (".route(", ".get(", ".post(", ".put(", ".delete(", ".patch(")
    for fn in extracted["functions"]:
        if fn.get("is_route") and fn.get("decorators"):
            for dec in fn["decorators"]:
                if any(m in dec for m in route_markers):
                    index["routes"].append({
                        "decorator": dec,
                        "function_id": fn["id"],
                        "function_name": fn["qualified_name"],
                        "file": fn["file"],
                    })

    return index


# ── Stage 1: Relevant-context selection ──────────────────────────────────

def _lexical_prefilter(question, repo_index, max_candidates=10):
    """
    Cheap keyword-overlap filter as a first pass.

    Returns candidate function IDs, file paths, and constant names that
    lexically match the question.  Zero cost, no API call.
    """
    q_words = {w.lower() for w in re.split(r'\W+', question) if len(w) > 2}

    scored_functions = []
    for fn in repo_index["functions"]:
        haystack = f"{fn['qualified_name']} {fn['file']} {fn.get('params', '')}".lower()
        if fn.get("decorators"):
            haystack += " " + " ".join(fn["decorators"]).lower()
        s = sum(1 for w in q_words if w in haystack)
        if s > 0:
            scored_functions.append((s, fn["id"]))
    scored_functions.sort(reverse=True)

    scored_files = []
    for f in repo_index["files"]:
        haystack = f["path"].lower().replace("/", " ").replace("\\", " ").replace("_", " ")
        s = sum(1 for w in q_words if w in haystack)
        if s > 0:
            scored_files.append((s, f["path"]))
    scored_files.sort(reverse=True)

    scored_constants = []
    for c in repo_index["constants"]:
        haystack = f"{c['name']} {c.get('source', '')}".lower()
        s = sum(1 for w in q_words if w in haystack)
        if s > 0:
            scored_constants.append((s, c["name"]))
    scored_constants.sort(reverse=True)

    scored_classes = []
    for cls in repo_index.get("classes", []):
        haystack = f"{cls['qualified_name']} {cls['file']}".lower()
        s = sum(1 for w in q_words if w in haystack)
        if s > 0:
            scored_classes.append((s, cls["qualified_name"]))
    scored_classes.sort(reverse=True)

    return {
        "files": [f for _, f in scored_files[:max_candidates]],
        "functions": [fid for _, fid in scored_functions[:max_candidates]],
        "classes": [c for _, c in scored_classes[:max_candidates]],
        "constants": [c for _, c in scored_constants[:max_candidates]],
        "imports": [],
    }


def _format_index_for_llm(repo_index, lexical_hints=None):
    """
    Format the repository structural index as a readable text block for
    the Stage 1 retrieval prompt.  No source code is included.
    """
    lines = []

    lines.append("FILES:")
    for f in repo_index["files"]:
        lines.append(f"  {f['path']}")

    if repo_index["classes"]:
        lines.append("\nCLASSES:")
        for cls in repo_index["classes"]:
            lines.append(f"  {cls['qualified_name']} [{cls['file']}]")

    lines.append("\nFUNCTIONS:")
    for fn in repo_index["functions"]:
        tag = " [ROUTE]" if fn.get("is_route") else ""
        decs = ""
        if fn.get("decorators"):
            decs = "  decorators: " + ", ".join(fn["decorators"][:2])
        lines.append(
            f"  {fn['qualified_name']}{fn.get('params', '()')}"
            f" [{fn['file']}:{fn['start_line']}]{tag}{decs}"
        )

    if repo_index["constants"]:
        lines.append("\nCONSTANTS:")
        for c in repo_index["constants"]:
            lines.append(f"  {c['name']} [{c['file']}:{c['line']}]")

    if repo_index["imports"]:
        lines.append("\nIMPORTS:")
        by_file = {}
        for imp in repo_index["imports"]:
            by_file.setdefault(imp.get("file", "?"), []).append(imp["text"])
        for file_path, texts in sorted(by_file.items()):
            for t in texts[:8]:  # cap per file to avoid overwhelming the prompt
                lines.append(f"  {t} [{file_path}]")
            if len(texts) > 8:
                lines.append(f"  ... and {len(texts) - 8} more [{file_path}]")

    if repo_index["routes"]:
        lines.append("\nROUTES:")
        for r in repo_index["routes"]:
            lines.append(f"  {r['decorator']} -> {r['function_name']} [{r['file']}]")

    # If lexical pre-filtering found candidates, surface them as hints.
    if lexical_hints and any(lexical_hints.get(k) for k in lexical_hints):
        lines.append("\nLEXICAL CANDIDATES (keyword-matched, for reference):")
        if lexical_hints.get("functions"):
            lines.append(f"  Functions: {', '.join(lexical_hints['functions'][:5])}")
        if lexical_hints.get("files"):
            lines.append(f"  Files: {', '.join(lexical_hints['files'][:5])}")
        if lexical_hints.get("classes"):
            lines.append(f"  Classes: {', '.join(lexical_hints['classes'][:5])}")
        if lexical_hints.get("constants"):
            lines.append(f"  Constants: {', '.join(lexical_hints['constants'][:5])}")

    return "\n".join(lines)


def _llm_select_components(question, repo_index, lexical_hints=None):
    """
    Stage 1: Ask the LLM to identify which repository components are
    relevant to answering the user's question.

    Receives only the structural index (no source code).
    Returns structured JSON with file paths, function IDs, class names,
    and constant names — all validated downstream before use.
    """
    index_text = _format_index_for_llm(repo_index, lexical_hints)

    prompt = f"""You are a code retrieval assistant. Given a user's question about a repository and the repository's structural index, identify which components are relevant to answering the question.

Return ONLY a JSON object with this exact shape:
{{
  "files": [],
  "functions": [],
  "classes": [],
  "constants": [],
  "imports": []
}}

Rules:
- "functions" must contain function IDs in the exact format shown (e.g. "auth.py::AuthService.authenticate")
- "files" must contain file paths exactly as listed
- "classes" must contain class qualified names exactly as listed
- "constants" must contain constant names exactly as listed
- "imports" must contain import text exactly as listed
- Only select components that are relevant to answering the question
- Select 2-8 functions unless the question clearly requires more
- Do NOT invent components that are not in the index
- If lexical candidates are provided, consider them but do not blindly include all of them

USER QUESTION:
{question}

REPOSITORY STRUCTURE:
{index_text}

Return ONLY the JSON object, no other text."""

    return select_relevant_components(prompt)


def _validate_selections(selected, repo_index):
    """
    Validate LLM-returned component IDs against the actual repository index.
    Silently drops any IDs that don't exist — never trust an LLM-generated
    identifier without checking.
    """
    valid_file_paths = {f["path"] for f in repo_index["files"]}
    valid_function_ids = {fn["id"] for fn in repo_index["functions"]}
    valid_class_names = {cls["qualified_name"] for cls in repo_index["classes"]}
    valid_constant_names = {c["name"] for c in repo_index["constants"]}
    valid_import_texts = {imp["text"] for imp in repo_index["imports"]}

    # Also allow lookup by qualified_name or bare name, so the LLM
    # doesn't have to perfectly recall the "file.py::Name" format.
    qname_to_id = {}
    for fn in repo_index["functions"]:
        qname_to_id[fn["qualified_name"]] = fn["id"]
        qname_to_id[fn["name"]] = fn["id"]

    validated = {
        "files": [f for f in selected.get("files", []) if f in valid_file_paths],
        "functions": [],
        "classes": [c for c in selected.get("classes", []) if c in valid_class_names],
        "constants": [c for c in selected.get("constants", []) if c in valid_constant_names],
        "imports": [i for i in selected.get("imports", []) if i in valid_import_texts],
    }

    # For functions, try exact ID first, then qualified-name / bare-name.
    for fid in selected.get("functions", []):
        if fid in valid_function_ids:
            validated["functions"].append(fid)
        elif fid in qname_to_id:
            validated["functions"].append(qname_to_id[fid])

    # Deduplicate while preserving order
    validated["functions"] = list(dict.fromkeys(validated["functions"]))

    return validated


def _count_selections(selected):
    """Total number of selected components across all categories."""
    return sum(len(selected.get(k, [])) for k in ("files", "functions", "classes", "constants"))


def _merge_selections(base, fallback):
    """Merge fallback selections into base without duplicates."""
    merged = {}
    for key in ("files", "functions", "classes", "constants", "imports"):
        seen = set(base.get(key, []))
        merged[key] = list(base.get(key, []))
        for item in fallback.get(key, []):
            if item not in seen:
                merged[key].append(item)
                seen.add(item)
    return merged


# ── Stage 2: Resolve actual source code ──────────────────────────────────

def _resolve_source(selected, functions_by_id, repo_data):
    """
    Stage 2: Retrieve actual source code for the selected components.

    Uses the already-parsed data stored during /api/analyze — does NOT
    re-read files from disk or ask the LLM to reproduce code.
    """
    context = {
        "functions": OrderedDict(),   # id -> {source, metadata, ...}
        "constants": [],
        "files_mentioned": set(selected.get("files", [])),
    }

    # ── Resolve selected functions ──
    for fid in selected.get("functions", []):
        fn = functions_by_id.get(fid)
        if fn and fid not in context["functions"]:
            context["functions"][fid] = _fn_to_context(fn, fid)

    # ── If classes were selected, include their methods ──
    for cls_name in selected.get("classes", []):
        for fid, fn in functions_by_id.items():
            if fn.get("class") == cls_name and fid not in context["functions"]:
                context["functions"][fid] = _fn_to_context(fn, fid)

    # ── If files were selected but no functions from them, pull all
    #    functions in those files so the LLM has some code to work with ──
    files_with_functions = {ctx["file"] for ctx in context["functions"].values()}
    for file_path in selected.get("files", []):
        if file_path not in files_with_functions:
            for fid, fn in functions_by_id.items():
                if fn["file"] == file_path and fid not in context["functions"]:
                    context["functions"][fid] = _fn_to_context(fn, fid)

    # ── Resolve constants ──
    repo_index = repo_data.get("repo_index", {})
    for const_name in selected.get("constants", []):
        for c in repo_index.get("constants", []):
            if c["name"] == const_name:
                context["constants"].append(c)
                break

    return context


def _fn_to_context(fn, fid, expanded=False):
    """Convert a function record to a context entry."""
    return {
        "id": fid,
        "qualified_name": fn["qualified_name"],
        "file": fn["file"],
        "start_line": fn["start_line"],
        "end_line": fn["end_line"],
        "source": fn["source"],
        "params": fn.get("params", "()"),
        "class": fn.get("class"),
        "is_route": fn.get("is_route", False),
        "decorators": fn.get("decorators", []),
        "expanded": expanded,
    }


# ── Stage 2.5: Graph-aware context expansion ─────────────────────────────

def _expand_via_graph(context, graph, functions_by_id,
                      max_callee_hops=2, max_caller_hops=1, max_expanded=12):
    """
    Stage 2.5: Expand selected functions through the existing NetworkX
    call graph.

    - Forward (callees): up to max_callee_hops hops so call chains like
      authenticate() → validate_token() → decode_token() are included
      even if only the root was explicitly selected.
    - Backward (callers): one hop to capture immediate callers.
    - Capped at max_expanded additions to avoid pulling the whole graph.
    """
    seed_ids = set(context["functions"].keys())
    expanded_ids = set()

    # ── Forward expansion (callees) ──
    frontier = list(seed_ids)
    for _hop in range(max_callee_hops):
        next_frontier = []
        for node_id in frontier:
            if node_id not in graph:
                continue
            for _, callee in graph.out_edges(node_id):
                if callee not in seed_ids and callee not in expanded_ids:
                    expanded_ids.add(callee)
                    next_frontier.append(callee)
        frontier = next_frontier
        if len(expanded_ids) >= max_expanded:
            break

    # ── Backward expansion (callers, one hop only) ──
    for node_id in list(seed_ids):
        if node_id not in graph:
            continue
        for caller, _ in graph.in_edges(node_id):
            if caller not in seed_ids and caller not in expanded_ids:
                expanded_ids.add(caller)
        if len(expanded_ids) >= max_expanded:
            break

    # ── Add expanded functions to context (marked as graph-expanded) ──
    for fid in list(expanded_ids)[:max_expanded]:
        fn = functions_by_id.get(fid)
        if fn and fid not in context["functions"]:
            context["functions"][fid] = _fn_to_context(fn, fid, expanded=True)

    # ── Build call-relationship descriptions for the prompt ──
    all_ids = set(context["functions"].keys())
    call_chains = []
    for fid in all_ids:
        if fid in graph:
            for _, callee in graph.out_edges(fid):
                if callee in all_ids:
                    caller_name = functions_by_id.get(fid, {}).get("qualified_name", fid)
                    callee_name = functions_by_id.get(callee, {}).get("qualified_name", callee)
                    call_chains.append(f"  {caller_name} -> {callee_name}")

    context["call_relationships"] = call_chains
    return context


# ── Git context attachment ───────────────────────────────────────────────

def _attach_git_history(context, workdir, limit=5):
    """
    Attach git-blame history to each function in the context.

    Only retrieves history for the selected/expanded functions —
    NOT the entire repository.
    """
    for fn_ctx in context["functions"].values():
        try:
            history = get_function_history(
                workdir,
                fn_ctx["file"],
                fn_ctx["start_line"],
                fn_ctx["end_line"],
                limit=limit,
            )
            fn_ctx["history"] = history
        except Exception:
            fn_ctx["history"] = []

    return context


# ── Context size enforcement ─────────────────────────────────────────────

def _enforce_context_limit(context, max_chars=30_000):
    """
    Prevent accidentally sending the entire repository to Gemini.

    Removes graph-expanded functions first (least important), then
    truncates remaining source if still over the limit.
    """
    def _estimate_size():
        total = 0
        for fn_ctx in context["functions"].values():
            total += len(fn_ctx.get("source", ""))
            for h in fn_ctx.get("history", []):
                total += len(str(h))
        for c in context.get("constants", []):
            total += len(c.get("source", ""))
        return total

    # Fast path: small enough already
    if _estimate_size() <= max_chars:
        return context

    # Drop graph-expanded functions first (they're supplementary)
    expanded_ids = [fid for fid, fn in context["functions"].items()
                    if fn.get("expanded")]
    for fid in reversed(expanded_ids):
        if _estimate_size() <= max_chars:
            break
        del context["functions"][fid]

    # If still over, truncate long sources
    if _estimate_size() > max_chars:
        for fn_ctx in context["functions"].values():
            src = fn_ctx.get("source", "")
            if len(src) > 2000:
                fn_ctx["source"] = src[:2000] + "\n# ... (truncated)"

    return context


# ── Final context formatting ─────────────────────────────────────────────

def _build_final_prompt(question, context):
    """
    Assemble the final Gemini prompt with ONLY the retrieved context.
    """
    sections = []

    # ── Call relationships ──
    if context.get("call_relationships"):
        sections.append("CALL RELATIONSHIPS:")
        sections.extend(context["call_relationships"])
        sections.append("")

    # ── Source code (grouped by file) ──
    by_file = {}
    for fn_ctx in context["functions"].values():
        by_file.setdefault(fn_ctx["file"], []).append(fn_ctx)

    if by_file:
        sections.append("RELEVANT SOURCE CODE:")
        for file_path in sorted(by_file):
            fns = sorted(by_file[file_path], key=lambda f: f["start_line"])
            for fn_ctx in fns:
                tag = " [graph-expanded]" if fn_ctx.get("expanded") else ""
                sections.append(
                    f"\n--- {file_path}: {fn_ctx['qualified_name']}"
                    f" (L{fn_ctx['start_line']}-{fn_ctx['end_line']}){tag} ---"
                )
                sections.append(f"```python\n{fn_ctx['source']}\n```")
        sections.append("")

    # ── Constants ──
    if context.get("constants"):
        sections.append("RELEVANT CONSTANTS:")
        for c in context["constants"]:
            sections.append(f"  {c['source']}  [{c['file']}]")
        sections.append("")

    # ── Git history ──
    history_lines = []
    for fn_ctx in context["functions"].values():
        if fn_ctx.get("history"):
            history_lines.append(f"  {fn_ctx['qualified_name']}:")
            for h in fn_ctx["history"]:
                history_lines.append(
                    f"    {h['commit']} . {h['author']} . "
                    f"{h['date'][:10]}: {h['message']}"
                )
    if history_lines:
        sections.append("RELEVANT GIT HISTORY:")
        sections.extend(history_lines)
        sections.append("")

    context_text = "\n".join(sections)

    return f"""You are a senior engineer explaining an unfamiliar codebase to a new teammate.

Answer the user's question using the repository context provided below.

USER QUESTION:
{question}

{context_text}
Instructions:
- Base the answer on the supplied repository context.
- Do not invent functions, files, behavior, or Git history not shown above.
- If the supplied context is insufficient, explicitly say what information is missing.
- Explain relationships between functions when relevant.
- Be concise and concrete, and reference function names directly."""


# ── Main orchestrator ────────────────────────────────────────────────────

def retrieve_and_answer(question, repo_data, max_context_chars=30_000):
    """
    Full two-stage retrieval pipeline.

    Flow:
        lexical pre-filter  (cheap keyword matching for candidate hints)
            ↓
        LLM retrieval       (Stage 1: selects components from the index)
            ↓
        source resolution   (Stage 2: fetches code from parsed data)
            ↓
        graph expansion     (Stage 2.5: includes call-chain neighbours)
            ↓
        git history         (attaches blame to selected functions)
            ↓
        context limit       (trims if too large)
            ↓
        final prompt        (sends only relevant context to Gemini)

    Returns (answer_text, highlighted_function_ids).
    """
    repo_index = repo_data["repo_index"]
    functions_by_id = repo_data["functions_by_id"]
    graph = repo_data["graph"]
    workdir = repo_data["workdir"]

    # ── Lexical pre-filter (zero cost, used as hints + fallback) ──
    lexical_hints = _lexical_prefilter(question, repo_index)

    # ── Stage 1: LLM-based component selection ──
    try:
        selected = _llm_select_components(question, repo_index, lexical_hints)
        selected = _validate_selections(selected, repo_index)
    except Exception:
        # Fallback: if LLM retrieval fails (bad JSON, API error, etc.),
        # fall back to the lexical results so /api/ask never fully breaks.
        selected = lexical_hints

    # If Stage 1 returned very few results, broaden with lexical fallback
    if _count_selections(selected) < 2:
        selected = _merge_selections(selected, lexical_hints)

    # If STILL nothing (no lexical matches either), grab the first few
    # functions so the prompt isn't empty.
    if _count_selections(selected) == 0:
        selected["functions"] = [
            fn["id"] for fn in repo_index["functions"][:4]
        ]

    # ── Stage 2: Resolve actual source code ──
    context = _resolve_source(selected, functions_by_id, repo_data)

    # ── Stage 2.5: Graph-aware expansion ──
    context = _expand_via_graph(context, graph, functions_by_id)

    # ── Attach git history to selected functions ──
    context = _attach_git_history(context, workdir)

    # ── Enforce context size limit ──
    context = _enforce_context_limit(context, max_context_chars)

    # ── Build and send final prompt ──
    final_prompt = _build_final_prompt(question, context)

    # Collect highlighted function IDs for the frontend graph overlay
    highlighted_ids = list(context["functions"].keys())

    try:
        answer = generate_response(final_prompt)
    except RuntimeError:
        raise  # Let the caller handle missing API key etc.

    return answer, highlighted_ids
