"""
IFS Core File Registry
======================
Provides a schema reference for merge decisions by mapping a conflict file
to its corresponding IFS Developer Studio core file and extracting the
top-level block structure from it.

Why this matters
----------------
When resolving conflicts the merge engine must know which named blocks are
legitimately separate (e.g. two different @Override entity blocks for
InventoryPart and InventoryQuality) vs which blocks from both conflict sides
are the same named unit whose children should be merged.  Without a
reference the engine can only guess — leading to bugs like two separate
entities being collapsed into one.

Usage
-----
    registry = CoreFileRegistry("/path/to/Core-Files/25R2")
    schema = registry.schema_for("/workspace/InventoryPartHandling-Cust.projection")
    # schema.top_level_keys  →  {"entity inventorypart", "entityset inventorypartset", …}
    # schema.known_block(key)  →  True / False
"""
from __future__ import annotations

import re
from pathlib import Path
from functools import lru_cache
from dataclasses import dataclass, field

# ── Layer-suffix patterns ────────────────────────────────────────────────────
# Strip these from filenames to recover the base (core) name.
# Examples: InventoryPartHandling-Cust  InventoryPart-Cust-Ext  MyFile-Ext2
_LAYER_SUFFIX = re.compile(
    r'(?:-(?:Core|Cust|Ext\d*|Customer|Extension|Custext|Overlay|[A-Z][a-z]{1,10}))+$',
    re.IGNORECASE,
)

# Component declaration inside file content
_COMPONENT_RE = re.compile(r'^\s*component\s+([A-Z0-9_]+)\s*;', re.IGNORECASE | re.MULTILINE)

# DSL top-level block opener — same as conflict_scanner but used here independently
_DSL_OPEN  = re.compile(r'\{')
_DSL_CLOSE = re.compile(r'^\s*\}\s*$')
_ANN_LINE  = re.compile(
    r'^\s*(?:@Override|@Overtake\s+Core|@DynamicComponentDependency\s+\S+|@CodeRegistration\s+\S+)',
    re.IGNORECASE,
)

# PL/SQL unit
_PLSQL_UNIT = re.compile(r'^\s*(?:@Override\s+)?(PROCEDURE|FUNCTION)\s+(\w+)', re.IGNORECASE)

# DDL registration
_CODE_REG = re.compile(r'^\s*@CodeRegistration\s+(\S+)', re.IGNORECASE)

# Views
_VIEWS_BLOCK = re.compile(r'^(?:COLUMN|VIEW)\s+(\S+)\s+IS', re.IGNORECASE)

# XML element name
_XML_NAME = re.compile(r'<NAME>(.+?)</NAME>', re.IGNORECASE)


# ── Schema result ────────────────────────────────────────────────────────────

@dataclass
class FileSchema:
    """Structural schema derived from a core file."""
    found:            bool          = False
    core_path:        str           = ""
    # Canonical (lower-cased, annotation-stripped) keys of ALL top-level blocks.
    top_level_keys:   set[str]      = field(default_factory=set)
    # Same keys in the ORDER they appear in the core file (for output ordering).
    ordered_keys:     list[str]     = field(default_factory=list)
    # Component name as declared in the file (upper-case).
    component:        str           = ""

    def known_block(self, canonical_key: str) -> bool:
        """True when the key matches a top-level block in the core file."""
        return canonical_key.lower() in self.top_level_keys

    def core_order(self, canonical_key: str) -> int:
        """Position of key in the core file (-1 if unknown / new block)."""
        k = canonical_key.lower()
        try:
            return self.ordered_keys.index(k)
        except ValueError:
            return -1

    def is_separate_from(self, key_a: str, key_b: str) -> bool:
        """
        True when both keys are known top-level blocks in the core file,
        implying they must remain as distinct blocks in the merged output.
        """
        a = key_a.lower()
        b = key_b.lower()
        return a in self.top_level_keys and b in self.top_level_keys and a != b


_EMPTY_SCHEMA = FileSchema()


