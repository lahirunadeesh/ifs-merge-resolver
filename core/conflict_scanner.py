from __future__ import annotations
import re
import difflib
from pathlib import Path
from core.file_types import IFS_FILE_TYPES
from core.beautifier import beautify, strip_blank_lines

CONFLICT_START = re.compile(r'^<{7} ')
CONFLICT_SEP   = re.compile(r'^={7}$')
CONFLICT_END   = re.compile(r'^>{7} ')

# ── IFS History-comment header patterns ───────────────────────────────────────
# Used in .ddlsource, .cdb, .plsql, .plsvc, .fragment, .projection, .client
_HIST_DATE   = re.compile(r'--\s+Date\s+Sign\s+History', re.IGNORECASE)
_HIST_DASHES = re.compile(r'--\s+-{3,}')
_HIST_ENTRY  = re.compile(r'--\s+\d{6,8}\s+\S')
_HIST_SEP    = re.compile(r'^-{20,}\s*$')

# ── Marble DSL block patterns (projection / client / fragment / utility) ──────
# Named blocks:  entity X { / attribute X Type { / list X for Y { / etc.
_DSL_BLOCK_OPEN  = re.compile(r'^(\s*)(\S.*?)\s*\{')
_DSL_BLOCK_CLOSE = re.compile(r'^\s*\}\s*$')

# ── XML element name (entity files) ───────────────────────────────────────────
_XML_NAME_TAG = re.compile(r'<NAME>(.+?)</NAME>', re.IGNORECASE)

# ── PL/SQL named unit patterns (.plsql / .plsvc) ──────────────────────────────
_PLSQL_UNIT = re.compile(
    r'^\s*(PROCEDURE|FUNCTION|PACKAGE(?:\s+BODY)?)\s+(\w+)',
    re.IGNORECASE
)

# ── DDL @CodeRegistration block (.ddlsource / .cdb) ──────────────────────────
_CODE_REG = re.compile(r'^\s*@CodeRegistration\s+(\S+)', re.IGNORECASE)


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
            repo_lines  = []
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

            local_b = [l + "\n" for l in local_text.splitlines()] if local_text else []
            repo_b  = [l + "\n" for l in repo_text.splitlines()]  if repo_text  else []

            try:
                diff = _build_diff(local_b, repo_b, start + 1)
            except Exception:
                diff = []

            raw_preview = _smart_merge_both(local_lines, repo_lines, ext)
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

def _smart_merge_both(local_lines: list[str], repo_lines: list[str], ext: str = "") -> str:
    """
    File-type-aware 'Keep Both' merge.

    IFS conflict resolution rules by file type:

    Marble DSL (.projection, .client, .fragment, .utility, .enumeration)
      Named blocks (entity X {}, attribute X Type {}, field X {}, etc.):
      • Blocks with the same declaration line → merge their children recursively
      • Blocks with different declaration lines → keep both in sequence
      • Loose lines (comments, markers like --(+)...) → keep both in sequence

    PL/SQL (.plsql, .plsvc, .pltst)
      Named units (PROCEDURE X, FUNCTION X, PACKAGE BODY X):
      • Units with the same name → keep both versions (developer resolves later)
      • Units with different names → keep both in sequence
      History comment header (if present) → merge date entries

    DDL / CDB (.ddlsource, .cdb)
      @CodeRegistration blocks:
      • Different registration names → keep both blocks
      • Same registration name → keep both (conflict within one registration)
      History comment header → merge date entries

    XML (.entity)
      <ATTRIBUTE>, <ASSOCIATION>, <COMMENT> elements keyed by <NAME>:
      • Different names → keep both elements
      • Same name → keep both (conflict within one element, user resolves)

    Views (.views)
      COLUMN X IS ... / VIEW X IS ... blocks:
      • Different names → keep both
      • Same name → keep both (user resolves)

    All file types: when no structural key can be identified, fall back to
    plain concatenation (local content followed by repo content).
    """
    if not local_lines:
        return "".join(repo_lines).rstrip()
    if not repo_lines:
        return "".join(local_lines).rstrip()

    # Step 1: try to merge the IFS history comment header if present on both sides
    local_hdr_end = _find_history_header_end(local_lines)
    repo_hdr_end  = _find_history_header_end(repo_lines)

    if local_hdr_end is not None and repo_hdr_end is not None:
        merged_hdr = _merge_history_headers(local_lines[:local_hdr_end],
                                             repo_lines[:repo_hdr_end])
        local_body = local_lines[local_hdr_end:]
        repo_body  = repo_lines[repo_hdr_end:]
        body = _merge_body(local_body, repo_body, ext)
        return ("".join(merged_hdr) + body).rstrip()

    # Step 2: structural body merge based on file type
    return _merge_body(local_lines, repo_lines, ext).rstrip()


