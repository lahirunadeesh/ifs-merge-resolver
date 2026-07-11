from __future__ import annotations
import re
import difflib
from pathlib import Path
from core.file_types import IFS_FILE_TYPES
from core.beautifier import beautify, strip_blank_lines

CONFLICT_START = re.compile(r'^<{7} ')
CONFLICT_SEP   = re.compile(r'^={7}$')
CONFLICT_END   = re.compile(r'^>{7} ')

# IFS history header patterns
_HIST_DATE  = re.compile(r'--\s+Date\s+Sign\s+History', re.IGNORECASE)
_HIST_DASHES = re.compile(r'--\s+-{3,}')
_HIST_ENTRY  = re.compile(r'--\s+\d{6,8}\s+\S')
_HIST_SEP    = re.compile(r'^-{20,}\s*$')


def scan_for_conflicts(root_path: str) -> list[dict]:
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
    path = Path(file_path)
    ext  = path.suffix.lower()

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

            while i < len(lines) and not CONFLICT_SEP.match(lines[i].rstrip()):
                local_lines.append(lines[i])
                i += 1
            i += 1  # skip =======

            while i < len(lines) and not CONFLICT_END.match(lines[i]):
                repo_lines.append(lines[i])
                i += 1

            end = i
            local_text = beautify("".join(local_lines).rstrip(), ext)
            repo_text  = beautify("".join(repo_lines).rstrip(), ext)

            # Rebuild beautified lines for diff
            local_b = [l + "\n" for l in local_text.splitlines()] if local_text else []
            repo_b  = [l + "\n" for l in repo_text.splitlines()]  if repo_text  else []

            try:
                diff = _build_diff(local_b, repo_b, start + 1)
            except Exception:
                diff = []

            raw_preview = _smart_merge_both(local_lines, repo_lines)
            preview     = strip_blank_lines(beautify(raw_preview, ext))

            conflicts.append({
                "index":      len(conflicts),
                "local":      local_text,
                "repo":       repo_text,
                "start_line": start,
                "end_line":   end,
                "preview":    preview,
                "diff":       diff,
            })
        i += 1

    return conflicts


def _build_diff(local_lines: list[str], repo_lines: list[str], start_line: int) -> list[dict]:
    local_clean = [l.rstrip("\n") for l in local_lines]
    repo_clean  = [l.rstrip("\n") for l in repo_lines]

    if not local_clean and not repo_clean:
        return []
    if not local_clean:
        return [{"line_no_local": None, "line_no_repo": start_line + k,
                 "text": repo_clean[k], "kind": "repo"}
                for k in range(len(repo_clean))]
    if not repo_clean:
        return [{"line_no_local": start_line + k, "line_no_repo": None,
                 "text": local_clean[k], "kind": "local"}
                for k in range(len(local_clean))]

    result   = []
    local_no = start_line
    repo_no  = start_line

    matcher = difflib.SequenceMatcher(None, local_clean, repo_clean, autojunk=False)

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                result.append({
                    "line_no_local": local_no + k,
                    "line_no_repo":  repo_no  + k,
                    "text": local_clean[i1 + k],
                    "kind": "context",
                })
            local_no += i2 - i1
            repo_no  += j2 - j1

        elif tag in ("replace", "delete"):
            for k in range(i2 - i1):
                result.append({
                    "line_no_local": local_no + k,
                    "line_no_repo":  None,
                    "text": local_clean[i1 + k],
                    "kind": "local",
                })
            local_no += i2 - i1
            if tag == "replace":
                for k in range(j2 - j1):
                    result.append({
                        "line_no_local": None,
                        "line_no_repo":  repo_no + k,
                        "text": repo_clean[j1 + k],
                        "kind": "repo",
                    })
                repo_no += j2 - j1

        elif tag == "insert":
            for k in range(j2 - j1):
                result.append({
                    "line_no_local": None,
                    "line_no_repo":  repo_no + k,
                    "text": repo_clean[j1 + k],
                    "kind": "repo",
                })
            repo_no += j2 - j1

    return result


# ── Smart merge: Keep Both ────────────────────────────────────────────────────

