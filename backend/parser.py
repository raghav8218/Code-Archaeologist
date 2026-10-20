import ast
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    from tree_sitter import Language, Parser
    import tree_sitter_javascript as tsjs
    _JS_LANGUAGE = Language(tsjs.language())
    _JS_PARSER = Parser(_JS_LANGUAGE)
    _HAS_TREE_SITTER_JS = True
except Exception:
    _HAS_TREE_SITTER_JS = False

IGNORE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__",
    "dist", "build", "env", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    ".tox", ".nox", "site-packages", "docs_src", "docs", "doc", "documentation",
    "tests", "test", "testing", "fixtures", "examples", "benchmarks", "benchmark",
    "migrations", "alembic", ".next", ".nuxt", "out", "coverage", ".turbo",
    "ci", "scripts", "tools", "asv_bench", "vendor", "bin"
}

MINIMAL_IGNORE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__",
    "dist", "build", "env", ".pytest_cache", ".next", "out"
}

ROUTE_MARKERS = (
    ".route(", ".get(", ".post(", ".put(", ".delete(", ".patch(",
    ".options(", ".head(", ".api_route(",
    "@app.", "@router.", "@blueprint.", "@api."
)

SUPPORTED_EXTENSIONS = (
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"
)


def list_source_files(repo_path: str, extensions=SUPPORTED_EXTENSIONS) -> List[str]:
    files = []
    for root, dirs, filenames in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d.lower() not in IGNORE_DIRS and not d.startswith(".")]
        for fname in filenames:
            if Path(fname).suffix.lower() in extensions:
                files.append(os.path.join(root, fname))

    # If aggressive filtering removed all files, fallback to minimal ignore
    if not files:
        for root, dirs, filenames in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d.lower() not in MINIMAL_IGNORE_DIRS]
            for fname in filenames:
                if Path(fname).suffix.lower() in extensions:
                    files.append(os.path.join(root, fname))

    return sorted(files)


def compute_cyclomatic_complexity(node: ast.AST) -> int:
    """McCabe Cyclomatic Complexity calculation from Python AST."""
    complexity = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.IfExp, ast.While, ast.For, ast.AsyncFor,
                              ast.ExceptHandler, ast.With, ast.AsyncWith, ast.Assert)):
            complexity += 1
        elif isinstance(child, ast.BoolOp):
            complexity += max(0, len(child.values) - 1)
        elif isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            complexity += len(child.generators)
            for gen in child.generators:
                complexity += len(gen.ifs)
    return complexity


def is_route_decorator(dec_str: str) -> bool:
    return any(marker in dec_str for marker in ROUTE_MARKERS)


def extract_decorator_str(dec_node: ast.AST) -> str:
    try:
        return "@" + ast.unparse(dec_node)
    except Exception:
        return "@unknown"


def extract_signature(node: ast.AST, source_lines: List[str]) -> str:
    """Extract clean definition signature."""
    try:
        start_line = getattr(node, "lineno", 1) - 1
        sig_parts = []
        for i in range(start_line, min(len(source_lines), start_line + 8)):
            line = source_lines[i].strip()
            if line.startswith("@"):
                continue
            sig_parts.append(line)
            if line.endswith(":"):
                break
        if sig_parts:
            return " ".join(sig_parts)
    except Exception:
        pass

    if isinstance(node, ast.ClassDef):
        bases_str = f"({', '.join(ast.unparse(b) for b in node.bases)})" if node.bases else ""
        return f"class {node.name}{bases_str}:"
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
        try:
            args_str = ast.unparse(node.args)
        except Exception:
            args_str = "..."
        returns_str = f" -> {ast.unparse(node.returns)}" if getattr(node, "returns", None) else ""
        return f"{prefix}{node.name}({args_str}){returns_str}:"
    return "symbol"


