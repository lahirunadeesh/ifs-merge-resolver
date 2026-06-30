from __future__ import annotations
import os
import re
import difflib
from pathlib import Path
from core.file_types import IFS_FILE_TYPES
from core.beautifier import beautify, strip_blank_lines

CONFLICT_START = re.compile(r'^<{7} ')
CONFLICT_SEP   = re.compile(r'^={7}$')
CONFLICT_END   = re.compile(r'^>{7} ')

# IFS comment line patterns
LINE_COMMENT    = re.compile(r'^\s*--')
BLOCK_COMMENT_S = re.compile(r'^\s*/\*')
BLOCK_COMMENT_E = re.compile(r'\*/\s*$')
# History entry: e.g. "-- 240102  NHENLK  SMDEV-21249 - ..."
HISTORY_ENTRY   = re.compile(r'^\s*--\s+\d{6}\s+\w+\s+')


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

            raw_preview = _smart_merge_preview(local_lines, repo_lines)
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
    """
    Build a structured line-by-line diff between local and repo sides.
    Each entry: { line_no_local, line_no_repo, text, kind }
    kind: 'local' (green) | 'repo' (red) | 'context' (shared)
    """
    # Normalise: strip trailing newlines for comparison, keep originals for display
    local_clean = [l.rstrip("\n") for l in local_lines]
    repo_clean  = [l.rstrip("\n") for l in repo_lines]

    # Edge cases: one side is empty
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


def _smart_merge_preview(local_lines: list[str], repo_lines: list[str]) -> str:
    """
    Preview of what 'Keep Both' will produce after smart comment merging.
    """
    return _smart_merge_both(local_lines, repo_lines)


def _smart_merge_both(local_lines: list[str], repo_lines: list[str]) -> str:
    """
    Merge local and repo sides intelligently:
    - Comment blocks (history headers, -- lines, /* */ blocks) are merged
      and deduplicated, with repo history entries inserted in the right place.
    - Non-comment code lines from both sides are concatenated (local first).
    """
    local_comments, local_code = _split_comments_and_code(local_lines)
    repo_comments,  repo_code  = _split_comments_and_code(repo_lines)

    merged_comments = _merge_comment_blocks(local_comments, repo_comments)
    merged_code     = _merge_code_lines(local_code, repo_code)

    parts = []
    if merged_comments:
        parts.append("".join(merged_comments).rstrip())
    if merged_code:
        parts.append("".join(merged_code).rstrip())

    return "\n".join(parts)


def _split_comments_and_code(lines: list[str]) -> tuple[list[str], list[str]]:
    """
    Separate a block of lines into:
    - comment_lines: leading comment block (-- lines and /* */ blocks)
    - code_lines: everything after the leading comments
    """
    comment_lines = []
    code_lines    = []
    in_block_comment = False
    past_comments    = False

    for line in lines:
        stripped = line.strip()

        if not past_comments:
            if in_block_comment:
                comment_lines.append(line)
                if BLOCK_COMMENT_E.search(line):
                    in_block_comment = False
            elif BLOCK_COMMENT_S.match(line):
                comment_lines.append(line)
                if not BLOCK_COMMENT_E.search(line):
                    in_block_comment = True
            elif LINE_COMMENT.match(line) or stripped == "":
                comment_lines.append(line)
            else:
                past_comments = True
                code_lines.append(line)
        else:
            code_lines.append(line)

    return comment_lines, code_lines


def _merge_comment_blocks(local: list[str], repo: list[str]) -> list[str]:
    """
    Merge two comment blocks. History entries from repo that don't exist
    in local are inserted in chronological order within the history section.
    Non-history comment lines are deduplicated (local wins for duplicates).
    """
    if not local and not repo:
        return []
    if not local:
        return repo
    if not repo:
        return local

    # Find history entries in local and repo
    local_history  = {l.strip() for l in local  if HISTORY_ENTRY.match(l)}
    repo_history   = {l.strip() for l in repo   if HISTORY_ENTRY.match(l)}
    new_repo_entries = [l for l in repo if HISTORY_ENTRY.match(l)
                        and l.strip() not in local_history]

    if not new_repo_entries:
        return local  # nothing new to add

    # Find insertion point: after the last existing history entry in local
    result = list(local)
    last_history_idx = -1
    for idx, line in enumerate(result):
        if HISTORY_ENTRY.match(line):
            last_history_idx = idx

    if last_history_idx >= 0:
        insert_at = last_history_idx + 1
        for entry in reversed(new_repo_entries):
            result.insert(insert_at, entry if entry.endswith("\n") else entry + "\n")
    else:
        result.extend(new_repo_entries)

    return result


