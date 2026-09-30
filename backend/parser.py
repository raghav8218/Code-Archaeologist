import os
from pathlib import Path

from tree_sitter import Language, Parser
import tree_sitter_python as tspython

PY_LANGUAGE = Language(tspython.language())

IGNORE_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build", "env"}

ROUTE_MARKERS = (".route(", ".get(", ".post(", ".put(", ".delete(", ".patch(")


def _make_parser():
    return Parser(PY_LANGUAGE)


def list_source_files(repo_path, extensions=(".py",)):
    files = []
    for root, dirs, filenames in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for fname in filenames:
            if Path(fname).suffix in extensions:
                files.append(os.path.join(root, fname))
    return files


def _is_route_decorator(text):
    return any(marker in text for marker in ROUTE_MARKERS)


def extract_python_file(file_path, repo_root):
    with open(file_path, "rb") as f:
        source = f.read()

    tree = _make_parser().parse(source)
    root = tree.root_node
    rel_path = os.path.relpath(file_path, repo_root)

    functions = []
    calls = []
    imports = []
    classes = []
    constants = []

    def node_text(node):
        return source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")

    def qualified(name, class_stack):
        return ".".join(class_stack + [name]) if class_stack else name

    def walk(node, class_stack, func_stack, pending_decorators=None):
        pending_decorators = pending_decorators or []

        if node.type in ("import_statement", "import_from_statement"):
            imports.append({"text": node_text(node), "line": node.start_point[0] + 1})
            return

        if node.type == "decorated_definition":
            decorators = [node_text(c) for c in node.children if c.type == "decorator"]
            for child in node.children:
                if child.type in ("function_definition", "class_definition"):
                    walk(child, class_stack, func_stack, decorators)
            return

        if node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            cname = node_text(name_node) if name_node else "UnknownClass"
            classes.append({
                "name": cname,
                "qualified_name": qualified(cname, class_stack),
                "file": rel_path,
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
            })
            for child in node.children:
                walk(child, class_stack + [cname], func_stack)
            return

        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            fname = node_text(name_node) if name_node else "unknown"
            qname = qualified(fname, class_stack)
            params_node = node.child_by_field_name("parameters")
            params = node_text(params_node) if params_node else "()"
            fn_id = f"{rel_path}::{qname}"

            functions.append({
                "id": fn_id,
                "name": fname,
                "qualified_name": qname,
                "file": rel_path,
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "params": params,
                "class": ".".join(class_stack) if class_stack else None,
                "decorators": pending_decorators,
                "is_route": any(_is_route_decorator(d) for d in pending_decorators),
                "source": node_text(node),
            })

            for child in node.children:
                walk(child, class_stack, func_stack + [fn_id])
            return

        if node.type == "call":
            func_node = node.child_by_field_name("function")
            if func_node is not None and func_stack:
                callee_text = node_text(func_node)
                callee_name = callee_text.split(".")[-1]
                calls.append({
                    "caller": func_stack[-1],
                    "callee_name": callee_name,
                    "line": node.start_point[0] + 1,
                })

        # Detect module-level constants (UPPER_CASE assignments at top level).
        # Only fires outside any class or function scope.
        if node.type == "assignment" and not class_stack and not func_stack:
            left = node.child_by_field_name("left")
            if left is None and node.children:
                left = node.children[0]
            if left and left.type == "identifier":
                const_name = node_text(left)
                if const_name.isupper() and len(const_name) > 1:
                    constants.append({
                        "name": const_name,
                        "file": rel_path,
                        "line": node.start_point[0] + 1,
                        "source": node_text(node).strip(),
                    })

        for child in node.children:
            walk(child, class_stack, func_stack, pending_decorators)

    walk(root, [], [])
    return {"functions": functions, "calls": calls, "imports": imports, "classes": classes, "constants": constants, "file": rel_path}


def extract_repo(repo_path, extensions=(".py",)):
    files = list_source_files(repo_path, extensions)
    all_functions, all_calls, all_imports = [], [], []
    all_classes, all_constants = [], []

    for f in files:
        try:
            result = extract_python_file(f, repo_path)
        except Exception:
            # Skip files that fail to parse (e.g. syntax errors, weird encodings)
            # rather than failing the whole analysis.
            continue
        all_functions.extend(result["functions"])
        all_calls.extend(result["calls"])
        for imp in result["imports"]:
            all_imports.append({**imp, "file": result["file"]})
        all_classes.extend(result.get("classes", []))
        all_constants.extend(result.get("constants", []))

    return {
        "functions": all_functions,
        "calls": all_calls,
        "imports": all_imports,
        "classes": all_classes,
        "constants": all_constants,
        "files": [os.path.relpath(f, repo_path) for f in files],
    }




