from __future__ import annotations
import re
import difflib
from pathlib import Path
from core.file_types import IFS_FILE_TYPES
from core.beautifier import beautify, strip_blank_lines
from core.core_registry import CoreFileRegistry, FileSchema, _EMPTY_SCHEMA

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

# ── IFS annotation line (marks the NEXT block, belongs to its header) ─────────
# Only @-prefixed annotations qualify; change markers (--(+)...) do NOT.
_ANN_LINE = re.compile(
    r'^\s*(?:@Override|@Overtake\s+Core|@DynamicComponentDependency\s+\S+|@CodeRegistration\s+\S+)\s*$',
    re.IGNORECASE,
)


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


def _prefix_depth(lines: list[str], upto: int) -> int:
    """
    Brace nesting depth of the file at line index `upto`.
    Earlier conflict hunks count only their local (HEAD) side so the depth
    reflects what the resolved file will look like.
    """
    depth = 0
    in_repo_side = False
    for line in lines[:upto]:
        r = line.rstrip()
        if CONFLICT_START.match(line):
            in_repo_side = False
            continue
        if CONFLICT_SEP.match(r):
            in_repo_side = True
            continue
        if CONFLICT_END.match(line):
            in_repo_side = False
            continue
        if in_repo_side:
            continue
        depth += line.count("{") - line.count("}")
    return max(0, depth)


def parse_conflicts(file_path: str) -> list[dict]:
    path = Path(file_path)
    ext  = path.suffix.lower()

    # Load core file schema for this file (used to guide structural merge)
    schema = CoreFileRegistry.instance().schema_for(file_path)

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
            base_depth = _prefix_depth(lines, start)
            local_text = beautify("".join(local_lines).rstrip(), ext, base_depth)
            repo_text  = beautify("".join(repo_lines).rstrip(), ext, base_depth)

            local_b = [l + "\n" for l in local_text.splitlines()] if local_text else []
            repo_b  = [l + "\n" for l in repo_text.splitlines()]  if repo_text  else []

            try:
                diff = _build_diff(local_b, repo_b, start + 1)
            except Exception:
                diff = []

            raw_preview = _smart_merge_both(local_lines, repo_lines, ext, schema)
            raw_preview = _validate_braces(local_lines, repo_lines, raw_preview)
            preview     = strip_blank_lines(beautify(raw_preview, ext, base_depth))

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

def _smart_merge_both(local_lines: list[str], repo_lines: list[str], ext: str = "",
                      schema: "FileSchema | None" = None) -> str:
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
        body = _merge_body(local_body, repo_body, ext, schema)
        return ("".join(merged_hdr) + body).rstrip()

    # Step 2: structural body merge based on file type
    return _merge_body(local_lines, repo_lines, ext, schema).rstrip()


def _merge_body(local: list[str], repo: list[str], ext: str,
                schema: "FileSchema | None" = None) -> str:
    """
    Merge body lines according to the structural rules of the file type.
    schema (optional): parsed core file schema used to disambiguate blocks.
    """
    if not local:
        return "".join(repo)
    if not repo:
        return "".join(local)

    # Marble DSL — brace-delimited block language
    if ext in (".projection", ".client", ".fragment"):
        return _merge_dsl(local, repo, schema)

    # PL/SQL — named procedure/function units
    if ext in (".plsql", ".plsvc", ".pltst"):
        return _merge_plsql(local, repo)

    # DDL — @CodeRegistration anonymous blocks
    if ext in (".ddlsource", ".cdb"):
        return _merge_ddl(local, repo)

    # XML — element-keyed by <NAME> or <ID>
    if ext in (".entity", ".utility", ".enumeration"):
        return _merge_xml_entity(local, repo)

    # Views — COLUMN/VIEW property blocks
    if ext == ".views":
        return _merge_views(local, repo)

    # Default: plain concatenation
    return _concat(local, repo)


# ── Marble DSL merge ──────────────────────────────────────────────────────────