# ── Registry ─────────────────────────────────────────────────────────────────

class CoreFileRegistry:
    """
    Singleton-style registry.  Call CoreFileRegistry.instance() after
    configure() has been called with the core directory path.
    """
    _instance: "CoreFileRegistry | None" = None

    def __init__(self, core_dir: str):
        self.core_dir = Path(core_dir) if core_dir else None
        self._cache: dict[str, FileSchema] = {}

    @classmethod
    def configure(cls, core_dir: str) -> "CoreFileRegistry":
        cls._instance = cls(core_dir)
        return cls._instance

    @classmethod
    def instance(cls) -> "CoreFileRegistry":
        if cls._instance is None:
            cls._instance = cls("")
        return cls._instance

    # ── Public API ───────────────────────────────────────────────────────────

    def schema_for(self, conflict_file: str) -> FileSchema:
        """Return the FileSchema for a conflict file (cached)."""
        key = str(conflict_file)
        if key not in self._cache:
            self._cache[key] = self._build_schema(conflict_file)
        return self._cache[key]

    def invalidate(self) -> None:
        self._cache.clear()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _build_schema(self, conflict_file: str) -> FileSchema:
        if not self.core_dir or not self.core_dir.exists():
            return _EMPTY_SCHEMA

        path = Path(conflict_file)
        ext  = path.suffix.lower()
        stem = path.stem  # filename without extension

        # Strip layer suffix to get base name
        base = _LAYER_SUFFIX.sub("", stem)
        if base == stem:
            # No suffix found — try common patterns manually
            for sfx in ("-Cust", "-Ext", "-Core"):
                if stem.endswith(sfx):
                    base = stem[: -len(sfx)]
                    break

        # Detect component from file content
        component = self._detect_component(path)

        # Find the core file
        core_path = self._locate_core_file(base, ext, component)
        if not core_path:
            return _EMPTY_SCHEMA

        # Parse top-level block structure (ordered list + fast-lookup set)
        ordered = self._extract_top_level_keys(core_path, ext)

        return FileSchema(
            found=True,
            core_path=str(core_path),
            top_level_keys={k.lower() for k in ordered},
            ordered_keys=[k.lower() for k in ordered],
            component=component,
        )

    def _detect_component(self, path: Path) -> str:
        """Read the file and extract the component declaration."""
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            m = _COMPONENT_RE.search(text)
            return m.group(1).upper() if m else ""
        except Exception:
            return ""

    def _locate_core_file(self, base: str, ext: str, component: str) -> Path | None:
        """Search the core directory for the matching file."""
        comp_lower = component.lower()

        # Candidate sub-paths based on IFS Developer Studio layout conventions
        candidates: list[Path] = []

        # Model files (.projection, .client, .fragment, .entity, .utility, .enumeration)
        if ext in (".projection", ".client", ".fragment", ".entity", ".utility", ".enumeration"):
            if comp_lower:
                candidates.append(self.core_dir / comp_lower / "model" / comp_lower / f"{base}{ext}")
            # Fallback: search across all components
            for comp_dir in self.core_dir.iterdir():
                if comp_dir.is_dir():
                    p = comp_dir / "model" / comp_dir.name / f"{base}{ext}"
                    if p not in candidates:
                        candidates.append(p)

        # Source files (.plsql, .plsvc, .pltst, .ddlsource, .cdb, .views)
        elif ext in (".plsql", ".plsvc", ".pltst", ".ddlsource", ".cdb", ".views"):
            if comp_lower:
                candidates.append(self.core_dir / comp_lower / "source" / comp_lower / "database" / f"{base}{ext}")
            for comp_dir in self.core_dir.iterdir():
                if comp_dir.is_dir():
                    p = comp_dir / "source" / comp_dir.name / "database" / f"{base}{ext}"
                    if p not in candidates:
                        candidates.append(p)

        for c in candidates:
            if c.exists():
                return c

        # Last-resort: recursive glob across the entire core directory.
        # Excludes Cust/Ext/Overlay layer files so we only match core files.
        _LAYER = re.compile(r'[-_](?:Cust|Ext\d*|Customer|Extension|Custext|Overlay)', re.IGNORECASE)
        for p in self.core_dir.rglob(f"{base}{ext}"):
            if not _LAYER.search(p.stem):
                return p

        return None

    def _extract_top_level_keys(self, core_path: Path, ext: str) -> list[str]:
        """Parse the core file and return canonical top-level block keys in order."""
        try:
            text = core_path.read_text(encoding="utf-8", errors="ignore")
            lines = text.splitlines(keepends=True)
        except Exception:
            return []

        if ext in (".projection", ".client", ".fragment"):
            return _parse_dsl_top_level_keys(lines)
        elif ext in (".plsql", ".plsvc", ".pltst"):
            return _parse_plsql_top_level_keys(lines)
        elif ext in (".ddlsource", ".cdb"):
            return _parse_ddl_top_level_keys(lines)
        elif ext in (".entity", ".utility", ".enumeration"):
            return _parse_xml_top_level_keys(lines)
        elif ext == ".views":
            return _parse_views_top_level_keys(lines)
        return []