class FileSymbolVisitor(ast.NodeVisitor):
    def __init__(self, rel_path: str, source_text: str, source_lines: List[str]):
        self.rel_path = rel_path.replace("\\", "/")
        self.source_text = source_text
        self.source_lines = source_lines
        self.classes: List[Dict[str, Any]] = []
        self.functions: List[Dict[str, Any]] = []
        self.calls: List[Dict[str, Any]] = []
        self.imports: List[Dict[str, Any]] = []
        self.constants: List[Dict[str, Any]] = []

        self.class_stack: List[str] = []
        self.scope_stack: List[str] = []

        # PyCG-inspired Alias & Instance Assignment Tables
        self.import_alias_map: Dict[str, str] = {}
        self.instance_assignment_map: Dict[str, str] = {}

    def get_source_slice(self, start_line: int, end_line: int) -> str:
        s = max(0, start_line - 1)
        e = min(len(self.source_lines), end_line)
        return "\n".join(self.source_lines[s:e])

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            alias_name = alias.asname or alias.name
            self.import_alias_map[alias_name] = alias.name
            self.imports.append({
                "text": f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else ""),
                "module": alias.name,
                "name": alias_name,
                "file": self.rel_path,
                "line": node.lineno,
            })
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = ("." * node.level) + (node.module or "")
        for alias in node.names:
            alias_name = alias.asname or alias.name
            full_origin = f"{module}.{alias.name}" if module else alias.name
            self.import_alias_map[alias_name] = full_origin
            self.import_alias_map[alias.name] = full_origin
            self.imports.append({
                "text": f"from {module} import {alias.name}" + (f" as {alias.asname}" if alias.asname else ""),
                "module": module,
                "name": alias_name,
                "source_name": alias.name,
                "file": self.rel_path,
                "line": node.lineno,
            })
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        # 1. Track instance assignments (e.g. service = AuthService()) for PyCG precision
        if isinstance(node.value, ast.Call):
            callee_class = ""
            if isinstance(node.value.func, ast.Name):
                callee_class = node.value.func.id
            elif isinstance(node.value.func, ast.Attribute):
                callee_class = node.value.func.attr

            if callee_class:
                if callee_class in self.import_alias_map:
                    callee_class = self.import_alias_map[callee_class]
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.instance_assignment_map[target.id] = callee_class

        # 2. Top-level constants (outside any class or function)
        if not self.class_stack and not self.scope_stack:
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper() and len(target.id) > 1:
                    src = self.get_source_slice(node.lineno, getattr(node, "end_lineno", node.lineno))
                    self.constants.append({
                        "name": target.id,
                        "file": self.rel_path,
                        "line": node.lineno,
                        "source": src.strip(),
                    })
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        cname = node.name
        qname = ".".join(self.class_stack + [cname]) if self.class_stack else cname
        bases = []
        for b in node.bases:
            try:
                base_name = ast.unparse(b)
                bases.append(self.import_alias_map.get(base_name, base_name))
            except Exception:
                bases.append("UnknownBase")

        decorators = [extract_decorator_str(d) for d in node.decorator_list]
        start_line = node.lineno
        end_line = getattr(node, "end_lineno", start_line)
        loc = max(1, end_line - start_line + 1)
        docstring = ast.get_docstring(node) or ""
        source = self.get_source_slice(start_line, end_line)
        complexity = compute_cyclomatic_complexity(node)
        signature = extract_signature(node, self.source_lines)

        class_id = f"cls_{qname}"

        cls_record = {
            "id": class_id,
            "raw_id": f"{self.rel_path}::{qname}",
            "name": cname,
            "label": cname,
            "qualified_name": qname,
            "kind": "class",
            "file": self.rel_path,
            "start_line": start_line,
            "end_line": end_line,
            "loc": loc,
            "complexity": complexity,
            "bases": bases,
            "decorators": decorators,
            "docstring": docstring,
            "signature": signature,
            "source": source,
            "methods": [],
        }
        self.classes.append(cls_record)

        self.class_stack.append(cname)
        self.scope_stack.append(class_id)

        for item in node.body:
            self.visit(item)

        self.scope_stack.pop()
        self.class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._handle_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._handle_function(node, is_async=True)

    def _handle_function(self, node: Any, is_async: bool = False):
        fname = node.name
        is_in_class = bool(self.class_stack)
        parent_class = self.class_stack[-1] if is_in_class else None
        qname = f"{parent_class}.{fname}" if is_in_class else fname

        decorators = [extract_decorator_str(d) for d in node.decorator_list]
        is_route = any(is_route_decorator(d) for d in decorators)

        if is_in_class:
            kind = "method"
        elif is_route:
            kind = "route"
        else:
            kind = "function"

        fn_id = f"fn_{qname.replace('.', '_')}"
        legacy_id = f"{self.rel_path}::{qname}"

        start_line = node.lineno
        end_line = getattr(node, "end_lineno", start_line)
        loc = max(1, end_line - start_line + 1)
        docstring = ast.get_docstring(node) or ""
        source = self.get_source_slice(start_line, end_line)
        complexity = compute_cyclomatic_complexity(node)
        signature = extract_signature(node, self.source_lines)

        try:
            params_str = f"({ast.unparse(node.args)})"
        except Exception:
            params_str = "()"

        label = f"{fname}()"
        class_id = f"cls_{parent_class}" if parent_class else None

        fn_record = {
            "id": fn_id,
            "raw_id": legacy_id,
            "legacy_id": legacy_id,
            "name": fname,
            "label": label,
            "qualified_name": qname,
            "kind": kind,
            "classId": class_id,
            "className": parent_class,
            "class": parent_class,
            "file": self.rel_path,
            "start_line": start_line,
            "end_line": end_line,
            "loc": loc,
            "complexity": complexity,
            "is_route": is_route,
            "is_async": is_async,
            "decorators": decorators,
            "signature": signature,
            "params": params_str,
            "docstring": docstring,
            "source": source,
        }
        self.functions.append(fn_record)

        if is_in_class and self.classes:
            self.classes[-1]["methods"].append(fn_id)

        self.scope_stack.append(fn_id)
        for item in node.body:
            self.visit(item)
        self.scope_stack.pop()

    def visit_Call(self, node: ast.Call):
        if self.scope_stack:
            caller = self.scope_stack[-1]
            callee_name = ""
            qualifier = ""

            if isinstance(node.func, ast.Name):
                callee_name = node.func.id
                if callee_name in self.import_alias_map:
                    callee_name = self.import_alias_map[callee_name]
            elif isinstance(node.func, ast.Attribute):
                callee_name = node.func.attr
                if isinstance(node.func.value, ast.Name):
                    qualifier = node.func.value.id
                    if qualifier in self.instance_assignment_map:
                        qualifier = self.instance_assignment_map[qualifier]
                    elif qualifier in self.import_alias_map:
                        qualifier = self.import_alias_map[qualifier]
            elif isinstance(node.func, ast.Call):
                if isinstance(node.func.func, ast.Name):
                    callee_name = node.func.func.id
                elif isinstance(node.func.func, ast.Attribute):
                    callee_name = node.func.func.attr

            if callee_name:
                self.calls.append({
                    "caller": caller,
                    "callee_name": callee_name,
                    "qualifier": qualifier,
                    "line": node.lineno,
                    "file": self.rel_path,
                })
        self.generic_visit(node)