def _merge_item_lists(local_items: list[dict], repo_items: list[dict],
                      schema: "FileSchema | None" = None) -> list[dict]:
    """
    Merge two already-parsed DSL item lists using SequenceMatcher.
    Used after _unwrap_if_asymmetric to merge the flattened children without
    duplicating items that appear on both sides.
    """
    local_keys = [_dsl_item_key(it) for it in local_items]
    repo_keys  = [_dsl_item_key(it) for it in repo_items]
    matcher = difflib.SequenceMatcher(None, local_keys, repo_keys, autojunk=False)
    result: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                l_it = local_items[i1 + k]
                r_it = repo_items[j1 + k]
                if l_it.get("type") == "block" and r_it.get("type") == "block":
                    result.append(_dsl_overtake_wins(l_it, r_it, schema))
                else:
                    result.append(l_it)
        elif tag == "delete":
            result.extend(local_items[i1:i2])
        elif tag == "insert":
            result.extend(repo_items[j1:j2])
        elif tag == "replace":
            result.extend(local_items[i1:i2])
            result.extend(repo_items[j1:j2])
    return result


def _merge_dsl(local: list[str], repo: list[str],
               schema: "FileSchema | None" = None) -> str:
    """
    Merge two Marble DSL line lists.

    Algorithm:
    1. Parse both sides into items (named blocks or loose lines).
    2. Sequence-diff on canonical keys (annotation-stripped, whitespace-normalised).
    3. equal  → same-named block: merge children recursively.
               @Overtake Core beats @Override — winning side kept whole.
               Core schema guard: if schema says both keys are separate
               top-level blocks, skip child-merge and keep both blocks intact.
    4. delete → local-only: keep.
    5. insert → repo-only: keep.
    6. replace → check asymmetric wrap before concatenating.
               Asymmetric: one side has a single WRAPPER block, other has
               only leaf items → unwrap the wrapper IF the core schema does
               NOT declare it as a separate top-level block at this level.
    """
    local_items = _parse_dsl_items(local)
    repo_items  = _parse_dsl_items(repo)

    local_keys = [_dsl_item_key(it) for it in local_items]
    repo_keys  = [_dsl_item_key(it) for it in repo_items]

    matcher = difflib.SequenceMatcher(None, local_keys, repo_keys, autojunk=False)
    merged_items: list[dict] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                local_it = local_items[i1 + k]
                repo_it  = repo_items[j1 + k]
                if local_it.get("type") == "block" and repo_it.get("type") == "block":
                    merged_items.append(_dsl_overtake_wins(local_it, repo_it, schema))
                else:
                    merged_items.append(local_it)

        elif tag == "delete":
            merged_items.extend(local_items[i1:i2])

        elif tag == "insert":
            merged_items.extend(repo_items[j1:j2])

        elif tag == "replace":
            local_chunk = local_items[i1:i2]
            repo_chunk  = repo_items[j1:j2]
            local_chunk, repo_chunk, did_unwrap, trailer = _unwrap_if_asymmetric(
                local_chunk, repo_chunk, schema
            )
            if did_unwrap:
                # Re-run SequenceMatcher on the unwrapped children so shared
                # attributes are merged once rather than duplicated.
                merged_items.extend(
                    _merge_item_lists(local_chunk, repo_chunk, schema)
                )
                # Append any trailing close-braces AFTER all merged content.
                # (Case B: the '}' that closes the surrounding entity block.)
                merged_items.extend(trailer)
            else:
                merged_items.extend(local_chunk)
                merged_items.extend(repo_chunk)

    # Reorder top-level blocks to follow core file structure.
    # New (Cust-layer) blocks not present in the core file go at the end.
    if schema and schema.found:
        merged_items = _reorder_by_schema(merged_items, schema)

    merged: list[str] = []
    for it in merged_items:
        merged.extend(_render_dsl_item(it))

    return "".join(merged)


# DSL keywords whose blocks act as wrappers (can contain attribute/field children).
# Leaf-level blocks (attribute, field, badge, commandgroup, …) are NOT in this list.
_DSL_WRAPPER_KW = re.compile(
    r'\b(entity|entityset|query|virtual|summary|singleton|structure|'
    r'list|page|dialog|group|selector|navigator|aggregate|array|reference)\b',
    re.IGNORECASE,
)