def _smart_merge_both(local_lines: list[str], repo_lines: list[str]) -> str:
    """
    Merge strategy for 'Keep Both':

    IFS conflicts arise when two developers each add new code (attributes,
    procedures, fields) in the same block.  The correct resolution is always
    to keep ALL content from BOTH sides.

    Algorithm:
      1. If both sides begin with an IFS history-comment header
         (--  Date  Sign  History / --  ------  / date entries / -----...),
         merge those headers into one (avoiding the duplicated boilerplate)
         and concatenate the bodies.
      2. Otherwise, concatenate local + repo as-is.

    No line deduplication is performed on the body — if the same section
    header appears in both sides it will appear twice, which is correct
    (each developer's block needs its own section context).
    """
    if not local_lines:
        return "".join(repo_lines).rstrip()
    if not repo_lines:
        return "".join(local_lines).rstrip()

    local_hdr_end = _find_history_header_end(local_lines)
    repo_hdr_end  = _find_history_header_end(repo_lines)

    if local_hdr_end is not None and repo_hdr_end is not None:
        merged_hdr  = _merge_history_headers(local_lines[:local_hdr_end],
                                              repo_lines[:repo_hdr_end])
        local_body  = local_lines[local_hdr_end:]
        repo_body   = repo_lines[repo_hdr_end:]
        return ("".join(merged_hdr) + _join_bodies(local_body, repo_body)).rstrip()

    return _join_bodies(local_lines, repo_lines).rstrip()


def _join_bodies(local: list[str], repo: list[str]) -> str:
    """
    Concatenate local body + repo body.  Strip leading blank lines from the
    repo side so we don't accumulate excess whitespace at the join point;
    ensure exactly one blank line separates them.
    """
    local_text = "".join(local)
    repo_text  = "".join(repo).lstrip("\n")

    if not local_text:
        return repo_text
    if not repo_text:
        return local_text

    # Ensure a single newline gap between the two halves
    if not local_text.endswith("\n"):
        local_text += "\n"

    return local_text + repo_text


def _find_history_header_end(lines: list[str]) -> int | None:
    """
    Return the index of the first line AFTER the IFS history header block, or
    None if no such header is found at the start of `lines`.

    A header looks like:
        --  Date    Sign    History
        --  ------  ------  ------...
        --  YYYYMMDD  Sign  ...entry...
        ...more entries...
        -------...   (long dash separator)
    """
    n = len(lines)
    i = 0

    # Skip any leading blank lines
    while i < n and not lines[i].strip():
        i += 1

    # Must start with the "Date Sign History" line
    if i >= n or not _HIST_DATE.search(lines[i]):
        return None
    i += 1

    # "------  ------" line
    if i >= n or not _HIST_DASHES.search(lines[i]):
        return None
    i += 1

    # One or more date entries
    entry_count = 0
    while i < n and _HIST_ENTRY.search(lines[i]):
        i += 1
        entry_count += 1

    if entry_count == 0:
        return None

    # Closing "------...----" separator (20+ dashes)
    if i < n and _HIST_SEP.match(lines[i].rstrip()):
        i += 1
        return i

    return None


def _merge_history_headers(local_hdr: list[str], repo_hdr: list[str]) -> list[str]:
    """
    Produce one merged IFS history comment header from the two sides.
    - Keep local's "Date / ------" lines (one copy).
    - Collect all date-entry lines from both sides (deduped by stripped text).
    - Add the closing separator once.
    - Append everything else from local (blank lines before code, etc.).
    """
    local_entries = [l for l in local_hdr if _HIST_ENTRY.search(l)]
    repo_entries  = [l for l in repo_hdr  if _HIST_ENTRY.search(l)]

    seen    = {l.strip() for l in local_entries}
    extra   = [l for l in repo_entries if l.strip() not in seen]
    all_entries = local_entries + extra

    merged: list[str] = []
    in_entries = False
    entries_written = False

    for line in local_hdr:
        if _HIST_ENTRY.search(line):
            if not in_entries:
                in_entries = True
            # Write all merged entries at the first entry position
            if not entries_written:
                merged.extend(all_entries)
                entries_written = True
            # Skip original local entry lines (already written above)
        else:
            merged.append(line)

    return merged


def apply_resolution(file_path: str, resolutions: list[dict]) -> None:
    path = Path(file_path)
    ext  = path.suffix.lower()

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    strategy_map = {r["index"]: r["strategy"] for r in resolutions}
    conflicts    = parse_conflicts(file_path)
    conflict_at  = {
        c["start_line"]: (c, strategy_map.get(c["index"], "local"))
        for c in conflicts
    }

    output = []
    i = 0
    while i < len(lines):
        if i in conflict_at:
            conflict, strategy = conflict_at[i]
            if strategy == "local":
                resolved = conflict["local"]
            elif strategy == "repo":
                resolved = conflict["repo"]
            else:
                resolved = conflict["preview"]

            if resolved:
                output.append(beautify(resolved, ext) + "\n")
            i = conflict["end_line"] + 1
        else:
            output.append(lines[i])
            i += 1

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(output)