def extract_python_file(file_path: str, repo_root: str) -> Dict[str, Any]:
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        source_text = f.read()

    source_lines = source_text.splitlines()
    rel_path = os.path.relpath(file_path, repo_root).replace("\\", "/")

    try:
        tree = ast.parse(source_text, filename=rel_path)
    except SyntaxError:
        return {
            "functions": [], "calls": [], "imports": [],
            "classes": [], "constants": [], "file": rel_path
        }

    visitor = FileSymbolVisitor(rel_path, source_text, source_lines)
    visitor.visit(tree)

    return {
        "functions": visitor.functions,
        "calls": visitor.calls,
        "imports": visitor.imports,
        "classes": visitor.classes,
        "constants": visitor.constants,
        "file": rel_path,
    }


def compute_js_complexity(node, source_bytes: bytes) -> int:
    """McCabe Cyclomatic Complexity calculation for JavaScript Tree-Sitter nodes."""
    complexity = 1
    branch_types = {
        "if_statement", "while_statement", "for_statement", "for_in_statement",
        "catch_clause", "ternary_expression", "switch_case"
    }

    def walk_node(curr):
        nonlocal complexity
        if curr.type in branch_types:
            complexity += 1
        elif curr.type == "binary_expression":
            op = source_bytes[curr.children[1].start_byte:curr.children[1].end_byte].decode("utf-8", "ignore") if len(curr.children) > 1 else ""
            if op in ("&&", "||", "??"):
                complexity += 1
        for c in curr.children:
            walk_node(c)

    walk_node(node)
    return complexity