def _merge_body(local: list[str], repo: list[str], ext: str) -> str:
    """
    Merge body lines according to the structural rules of the file type.
    """
    if not local:
        return "".join(repo)
    if not repo:
        return "".join(local)

    if ext in (".projection", ".client", ".fragment", ".utility", ".enumeration"):
        return _merge_dsl(local, repo)

    if ext in (".plsql", ".plsvc", ".pltst"):
        return _merge_plsql(local, repo)

    if ext in (".ddlsource", ".cdb"):
        return _merge_ddl(local, repo)

    if ext == ".entity":
        return _merge_xml_entity(local, repo)

    if ext == ".views":
        return _merge_views(local, repo)

    # Default: plain concatenation
    return _concat(local, repo)


# ── Marble DSL merge ──────────────────────────────────────────────────────────

def _merge_dsl(local: list[str], repo: list[str]) -> str:
    """
    Merge two Marble DSL line lists.

    Structural key: the full declaration line before the opening '{', e.g.
      'attribute CIpOrdRelLeadtime Number'
      'field CCrCn'
      '@Override\nentity InventoryPart'
      '--(+) 20260612 WiaDinushikaR ME# 605169 (START)'  ← treated as loose line

    Algorithm:
    1. Parse both sides into a flat sequence of items, where each item is
       either a named block (header + children + footer) or a loose line.
    2. Build an identity map: declaration_key → item for each side.
    3. Walk the repo sequence to insert repo-only items in order. For items
       that exist on both sides with the same key, merge their children.
    4. Append any local-only items that didn't appear in repo.
    """
    local_items = _parse_dsl_items(local)
    repo_items  = _parse_dsl_items(repo)

    local_keys = [_dsl_item_key(it) for it in local_items]
    repo_keys  = [_dsl_item_key(it) for it in repo_items]

    matcher = difflib.SequenceMatcher(None, local_keys, repo_keys, autojunk=False)
    merged: list[str] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                merged.extend(_render_dsl_item(local_items[i1 + k]))
        elif tag == "delete":
            # In local only → keep
            for it in local_items[i1:i2]:
                merged.extend(_render_dsl_item(it))
        elif tag == "insert":
            # In repo only → keep
            for it in repo_items[j1:j2]:
                merged.extend(_render_dsl_item(it))
        elif tag == "replace":
            # Both sides differ → keep local version, then repo version
            for it in local_items[i1:i2]:
                merged.extend(_render_dsl_item(it))
            for it in repo_items[j1:j2]:
                merged.extend(_render_dsl_item(it))

    return "".join(merged)


