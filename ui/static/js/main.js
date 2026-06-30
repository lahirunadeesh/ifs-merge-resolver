// ── State ─────────────────────────────────────────────────────────────────────
let currentFile      = null;
let currentConflicts = [];
let currentIndex     = 0;
let selectedPath     = null;
let editingProjectId = null;   // null = new project, string = editing existing

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", loadProjects);

// ── Projects ──────────────────────────────────────────────────────────────────

async function loadProjects() {
    const res  = await fetch("/api/projects");
    const data = await res.json();
    renderProjects(data.projects);
}

function renderProjects(projects) {
    const list = document.getElementById("projectList");
    if (!projects.length) {
        list.innerHTML = "<p class='empty'>No saved projects yet. Browse a folder and save it as a project.</p>";
        return;
    }
    list.innerHTML = "";
    projects.forEach(p => {
        const card = document.createElement("div");
        card.className = "project-card";
        card.innerHTML = `
            <div class="project-info">
                <span class="project-name">${escapeHtml(p.name)}</span>
                <span class="project-path">${escapeHtml(p.path)}</span>
            </div>
            <div class="project-actions">
                <button class="btn-project-scan" onclick="scanProject('${p.id}','${escapeAttr(p.path)}','${escapeAttr(p.name)}')">
                    Scan for Conflicts
                </button>
                <button class="btn-project-edit" onclick="showEditProject('${p.id}','${escapeAttr(p.name)}','${escapeAttr(p.path)}')">
                    Edit
                </button>
                <button class="btn-project-delete" onclick="deleteProject('${p.id}')">
                    Delete
                </button>
            </div>`;
        list.appendChild(card);
    });
}

function showAddProject() {
    editingProjectId = null;
    document.getElementById("projectModalTitle").textContent = "New Project";
    document.getElementById("projectName").value = "";
    document.getElementById("projectPathDisplay").textContent = selectedPath || "No folder selected";
    document.getElementById("projectPathDisplay").classList.toggle("has-path", !!selectedPath);
    document.getElementById("projectSaveBtn").textContent = "Save Project";
    document.getElementById("projectModalOverlay").style.display = "flex";
    document.getElementById("projectName").focus();
}

function showEditProject(id, name, path) {
    editingProjectId = id;
    document.getElementById("projectModalTitle").textContent = "Edit Project";
    document.getElementById("projectName").value = name;
    document.getElementById("projectPathDisplay").textContent = path;
    document.getElementById("projectPathDisplay").classList.add("has-path");
    // Store path for saving
    document.getElementById("projectPathDisplay").dataset.path = path;
    document.getElementById("projectSaveBtn").textContent = "Update Project";
    document.getElementById("projectModalOverlay").style.display = "flex";
    document.getElementById("projectName").focus();
}

function closeProjectModal() {
    document.getElementById("projectModalOverlay").style.display = "none";
    editingProjectId = null;
}

async function browseProjectFolder() {
    const res  = await fetch("/api/browse");
    const data = await res.json();
    if (!data.path) return;
    const display = document.getElementById("projectPathDisplay");
    display.textContent = data.path;
    display.dataset.path = data.path;
    display.classList.add("has-path");
}