# ── File-type parsers ─────────────────────────────────────────────────────────

_ANN_PREFIX_RE = re.compile(
    r'^\s*(?:@Override|@Overtake\s+Core|@DynamicComponentDependency\s+\S+|@CodeRegistration\s+\S+)\s*\n?',
    re.IGNORECASE | re.MULTILINE,
)


def _canonical_key(header: str) -> str:
    """Strip annotations and normalise whitespace — matches _dsl_item_key."""
    stripped = _ANN_PREFIX_RE.sub("", header.strip()).strip()
    # Remove trailing '{' for cleaner matching
    stripped = stripped.rstrip("{").strip()
    return re.sub(r'\s+', ' ', stripped).lower()


def _parse_dsl_top_level_keys(lines: list[str]) -> list[str]:
    """Extract top-level named block keys from a DSL file, in file order."""
    keys: list[str] = []
    seen: set[str] = set()
    depth = 0
    pending: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if depth == 0:
                pending = []
            continue

        # Annotation prefix lines (only accumulate at top level)
        if _ANN_LINE.match(stripped):
            if depth == 0:
                pending.append(line)
            continue

        # Block open
        if stripped.endswith("{"):
            if depth == 0:
                pending.append(line)
                header = "".join(pending)
                key = _canonical_key(header)
                if key and key not in seen:
                    keys.append(key)
                    seen.add(key)
                pending = []
            depth += 1
            continue

        # Block close
        if _DSL_CLOSE.match(stripped):
            if depth > 0:
                depth -= 1
            if depth == 0:
                pending = []
            continue

        if depth == 0:
            # Non-annotation, non-block line at top level — reset pending
            if not _ANN_LINE.match(stripped):
                pending = []

    return keys


def _parse_plsql_top_level_keys(lines: list[str]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for line in lines:
        m = _PLSQL_UNIT.match(line)
        if m:
            k = f"{m.group(1).upper()} {m.group(2).upper()}"
            if k not in seen:
                keys.append(k)
                seen.add(k)
    return keys


def _parse_ddl_top_level_keys(lines: list[str]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for line in lines:
        m = _CODE_REG.match(line)
        if m:
            k = m.group(1).upper()
            if k not in seen:
                keys.append(k)
                seen.add(k)
    return keys


def _parse_xml_top_level_keys(lines: list[str]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    text = "".join(lines)
    for m in _XML_NAME.finditer(text):
        k = m.group(1).strip().lower()
        if k not in seen:
            keys.append(k)
            seen.add(k)
    return keys


def _parse_views_top_level_keys(lines: list[str]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for line in lines:
        m = _VIEWS_BLOCK.match(line)
        if m:
            k = m.group(1).upper()
            if k not in seen:
                keys.append(k)
                seen.add(k)
    return keys
