import io
import json
import os
import re
import subprocess
import tarfile
import urllib.request
from collections import Counter
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

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


def get_temporal_coupling(repo_path: str, limit_commits: int = 40, min_co_commits: int = 2) -> Dict[str, List[Dict[str, Any]]]:
    """
    Computes temporal coupling (co-change coupling) inspired by CodeScene.
    Discovers files that frequently change together in the same commits.
    """
    try:
        repo = git.Repo(repo_path)
        file_commit_counts: Counter = Counter()
        co_counts: Dict[str, Counter] = {}

        for c in list(repo.iter_commits(max_count=limit_commits)):
            # Ignore massive merge commits touching > 30 files (noise filter)
            changed_files = [f.replace("\\", "/") for f in c.stats.files.keys() if f.endswith(".py") or f.endswith(".js") or f.endswith(".ts")]
            if len(changed_files) > 25 or len(changed_files) < 2:
                continue

            for f in changed_files:
                file_commit_counts[f] += 1
                if f not in co_counts:
                    co_counts[f] = Counter()
                for other in changed_files:
                    if other != f:
                        co_counts[f][other] += 1

        coupling_results = {}
        for f, others in co_counts.items():
            total_f = file_commit_counts[f]
            if total_f < min_co_commits:
                continue
            couplings = []
            for other_f, count in others.most_common(5):
                if count >= min_co_commits:
                    pct = round((count / total_f) * 100)
                    couplings.append({"file": other_f, "co_commits": count, "strength_pct": pct})
            if couplings:
                coupling_results[f] = couplings

        return coupling_results
    except Exception:
        return {}


def fetch_github_in_memory(raw_url: str, requested_branch: Optional[str] = None) -> Tuple[Dict[str, str], List[Dict[str, Any]], Dict[str, int], str, str]:
    """
    Zero-disk streaming fetch from GitHub.
    Downloads compressed tarball directly into memory, extracts source code files into RAM,
    and fetches recent commit history via GitHub REST API.
    Zero bytes stored on hard drive!
    """
    owner_repo = parse_github_owner_repo(raw_url)
    if not owner_repo:
        raise ValueError(f"Could not parse GitHub owner/repo from {raw_url}")

    active_branch = requested_branch.strip() if requested_branch and requested_branch.strip() else "main"
    headers = {"User-Agent": "Code-Archaeologist"}
    gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if gh_token:
        headers["Authorization"] = f"token {gh_token}"

    # Attempt download for requested branch; fallback to master if main 404s
    tar_url = f"https://codeload.github.com/{owner_repo}/tar.gz/refs/heads/{active_branch}"
    req = urllib.request.Request(tar_url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=25)
    except urllib.error.HTTPError as e:
        if e.code == 404 and not requested_branch:
            active_branch = "master"
            tar_url = f"https://codeload.github.com/{owner_repo}/tar.gz/refs/heads/{active_branch}"
            req = urllib.request.Request(tar_url, headers=headers)
            resp = urllib.request.urlopen(req, timeout=25)
        else:
            raise e

    tar_bytes = resp.read()

    from parser import IGNORE_DIRS, SUPPORTED_EXTENSIONS
    files_dict: Dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            parts = member.name.split("/", 1)
            if len(parts) < 2:
                continue
            rel_path = parts[1]
            path_parts = rel_path.lower().split("/")
            if any(p in IGNORE_DIRS or p.startswith(".") for p in path_parts[:-1]):
                continue
            ext = Path(rel_path).suffix.lower()
            if ext in SUPPORTED_EXTENSIONS:
                f_obj = tar.extractfile(member)
                if f_obj:
                    files_dict[rel_path] = f_obj.read().decode("utf-8", errors="ignore")

    # Fetch recent commits and file change frequencies via GitHub REST API
    commits = []
    file_change_freq = Counter()
    try:
        commits_url = f"https://api.github.com/repos/{owner_repo}/commits?per_page=30"
        c_req = urllib.request.Request(commits_url, headers=headers)
        with urllib.request.urlopen(c_req, timeout=12) as c_resp:
            c_data = json.loads(c_resp.read().decode("utf-8"))
            for item in c_data:
                sha = item["sha"][:8]
                author = item["commit"]["author"]["name"] if item.get("commit") and item["commit"].get("author") else "Unknown"
                date = item["commit"]["author"]["date"] if item.get("commit") and item["commit"].get("author") else ""
                msg = item["commit"]["message"].split("\n")[0] if item.get("commit") else ""
                commits.append({
                    "hash": sha,
                    "hexsha": item["sha"],
                    "author": author,
                    "date": date,
                    "relative_date": date[:10],
                    "message": msg,
                    "url": item.get("html_url"),
                    "files_changed": 1,
                })
    except Exception:
        pass

    return files_dict, commits, dict(file_change_freq), owner_repo, active_branch