def _is_wrapper_block(item: dict) -> bool:
    return (item.get("type") == "block"
            and bool(_DSL_WRAPPER_KW.search(item.get("header", ""))))


def _unwrap_if_asymmetric(
    local_items: list[dict], repo_items: list[dict],
    schema: "FileSchema | None" = None,
) -> tuple[list[dict], list[dict]]:
    """
    Handle the asymmetric conflict where one branch re-declared the surrounding
    WRAPPER block (entity/list/page/dialog/…) while the other just added
    leaf children inside the already-open block.

    Core schema guard (critical):
    If the schema from the core file declares the wrapper block's key as a
    known top-level block, it means this block IS a legitimate separate block
    in the file — do NOT unwrap it.  This prevents entity InventoryPart's
    children from being incorrectly inserted into entity InventoryQuality when
    a conflict hunk spans both entities.

    Wrapper keywords: entity, entityset, query, list, page, dialog, group,
    selector, navigator, structure, virtual, summary, singleton, aggregate.
    Leaf keywords (attribute, field, badge, commandgroup, …) are NOT unwrapped.
    """
    def _sole_wrapper(items: list[dict]) -> dict | None:
        wrappers = [it for it in items if _is_wrapper_block(it)]
        return wrappers[0] if len(wrappers) == 1 else None

    def _has_no_wrappers(items: list[dict]) -> bool:
        return not any(_is_wrapper_block(it) for it in items)

    def _has_unmatched_close(items: list[dict]) -> bool:
        return any(
            it.get("type") == "line" and it.get("text", "").strip() == "}"
            for it in items
        )

    def _should_unwrap(wrapper: dict, flat_has_close: bool) -> bool:
        """
        Decide whether to unwrap 'wrapper' given that the flat side may have
        an unmatched closing brace.

        Three cases:
        A) flat_has_close=False  — conflict is cleanly inside an open block.
           Both sides talk about the SAME entity context → always unwrap.

        B) flat_has_close=True, wrapper.footer is not None (complete block)
           — flat side closes the outer block, wrapper ALSO closes itself within
           the hunk.  This means the wrapper is a re-declaration of the SAME
           entity (common in Cust layers that use @Override entity X { ... }).
           → unwrap and merge children.

        C) flat_has_close=True, wrapper.footer is None (unclosed block)
           — flat side closes the outer block, wrapper is NOT closed in the hunk
           (its '}' is outside the conflict markers, i.e. it is a brand-new
           separate top-level entity added by the repo branch).
           → do NOT unwrap; keep both sides intact.
        """
        if not flat_has_close:
            return True                            # Case A
        return wrapper.get("footer") is not None   # Case B=True, Case C=False

    local_sole = _sole_wrapper(local_items)
    repo_sole  = _sole_wrapper(repo_items)

    def _split_trailing_close(items: list[dict]) -> tuple[list[dict], list[dict]]:
        """
        Separate trailing unmatched-close line items (standalone '}') from the
        rest of the items.  In Case B the '}' closes the surrounding entity and
        must be placed AFTER all merged children, not wherever SequenceMatcher
        happens to put it.
        Returns (items_without_close, close_items).
        """
        body: list[dict] = []
        trailer: list[dict] = []
        for it in items:
            if it.get("type") == "line" and it.get("text", "").strip() == "}":
                trailer.append(it)
            else:
                body.append(it)
        return body, trailer

    # Returns (local_items, repo_items, did_unwrap, trailer)
    # trailer: items that must be appended AFTER the merged content (e.g. the
    # closing brace from Case B that closes the surrounding entity block).
    if repo_sole is not None and _has_no_wrappers(local_items):
        local_has_close = _has_unmatched_close(local_items)
        if _should_unwrap(repo_sole, local_has_close):
            child_lines = _children_to_lines(repo_sole)
            repo_children = _parse_dsl_items(child_lines)
            if local_has_close:
                # Case B: strip the closing '}' so it doesn't appear mid-merge;
                # it will be re-appended after all merged attributes.
                local_body, trailer = _split_trailing_close(local_items)
                return local_body, repo_children, True, trailer
            return local_items, repo_children, True, []

    if local_sole is not None and _has_no_wrappers(repo_items):
        repo_has_close = _has_unmatched_close(repo_items)
        if _should_unwrap(local_sole, repo_has_close):
            child_lines = _children_to_lines(local_sole)
            local_children = _parse_dsl_items(child_lines)
            if repo_has_close:
                repo_body, trailer = _split_trailing_close(repo_items)
                return local_children, repo_body, True, trailer
            return local_children, repo_items, True, []

    return local_items, repo_items, False, []


