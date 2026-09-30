
import subprocess
from collections import Counter

import git


def get_blame(repo_path, file_path, start_line, end_line):
    repo = git.Repo(repo_path)
    try:
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
                    "author": commit.author.name,
                    "date": commit.committed_datetime.isoformat(),
                    "message": commit.message.strip().split("\n")[0],
                })
            current_line += 1

    return results


def get_function_history(repo_path, file_path, start_line, end_line, limit=5):
    blame = get_blame(repo_path, file_path, start_line, end_line)

    seen = {}
    for entry in blame:
        seen.setdefault(entry["commit"], entry)

    commits = sorted(seen.values(), key=lambda c: c["date"], reverse=True)
    return commits[:limit]


def get_repo_change_frequency(repo_path):
    
    try:
        result = subprocess.run(
            ["git", "log", "--name-only", "--pretty=format:"],
            cwd=repo_path, capture_output=True, text=True, timeout=30,
        )
        paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return dict(Counter(paths))
    except Exception:
        return {}
