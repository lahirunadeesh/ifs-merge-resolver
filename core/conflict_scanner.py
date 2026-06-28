import os
import re
from pathlib import Path
from core.file_types import IFS_FILE_TYPES

CONFLICT_START = re.compile(r'^<{7} ')
CONFLICT_SEP   = re.compile(r'^={7}$')
CONFLICT_END   = re.compile(r'^>{7} ')


def scan_for_conflicts(root_path: str) -> list[dict]:
    """Walk root_path and return all IFS files that contain Git conflict markers."""
    results = []
    root = Path(root_path)

    if not root.exists() or not root.is_dir():
        raise ValueError(f"Path does not exist or is not a directory: {root_path}")

    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue

        ext = file_path.suffix.lower()
        if ext not in IFS_FILE_TYPES:
            continue

        if _has_conflict_markers(file_path):
            results.append({
                "path": str(file_path),
                "relative_path": str(file_path.relative_to(root)),
                "type": IFS_FILE_TYPES[ext],
                "extension": ext,
            })

    return sorted(results, key=lambda f: f["relative_path"])


def _has_conflict_markers(file_path: Path) -> bool:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if CONFLICT_START.match(line):
                    return True
    except Exception:
        pass
    return False


def parse_conflicts(file_path: str) -> list[dict]:
    """
    Parse a file and extract all conflict blocks.
    Returns a list of {index, local, repo, start_line, end_line}.
    """
    path = Path(file_path)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    conflicts = []
    i = 0
    while i < len(lines):
        if CONFLICT_START.match(lines[i]):
            start = i
            local_lines = []
            repo_lines = []
            i += 1

            # Collect local (HEAD) side
            while i < len(lines) and not CONFLICT_SEP.match(lines[i].rstrip()):
                local_lines.append(lines[i])
                i += 1
            i += 1  # skip =======

            # Collect repo (incoming) side
            while i < len(lines) and not CONFLICT_END.match(lines[i]):
                repo_lines.append(lines[i])
                i += 1

            end = i
            conflicts.append({
                "index": len(conflicts),
                "local": "".join(local_lines).rstrip(),
                "repo": "".join(repo_lines).rstrip(),
                "start_line": start,
                "end_line": end,
            })
        i += 1

    return conflicts


def apply_resolution(file_path: str, resolutions: list[dict]) -> None:
    """
    Apply resolutions to a file. Each resolution has {index, strategy}.
    Strategies: 'local', 'repo', 'both'.
    Rewrites the file in one pass.
    """
    path = Path(file_path)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    # Build a lookup of conflict index → strategy
    strategy_map = {r["index"]: r["strategy"] for r in resolutions}

    # Re-parse to get positions
    conflicts = parse_conflicts(file_path)
    # Map start_line → conflict info + strategy
    conflict_at = {
        c["start_line"]: (c, strategy_map.get(c["index"], "local"))
        for c in conflicts
    }

    output = []
    i = 0
    while i < len(lines):
        if i in conflict_at:
            conflict, strategy = conflict_at[i]
            if strategy == "local":
                output.append(conflict["local"] + "\n" if conflict["local"] else "")
            elif strategy == "repo":
                output.append(conflict["repo"] + "\n" if conflict["repo"] else "")
            elif strategy == "both":
                if conflict["local"]:
                    output.append(conflict["local"] + "\n")
                if conflict["repo"]:
                    output.append(conflict["repo"] + "\n")
            i = conflict["end_line"] + 1
        else:
            output.append(lines[i])
            i += 1

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(output)