def _merge_dsl_block(local_block: dict, repo_block: dict,
                     schema: "FileSchema | None" = None) -> dict:
    """
    Merge two DSL blocks that share the same declaration (same key).
    Renders both children lists back to lines, merges them with _merge_dsl
    (recursive), then wraps the result back into a single block dict.
    """
    local_child_lines = _children_to_lines(local_block)
    repo_child_lines  = _children_to_lines(repo_block)
    merged_text = _merge_dsl(local_child_lines, repo_child_lines, schema)
    merged_lines = (merged_text + "\n").splitlines(keepends=True) if merged_text else []
    return {
        "type":     "block",
        "header":   local_block["header"],
        "children": [{"type": "line", "text": l} for l in merged_lines],
        "footer":   local_block.get("footer") or repo_block.get("footer"),
    }


def _children_to_lines(block: dict) -> list[str]:
    """Render a block's children back to a flat list of strings."""
    out: list[str] = []
    for child in block["children"]:
        if isinstance(child, dict):
            out.extend(_render_dsl_item(child))
        else:
            out.append(child)
    return out


def _parse_dsl_items(lines: list[str]) -> list[dict]:
    """
    Parse Marble DSL lines into a list of items:
      {'type': 'block', 'header': str, 'children': [item|str, ...], 'footer': str|None}
      {'type': 'line',  'text': str}

    Rules:
    - Only true @-annotation lines (@Override, @DynamicComponentDependency, etc.)
      appearing immediately before a block opener are accumulated into that block's
      header.  IFS change markers (--(+)...) and other comment lines are stored as
      independent line items — they are NOT merged into a following block's header.
    - A closing '}' that appears when the stack is empty is stored as a plain line
      item.  It means the conflict hunk crosses a block boundary (the brace closes
      a block that was opened BEFORE the hunk started).
    - A block is added to its parent (or to the top-level items list) only when it
      CLOSES — not when it opens — to avoid double-append.
    - Unclosed blocks at end of input are flushed with footer=None (the closing brace
      was outside the conflict hunk).
    """
    items: list[dict] = []
    stack: list[dict] = []     # currently open (unclosed) blocks
    pending: list[str] = []    # @-annotation lines waiting for the next block opener

    def _flush_pending_as_lines() -> None:
        """Emit any queued pending lines as plain line items (no block followed)."""
        for p in pending:
            items.append({"type": "line", "text": p})
        pending.clear()

    for line in lines:
        stripped = line.strip()

        # ── blank line ────────────────────────────────────────────────────────
        if not stripped:
            if stack:
                stack[-1]["children"].append(line)
            else:
                _flush_pending_as_lines()
                items.append({"type": "line", "text": line})
            continue

        # ── closing brace ─────────────────────────────────────────────────────
        if _DSL_BLOCK_CLOSE.match(stripped):
            if stack:
                block = stack.pop()
                block["footer"] = line
                pending.clear()
                if stack:
                    stack[-1]["children"].append(block)
                else:
                    items.append(block)
            else:
                # Unmatched close: the hunk crosses a block boundary.
                # Store as a plain line so _has_unmatched_close() can detect it.
                _flush_pending_as_lines()
                items.append({"type": "line", "text": line})
            continue

        # ── opening brace (block header) ──────────────────────────────────────
        if _DSL_BLOCK_OPEN.search(stripped) and stripped.endswith("{"):
            pending.append(line)
            header = "".join(pending)
            pending.clear()
            new_block: dict = {"type": "block", "header": header, "children": [], "footer": None}
            if stack:
                stack.append(new_block)
            else:
                stack.append(new_block)
            continue

        # ── regular line ──────────────────────────────────────────────────────
        if stack:
            stack[-1]["children"].append(line)
        elif _ANN_LINE.match(stripped):
            # True @-annotation — belongs to the NEXT block opener
            pending.append(line)
        else:
            # Change marker, comment, or bare text: emit immediately.
            # Flush any preceding annotation lines that didn't find a block.
            _flush_pending_as_lines()
            items.append({"type": "line", "text": line})

    # ── end of input: flush any unclosed blocks ───────────────────────────────
    while stack:
        block = stack.pop()
        block["footer"] = None   # closing brace was outside this conflict hunk
        if stack:
            stack[-1]["children"].append(block)
        else:
            items.append(block)

    # Flush any trailing annotation lines that had no following block
    _flush_pending_as_lines()

    return items


