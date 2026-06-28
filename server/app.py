from __future__ import annotations
import os
import sys
import platform
import subprocess
import webbrowser
import threading
import asyncio
from concurrent.futures import ThreadPoolExecutor

_executor = ThreadPoolExecutor(max_workers=2)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from pydantic import BaseModel
import uvicorn

from core.conflict_scanner import scan_for_conflicts, parse_conflicts, apply_resolution
from core.project_store import list_projects, add_project, delete_project, rename_project
from licensing.machine_id import get_machine_id
from licensing.validator import is_licensed, activate as do_activate

app = FastAPI(title="IFS Merge Conflict Resolver")

# When frozen by PyInstaller, resources live in Contents/Resources (sys._MEIPASS)
if getattr(sys, "frozen", False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "ui", "templates"))


# ── UI ────────────────────────────────────────────────────────────────────────

@app.get("/")
async def home(request: Request):
    if not is_licensed():
        return templates.TemplateResponse("activate.html", {"request": request})
    return templates.TemplateResponse("home.html", {"request": request})

@app.get("/app")
async def index(request: Request):
    if not is_licensed():
        return templates.TemplateResponse("activate.html", {"request": request})
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/activate")
async def activate_page(request: Request):
    return templates.TemplateResponse("activate.html", {"request": request})


# ── API models ────────────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    path: str

class ConflictRequest(BaseModel):
    file: str

class Resolution(BaseModel):
    index: int
    strategy: str  # 'local' | 'repo' | 'both'

class ResolveRequest(BaseModel):
    file: str
    resolutions: list[Resolution]

class SaveProjectRequest(BaseModel):
    name: str
    path: str

class RenameProjectRequest(BaseModel):
    name: str

class ActivateRequest(BaseModel):
    license_key: str


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/browse")
async def browse_folder():
    """Open a native OS folder picker dialog."""
    loop = asyncio.get_event_loop()
    folder = await loop.run_in_executor(_executor, _open_folder_dialog)
    return {"path": folder}


def _open_folder_dialog():
    """Platform-specific native folder picker (no tkinter)."""
    system = platform.system()

    if system == "Darwin":
        script = (
            'tell app "Finder" to POSIX path of '
            '(choose folder with prompt "Select IFS Project Root")'
        )
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True
        )
        path = result.stdout.strip()
        return path if path else None

    elif system == "Windows":
        import ctypes
        import ctypes.wintypes
        BFFM_INITIALIZED = 1
        shell32 = ctypes.windll.shell32
        buf = ctypes.create_unicode_buffer(256)
        bi = ctypes.create_string_buffer(76)
        result = shell32.SHGetPathFromIDListW(
            shell32.SHBrowseForFolderW(ctypes.byref(bi)), buf
        )
        return buf.value if result else None

    else:
        # Linux fallback: zenity
        result = subprocess.run(
            ["zenity", "--file-selection", "--directory",
             "--title=Select IFS Project Root"],
            capture_output=True, text=True
        )
        path = result.stdout.strip()
        return path if path else None


@app.post("/api/scan")
async def scan(req: ScanRequest):
    try:
        loop = asyncio.get_event_loop()
        files = await loop.run_in_executor(_executor, scan_for_conflicts, req.path)
        return {"files": files, "count": len(files)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/conflicts")
async def get_conflicts(req: ConflictRequest):
    try:
        conflicts = parse_conflicts(req.file)
        return {"file": req.file, "conflicts": conflicts, "count": len(conflicts)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/resolve")
async def resolve(req: ResolveRequest):
    try:
        resolutions = [{"index": r.index, "strategy": r.strategy} for r in req.resolutions]
        apply_resolution(req.file, resolutions)
        return {"status": "ok", "file": req.file}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/projects")
async def get_projects():
    return {"projects": list_projects()}

@app.post("/api/projects")
async def save_project(req: SaveProjectRequest):
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="Project name cannot be empty.")
    if not req.path.strip():
        raise HTTPException(status_code=400, detail="Path cannot be empty.")
    project = add_project(req.name, req.path)
    return {"project": project}

@app.delete("/api/projects/{project_id}")
async def remove_project(project_id: str):
    if not delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"status": "deleted"}

@app.patch("/api/projects/{project_id}")
async def update_project(project_id: str, req: RenameProjectRequest):
    if not rename_project(project_id, req.name):
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"status": "renamed"}


@app.get("/api/device-id")
async def device_id():
    return {"device_id": get_machine_id()}

@app.post("/api/activate")
async def activate(req: ActivateRequest):
    success, message = do_activate(req.license_key)
    if not success:
        raise HTTPException(status_code=403, detail=message)
    return {"success": True, "message": message}

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Static files — must be mounted AFTER all API routes ──────────────────────
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "ui", "static")), name="static")


# ── Entry point ───────────────────────────────────────────────────────────────

def open_browser():
    webbrowser.open("http://localhost:7845/")

if __name__ == "__main__":
    threading.Timer(1.0, open_browser).start()
    uvicorn.run(app, host="127.0.0.1", port=7845)