def _parse_dsl_items(lines: list[str]) -> list[dict]:
    """
    Parse Marble DSL lines into a flat list of items:
      {'type': 'block', 'header': str, 'children': [str, ...], 'footer': str|None}
      {'type': 'line',  'text': str}
    """
    items: list[dict] = []
    stack: list[dict] = []  # open blocks
    pending_header_lines: list[str] = []  # lines accumulated before a '{' opens

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            if stack:
                stack[-1]["children"].append(line)
            elif pending_header_lines:
                pending_header_lines.append(line)
            else:
                items.append({"type": "line", "text": line})
            i += 1
            continue

        if _DSL_BLOCK_CLOSE.match(stripped) and stack:
            block = stack.pop()
            block["footer"] = line
            if stack:
                stack[-1]["children"].append(block)
            else:
                items.append(block)
            pending_header_lines = []
            i += 1
            continue

        if _DSL_BLOCK_OPEN.search(stripped) and stripped.endswith("{"):
            pending_header_lines.append(line)
            header = "".join(pending_header_lines)
            pending_header_lines = []
            block: dict = {"type": "block", "header": header, "children": [], "footer": None}
            if stack:
                stack[-1]["children"].append(block)
            stack.append(block)
            i += 1
            continue

        # Regular line or annotation — may be a prefix for the next block header
        if stack:
            stack[-1]["children"].append(line)
        else:
            # Could be an @Override / @DynamicComponentDependency that belongs to the next block
            pending_header_lines.append(line)

        i += 1

    # Flush unclosed blocks
    while stack:
        block = stack.pop()
        block["footer"] = None
        if stack:
            stack[-1]["children"].append(block)
        else:
            items.append(block)

    # Flush any remaining pending lines
    for l in pending_header_lines:
        items.append({"type": "line", "text": l})

    return items


def _dsl_item_key(item: dict) -> str:
    """
    Return the canonical identity key for a DSL item.
    For blocks: the stripped header text (multi-line headers collapsed).
    For lines: the stripped text.
    """
    if item["type"] == "block":
        return item["header"].strip().replace("\n", " ")
    return item["text"].strip()


def _render_dsl_item(item: dict) -> list[str]:
    if item["type"] == "line":
        return [item["text"]]
    out = [item["header"]]
    for child in item["children"]:
        if isinstance(child, dict):
            out.extend(_render_dsl_item(child))
        else:
            out.append(child)
    if item.get("footer") is not None:
        out.append(item["footer"])
    return out


# ── PL/SQL merge (.plsql, .plsvc, .pltst) ────────────────────────────────────

def _merge_plsql(local: list[str], repo: list[str]) -> str:
    """
    Merge PL/SQL lines.

    IFS PL/SQL files contain named PROCEDURE/FUNCTION units and IFS section
    comment dividers (---- PUBLIC METHODS ----).  The correct resolution is
    always to keep ALL content from both sides; the section dividers often
    appear at different positions in local vs repo (one side has it at the
    top of the conflict, the other at the bottom), so using sequence-diff
    would collapse them to one occurrence.  Plain concatenation (local then
    repo) is the correct and expected output.
    """
    return _concat(local, repo)


# ── DDL / CDB merge ───────────────────────────────────────────────────────────

def _merge_ddl(local: list[str], repo: list[str]) -> str:
    """
    Merge DDL/CDB lines.

    @CodeRegistration blocks are keyed by their registration name.
    Blocks with different names are kept from both sides.
    History header (if present) was already merged before this is called.
    """
    local_blocks = _parse_ddl_blocks(local)
    repo_blocks  = _parse_ddl_blocks(repo)

    local_keys = [b["key"] for b in local_blocks]
    repo_keys  = [b["key"] for b in repo_blocks]

    matcher = difflib.SequenceMatcher(None, local_keys, repo_keys, autojunk=False)
    merged: list[str] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                merged.extend(local_blocks[i1 + k]["lines"])
        elif tag == "delete":
            for b in local_blocks[i1:i2]:
                merged.extend(b["lines"])
        elif tag == "insert":
            for b in repo_blocks[j1:j2]:
                merged.extend(b["lines"])
        elif tag == "replace":
            for b in local_blocks[i1:i2]:
                merged.extend(b["lines"])
            for b in repo_blocks[j1:j2]:
                merged.extend(b["lines"])

    return "".join(merged)


