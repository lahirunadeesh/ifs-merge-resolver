from __future__ import annotations
import os
import sys
import platform
import subprocess
import webbrowser
import threading
import asyncio
import urllib.request
import time
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
from licensing.validator import is_licensed, activate as do_activate, license_status

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
        # Use PowerShell folder picker — reliable on all Windows versions
        ps_script = (
            "[System.Reflection.Assembly]::LoadWithPartialName('System.Windows.Forms') | Out-Null;"
            "$dlg = New-Object System.Windows.Forms.FolderBrowserDialog;"
            "$dlg.Description = 'Select IFS Project Root';"
            "$dlg.ShowNewFolderButton = $false;"
            "if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $dlg.SelectedPath }"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True, text=True, timeout=60
        )
        # Normalize: strip whitespace, convert backslashes to forward slashes
        path = result.stdout.strip().replace("\r", "").replace("\n", "")
        path = os.path.normpath(path) if path else None
        return path if path else None

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

@app.get("/api/license-status")
async def get_license_status():
    return license_status()

@app.post("/api/activate")
async def activate(req: ActivateRequest):
    success, message, kind = do_activate(req.license_key)
    if not success:
        raise HTTPException(status_code=403, detail=message)
    return {"success": True, "message": message, "type": kind}

@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Static files — must be mounted AFTER all API routes ──────────────────────
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "ui", "static")), name="static")


# ── Entry point ───────────────────────────────────────────────────────────────

URL = "http://localhost:7845/"


def _open_browser():
    """Open browser — use subprocess on Windows for reliability inside frozen app."""
    if platform.system() == "Windows":
        subprocess.Popen(["cmd", "/c", "start", "", URL], shell=False)
    else:
        webbrowser.open(URL)


def _wait_and_open_browser():
    for _ in range(60):
        try:
            urllib.request.urlopen("http://127.0.0.1:7845/health")
            break
        except Exception:
            time.sleep(0.5)
    _open_browser()


def _start_server():
    uvicorn.run(app, host="127.0.0.1", port=7845, log_config=None)


def _make_tray_icon():
    from PIL import Image
    icon_path = os.path.join(BASE_DIR, "ui", "static", "icon.png")
    try:
        return Image.open(icon_path).resize((64, 64), Image.LANCZOS)
    except Exception:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        from PIL import ImageDraw
        ImageDraw.Draw(img).ellipse([4, 4, 60, 60], fill=(88, 166, 255, 255))
        return img


if __name__ == "__main__":
    # Start server in background thread
    server_thread = threading.Thread(target=_start_server, daemon=True)
    server_thread.start()

    # Open browser once server is ready
    threading.Thread(target=_wait_and_open_browser, daemon=True).start()

    # System tray icon
    try:
        import pystray
        from PIL import Image

        icon_image = _make_tray_icon()

        def on_open(icon, item):
            threading.Thread(target=_open_browser, daemon=True).start()

        def on_quit(icon, item):
            icon.stop()
            os._exit(0)

        tray = pystray.Icon(
            "IFSMergeResolver",
            icon_image,
            "IFS Merge Resolver",
            menu=pystray.Menu(
                pystray.MenuItem("Open", on_open, default=True),
                pystray.MenuItem("Quit", on_quit),
            )
        )
        tray.run()
    except Exception:
        server_thread.join()