def extract_javascript_file(file_path: str, repo_root: str) -> Dict[str, Any]:
    """Extracts symbols, classes, routes, and calls from JS/TS using Tree-Sitter."""
    if not _HAS_TREE_SITTER_JS:
        return {"functions": [], "calls": [], "imports": [], "classes": [], "constants": [], "file": ""}

    with open(file_path, "rb") as f:
        source_bytes = f.read()

    source_text = source_bytes.decode("utf-8", errors="ignore")
    source_lines = source_text.splitlines()
    rel_path = os.path.relpath(file_path, repo_root).replace("\\", "/")

    try:
        tree = _JS_PARSER.parse(source_bytes)
    except Exception:
        return {"functions": [], "calls": [], "imports": [], "classes": [], "constants": [], "file": rel_path}

    functions: List[Dict[str, Any]] = []
    classes: List[Dict[str, Any]] = []
    calls: List[Dict[str, Any]] = []
    imports: List[Dict[str, Any]] = []
    constants: List[Dict[str, Any]] = []

    scope_stack: List[str] = []
    class_stack: List[str] = []

    def get_slice(start_line: int, end_line: int) -> str:
        s = max(0, start_line - 1)
        e = min(len(source_lines), end_line)
        return "\n".join(source_lines[s:e])

    def traverse(node):
        ntype = node.type

        # 1. Imports (ES6 import & CommonJS require)
        if ntype == "import_statement":
            src = source_bytes[node.start_byte:node.end_byte].decode("utf-8", "ignore").strip()
            imports.append({
                "text": src,
                "module": src.split("from")[-1].replace("'", "").replace('"', '').replace(';', '').strip(),
                "file": rel_path,
                "line": node.start_point[0] + 1,
            })

        # 2. Classes
        elif ntype == "class_declaration":
            cname = ""
            for child in node.children:
                if child.type == "identifier":
                    cname = source_bytes[child.start_byte:child.end_byte].decode("utf-8", "ignore")
                    break
            if cname:
                start_l = node.start_point[0] + 1
                end_l = node.end_point[0] + 1
                class_id = f"cls_{cname}"
                cls_rec = {
                    "id": class_id,
                    "raw_id": f"{rel_path}::{cname}",
                    "name": cname,
                    "label": cname,
                    "qualified_name": cname,
                    "kind": "class",
                    "file": rel_path,
                    "start_line": start_l,
                    "end_line": end_l,
                    "loc": max(1, end_l - start_l + 1),
                    "complexity": compute_js_complexity(node, source_bytes),
                    "signature": f"class {cname}",
                    "source": get_slice(start_l, end_l),
                    "methods": [],
                }
                classes.append(cls_rec)
                class_stack.append(cname)
                scope_stack.append(class_id)
                for c in node.children:
                    traverse(c)
                scope_stack.pop()
                class_stack.pop()
                return

        # 3. Functions & Methods
        elif ntype in ("function_declaration", "method_definition", "arrow_function"):
            fname = ""
            if ntype == "function_declaration":
                for child in node.children:
                    if child.type == "identifier":
                        fname = source_bytes[child.start_byte:child.end_byte].decode("utf-8", "ignore")
                        break
            elif ntype == "method_definition":
                for child in node.children:
                    if child.type == "property_identifier":
                        fname = source_bytes[child.start_byte:child.end_byte].decode("utf-8", "ignore")
                        break
            elif ntype == "arrow_function":
                # Check if parent is variable_declarator: const myFn = () => {}
                parent = node.parent
                if parent and parent.type == "variable_declarator":
                    for c in parent.children:
                        if c.type == "identifier":
                            fname = source_bytes[c.start_byte:c.end_byte].decode("utf-8", "ignore")
                            break

            if fname:
                parent_cls = class_stack[-1] if class_stack else None
                qname = f"{parent_cls}.{fname}" if parent_cls else fname
                start_l = node.start_point[0] + 1
                end_l = node.end_point[0] + 1
                is_in_class = bool(parent_cls)
                fn_id = f"fn_{qname.replace('.', '_')}"

                # Detect route handlers in Express / Next
                node_text = source_bytes[node.start_byte:min(node.start_byte + 200, node.end_byte)].decode("utf-8", "ignore")
                is_route = any(m in node_text for m in ("req", "res", "next", "Response", "Request"))

                fn_rec = {
                    "id": fn_id,
                    "raw_id": f"{rel_path}::{qname}",
                    "name": fname,
                    "label": f"{fname}()",
                    "qualified_name": qname,
                    "kind": "method" if is_in_class else ("route" if is_route else "function"),
                    "classId": f"cls_{parent_cls}" if parent_cls else None,
                    "className": parent_cls,
                    "file": rel_path,
                    "start_line": start_l,
                    "end_line": end_l,
                    "loc": max(1, end_l - start_l + 1),
                    "complexity": compute_js_complexity(node, source_bytes),
                    "is_route": is_route,
                    "signature": f"function {fname}()",
                    "source": get_slice(start_l, end_l),
                }
                functions.append(fn_rec)
                if is_in_class and classes:
                    classes[-1]["methods"].append(fn_id)

                scope_stack.append(fn_id)
                for c in node.children:
                    traverse(c)
                scope_stack.pop()
                return

        # 4. Calls
        elif ntype == "call_expression" and scope_stack:
            caller = scope_stack[-1]
            func_node = node.children[0] if node.children else None
            callee_name = ""
            if func_node:
                if func_node.type == "identifier":
                    callee_name = source_bytes[func_node.start_byte:func_node.end_byte].decode("utf-8", "ignore")
                elif func_node.type == "member_expression":
                    for c in func_node.children:
                        if c.type == "property_identifier":
                            callee_name = source_bytes[c.start_byte:c.end_byte].decode("utf-8", "ignore")
            if callee_name:
                calls.append({
                    "caller": caller,
                    "callee_name": callee_name,
                    "line": node.start_point[0] + 1,
                    "file": rel_path,
                })

        for child in node.children:
            traverse(child)

    traverse(tree.root_node)

    return {
        "functions": functions,
        "classes": classes,
        "calls": calls,
        "imports": imports,
        "constants": constants,
        "file": rel_path,
    }


