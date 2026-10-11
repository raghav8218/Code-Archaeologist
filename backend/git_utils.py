import re
import subprocess
from collections import Counter
from typing import List, Dict, Any, Optional

import git


def get_blame(repo_path: str, file_path: str, start_line: int, end_line: int) -> List[Dict[str, Any]]:
    try:
        repo = git.Repo(repo_path)
        blame_entries = repo.blame("HEAD", file_path)
    except Exception:
        return []

    results = []
    current_line = 1
    for commit, lines in blame_entries:
        for _ in lines:
            if start_line <= current_line <= end_line:
                results.append({
                    "line": current_line,
                    "commit": commit.hexsha[:8],
                    "hexsha": commit.hexsha,
                    "author": commit.author.name if commit.author else "Unknown",
                    "date": commit.committed_datetime.isoformat(),
                    "message": commit.message.strip().split("\n")[0],
                })
            current_line += 1

    return results


def get_function_history(repo_path: str, file_path: str, start_line: int, end_line: int, limit: int = 5) -> List[Dict[str, Any]]:
    blame = get_blame(repo_path, file_path, start_line, end_line)

    seen = {}
    for entry in blame:
        seen.setdefault(entry["commit"], entry)

    commits = sorted(seen.values(), key=lambda c: c["date"], reverse=True)
    return commits[:limit]


def get_repo_change_frequency(repo_path: str) -> Dict[str, int]:
    try:
        result = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:"],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )
        paths = [line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()]
        return dict(Counter(paths))
    except Exception:
        return {}


def parse_github_owner_repo(repo_url: str) -> Optional[str]:
    """Extract owner/repo from GitHub URL."""
    match = re.search(r"github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?$", repo_url.strip())
    if match:
        return f"{match.group(1)}/{match.group(2)}"
    clean = repo_url.strip().strip("/")
    parts = clean.split("/")
    if len(parts) == 2 and not clean.startswith("http"):
        return f"{parts[0]}/{parts[1]}"
    return None


def get_repo_commits(repo_path: str, repo_url: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve commit history with GitHub links and change stats."""
    commits = []
    owner_repo = parse_github_owner_repo(repo_url) if repo_url else None

    try:
        repo = git.Repo(repo_path)
        for c in list(repo.iter_commits(max_count=limit)):
            commit_hash = c.hexsha[:8]
            gh_url = f"https://github.com/{owner_repo}/commit/{c.hexsha}" if owner_repo else None

            # Get basic stats if available
            files_changed = 0
            try:
                stats = c.stats.total
                files_changed = stats.get("files", 0)
            except Exception:
                pass

            commits.append({
                "hash": commit_hash,
                "hexsha": c.hexsha,
                "author": c.author.name if c.author else "Unknown",
                "email": c.author.email if c.author else "",
                "date": c.committed_datetime.isoformat(),
                "relative_date": c.committed_datetime.strftime("%Y-%m-%d %H:%M"),
                "message": c.message.strip().split("\n")[0],
                "full_message": c.message.strip(),
                "url": gh_url,
                "files_changed": files_changed,
            })
    except Exception:
        pass

    return commits