def _parse_ddl_blocks(lines: list[str]) -> list[dict]:
    blocks: list[dict] = []
    current_key   = "__preamble__"
    current_lines: list[str] = []

    for line in lines:
        m = _CODE_REG.match(line)
        if m:
            if current_lines:
                blocks.append({"key": current_key, "lines": current_lines})
            current_key   = m.group(1).upper()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        blocks.append({"key": current_key, "lines": current_lines})

    return blocks


# ── XML Entity merge (.entity) ────────────────────────────────────────────────

def _merge_xml_entity(local: list[str], repo: list[str]) -> str:
    """
    Merge .entity XML lines.

    The .entity XML format contains repeating child elements such as
    <ATTRIBUTE>, <ASSOCIATION>, <COMMENT> each identified by a <NAME> child.
    When both sides add a DIFFERENT named element we keep both.
    When the conflict cuts through an element boundary (git doesn't know XML),
    we fall back to plain concatenation.
    """
    local_elements = _parse_xml_elements(local)
    repo_elements  = _parse_xml_elements(repo)

    if not local_elements or not repo_elements:
        return _concat(local, repo)

    local_keys = [e["key"] for e in local_elements]
    repo_keys  = [e["key"] for e in repo_elements]

    matcher = difflib.SequenceMatcher(None, local_keys, repo_keys, autojunk=False)
    merged: list[str] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                merged.extend(local_elements[i1 + k]["lines"])
        elif tag == "delete":
            for e in local_elements[i1:i2]:
                merged.extend(e["lines"])
        elif tag == "insert":
            for e in repo_elements[j1:j2]:
                merged.extend(e["lines"])
        elif tag == "replace":
            for e in local_elements[i1:i2]:
                merged.extend(e["lines"])
            for e in repo_elements[j1:j2]:
                merged.extend(e["lines"])

    return "".join(merged)


_XML_ELEM_START = re.compile(r'^\s*<([A-Z_]+)>')
_XML_ELEM_END   = re.compile(r'^\s*</([A-Z_]+)>')

def _parse_xml_elements(lines: list[str]) -> list[dict] | None:
    """
    Try to parse lines as a sequence of top-level XML elements.
    Returns a list of {key, lines} or None if parsing fails.
    Each element's key is derived from its <NAME> child if present,
    otherwise from its tag name + index.
    """
    elements: list[dict] = []
    depth  = 0
    current_tag   = None
    current_lines: list[str] = []
    preamble: list[str] = []

    for line in lines:
        start_m = _XML_ELEM_START.match(line)
        end_m   = _XML_ELEM_END.match(line)

        if start_m and depth == 0:
            if preamble:
                elements.append({"key": "__preamble__", "lines": preamble})
                preamble = []
            current_tag   = start_m.group(1)
            current_lines = [line]
            depth = 1
        elif end_m and depth == 1 and end_m.group(1) == current_tag:
            current_lines.append(line)
            # Extract <NAME> from children
            content = "".join(current_lines)
            nm = _XML_NAME_TAG.search(content)
            key = f"{current_tag}:{nm.group(1).strip()}" if nm else f"{current_tag}:{len(elements)}"
            elements.append({"key": key, "lines": current_lines})
            current_tag   = None
            current_lines = []
            depth = 0
        elif depth > 0:
            current_lines.append(line)
            if start_m:
                depth += 1
            elif end_m:
                depth -= 1
        else:
            preamble.append(line)

    # If we have unclosed elements the XML is a partial fragment — fall back
    if depth > 0:
        return None

    if preamble:
        elements.append({"key": "__trailing__", "lines": preamble})

    return elements if elements else None


# ── Views merge (.views) ──────────────────────────────────────────────────────

_VIEWS_COLUMN = re.compile(r'^COLUMN\s+(\S+)\s+IS', re.IGNORECASE)
_VIEWS_VIEW   = re.compile(r'^VIEW\s+(\S+)\s+IS', re.IGNORECASE)

