from __future__ import annotations
import re
import xml.dom.minidom as minidom

# ── Public entry point ─────────────────────────────────────────────────────────

def beautify(text: str, extension: str) -> str:
    """Format text according to IFS file-type conventions."""
    if not text or not text.strip():
        return text
    try:
        ext = extension.lower()
        if ext == ".entity":
            return _beautify_xml(text)
        elif ext in (".projection", ".client", ".fragment", ".utility", ".enumeration"):
            return _beautify_dsl(text)
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
        pretty = dom.toprettyxml(indent="   ", encoding=None)
        lines = pretty.split("\n")
        if lines and lines[0].startswith("<?xml"):
            if not text.strip().startswith("<?xml"):
                lines = lines[1:]
        result = "\n".join(lines)
        return _remove_excess_blank_lines(result.strip())
    except Exception:
        # Partial XML fragment (e.g. cut mid-element by git conflict marker)
        # Preserve original whitespace rather than mangling it
        return _beautify_generic(text)


# ── Marble DSL (.projection, .client, .fragment, .utility, .enumeration) ──────
#
# IFS Marble DSL uses curly-brace blocks with 3-space indentation.
# Named constructs: entity, attribute, action, function, list, group, field,
# page, command, selector, dialog, navigator, enumeration, structure, query.

_DSL_BLOCK_OPEN  = re.compile(r'\{\s*$')
_DSL_BLOCK_CLOSE = re.compile(r'^\s*\}')
_INDENT = "   "  # IFS Developer Studio standard: 3 spaces

def _beautify_dsl(text: str) -> str:
    lines = text.splitlines()
    result = []
    depth = 0

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
    return re.sub(r'\n{3,}', '\n\n', text).strip()


def strip_blank_lines(text: str) -> str:
    """Remove all standalone blank lines — used for compact inline blocks."""
    lines = [l for l in text.splitlines() if l.strip()]
    return "\n".join(lines)
