import os
import sys
import webbrowser
import threading
import tkinter as tk
from tkinter import filedialog

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from pydantic import BaseModel
import uvicorn

from core.conflict_scanner import scan_for_conflicts, parse_conflicts, apply_resolution

app = FastAPI(title="IFS Merge Conflict Resolver")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "ui", "templates"))


# ── UI ────────────────────────────────────────────────────────────────────────

@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


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


# ── API endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/browse")
async def browse_folder():
    """Open a native OS folder picker and return the selected path."""
    root = tk.Tk()
    root.withdraw()
    root.wm_attributes("-topmost", True)
    folder = filedialog.askdirectory(title="Select IFS Project Root")
    root.destroy()
    if not folder:
        return {"path": None}
    return {"path": folder}


@app.post("/api/scan")
async def scan(req: ScanRequest):
    try:
        files = scan_for_conflicts(req.path)
        return {"files": files, "count": len(files)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Static files — must be mounted AFTER all API routes ──────────────────────
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "ui", "static")), name="static")


# ── Entry point ───────────────────────────────────────────────────────────────

def open_browser():
    webbrowser.open("http://localhost:7845")

if __name__ == "__main__":
    threading.Timer(1.0, open_browser).start()
    uvicorn.run(app, host="127.0.0.1", port=7845)
