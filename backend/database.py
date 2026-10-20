import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Dict, Any, List, Optional

DB_DIR = Path(__file__).resolve().parent / "data"
DB_PATH = DB_DIR / "archaeologist.db"


def get_db_connection() -> sqlite3.Connection:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=20.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db():
    conn = get_db_connection()
    try:
        with conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS repositories (
                id TEXT PRIMARY KEY,
                repo_url TEXT NOT NULL,
                repo_name TEXT NOT NULL,
                branch TEXT NOT NULL,
                commit_sha TEXT,
                num_files INTEGER DEFAULT 0,
                num_functions INTEGER DEFAULT 0,
                num_classes INTEGER DEFAULT 0,
                unresolved_calls INTEGER DEFAULT 0,
                architectural_context TEXT DEFAULT '',
                commits_json TEXT DEFAULT '[]',
                file_change_freq_json TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_repos_url_branch ON repositories(repo_url, branch);

            CREATE TABLE IF NOT EXISTS graph_cache (
                repo_id TEXT PRIMARY KEY REFERENCES repositories(id) ON DELETE CASCADE,
                nodes_json TEXT NOT NULL,
                edges_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS symbols (
                repo_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
                id TEXT NOT NULL,
                raw_id TEXT,
                name TEXT NOT NULL,
                qualified_name TEXT,
                kind TEXT,
                file TEXT,
                start_line INTEGER,
                end_line INTEGER,
                loc INTEGER,
                complexity INTEGER,
                is_route INTEGER DEFAULT 0,
                is_async INTEGER DEFAULT 0,
                decorators_json TEXT DEFAULT '[]',
                signature TEXT,
                params TEXT,
                docstring TEXT,
                source TEXT,
                change_frequency INTEGER DEFAULT 0,
                history_json TEXT DEFAULT '[]',
                incoming_callers_json TEXT DEFAULT '[]',
                outgoing_dependencies_json TEXT DEFAULT '[]',
                PRIMARY KEY (repo_id, id)
            );

            CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(repo_id, file);
            CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(repo_id, name);
            CREATE INDEX IF NOT EXISTS idx_symbols_qname ON symbols(repo_id, qualified_name);

            CREATE TABLE IF NOT EXISTS qa_threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_id TEXT NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                highlighted_ids_json TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_qa_repo ON qa_threads(repo_id, created_at);
            """)
    finally:
        conn.close()


def normalize_repo_url(url: str) -> str:
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://") and not url.startswith("git@"):
        clean = url.strip("/")
        if len(clean.split("/")) == 2:
            return f"https://github.com/{clean}.git"
    if url.endswith("/"):
        url = url[:-1]
    return url


def find_cached_repo(repo_url: str, branch: Optional[str] = None) -> Optional[Dict[str, Any]]:
    norm_url = normalize_repo_url(repo_url)
    conn = get_db_connection()
    try:
        if branch and branch.strip():
            row = conn.execute(
                "SELECT * FROM repositories WHERE (repo_url = ? OR repo_url = ?) AND branch = ? ORDER BY created_at DESC LIMIT 1",
                (norm_url, repo_url.strip(), branch.strip()),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM repositories WHERE repo_url = ? OR repo_url = ? ORDER BY created_at DESC LIMIT 1",
                (norm_url, repo_url.strip()),
            ).fetchone()

        if not row:
            return None

        repo_id = row["id"]
        graph_row = conn.execute("SELECT * FROM graph_cache WHERE repo_id = ?", (repo_id,)).fetchone()
        if not graph_row:
            return None

        nodes = json.loads(graph_row["nodes_json"])
        edges = json.loads(graph_row["edges_json"])
        commits = json.loads(row["commits_json"])

        return {
            "repo_id": row["id"],
            "repo_url": row["repo_url"],
            "repo_name": row["repo_name"],
            "branch": row["branch"],
            "graph": {"nodes": nodes, "edges": edges},
            "num_files": row["num_files"],
            "num_functions": row["num_functions"],
            "num_classes": row["num_classes"],
            "unresolved_calls": row["unresolved_calls"],
            "commits": commits,
            "architectural_context": row["architectural_context"],
            "is_cached": True,
        }
    finally:
        conn.close()


def save_repository_analysis(
    repo_id: str,
    repo_url: str,
    repo_name: str,
    branch: str,
    graph_data: Dict[str, Any],
    extracted: Dict[str, Any],
    file_change_freq: Dict[str, int],
    commits: List[Dict[str, Any]],
    architectural_context: str,
    symbols_by_id: Dict[str, Dict[str, Any]],
    unresolved_count: int = 0,
):
    norm_url = normalize_repo_url(repo_url)
    conn = get_db_connection()
    try:
        with conn:
            # 1. Upsert repository record
            conn.execute(
                """
                INSERT INTO repositories (
                    id, repo_url, repo_name, branch,
                    num_files, num_functions, num_classes, unresolved_calls,
                    architectural_context, commits_json, file_change_freq_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    repo_url=excluded.repo_url,
                    repo_name=excluded.repo_name,
                    branch=excluded.branch,
                    num_files=excluded.num_files,
                    num_functions=excluded.num_functions,
                    num_classes=excluded.num_classes,
                    unresolved_calls=excluded.unresolved_calls,
                    architectural_context=excluded.architectural_context,
                    commits_json=excluded.commits_json,
                    file_change_freq_json=excluded.file_change_freq_json
                """,
                (
                    repo_id,
                    norm_url,
                    repo_name,
                    branch,
                    len(extracted.get("files", [])),
                    len(extracted.get("functions", [])),
                    len(extracted.get("classes", [])),
                    unresolved_count,
                    architectural_context,
                    json.dumps(commits),
                    json.dumps(file_change_freq),
                ),
            )

            # 2. Cache Graph nodes & edges
            conn.execute(
                """
                INSERT INTO graph_cache (repo_id, nodes_json, edges_json)
                VALUES (?, ?, ?)
                ON CONFLICT(repo_id) DO UPDATE SET
                    nodes_json=excluded.nodes_json,
                    edges_json=excluded.edges_json
                """,
                (
                    repo_id,
                    json.dumps(graph_data.get("nodes", [])),
                    json.dumps(graph_data.get("edges", [])),
                ),
            )

            # 3. Store Symbols
            symbol_rows = []
            for sym_id, sym in symbols_by_id.items():
                # Avoid duplicate insertion for raw_id aliases
                if sym.get("id") != sym_id:
                    continue

                symbol_rows.append((
                    repo_id,
                    sym.get("id", sym_id),
                    sym.get("raw_id", ""),
                    sym.get("name", ""),
                    sym.get("qualified_name", sym.get("name", "")),
                    sym.get("kind", "function"),
                    sym.get("file", ""),
                    sym.get("start_line", 1),
                    sym.get("end_line", 1),
                    sym.get("loc", 1),
                    sym.get("complexity", 1),
                    1 if sym.get("is_route") else 0,
                    1 if sym.get("is_async") else 0,
                    json.dumps(sym.get("decorators", [])),
                    sym.get("signature", ""),
                    sym.get("params", ""),
                    sym.get("docstring", ""),
                    sym.get("source", ""),
                    sym.get("change_frequency", 0),
                    json.dumps(sym.get("history", [])),
                    json.dumps(sym.get("incoming_callers", [])),
                    json.dumps(sym.get("outgoing_dependencies", [])),
                ))

            if symbol_rows:
                conn.executemany(
                    """
                    INSERT INTO symbols (
                        repo_id, id, raw_id, name, qualified_name, kind, file,
                        start_line, end_line, loc, complexity, is_route, is_async,
                        decorators_json, signature, params, docstring, source,
                        change_frequency, history_json, incoming_callers_json, outgoing_dependencies_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(repo_id, id) DO UPDATE SET
                        source=excluded.source,
                        complexity=excluded.complexity,
                        change_frequency=excluded.change_frequency,
                        history_json=excluded.history_json,
                        incoming_callers_json=excluded.incoming_callers_json,
                        outgoing_dependencies_json=excluded.outgoing_dependencies_json
                    """,
                    symbol_rows,
                )
    finally:
        conn.close()


def get_repository_analysis(repo_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT * FROM repositories WHERE id = ?", (repo_id,)).fetchone()
        if not row:
            return None

        graph_row = conn.execute("SELECT * FROM graph_cache WHERE repo_id = ?", (repo_id,)).fetchone()
        nodes = json.loads(graph_row["nodes_json"]) if graph_row else []
        edges = json.loads(graph_row["edges_json"]) if graph_row else []

        return {
            "repo_id": row["id"],
            "repo_url": row["repo_url"],
            "repo_name": row["repo_name"],
            "branch": row["branch"],
            "graph": {"nodes": nodes, "edges": edges},
            "num_files": row["num_files"],
            "num_functions": row["num_functions"],
            "num_classes": row["num_classes"],
            "unresolved_calls": row["unresolved_calls"],
            "commits": json.loads(row["commits_json"]),
            "file_change_freq": json.loads(row["file_change_freq_json"]),
            "architectural_context": row["architectural_context"],
        }
    finally:
        conn.close()


def get_symbol_details(repo_id: str, symbol_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        # Check by id, raw_id, or qualified_name
        row = conn.execute(
            """
            SELECT * FROM symbols
            WHERE repo_id = ? AND (id = ? OR raw_id = ? OR name = ? OR qualified_name = ?)
            LIMIT 1
            """,
            (repo_id, symbol_id, symbol_id, symbol_id, symbol_id),
        ).fetchone()

        if not row:
            return None

        return {
            "id": row["id"],
            "raw_id": row["raw_id"],
            "name": row["name"],
            "label": f"{row['name']}()" if row["kind"] in ("function", "method", "route") else row["name"],
            "qualified_name": row["qualified_name"],
            "kind": row["kind"],
            "file": row["file"],
            "start_line": row["start_line"],
            "end_line": row["end_line"],
            "loc": row["loc"],
            "complexity": row["complexity"],
            "is_route": bool(row["is_route"]),
            "is_async": bool(row["is_async"]),
            "decorators": json.loads(row["decorators_json"] or "[]"),
            "signature": row["signature"],
            "params": row["params"],
            "docstring": row["docstring"],
            "source": row["source"],
            "change_frequency": row["change_frequency"],
            "history": json.loads(row["history_json"] or "[]"),
            "incoming_callers": json.loads(row["incoming_callers_json"] or "[]"),
            "outgoing_dependencies": json.loads(row["outgoing_dependencies_json"] or "[]"),
        }
    finally:
        conn.close()


def get_all_symbols(repo_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute("SELECT * FROM symbols WHERE repo_id = ?", (repo_id,)).fetchall()
        symbols = []
        for row in rows:
            symbols.append({
                "id": row["id"],
                "raw_id": row["raw_id"],
                "name": row["name"],
                "label": f"{row['name']}()" if row["kind"] in ("function", "method", "route") else row["name"],
                "qualified_name": row["qualified_name"],
                "kind": row["kind"],
                "file": row["file"],
                "start_line": row["start_line"],
                "end_line": row["end_line"],
                "loc": row["loc"],
                "complexity": row["complexity"],
                "is_route": bool(row["is_route"]),
                "is_async": bool(row["is_async"]),
                "decorators": json.loads(row["decorators_json"] or "[]"),
                "signature": row["signature"],
                "params": row["params"],
                "docstring": row["docstring"],
                "source": row["source"],
                "change_frequency": row["change_frequency"],
                "history": json.loads(row["history_json"] or "[]"),
                "incoming_callers": json.loads(row["incoming_callers_json"] or "[]"),
                "outgoing_dependencies": json.loads(row["outgoing_dependencies_json"] or "[]"),
            })
        return symbols
    finally:
        conn.close()


def save_qa_thread(repo_id: str, question: str, answer: str, highlighted_ids: List[str]) -> Dict[str, Any]:
    conn = get_db_connection()
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO qa_threads (repo_id, question, answer, highlighted_ids_json)
                VALUES (?, ?, ?, ?)
                """,
                (repo_id, question.strip(), answer.strip(), json.dumps(highlighted_ids or [])),
            )
            thread_id = cur.lastrowid
            row = conn.execute("SELECT * FROM qa_threads WHERE id = ?", (thread_id,)).fetchone()
            return {
                "id": row["id"],
                "repo_id": row["repo_id"],
                "question": row["question"],
                "answer": row["answer"],
                "highlighted_ids": json.loads(row["highlighted_ids_json"] or "[]"),
                "created_at": row["created_at"],
            }
    finally:
        conn.close()


def get_qa_threads(repo_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM qa_threads WHERE repo_id = ? ORDER BY id ASC",
            (repo_id,),
        ).fetchall()

        threads = []
        for r in rows:
            threads.append({
                "id": r["id"],
                "repo_id": r["repo_id"],
                "question": r["question"],
                "answer": r["answer"],
                "highlighted_ids": json.loads(r["highlighted_ids_json"] or "[]"),
                "created_at": r["created_at"],
            })
        return threads
    finally:
        conn.close()


def _remove_readonly(func, path, excinfo):
    import stat
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass


def safe_delete_tree(path: Path | str):
    """Safely removes a directory tree on Windows handling read-only git packfile attributes."""
    if not path or not os.path.exists(path):
        return
    try:
        shutil.rmtree(str(path), onerror=_remove_readonly)
    except Exception:
        try:
            shutil.rmtree(str(path), ignore_errors=True)
        except Exception:
            pass


def cleanup_all_temp_clones():
    """Wipes legacy orphaned cloned folders in the OS temp directory to reclaim disk space."""
    temp_base = Path(tempfile.gettempdir()) / "code-archaeologist"
    if temp_base.exists():
        for item in temp_base.iterdir():
            if item.is_dir():
                safe_delete_tree(item)
            else:
                try:
                    os.remove(item)
                except Exception:
                    pass


# Automatically initialize schema on module import
init_db()