BLOCK_OPEN_RE  = re.compile(r'\{\s*$')
BLOCK_CLOSE_RE = re.compile(r'^\s*\}\s*;?\s*$')


def _parse_block_tree(lines: list[str]) -> list[dict]:
    """
    Parse a flat list of code lines into a tree of brace-delimited blocks:
      {'type': 'block', 'header': line, 'children': [...], 'footer': line|None}
      {'type': 'line',  'text': line}
    A block's footer is None if its closing brace falls outside this
    slice of lines (e.g. the conflict hunk didn't include it) — in that
    case we must never invent a synthetic '}' when rendering back out,
    since the real one already exists later in the file.
    """
    root: dict = {"children": []}
    stack = [root]

    for line in lines:
        stripped = line.rstrip("\n")
        if BLOCK_CLOSE_RE.match(stripped) and len(stack) > 1:
            block = stack.pop()
            block["footer"] = line
            stack[-1]["children"].append(block)
        elif BLOCK_OPEN_RE.search(stripped):
            stack.append({"type": "block", "header": line, "children": [], "footer": None})
        else:
            stack[-1]["children"].append({"type": "line", "text": line})

    # Any still-open blocks had their closing brace outside this slice —
    # flush them up with footer=None so we don't fabricate one later.
    while len(stack) > 1:
        block = stack.pop()
        stack[-1]["children"].append(block)

    return root["children"]


def _render_block_tree(items: list[dict]) -> list[str]:
    out = []
    for item in items:
        if item.get("type") == "block":
            out.append(item["header"])
            out.extend(_render_block_tree(item["children"]))
            if item.get("footer") is not None:
                out.append(item["footer"])
        else:
            out.append(item["text"])
    return out


def _block_key(item: dict) -> str | None:
    if item.get("type") == "block":
        return item["header"].strip()
    return None


def _merge_block_trees(local_items: list[dict], repo_items: list[dict]) -> list[dict]:
    """
    Structural merge: walk repo's items and either merge them into the
    matching local block (same header text, merged recursively) or, if
    no match exists, append them as genuinely new content. Local's order
    and brace structure is otherwise left untouched.
    """
    local_blocks_by_key = {
        _block_key(it): it for it in local_items if it.get("type") == "block"
    }
    local_line_texts = {
        it["text"].strip() for it in local_items
        if it.get("type") == "line" and it["text"].strip()
    }

    merged = list(local_items)
    extra: list[dict] = []

    for item in repo_items:
        if item.get("type") == "block":
            key = _block_key(item)
            match = local_blocks_by_key.get(key)
            if match is not None:
                match["children"] = _merge_block_trees(match["children"], item["children"])
                if match.get("footer") is None and item.get("footer") is not None:
                    match["footer"] = item["footer"]
            else:
                extra.append(item)
        else:
            text = item["text"].strip()
            if text and text not in local_line_texts:
                extra.append(item)
            elif not text:
                # blank lines: keep, harmless and helps readability
                extra.append(item)

    merged.extend(extra)
    return merged


def _merge_code_lines(local: list[str], repo: list[str]) -> list[str]:
    """
    Combine code lines from both sides using a structural (brace-tree) merge:
    matching blocks (same declaration, e.g. 'group X for Y {') are merged
    recursively so only genuinely new content is inserted, in place, instead
    of duplicating the whole block. Closing braces are never treated as
    standalone lines — they belong to their block — so nesting can't break.

    Falls back to plain concatenation when the content has no braces at all
    (nothing structural to key off), which still guarantees no line is lost.
    """
    if not local:
        return list(repo)
    if not repo:
        return list(local)

    has_braces = any("{" in l or "}" in l for l in local + repo)
    if not has_braces:
        # No block structure to merge on — just append repo lines that
        # aren't already present verbatim in local.
        local_set = {l.strip() for l in local if l.strip()}
        merged = list(local)
        for line in repo:
            if line.strip() and line.strip() not in local_set:
                merged.append(line)
        return merged

    local_tree = _parse_block_tree(local)
    repo_tree  = _parse_block_tree(repo)
    merged_tree = _merge_block_trees(local_tree, repo_tree)
    return _render_block_tree(merged_tree)


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
