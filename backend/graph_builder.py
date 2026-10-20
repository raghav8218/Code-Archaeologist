"""
Turns extracted classes, functions, methods, imports, and calls into a compound graph.
Includes PyCG-style call resolution, PageRank keystone identification, and Tarjan's cycle detection.
"""

from typing import Dict, List, Any, Tuple
import math
import networkx as nx


def build_graph(extracted: Dict[str, Any]) -> Tuple[nx.DiGraph, List[Dict[str, Any]], Dict[str, Any]]:
    G = nx.DiGraph()

    classes = extracted.get("classes", [])
    functions = extracted.get("functions", [])
    calls = extracted.get("calls", [])
    imports = extracted.get("imports", [])

    # Index by name and qualified name for fast lookup
    class_by_name: Dict[str, List[Dict[str, Any]]] = {}
    class_by_id: Dict[str, Dict[str, Any]] = {}
    for cls in classes:
        class_by_name.setdefault(cls["name"], []).append(cls)
        class_by_id[cls["id"]] = cls

    func_by_name: Dict[str, List[Dict[str, Any]]] = {}
    func_by_id: Dict[str, Dict[str, Any]] = {}
    func_by_qname: Dict[str, Dict[str, Any]] = {}
    for fn in functions:
        func_by_name.setdefault(fn["name"], []).append(fn)
        func_by_id[fn["id"]] = fn
        if fn.get("qualified_name"):
            func_by_qname[fn["qualified_name"]] = fn

    # 1. Add Class nodes
    for cls in classes:
        node_attrs = {k: v for k, v in cls.items() if k not in ("raw_id",)}
        G.add_node(cls["id"], **node_attrs)

    # 2. Add Function / Method / Route nodes
    for fn in functions:
        node_attrs = {k: v for k, v in fn.items() if k not in ("raw_id",)}
        G.add_node(fn["id"], **node_attrs)

    # 3. Add 'contains' edges: Class -> Method
    for cls in classes:
        for method_id in cls.get("methods", []):
            if G.has_node(method_id):
                G.add_edge(cls["id"], method_id, type="contains", weight=1)

    # 4. Add 'inherits' edges: Derived Class -> Base Class
    for cls in classes:
        for base in cls.get("bases", []):
            clean_base = base.split(".")[-1]
            base_candidates = class_by_name.get(clean_base, [])
            if base_candidates:
                same_file = [c for c in base_candidates if c["file"] == cls["file"]]
                target = same_file[0] if same_file else base_candidates[0]
                G.add_edge(cls["id"], target["id"], type="inherits", weight=1)

    # 5. Resolve calls (PyCG-inspired Qualifier Resolution + Local-Scope Precedence)
    unresolved = []
    external_call_counts: Dict[str, int] = {}
    external_calls_map: List[Tuple[str, str]] = []

    for call in calls:
        caller = call["caller"]
        callee_name = call["callee_name"]
        qualifier = call.get("qualifier", "")

        if not G.has_node(caller):
            continue

        caller_node = G.nodes[caller]
        caller_file = caller_node.get("file", "")

        resolved = False

        # Strategy A (PyCG): If qualifier matches an instantiated class, target its method directly
        if qualifier:
            clean_qualifier = qualifier.split(".")[-1]
            if clean_qualifier in class_by_name:
                cls_cands = class_by_name[clean_qualifier]
                target_cls = cls_cands[0]
                target_fn_id = f"fn_{target_cls['name']}_{callee_name}"
                if G.has_node(target_fn_id):
                    if G.has_edge(caller, target_fn_id):
                        G[caller][target_fn_id]["weight"] += 1
                    else:
                        G.add_edge(caller, target_fn_id, type="calls", weight=1)
                    resolved = True
                    continue

        # Strategy B: Check if callee is a Class (Instantiates)
        clean_callee = callee_name.split(".")[-1]
        if clean_callee in class_by_name:
            candidates = class_by_name[clean_callee]
            same_file = [c for c in candidates if c["file"] == caller_file]
            target_cls = same_file[0] if same_file else candidates[0]

            if G.has_edge(caller, target_cls["id"]):
                G[caller][target_cls["id"]]["weight"] += 1
            else:
                G.add_edge(caller, target_cls["id"], type="instantiates", weight=1)
            resolved = True
            continue

        # Strategy C: Check if callee is a Function/Method (Calls)
        if clean_callee in func_by_name:
            candidates = func_by_name[clean_callee]
            same_file = [f for f in candidates if f["file"] == caller_file]
            target_fn = same_file[0] if same_file else candidates[0]

            if target_fn["id"] == caller:
                continue

            if G.has_edge(caller, target_fn["id"]):
                G[caller][target_fn["id"]]["weight"] += 1
            else:
                G.add_edge(caller, target_fn["id"], type="calls", weight=1)
            resolved = True
            continue

        # Strategy D: Fast O(1) Lookup for qualified names or IDs
        target_fn = func_by_qname.get(callee_name) or func_by_id.get(callee_name)
        if target_fn:
            fid = target_fn["id"]
            if fid != caller:
                if G.has_edge(caller, fid):
                    G[caller][fid]["weight"] += 1
                else:
                    G.add_edge(caller, fid, type="calls", weight=1)
                resolved = True
                continue

        if resolved:
            continue

        # Otherwise it's unresolved or an external library call
        unresolved.append(call)
        if len(clean_callee) > 1 and not clean_callee.startswith("_"):
            external_call_counts[clean_callee] = external_call_counts.get(clean_callee, 0) + 1
            external_calls_map.append((caller, clean_callee))

    # Anti-Spaghetti Filter: Drop generic python / ORM method names
    GENERIC_METHODS = {
        "get", "post", "put", "delete", "first", "all", "filter", "filter_by",
        "add", "commit", "rollback", "lower", "upper", "strip", "split", "join",
        "replace", "find", "count", "items", "keys", "values", "pop", "append",
        "extend", "insert", "clear", "copy", "update", "format", "render",
        "execute", "close", "connect", "print", "len", "str", "int", "dict", "list", "set",
        "String", "Column", "Integer", "Boolean", "DateTime", "ForeignKey", "Text"
    }

    # Only prominent external utilities/services called frequently (>= 3 times)
    top_externals = {
        k for k, v in external_call_counts.items()
        if v >= 3 and k not in GENERIC_METHODS and len(k) > 2
    }
    for ext_name in top_externals:
        ext_id = f"ext_{ext_name}"
        if not G.has_node(ext_id):
            G.add_node(
                ext_id,
                id=ext_id,
                label=ext_name,
                name=ext_name,
                qualified_name=ext_name,
                kind="external",
                file="external",
                loc=0,
                complexity=1,
            )

    for caller, ext_name in external_calls_map:
        if ext_name in top_externals:
            ext_id = f"ext_{ext_name}"
            if G.has_edge(caller, ext_id):
                G[caller][ext_id]["weight"] += 1
            else:
                G.add_edge(caller, ext_id, type="calls", weight=1)

    # 6. Add 'imports' edges across module boundaries
    file_nodes: Dict[str, List[str]] = {}
    for node_id, data in G.nodes(data=True):
        f = data.get("file", "")
        if f:
            file_nodes.setdefault(f, []).append(node_id)

    for imp in imports:
        imp_file = imp.get("file", "")
        imp_name = imp.get("name", "")

        target_node_id = None
        if imp_name in class_by_name:
            target_node_id = class_by_name[imp_name][0]["id"]
        elif imp_name in func_by_name:
            target_node_id = func_by_name[imp_name][0]["id"]

        if target_node_id and imp_file in file_nodes:
            for src_id in file_nodes[imp_file]:
                if not G.has_edge(src_id, target_node_id):
                    G.add_edge(src_id, target_node_id, type="imports", weight=1)
                break

    # 7. PageRank & Architectural Keystone Detection
    keystones = []
    if G.number_of_nodes() > 0:
        try:
            pagerank_scores = nx.pagerank(G, alpha=0.85, max_iter=100)
        except Exception:
            # Fallback to in-degree centrality
            pagerank_scores = nx.in_degree_centrality(G)

        # Attach scores to nodes
        sorted_ranks = sorted(pagerank_scores.items(), key=lambda x: x[1], reverse=True)
        top_count = max(3, math.ceil(len(sorted_ranks) * 0.10))
        top_keystone_ids = set(nid for nid, _ in sorted_ranks[:top_count])

        for nid, data in G.nodes(data=True):
            data["pagerank"] = round(pagerank_scores.get(nid, 0), 4)
            data["is_keystone"] = nid in top_keystone_ids

        keystones = [
            {"id": nid, "score": round(score, 4), "label": G.nodes[nid].get("label", nid)}
            for nid, score in sorted_ranks[:5]
        ]

    # 8. Circular Dependency Detection (Tarjan's SCC Algorithm - O(V + E) Linear Time)
    circular_cycles = []
    try:
        sccs = [c for c in nx.strongly_connected_components(G) if len(c) > 1]
        for scc in sccs[:10]:
            files_in_scc = {G.nodes[n].get("file") for n in scc if G.has_node(n)}
            if len(files_in_scc) >= 2:
                circular_cycles.append([G.nodes[n].get("label", n) for n in list(scc)[:6]])
                for n in scc:
                    if G.has_node(n):
                        G.nodes[n]["has_circular_dependency"] = True
    except Exception:
        pass

    metadata = {
        "keystones": keystones,
        "circular_dependencies": circular_cycles,
    }

    return G, unresolved, metadata


def graph_to_json(G: nx.DiGraph) -> Dict[str, Any]:
    nodes = []
    for node_id, data in G.nodes(data=True):
        # CodeScene Hotspot Score: Complexity * log2(Churn + 1)
        complexity = data.get("complexity", 1)
        churn = data.get("change_frequency", 0)
        hotspot_score = round(complexity * math.log2(churn + 1), 2) if churn > 0 else 0.0

        node_obj = {
            "id": node_id,
            "label": data.get("label", node_id),
            "kind": data.get("kind", "function"),
            "file": data.get("file", ""),
            "hotspot_score": hotspot_score,
            **{k: v for k, v in data.items() if k not in ("id", "label", "kind", "file", "hotspot_score")},
        }
        nodes.append(node_obj)

    edges = []
    for s, t, data in G.edges(data=True):
        edge_obj = {
            "source": s,
            "target": t,
            "type": data.get("type", "calls"),
            "weight": data.get("weight", 1),
        }
        edges.append(edge_obj)

    return {"nodes": nodes, "edges": edges}