_ANN_PREFIX = re.compile(
    r'^\s*(?:@Override|@Overtake\s+Core|@DynamicComponentDependency\s+\S+|@CodeRegistration\s+\S+)\s*\n?',
    re.IGNORECASE | re.MULTILINE,
)


# ── Brace validation ──────────────────────────────────────────────────────────

def _net_braces(text: str) -> int:
    """Count '{' minus '}', ignoring characters inside string literals."""
    depth = 0
    in_str = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == '"' and not in_str:
            in_str = True
        elif ch == '"' and in_str:
            in_str = False
        elif not in_str:
            if ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
        i += 1
    return depth


def _validate_braces(local_lines: list[str], repo_lines: list[str], merged: str) -> str:
    """
    Compare the brace balance of the merged output against the combined inputs.
    If the merge introduced extra or missing braces, append a warning comment so
    the developer is alerted without the tool making potentially wrong auto-fixes.

    A conflict hunk is often INSIDE a block, so both sides having net < 0 is
    normal (the outer close is outside the hunk).  We compare relative balance:
    merged_net should equal local_net + repo_net when nothing was lost or doubled.
    For 'Keep Both' semantics the merged output may legitimately differ — we only
    warn when the difference is outside a reasonable range.
    """
    local_net  = _net_braces("".join(local_lines))
    repo_net   = _net_braces("".join(repo_lines))
    merged_net = _net_braces(merged)

    # When both sides have the same net, the merged output should too
    if local_net == repo_net and merged_net != local_net:
        delta = merged_net - local_net
        sign = "+" if delta > 0 else ""
        merged = merged.rstrip() + (
            f"\n-- [MERGE WARNING: brace mismatch detected (net {sign}{delta})."
            f" Please review bracket balance before committing.]\n"
        )
    return merged


# ── Core-file-guided block ordering ──────────────────────────────────────────

def _reorder_by_schema(items: list[dict], schema: "FileSchema") -> list[dict]:
    """
    Reorder top-level block items to match the order in the core file.
    - Blocks whose key is known to the core file appear in core-file order.
    - New blocks (Cust-layer additions not in the core file) are appended after
      known blocks, preserving their relative order among themselves.
    - Loose line items (change markers, blank lines) stay grouped with the block
      they immediately precede in the current sequence.
    """
    if not schema or not schema.found or not schema.ordered_keys:
        return items

    # Group items into (leading_lines, block) pairs + trailing lines
    groups: list[tuple[list[dict], dict | None]] = []
    leading: list[dict] = []
    for it in items:
        if it.get("type") == "line":
            leading.append(it)
        else:
            groups.append((leading, it))
            leading = []
    trailing = leading  # any lines after the last block

    if not groups:
        return items  # no blocks to reorder

    # Separate known (core-file) blocks from new (Cust-layer) blocks
    known: list[tuple[int, list[dict], dict]] = []   # (core_index, leading_lines, block)
    new_blocks: list[tuple[list[dict], dict]]  = []  # (leading_lines, block)

    for lead, block in groups:
        raw_key = _dsl_item_key(block).rstrip("{").strip()
        idx = schema.core_order(raw_key)
        if idx >= 0:
            known.append((idx, lead, block))
        else:
            new_blocks.append((lead, block))

    known.sort(key=lambda x: x[0])

    result: list[dict] = []
    for _, lead, block in known:
        result.extend(lead)
        result.append(block)
    for lead, block in new_blocks:
        result.extend(lead)
        result.append(block)
    result.extend(trailing)
    return result


