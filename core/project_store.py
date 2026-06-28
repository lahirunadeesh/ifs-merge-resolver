from __future__ import annotations
import json
import uuid
import os
from pathlib import Path

STORE_PATH = Path.home() / ".ifs_merge_projects.json"


def _load() -> list[dict]:
    if not STORE_PATH.exists():
        return []
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(projects: list[dict]) -> None:
    STORE_PATH.write_text(json.dumps(projects, indent=2), encoding="utf-8")


def list_projects() -> list[dict]:
    return _load()


def add_project(name: str, path: str) -> dict:
    projects = _load()
    project = {"id": str(uuid.uuid4()), "name": name.strip(), "path": path}
    projects.append(project)
    _save(projects)
    return project


def delete_project(project_id: str) -> bool:
    projects = _load()
    filtered = [p for p in projects if p["id"] != project_id]
    if len(filtered) == len(projects):
        return False
    _save(filtered)
    return True


def rename_project(project_id: str, new_name: str) -> bool:
    projects = _load()
    for p in projects:
        if p["id"] == project_id:
            p["name"] = new_name.strip()
            _save(projects)
            return True
    return False