async function saveProject() {
    const name = document.getElementById("projectName").value.trim();
    const display = document.getElementById("projectPathDisplay");
    const path = display.dataset.path || (display.textContent !== "No folder selected" ? display.textContent : null) || selectedPath;

    if (!name) return showNotification("Please enter a project name.", "error");
    if (!path || path === "No folder selected") return showNotification("Please select a folder.", "error");

    if (editingProjectId) {
        // Rename only (path stays the same for now)
        const res = await fetch(`/api/projects/${editingProjectId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name })
        });
        if (!res.ok) return showNotification("Failed to update project.", "error");
        showNotification("Project updated.", "success");
    } else {
        const res = await fetch("/api/projects", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, path })
        });
        if (!res.ok) return showNotification("Failed to save project.", "error");
        showNotification(`Project "${name}" saved.`, "success");
    }

    closeProjectModal();
    loadProjects();
}

async function deleteProject(id) {
    if (!confirm("Delete this project?")) return;
    await fetch(`/api/projects/${id}`, { method: "DELETE" });
    loadProjects();
}

async function scanProject(id, path, name) {
    selectedPath = path;
    document.getElementById("pathDisplay").textContent = path;
    document.getElementById("pathDisplay").classList.add("has-path");
    document.getElementById("scanBtn").disabled = false;
    document.getElementById("resultsContext").textContent = `— ${name}`;

    // Scroll to results area
    document.getElementById("setup").scrollIntoView({ behavior: "smooth" });
    await scanFolder();
}

// ── Folder browse (main scan area) ───────────────────────────────────────────

async function browseFolder() {
    const res  = await fetch("/api/browse");
    const data = await res.json();
    if (!data.path) return;
    selectedPath = data.path;
    document.getElementById("pathDisplay").textContent = selectedPath;
    document.getElementById("pathDisplay").classList.add("has-path");
    document.getElementById("scanBtn").disabled = false;
    document.getElementById("resultsContext").textContent = "";
}

// ── Scan ──────────────────────────────────────────────────────────────────────

function setLoader(visible, text) {
    const loader = document.getElementById("scanLoader");
    loader.style.display = visible ? "flex" : "none";
    if (text) document.getElementById("loaderText").textContent = text;
}

async function scanFolder() {
    if (!selectedPath) return;

    document.getElementById("scanBtn").disabled = true;
    document.getElementById("results").style.display = "none";
    document.getElementById("resolver").style.display = "none";
    setLoader(true, "Scanning for conflict files…");

    try {
        const res  = await fetch("/api/scan", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: selectedPath })
        });
        const data = await res.json();
        if (!res.ok) { setLoader(false); return showNotification(data.detail || "Scan failed.", "error"); }
        renderFileList(data.files);
        showScanResult(data.files.length);
    } catch (err) {
        showNotification("Scan error: " + err.message, "error");
    } finally {
        setLoader(false);
        document.getElementById("scanBtn").disabled = false;
    }
}

function showScanResult(count) {
    if (count === 0) {
        showNotification("No conflict files found in the selected folder.", "info");
    } else {
        showNotification(
            `Found ${count} file${count === 1 ? "" : "s"} with merge conflicts. Click a file to start resolving.`,
            "success"
        );
    }
}

// ── Notifications ─────────────────────────────────────────────────────────────

function showNotification(message, type) {
    const existing = document.getElementById("scanNotification");
    if (existing) existing.remove();
    const icons = { success: "✓", error: "✕", info: "ℹ" };
    const el = document.createElement("div");
    el.id = "scanNotification";
    el.className = `scan-notification notif-${type}`;
    el.innerHTML = `<span class="notif-icon">${icons[type] || "ℹ"}</span><span>${message}</span><button class="notif-close" onclick="this.parentElement.remove()">×</button>`;
    const setup = document.getElementById("setup");
    setup.parentNode.insertBefore(el, setup.nextSibling);
    if (type !== "error") setTimeout(() => el && el.remove(), 6000);
}

// ── File list ─────────────────────────────────────────────────────────────────

function renderFileList(files) {
    const section = document.getElementById("results");
    const list    = document.getElementById("fileList");
    list.innerHTML = "";

    if (files.length === 0) {
        list.innerHTML = "<p class='empty'>No conflict files found in this folder.</p>";
    } else {
        files.forEach(f => {
            const div = document.createElement("div");
            div.className = "file-item";
            div.innerHTML = `<span class="file-path">${f.relative_path}</span><span class="file-type">${f.type}</span>`;
            div.onclick = () => loadFile(f.path, f.relative_path);
            list.appendChild(div);
        });
    }
    section.style.display = "block";
    document.getElementById("resolver").style.display = "none";
}

async function loadFile(filePath, relativePath) {
    setLoader(true, `Loading conflicts for ${relativePath}…`);
    const res  = await fetch("/api/conflicts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file: filePath })
    });
    setLoader(false);
    const data = await res.json();
    if (!res.ok) return showNotification(data.detail || "Failed to load file.", "error");

    currentFile      = filePath;
    currentConflicts = data.conflicts;
    currentIndex     = 0;

    document.getElementById("currentFileName").textContent = relativePath;
    document.getElementById("resolver").style.display = "block";
    document.getElementById("resolver").scrollIntoView({ behavior: "smooth" });
    renderConflict();
}

// ── Conflict view ─────────────────────────────────────────────────────────────

function renderConflict() {
    if (currentConflicts.length === 0) {
        document.getElementById("resolver").style.display = "none";
        return;
    }
    const c = currentConflicts[currentIndex];
    document.getElementById("conflictCounter").textContent =
        `Conflict ${currentIndex + 1} of ${currentConflicts.length}`;

    const diffData = c.diff && c.diff.length > 0 ? c.diff : buildFallbackDiff(c.local, c.repo);
    renderDiff(diffData);

    const previewPane = document.getElementById("previewPane");
    if (c.preview && c.local && c.repo) {
        document.getElementById("previewCode").textContent = c.preview;
        previewPane.style.display = "block";
    } else {
        previewPane.style.display = "none";
    }
    setInfoMessage("", "");
}

// ── Resolution ────────────────────────────────────────────────────────────────

const STRATEGY_LABELS = {
    local: { text: "Local changes will be kept. Incoming repo changes will be discarded.", type: "local", btnClass: "btn-confirm-local" },
    repo:  { text: "Incoming repo changes will be kept. Your local changes will be discarded.", type: "repo", btnClass: "btn-confirm-repo" },
    both:  { text: "Both changes will be merged using the preview below.", type: "both", btnClass: "btn-confirm-both" },
};

let pendingStrategy = null;

function setInfoMessage(text, type) {
    const el = document.getElementById("infoMessage");
    el.textContent = text;
    el.className = "info-message" + (type ? ` info-${type}` : "");
    el.style.display = text ? "block" : "none";
}

function resolve(strategy) {
    const info = STRATEGY_LABELS[strategy];
    const c    = currentConflicts[currentIndex];
    pendingStrategy = strategy;

    document.getElementById("modalTitle").textContent =
        strategy === "local" ? "Keep Local Changes" :
        strategy === "repo"  ? "Keep Repo Changes"  : "Keep Both Changes";
    document.getElementById("modalMessage").textContent = info.text;

    const lines = strategy === "both"
        ? (c.preview || "").split("\n")
        : strategy === "local"
            ? (c.local || "").split("\n")
            : (c.repo  || "").split("\n");

    document.getElementById("modalPreview").textContent = lines.join("\n");
    document.getElementById("modalPreviewWrap").style.display =
        lines.some(l => l.trim()) ? "block" : "none";

    document.getElementById("modalConfirmBtn").className = info.btnClass;
    document.getElementById("modalOverlay").style.display = "flex";
}

function cancelResolve() {
    pendingStrategy = null;
    document.getElementById("modalOverlay").style.display = "none";
}

async function confirmResolve() {
    document.getElementById("modalOverlay").style.display = "none";
    const strategy = pendingStrategy;
    pendingStrategy = null;

    setInfoMessage(
        strategy === "local" ? "✓ Local changes applied." :
        strategy === "repo"  ? "✓ Repo changes applied." : "✓ Both changes merged.",
        STRATEGY_LABELS[strategy].type
    );

    const res = await fetch("/api/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            file: currentFile,
            resolutions: [{ index: currentConflicts[currentIndex].index, strategy }]
        })
    });
    if (!res.ok) { const d = await res.json(); return showNotification(d.detail || "Resolve failed.", "error"); }

    const updated = await fetch("/api/conflicts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file: currentFile })
    });
    const data = await updated.json();
    currentConflicts = data.conflicts;
    currentIndex     = 0;

    if (currentConflicts.length === 0) {
        document.getElementById("resolver").style.display = "none";
        showToast("All conflicts resolved in this file!");
        scanFolder();
    } else {
        renderConflict();
    }
}

// ── Diff rendering ────────────────────────────────────────────────────────────

function buildFallbackDiff(local, repo) {
    const result = [];
    (local || "").split("\n").forEach((text, i) =>
        result.push({ line_no_local: i + 1, line_no_repo: null, text, kind: "local" }));
    (repo  || "").split("\n").forEach((text, i) =>
        result.push({ line_no_local: null, line_no_repo: i + 1, text, kind: "repo" }));
    return result;
}

function renderDiff(diffLines) {
    const container = document.getElementById("diffView");
    container.innerHTML = "";
    if (!diffLines.length) {
        container.innerHTML = '<div class="diff-empty">No differences detected.</div>';
        return;
    }
    diffLines.forEach(entry => {
        const row    = document.createElement("div");
        row.className = `diff-row diff-${entry.kind}`;

        const localNo = document.createElement("span");
        localNo.className = "diff-lineno";
        localNo.textContent = entry.line_no_local !== null ? entry.line_no_local : "";

        const repoNo = document.createElement("span");
        repoNo.className = "diff-lineno";
        repoNo.textContent = entry.line_no_repo !== null ? entry.line_no_repo : "";

        const marker = document.createElement("span");
        marker.className = "diff-marker";
        marker.textContent = entry.kind === "local" ? "−" : entry.kind === "repo" ? "+" : " ";

        const code = document.createElement("span");
        code.className = "diff-code";
        code.textContent = entry.text;

        row.append(localNo, repoNo, marker, code);
        container.appendChild(row);
    });
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function showToast(msg) {
    const t = document.createElement("div");
    t.className = "toast";
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3000);
}

function escapeHtml(str) {
    return (str || "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function escapeAttr(str) {
    // Escape backslashes FIRST (Windows paths), then single quotes —
    // otherwise inline onclick="..." JS string literals silently eat
    // backslashes before unrecognized escapes like \H, \D, \w.
    return (str || "").replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}
