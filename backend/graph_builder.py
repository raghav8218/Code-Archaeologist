"""
Turns extracted functions + raw call sites into a networkx call graph.

Call resolution is name-based and heuristic, not full type-aware resolution
(that would require a real type checker). When a call's name matches more
than one function in the repo, we prefer a same-file match; otherwise we
link to every candidate. This is stated as a known limitation, not hidden.
"""

import networkx as nx


def build_graph(extracted):
    G = nx.DiGraph()
    functions = extracted["functions"]
    calls = extracted["calls"]

    name_index = {}
    for fn in functions:
        node_attrs = {k: v for k, v in fn.items() if k != "source"}
        G.add_node(fn["id"], type="function", **node_attrs)
        name_index.setdefault(fn["name"], []).append(fn["id"])

    unresolved = []
    for call in calls:
        caller = call["caller"]
        callee_name = call["callee_name"]
        candidates = name_index.get(callee_name, [])

        if not candidates:
            unresolved.append(call)
            continue

        same_file = [c for c in candidates if c.split("::")[0] == caller.split("::")[0]]
        targets = same_file if same_file else candidates

        for target in targets:
            if target == caller:
                continue
            if G.has_edge(caller, target):
                G[caller][target]["weight"] += 1
            else:
                G.add_edge(caller, target, type="calls", weight=1)

    return G, unresolved


def graph_to_json(G):
    nodes = [{"id": node_id, **data} for node_id, data in G.nodes(data=True)]
    edges = [{"source": s, "target": t, **data} for s, t, data in G.edges(data=True)]
    return {"nodes": nodes, "edges": edges}