def _merge_views(local: list[str], repo: list[str]) -> str:
    """
    Merge .views property-override blocks.

    COLUMN X IS ... / VIEW X IS ... blocks are keyed by their name.
    Blocks with different names → keep both.
    Blocks with the same name → keep both (user resolves the difference).
    """
    local_blocks = _parse_views_blocks(local)
    repo_blocks  = _parse_views_blocks(repo)

    local_keys = [b["key"] for b in local_blocks]
    repo_keys  = [b["key"] for b in repo_blocks]

    matcher = difflib.SequenceMatcher(None, local_keys, repo_keys, autojunk=False)
    merged: list[str] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                merged.extend(local_blocks[i1 + k]["lines"])
        elif tag == "delete":
            for b in local_blocks[i1:i2]:
                merged.extend(b["lines"])
        elif tag == "insert":
            for b in repo_blocks[j1:j2]:
                merged.extend(b["lines"])
        elif tag == "replace":
            for b in local_blocks[i1:i2]:
                merged.extend(b["lines"])
            for b in repo_blocks[j1:j2]:
                merged.extend(b["lines"])

    return "".join(merged)


def _parse_views_blocks(lines: list[str]) -> list[dict]:
    blocks: list[dict] = []
    current_key   = "__preamble__"
    current_lines: list[str] = []

    for line in lines:
        mc = _VIEWS_COLUMN.match(line)
        mv = _VIEWS_VIEW.match(line)
        if mc or mv:
            if current_lines:
                blocks.append({"key": current_key, "lines": current_lines})
            name = (mc or mv).group(1).upper()
            prefix = "COLUMN" if mc else "VIEW"
            current_key   = f"{prefix}:{name}"
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        blocks.append({"key": current_key, "lines": current_lines})

    return blocks


# ── IFS History-comment header helpers ────────────────────────────────────────

def _find_history_header_end(lines: list[str]) -> int | None:
    """
    Return index of the first line AFTER the IFS history header block, or None.

    Header pattern:
        --  Date    Sign    History
        --  ------  ------  ----...
        --  YYYYMMDD  Sign  description   (one or more)
        -------...   (long separator, 20+ dashes)
    """
    n = len(lines)
    i = 0

    while i < n and not lines[i].strip():
        i += 1

    if i >= n or not _HIST_DATE.search(lines[i]):
        return None
    i += 1

    if i >= n or not _HIST_DASHES.search(lines[i]):
        return None
    i += 1

    entry_count = 0
    while i < n and _HIST_ENTRY.search(lines[i]):
        i += 1
        entry_count += 1

    if entry_count == 0:
        return None

    if i < n and _HIST_SEP.match(lines[i].rstrip()):
        i += 1
        return i

    return None


def _merge_history_headers(local_hdr: list[str], repo_hdr: list[str]) -> list[str]:
    """
    Merge two IFS history comment headers into one.
    Keeps local's structure; appends any repo date-entries not already in local.
    """
    local_entries = [l for l in local_hdr if _HIST_ENTRY.search(l)]
    repo_entries  = [l for l in repo_hdr  if _HIST_ENTRY.search(l)]

    seen  = {l.strip() for l in local_entries}
    extra = [l for l in repo_entries if l.strip() not in seen]

    merged: list[str] = []
    entries_written = False

    for line in local_hdr:
        if _HIST_ENTRY.search(line):
            if not entries_written:
                merged.extend(local_entries)
                merged.extend(extra)
                entries_written = True
            # original local entry line already included above
        else:
            merged.append(line)

    return merged


# ── Plain concatenation fallback ──────────────────────────────────────────────

def _concat(local: list[str], repo: list[str]) -> str:
    """
    Fallback: local content followed by repo content.
    Strips leading blank lines from the repo side to avoid excess whitespace
    at the join point, then ensures a single newline separator.
    """
    local_text = "".join(local)
    repo_text  = "".join(repo).lstrip("\n")

    if not local_text:
        return repo_text
    if not repo_text:
        return local_text

    if not local_text.endswith("\n"):
        local_text += "\n"

    return local_text + repo_text


# ── Resolution writer ─────────────────────────────────────────────────────────

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
