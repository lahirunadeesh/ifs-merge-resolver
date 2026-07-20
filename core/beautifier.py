from __future__ import annotations
import re
import xml.dom.minidom as minidom

# ── Public entry point ─────────────────────────────────────────────────────────

def beautify(text: str, extension: str, base_depth: int = 0) -> str:
    """Format text according to IFS file-type conventions.

    base_depth: brace nesting level at the start of `text` — used when the
    text is a fragment that begins inside an already-open block (e.g. a git
    conflict hunk inside an entity), so indentation is preserved correctly.
    """
    if not text or not text.strip():
        return text
    try:
        ext = extension.lower()
        if ext == ".entity":
            return _beautify_xml(text)
        elif ext in (".projection", ".client", ".fragment", ".utility", ".enumeration"):
            return _beautify_dsl(text, base_depth)
        elif ext in (".plsql", ".plsvc", ".pltst"):
            return _beautify_plsql(text)
        elif ext in (".ddlsource", ".cdb"):
            return _beautify_ddl(text)
        elif ext == ".views":
            return _beautify_views(text)
        else:
            return _beautify_generic(text)
    except Exception:
        return text


# ── XML (.entity) ──────────────────────────────────────────────────────────────

def _beautify_xml(text: str) -> str:
    try:
        dom = minidom.parseString(text.encode("utf-8"))
        # Drop whitespace-only text nodes: toprettyxml keeps them AND adds
        # its own indentation, producing blank lines between every element.
        _strip_ws_text_nodes(dom.documentElement)
        pretty = dom.toprettyxml(indent="   ", encoding=None)
        # Remove any remaining whitespace-only lines
        lines = [l for l in pretty.split("\n") if l.strip()]
        if lines and lines[0].startswith("<?xml"):
            if not text.strip().startswith("<?xml"):
                lines = lines[1:]
        return "\n".join(lines).strip()
    except Exception:
        # Partial XML fragment (e.g. cut mid-element by git conflict marker)
        # Preserve original whitespace rather than mangling it
        return _beautify_generic(text)


def _strip_ws_text_nodes(node) -> None:
    """Recursively remove whitespace-only text nodes from a DOM tree."""
    for child in list(node.childNodes):
        if child.nodeType == child.TEXT_NODE and not child.data.strip():
            node.removeChild(child)
        elif child.nodeType == child.ELEMENT_NODE:
            _strip_ws_text_nodes(child)


# ── Marble DSL (.projection, .client, .fragment, .utility, .enumeration) ──────
#
# IFS Marble DSL uses curly-brace blocks with 3-space indentation.
# Named constructs: entity, attribute, action, function, list, group, field,
# page, command, selector, dialog, navigator, enumeration, structure, query.

_DSL_BLOCK_OPEN  = re.compile(r'\{\s*$')
_DSL_BLOCK_CLOSE = re.compile(r'^\s*\}')
_INDENT = "   "  # IFS Developer Studio standard: 3 spaces

def _beautify_dsl(text: str, base_depth: int = 0) -> str:
    lines = text.splitlines()
    result = []
    depth = max(0, base_depth)

    for line in lines:
        stripped = line.strip()

        if not stripped:
            result.append("")
            continue

        # Decrease indent before closing brace
        if stripped.startswith("}"):
            depth = max(0, depth - 1)

        result.append(_INDENT * depth + stripped)

        # Increase indent after opening brace
        if stripped.endswith("{"):
            depth += 1

    return _remove_excess_blank_lines("\n".join(result))


# ── PL/SQL (.plsql, .plsvc, .pltst) ───────────────────────────────────────────
#
# IFS PL/SQL follows Oracle package body conventions with IFS-specific section
# comment headers (e.g. "---- PUBLIC METHODS ----").
#
# We deliberately do NOT re-indent PL/SQL. IFS developers use aligned parameter
# lists, CURSOR body formatting, and multi-level nested IF/LOOP structures that
# a keyword-based re-indenter breaks. Preserve original indentation; only strip
# trailing whitespace and collapse excess blank lines.

def _beautify_plsql(text: str) -> str:
    lines = text.splitlines()
    result = [line.rstrip() for line in lines]
    return _remove_excess_blank_lines("\n".join(result))


# ── DDL / CDB (.ddlsource, .cdb) ───────────────────────────────────────────────
#
# IFS .ddlsource files: IFS history header comment + @CodeRegistration blocks
#   or TABLE/INDEX/SEQUENCE declarative DDL.
# IFS .cdb files: IFS history header + anonymous PL/SQL blocks using
#   Database_SYS API calls, each preceded by @CodeRegistration or PROMPT.
#
# Preserve original formatting — only strip trailing whitespace.

def _beautify_ddl(text: str) -> str:
    lines = text.splitlines()
    result = [line.rstrip() for line in lines]
    return _remove_excess_blank_lines("\n".join(result))


# ── Views (.views) ─────────────────────────────────────────────────────────────
#
# IFS .views files use a property-override DSL:
#   COLUMN <ColumnName> IS
#      Flags    = 'KMI--'
#      Datatype = 'STRING(30)/UPPERCASE'
#      Prompt   = 'Display Name';
#   VIEW <ViewName> IS
#      <ColumnName> IS
#         Prompt = 'Override Label';
#
# Preserve developer formatting.

def _beautify_views(text: str) -> str:
    lines = text.splitlines()
    result = [line.rstrip() for line in lines]
    return _remove_excess_blank_lines("\n".join(result))


# ── Generic (any other type) ───────────────────────────────────────────────────

def _beautify_generic(text: str) -> str:
    lines = [l.rstrip() for l in text.splitlines()]
    return _remove_excess_blank_lines("\n".join(lines))


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _remove_excess_blank_lines(text: str) -> str:
    """Collapse 2+ consecutive blank lines down to 1."""
    # strip("\n") not strip() — a full strip would delete the first line's
    # indentation when the fragment starts inside an open block.
    return re.sub(r'\n{3,}', '\n\n', text).strip("\n").rstrip()


def strip_blank_lines(text: str) -> str:
    """Remove all standalone blank lines — used for compact inline blocks."""
    lines = [l for l in text.splitlines() if l.strip()]
    return "\n".join(lines)