def extract_repo(repo_path: str, extensions=SUPPORTED_EXTENSIONS) -> Dict[str, Any]:
    files = list_source_files(repo_path, extensions)
    all_functions: List[Dict[str, Any]] = []
    all_calls: List[Dict[str, Any]] = []
    all_imports: List[Dict[str, Any]] = []
    all_classes: List[Dict[str, Any]] = []
    all_constants: List[Dict[str, Any]] = []

    id_counts: Dict[str, int] = {}

    for f in files:
        ext = Path(f).suffix.lower()
        try:
            if ext == ".py":
                result = extract_python_file(f, repo_path)
            elif ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"):
                result = extract_javascript_file(f, repo_path)
            else:
                continue
        except Exception:
            continue

        for cls in result["classes"]:
            base_id = cls["id"]
            if base_id in id_counts:
                id_counts[base_id] += 1
                cls["id"] = f"{base_id}_{id_counts[base_id]}"
            else:
                id_counts[base_id] = 1
            all_classes.append(cls)

        for fn in result["functions"]:
            base_id = fn["id"]
            if base_id in id_counts:
                id_counts[base_id] += 1
                fn["id"] = f"{base_id}_{id_counts[base_id]}"
            else:
                id_counts[base_id] = 1
            all_functions.append(fn)

        all_calls.extend(result["calls"])
        all_imports.extend(result["imports"])
        all_constants.extend(result["constants"])

    return {
        "functions": all_functions,
        "calls": all_calls,
        "imports": all_imports,
        "classes": all_classes,
        "constants": all_constants,
        "files": [os.path.relpath(f, repo_path).replace("\\", "/") for f in files],
    }