def _dsl_item_key(item: dict) -> str:
    """
    Canonical identity key for a DSL item used for SequenceMatcher alignment.

    For blocks: strip annotation prefixes (@Override, @Overtake Core,
    @DynamicComponentDependency) then normalise whitespace.  This ensures
    that '@Override entity InventoryPart {' and 'entity InventoryPart {'
    are treated as the SAME block so they get merged rather than duplicated.

    For loose lines: stripped text.
    """
    if item["type"] == "block":
        raw = item["header"].strip()
        # Strip all leading annotation lines, then normalise whitespace
        stripped = _ANN_PREFIX.sub("", raw).strip()
        return re.sub(r'\s+', ' ', stripped)
    return item["text"].strip()


def _dsl_overtake_wins(local_it: dict, repo_it: dict,
                       schema: "FileSchema | None" = None) -> dict:
    """
    When both sides have the same block key but one carries @Overtake Core,
    that version completely replaces the other (no child-merging).
    Returns the winning item.
    """
    local_hdr = local_it.get("header", "")
    repo_hdr  = repo_it.get("header", "")
    local_overtake = bool(re.search(r'@Overtake\s+Core', local_hdr, re.IGNORECASE))
    repo_overtake  = bool(re.search(r'@Overtake\s+Core', repo_hdr,  re.IGNORECASE))
    if local_overtake and not repo_overtake:
        return local_it
    if repo_overtake and not local_overtake:
        return repo_it
    # Both override or neither — merge children recursively
    return _merge_dsl_block(local_it, repo_it, schema)


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

_PLSQL_UNIT_START = re.compile(
    r'^\s*(?:@Override\s+)?(PROCEDURE|FUNCTION)\s+(\w+)',
    re.IGNORECASE,
)
_PLSQL_UNIT_END = re.compile(
    r'^\s*END\s+(\w+)\s*;',
    re.IGNORECASE,
)
_PLSQL_SECTION = re.compile(r'^-{4,}.*-{4,}\s*$')


def _merge_plsql(local: list[str], repo: list[str]) -> str:
    """
    Merge PL/SQL lines (IFS .plsql / .plsvc / .pltst).

    IFS PL/SQL files are structured as named PROCEDURE/FUNCTION units
    separated by IFS section dividers (---- PUBLIC METHODS ----).

    Deduplication rules (matching IFS layering standards):
    - Same-named unit on both sides → keep LOCAL version (it is the
      working branch; repo changes are already present as the base).
    - Unit only on one side → keep it.
    - IFS section dividers → deduplicate by name (keep one occurrence).
    - Preamble content (TYPE declarations, SUBTYPE, constants) → merge
      using sequence-diff to avoid duplicating shared declarations.

    Section header comment dividers (---- … ----) are kept once even
    when both sides carry them at different positions.
    """
    local_units = _parse_plsql_units(local)
    repo_units  = _parse_plsql_units(repo)

    local_keys = [u["key"] for u in local_units]
    repo_keys  = [u["key"] for u in repo_units]

    matcher = difflib.SequenceMatcher(None, local_keys, repo_keys, autojunk=False)
    merged: list[str] = []
    seen_sections: set[str] = set()

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                unit = local_units[i1 + k]
                if unit["kind"] == "section":
                    key = unit["key"]
                    if key not in seen_sections:
                        seen_sections.add(key)
                        merged.extend(unit["lines"])
                else:
                    merged.extend(unit["lines"])

        elif tag == "delete":
            # Local-only content — keep it
            for u in local_units[i1:i2]:
                if u["kind"] == "section":
                    key = u["key"]
                    if key not in seen_sections:
                        seen_sections.add(key)
                        merged.extend(u["lines"])
                else:
                    merged.extend(u["lines"])

        elif tag == "insert":
            # Repo-only content — keep it
            for u in repo_units[j1:j2]:
                if u["kind"] == "section":
                    key = u["key"]
                    if key not in seen_sections:
                        seen_sections.add(key)
                        merged.extend(u["lines"])
                else:
                    merged.extend(u["lines"])

        elif tag == "replace":
            local_chunk = local_units[i1:i2]
            repo_chunk  = repo_units[j1:j2]

            # For named procedure/function units: same name on both sides →
            # keep local (branch version), discard repo duplicate.
            local_proc_keys = {u["key"] for u in local_chunk if u["kind"] == "proc"}
            for u in local_chunk:
                if u["kind"] == "section":
                    key = u["key"]
                    if key not in seen_sections:
                        seen_sections.add(key)
                        merged.extend(u["lines"])
                else:
                    merged.extend(u["lines"])
            for u in repo_chunk:
                if u["kind"] == "proc" and u["key"] in local_proc_keys:
                    continue   # duplicate — repo version already covered by local
                if u["kind"] == "section":
                    key = u["key"]
                    if key not in seen_sections:
                        seen_sections.add(key)
                        merged.extend(u["lines"])
                else:
                    merged.extend(u["lines"])

    return "".join(merged)


