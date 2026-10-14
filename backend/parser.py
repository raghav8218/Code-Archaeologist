import ast
import os
import re
from pathlib import Path
from typing import Dict, List, Any, Optional

IGNORE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__",
    "dist", "build", "env", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    ".tox", ".nox", "site-packages", "docs_src", "docs", "documentation",
    "tests", "test", "testing", "fixtures", "examples", "benchmarks", "benchmark"
}

MINIMAL_IGNORE_DIRS = {
    ".git", "node_modules", "venv", ".venv", "__pycache__",
    "dist", "build", "env", ".pytest_cache"
}

ROUTE_MARKERS = (
    ".route(", ".get(", ".post(", ".put(", ".delete(", ".patch(",
    ".options(", ".head(", ".api_route(",
    "@app.", "@router.", "@blueprint.", "@api."
)


def list_source_files(repo_path: str, extensions=(".py",)) -> List[str]:
    files = []
    for root, dirs, filenames in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d.lower() not in IGNORE_DIRS and not d.startswith(".")]
        for fname in filenames:
            if Path(fname).suffix in extensions:
                files.append(os.path.join(root, fname))
    
    # If filtering removed all files (e.g. a repo whose only python code is in examples or tests), fallback
    if not files:
        for root, dirs, filenames in os.walk(repo_path):
            dirs[:] = [d for d in dirs if d.lower() not in MINIMAL_IGNORE_DIRS]
            for fname in filenames:
                if Path(fname).suffix in extensions:
                    files.append(os.path.join(root, fname))

    return sorted(files)


def compute_cyclomatic_complexity(node: ast.AST) -> int:
    """McCabe Cyclomatic Complexity calculation from AST."""
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
        end_line = getattr(node, "end_lineno", start_line + 1)
        
        # Look for def/class line(s) ending with ':'
        sig_parts = []
        for i in range(start_line, min(len(source_lines), start_line + 8)):
            line = source_lines[i].strip()
            # Skip decorators
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

    def get_source_slice(self, start_line: int, end_line: int) -> str:
        s = max(0, start_line - 1)
        e = min(len(self.source_lines), end_line)
        return "\n".join(self.source_lines[s:e])

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.imports.append({
                "text": f"import {alias.name}" + (f" as {alias.asname}" if alias.asname else ""),
                "module": alias.name,
                "name": alias.asname or alias.name,
                "file": self.rel_path,
                "line": node.lineno,
            })
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = ("." * node.level) + (node.module or "")
        for alias in node.names:
            self.imports.append({
                "text": f"from {module} import {alias.name}" + (f" as {alias.asname}" if alias.asname else ""),
                "module": module,
                "name": alias.asname or alias.name,
                "source_name": alias.name,
                "file": self.rel_path,
                "line": node.lineno,
            })
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        # Top-level constants (outside any class or function)
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
                bases.append(ast.unparse(b))
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
            "methods": [],  # Will be populated during child visit
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
            # Add to current class methods list
            self.classes[-1]["methods"].append(fn_id)

        self.scope_stack.append(fn_id)
        for item in node.body:
            self.visit(item)
        self.scope_stack.pop()

    def visit_Call(self, node: ast.Call):
        if self.scope_stack:
            caller = self.scope_stack[-1]
            callee_name = ""
            if isinstance(node.func, ast.Name):
                callee_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                callee_name = node.func.attr
            elif isinstance(node.func, ast.Call):
                # Chained calls e.g. foo()()
                if isinstance(node.func.func, ast.Name):
                    callee_name = node.func.func.id
                elif isinstance(node.func.func, ast.Attribute):
                    callee_name = node.func.func.attr

            if callee_name:
                self.calls.append({
                    "caller": caller,
                    "callee_name": callee_name,
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
        # Fall back to empty or partial if syntax error
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


def extract_repo(repo_path: str, extensions=(".py",)) -> Dict[str, Any]:
    files = list_source_files(repo_path, extensions)
    all_functions: List[Dict[str, Any]] = []
    all_calls: List[Dict[str, Any]] = []
    all_imports: List[Dict[str, Any]] = []
    all_classes: List[Dict[str, Any]] = []
    all_constants: List[Dict[str, Any]] = []

    # Map name collisions if necessary
    id_counts: Dict[str, int] = {}

    for f in files:
        try:
            result = extract_python_file(f, repo_path)
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
