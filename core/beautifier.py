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
        elif ext in (".projection", ".client", ".fragment", ".views", ".utility"):
            return _beautify_dsl(text)
        elif ext in (".plsql", ".plsvc", ".ddlsource", ".cdb", ".pltst"):
            return _beautify_sql(text)
        else:
            return _beautify_generic(text)
    except Exception:
        # Never break the workflow — return original if formatting fails
        return text


# ── XML (.entity) ──────────────────────────────────────────────────────────────

def _beautify_xml(text: str) -> str:
    try:
        dom = minidom.parseString(text.encode("utf-8"))
        pretty = dom.toprettyxml(indent="   ", encoding=None)
        # toprettyxml adds an XML declaration — strip it if it wasn't there
        lines = pretty.split("\n")
        if lines and lines[0].startswith("<?xml"):
            if not text.strip().startswith("<?xml"):
                lines = lines[1:]
        result = "\n".join(lines)
        return _remove_excess_blank_lines(result.strip())
    except Exception:
        return _beautify_generic(text)


# ── DSL (.projection, .client, .fragment) ─────────────────────────────────────

_DSL_BLOCK_OPEN  = re.compile(r'\{\s*$')
_DSL_BLOCK_CLOSE = re.compile(r'^\s*\}')
_INDENT = "   "  # IFS standard 3-space indent

def _beautify_dsl(text: str) -> str:
    lines = text.splitlines()
    result = []
    depth = 0

    for line in lines:
        stripped = line.strip()

        if not stripped:
            # Preserve single blank lines, collapse multiples later
            result.append("")
            continue

        # Decrease indent before closing brace
        if stripped.startswith("}"):
            depth = max(0, depth - 1)

        # Comment lines and annotation lines keep current depth
        indented = _INDENT * depth + stripped
        result.append(indented)

        # Increase indent after opening brace
        if stripped.endswith("{"):
            depth += 1

    return _remove_excess_blank_lines("\n".join(result))


# ── SQL / PL/SQL (.plsql, .ddlsource, .plsvc) ─────────────────────────────────

_SQL_KEYWORDS = re.compile(
    r'\b(SELECT|FROM|WHERE|AND|OR|ORDER BY|GROUP BY|HAVING|INSERT|UPDATE|DELETE'
    r'|SET|JOIN|LEFT|RIGHT|INNER|OUTER|ON|AS|BEGIN|END|DECLARE|IS|RETURN'
    r'|PROCEDURE|FUNCTION|PACKAGE|CURSOR|IF|THEN|ELSE|ELSIF|LOOP|FOR|WHILE'
    r'|EXCEPTION|WHEN|RAISE|NULL|NOT|IN|OUT|COMMIT|ROLLBACK)\b',
    re.IGNORECASE
)

def _beautify_sql(text: str) -> str:
    lines = text.splitlines()
    result = []
    depth = 0

    for line in lines:
        stripped = line.strip()

        if not stripped:
            result.append("")
            continue

        # Decrease indent before END / END; / EXCEPTION
        if re.match(r'^(END\b|EXCEPTION\b)', stripped, re.IGNORECASE):
            depth = max(0, depth - 1)

        indented = _INDENT * depth + stripped
        result.append(indented)

        # Increase indent after BEGIN / IS / THEN / LOOP / DECLARE
        if re.match(r'^(BEGIN|IS|THEN|LOOP|DECLARE)\b', stripped, re.IGNORECASE):
            depth += 1
        # @CodeRegistration blocks always reset to depth 0
        if stripped.startswith("@CodeRegistration"):
            depth = 0

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