def _parse_plsql_units(lines: list[str]) -> list[dict]:
    """
    Parse PL/SQL lines into units:
      {"kind": "proc",    "key": "PROCEDURE_FOO",      "lines": [...]}
      {"kind": "section", "key": "SECTION:---- PUB --", "lines": [...]}
      {"kind": "other",   "key": "__other_N__",         "lines": [...]}

    A unit starts at PROCEDURE/FUNCTION declaration (with optional @Override)
    and ends at the matching END <name>; line.  Section dividers (---- … ----)
    are captured as single-line units.  Everything else is "other".
    """
    units: list[dict] = []
    current_lines: list[str] = []
    current_kind  = "other"
    current_key   = "__preamble__"
    in_proc       = False
    proc_name     = ""
    depth         = 0   # BEGIN/END depth inside a proc body

    _KW_BEGIN = re.compile(r'\bBEGIN\b', re.IGNORECASE)
    _KW_END   = re.compile(r'\bEND\b',   re.IGNORECASE)

    def flush():
        nonlocal current_lines, current_kind, current_key
        if current_lines:
            units.append({"kind": current_kind, "key": current_key, "lines": current_lines})
        current_lines = []
        current_kind  = "other"
        current_key   = f"__other_{len(units)}__"

    for line in lines:
        stripped = line.strip()

        # IFS section divider  (---- PUBLIC METHODS ----)
        if _PLSQL_SECTION.match(stripped) and not in_proc:
            flush()
            key = re.sub(r'\s+', ' ', stripped)
            units.append({"kind": "section", "key": f"SECTION:{key}", "lines": [line]})
            continue

        # PROCEDURE / FUNCTION start
        m = _PLSQL_UNIT_START.match(stripped)
        if m and not in_proc:
            flush()
            proc_name   = m.group(2).upper()
            current_kind = "proc"
            current_key  = f"{m.group(1).upper()}_{proc_name}"
            current_lines = [line]
            in_proc = True
            depth   = 0
            continue

        if in_proc:
            current_lines.append(line)
            # Track nested BEGIN/END to find the matching END <name>;
            if _KW_BEGIN.search(stripped):
                depth += 1
            end_m = _PLSQL_UNIT_END.match(stripped)
            if end_m and end_m.group(1).upper() == proc_name:
                # Matched END <name>; — close this unit
                flush()
                in_proc = False
                proc_name = ""
                depth = 0
            elif _KW_END.search(stripped) and depth > 0:
                depth -= 1
            continue

        current_lines.append(line)

    flush()
    return units


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
            local_chunk = local_blocks[i1:i2]
            repo_chunk  = repo_blocks[j1:j2]
            local_reg_keys = {b["key"] for b in local_chunk
                              if not b["key"].startswith("__")}
            for b in local_chunk:
                merged.extend(b["lines"])
            for b in repo_chunk:
                # Same @CodeRegistration name on both sides → keep local only.
                # Different name → keep repo (additive, new migration script).
                if b["key"] not in local_reg_keys:
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
    Merge XML files: .entity (state machine / entity descriptor),
    .utility (LU registration), .enumeration (enum value list).

    Each top-level XML element is keyed by its <NAME> child (or <ID> for
    diagram nodes).  Elements with the same key from both sides are
    deduplicated — the local version is kept.  Elements with different
    keys are kept from both sides (additive merge).

    Falls back to plain concatenation when the XML cannot be parsed as a
    clean sequence of top-level elements (e.g. conflict cuts mid-element).
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
            local_chunk = local_elements[i1:i2]
            repo_chunk  = repo_elements[j1:j2]
            local_elem_keys = {e["key"] for e in local_chunk
                               if not e["key"].startswith("__")}
            for e in local_chunk:
                merged.extend(e["lines"])
            for e in repo_chunk:
                # Same-named element already emitted from local → skip duplicate
                if e["key"] not in local_elem_keys:
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
            content = "".join(current_lines)
            # Prefer <NAME> as identity key; fall back to <ID> (diagram nodes), then index
            nm = _XML_NAME_TAG.search(content)
            if nm:
                key = f"{current_tag}:{nm.group(1).strip()}"
            else:
                id_m = re.search(r'<ID>(.+?)</ID>', content, re.IGNORECASE)
                key = f"{current_tag}:{id_m.group(1).strip()}" if id_m else f"{current_tag}:{len(elements)}"
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

    IFS .views structure (keyed units):
      COLUMN <Name> IS …  — shared column metadata definition
      VIEW   <Name> IS …  — view-level property overrides

    Deduplication rules:
    - Different names → keep both (additive: two different columns/views)
    - Same name, same kind → merge the two blocks' content line-by-line
      with sequence-diff so properties from both sides are preserved
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
                lb = local_blocks[i1 + k]
                rb = repo_blocks[j1 + k]
                # Same-named block — merge the property lines, don't duplicate
                if lb["key"] == rb["key"] and not lb["key"].startswith("__"):
                    merged.extend(_merge_views_block(lb, rb))
                else:
                    merged.extend(lb["lines"])
        elif tag == "delete":
            for b in local_blocks[i1:i2]:
                merged.extend(b["lines"])
        elif tag == "insert":
            for b in repo_blocks[j1:j2]:
                merged.extend(b["lines"])
        elif tag == "replace":
            local_chunk = local_blocks[i1:i2]
            repo_chunk  = repo_blocks[j1:j2]
            local_view_keys = {b["key"] for b in local_chunk
                               if not b["key"].startswith("__")}
            for b in local_chunk:
                merged.extend(b["lines"])
            for b in repo_chunk:
                # Same view/column name already emitted from local → skip duplicate
                if b["key"] not in local_view_keys:
                    merged.extend(b["lines"])

    return "".join(merged)


def _merge_views_block(local_b: dict, repo_b: dict) -> list[str]:
    """
    Merge two same-named COLUMN/VIEW blocks by line-level sequence diff.
    The header line (COLUMN X IS / VIEW X IS) is kept once; inner property
    lines are merged so properties from both sides appear.
    """
    # First line of each is the header (COLUMN X IS / VIEW X IS)
    header = local_b["lines"][:1]
    local_body = local_b["lines"][1:]
    repo_body  = repo_b["lines"][1:]

    # Deduplicate property lines by property name (key = left side of '=')
    def _prop_key(line: str) -> str:
        m = re.match(r'\s*(\w+)\s*=', line)
        return m.group(1).upper() if m else line.strip()

    seen: dict[str, str] = {}
    result: list[str] = list(header)
    for line in local_body + repo_body:
        k = _prop_key(line)
        if k not in seen:
            seen[k] = line
            result.append(line)
    return result


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
                base_depth = _prefix_depth(lines, i)
                output.append(beautify(resolved, ext, base_depth) + "\n")
            i = conflict["end_line"] + 1
        else:
            output.append(lines[i])
            i += 1

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(output)