def extract_from_in_memory_files(files_dict: Dict[str, str]) -> Dict[str, Any]:
    """
    Parses Python and JS/TS syntax trees directly from an in-memory dictionary of source code.
    Zero disk reads or temporary files required!
    """
    all_functions: List[Dict[str, Any]] = []
    all_calls: List[Dict[str, Any]] = []
    all_imports: List[Dict[str, Any]] = []
    all_classes: List[Dict[str, Any]] = []
    all_constants: List[Dict[str, Any]] = []

    id_counts: Dict[str, int] = {}

    for rel_path, source_text in files_dict.items():
        ext = Path(rel_path).suffix.lower()
        result = None

        if ext == ".py":
            source_lines = source_text.splitlines()
            try:
                tree = ast.parse(source_text, filename=rel_path)
            except SyntaxError:
                continue
            visitor = FileSymbolVisitor(rel_path, source_text, source_lines)
            visitor.visit(tree)
            result = {
                "functions": visitor.functions,
                "calls": visitor.calls,
                "imports": visitor.imports,
                "classes": visitor.classes,
                "constants": visitor.constants,
                "file": rel_path,
            }
        elif ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs") and _HAS_TREE_SITTER_JS:
            try:
                source_bytes = source_text.encode("utf-8")
                tree = _JS_PARSER.parse(source_bytes)

                classes = []
                functions = []
                calls = []
                imports = []
                constants = []
                scope_stack = []
                class_stack = []

                source_lines = source_text.splitlines()

                def get_slice(start, end):
                    return "\n".join(source_lines[start - 1:end])

                def traverse(node):
                    ntype = node.type
                    if ntype == "class_declaration":
                        cname = ""
                        for c in node.children:
                            if c.type == "identifier":
                                cname = source_bytes[c.start_byte:c.end_byte].decode("utf-8", "ignore")
                                break
                        if cname:
                            cls_id = f"cls_{cname}"
                            start_l = node.start_point[0] + 1
                            end_l = node.end_point[0] + 1
                            classes.append({
                                "id": cls_id,
                                "raw_id": f"{rel_path}::{cname}",
                                "name": cname,
                                "label": cname,
                                "qualified_name": cname,
                                "kind": "class",
                                "file": rel_path,
                                "start_line": start_l,
                                "end_line": end_l,
                                "loc": max(1, end_l - start_l + 1),
                                "methods": [],
                                "bases": [],
                                "signature": f"class {cname}",
                                "source": get_slice(start_l, end_l),
                            })
                            class_stack.append(cname)
                            for c in node.children:
                                traverse(c)
                            class_stack.pop()
                            return

                    elif ntype in ("function_declaration", "method_definition", "arrow_function"):
                        fname = ""
                        if ntype == "function_declaration":
                            for c in node.children:
                                if c.type == "identifier":
                                    fname = source_bytes[c.start_byte:c.end_byte].decode("utf-8", "ignore")
                                    break
                        elif ntype == "method_definition":
                            for c in node.children:
                                if c.type == "property_identifier":
                                    fname = source_bytes[c.start_byte:c.end_byte].decode("utf-8", "ignore")
                                    break
                        elif ntype == "arrow_function":
                            p = node.parent
                            if p and p.type == "variable_declarator":
                                for c in p.children:
                                    if c.type == "identifier":
                                        fname = source_bytes[c.start_byte:c.end_byte].decode("utf-8", "ignore")
                                        break
                        if fname:
                            parent_cls = class_stack[-1] if class_stack else None
                            qname = f"{parent_cls}.{fname}" if parent_cls else fname
                            start_l = node.start_point[0] + 1
                            end_l = node.end_point[0] + 1
                            is_in_class = bool(parent_cls)
                            fn_id = f"fn_{qname.replace('.', '_')}"
                            node_text = source_bytes[node.start_byte:min(node.start_byte + 200, node.end_byte)].decode("utf-8", "ignore")
                            is_route = any(m in node_text for m in ("req", "res", "next", "Response", "Request"))

                            fn_rec = {
                                "id": fn_id,
                                "raw_id": f"{rel_path}::{qname}",
                                "name": fname,
                                "label": f"{fname}()",
                                "qualified_name": qname,
                                "kind": "method" if is_in_class else ("route" if is_route else "function"),
                                "classId": f"cls_{parent_cls}" if parent_cls else None,
                                "className": parent_cls,
                                "file": rel_path,
                                "start_line": start_l,
                                "end_line": end_l,
                                "loc": max(1, end_l - start_l + 1),
                                "complexity": compute_js_complexity(node, source_bytes),
                                "is_route": is_route,
                                "signature": f"function {fname}()",
                                "source": get_slice(start_l, end_l),
                            }
                            functions.append(fn_rec)
                            if is_in_class and classes:
                                classes[-1]["methods"].append(fn_id)

                            scope_stack.append(fn_id)
                            for c in node.children:
                                traverse(c)
                            scope_stack.pop()
                            return

                    elif ntype == "call_expression" and scope_stack:
                        caller = scope_stack[-1]
                        fnode = node.children[0] if node.children else None
                        cname = ""
                        if fnode:
                            if fnode.type == "identifier":
                                cname = source_bytes[fnode.start_byte:fnode.end_byte].decode("utf-8", "ignore")
                            elif fnode.type == "member_expression":
                                for c in fnode.children:
                                    if c.type == "property_identifier":
                                        cname = source_bytes[c.start_byte:c.end_byte].decode("utf-8", "ignore")
                        if cname:
                            calls.append({
                                "caller": caller,
                                "callee_name": cname,
                                "line": node.start_point[0] + 1,
                                "file": rel_path,
                            })

                    for c in node.children:
                        traverse(c)

                traverse(tree.root_node)
                result = {
                    "functions": functions,
                    "classes": classes,
                    "calls": calls,
                    "imports": imports,
                    "constants": constants,
                    "file": rel_path,
                }
            except Exception:
                continue

        if not result:
            continue

        for cls in result["classes"]:
            base_id = cls["id"]
            if base_id in id_counts:
                id_counts[base_id] += 1
                cls["id"] = f"{base_id}_{id_counts[base_id]}"
            else:
                id_counts[base_id] = 1
            all_classes.append(cls)

        for fn in result["functions"]:
            base_id = fn["id"]
            if base_id in id_counts:
                id_counts[base_id] += 1
                fn["id"] = f"{base_id}_{id_counts[base_id]}"
            else:
                id_counts[base_id] = 1
            all_functions.append(fn)

        all_calls.extend(result["calls"])
        all_imports.extend(result["imports"])
        all_constants.extend(result["constants"])

    return {
        "functions": all_functions,
        "calls": all_calls,
        "imports": all_imports,
        "classes": all_classes,
        "constants": all_constants,
        "files": sorted(list(files_dict.keys())),
    }
