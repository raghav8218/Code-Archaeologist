"""
Turns extracted classes, functions, methods, imports, and calls into a compound graph.

Format:
{
  "nodes": [
    { "id": "cls_Parser", "label": "CodeParser", "kind": "class", "file": "backend/parser.py", "methods": ["fn_parse", "fn_extract"] },
    { "id": "fn_parse", "label": "parse()", "kind": "method", "classId": "cls_Parser", "file": "backend/parser.py" }
  ],
  "edges": [
    { "source": "fn_main", "target": "cls_Parser", "type": "instantiates" },
    { "source": "cls_Parser", "target": "fn_parse", "type": "contains" },
    { "source": "fn_parse", "target": "fn_extract", "type": "calls" }
  ]
}
"""

from typing import Dict, List, Any, Tuple
import networkx as nx


def build_graph(extracted: Dict[str, Any]) -> Tuple[nx.DiGraph, List[Dict[str, Any]]]:
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
    for fn in functions:
        func_by_name.setdefault(fn["name"], []).append(fn)
        func_by_id[fn["id"]] = fn

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
            base_candidates = class_by_name.get(base, [])
            if base_candidates:
                # Same file preferred
                same_file = [c for c in base_candidates if c["file"] == cls["file"]]
                target = same_file[0] if same_file else base_candidates[0]
                G.add_edge(cls["id"], target["id"], type="inherits", weight=1)

    # 5. Resolve calls: calls, instantiates, or external utility
    unresolved = []
    external_call_counts: Dict[str, int] = {}
    external_calls_map: List[Tuple[str, str]] = []

    for call in calls:
        caller = call["caller"]
        callee_name = call["callee_name"]

        if not G.has_node(caller):
            continue

        caller_node = G.nodes[caller]
        caller_file = caller_node.get("file", "")

        # Check if callee is a Class (Instantiates)
        if callee_name in class_by_name:
            candidates = class_by_name[callee_name]
            same_file = [c for c in candidates if c["file"] == caller_file]
            target_cls = same_file[0] if same_file else candidates[0]

            if G.has_edge(caller, target_cls["id"]):
                G[caller][target_cls["id"]]["weight"] += 1
            else:
                G.add_edge(caller, target_cls["id"], type="instantiates", weight=1)
            continue

        # Check if callee is a Function/Method (Calls)
        if callee_name in func_by_name:
            candidates = func_by_name[callee_name]
            same_file = [f for f in candidates if f["file"] == caller_file]
            target_fn = same_file[0] if same_file else candidates[0]

            if target_fn["id"] == caller:
                continue

            if G.has_edge(caller, target_fn["id"]):
                G[caller][target_fn["id"]]["weight"] += 1
            else:
                G.add_edge(caller, target_fn["id"], type="calls", weight=1)
            continue

        # Otherwise it's unresolved or an external library call
        unresolved.append(call)
        if len(callee_name) > 1 and not callee_name.startswith("_"):
            external_call_counts[callee_name] = external_call_counts.get(callee_name, 0) + 1
            external_calls_map.append((caller, callee_name))

    # Filter out generic python / ORM method names from external utility nodes
    # so we don't pollute the graph with generic dots like .get(), .first(), .add()
    GENERIC_METHODS = {
        "get", "post", "put", "delete", "first", "all", "filter", "filter_by",
        "add", "commit", "rollback", "lower", "upper", "strip", "split", "join",
        "replace", "find", "count", "items", "keys", "values", "pop", "append",
        "extend", "insert", "clear", "copy", "update", "format", "render",
        "execute", "close", "connect", "print", "len", "str", "int", "dict", "list", "set",
        "String", "Column", "Integer", "Boolean", "DateTime", "ForeignKey", "Text"
    }

    # Only prominent external utilities/services called frequently (e.g. requests, jwt, bcrypt)
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
        module = imp.get("module", "")
        imp_name = imp.get("name", "")

        # Try to find target file or symbol in repo
        target_node_id = None

        # Check if imported name matches a class
        if imp_name in class_by_name:
            candidates = class_by_name[imp_name]
            target_node_id = candidates[0]["id"]
        elif imp_name in func_by_name:
            candidates = func_by_name[imp_name]
            target_node_id = candidates[0]["id"]

        if target_node_id and imp_file in file_nodes:
            # Connect from the first symbol in the importing file
            for src_id in file_nodes[imp_file]:
                if not G.has_edge(src_id, target_node_id):
                    G.add_edge(src_id, target_node_id, type="imports", weight=1)
                break

    return G, unresolved


def graph_to_json(G: nx.DiGraph) -> Dict[str, Any]:
    nodes = []
    for node_id, data in G.nodes(data=True):
        # Format node ensuring required fields
        node_obj = {
            "id": node_id,
            "label": data.get("label", node_id),
            "kind": data.get("kind", "function"),
            "file": data.get("file", ""),
            **{k: v for k, v in data.items() if k not in ("id", "label", "kind", "file")},
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
