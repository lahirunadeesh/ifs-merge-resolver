// ── State ─────────────────────────────────────────────────────────────────────
let currentFile      = null;
let currentConflicts = [];
let currentIndex     = 0;
let selectedPath     = null;
let editingProjectId = null;   // null = new project, string = editing existing

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    loadProjects();
    loadCoreDir();
});

// ── Core Files Directory ───────────────────────────────────────────────────────

async function loadCoreDir() {
    const res  = await fetch("/api/settings/core-dir");
    const data = await res.json();
    _renderCoreDir(data);
}

function _renderCoreDir(data) {
    const display = document.getElementById("coreDirDisplay");
    const status  = document.getElementById("coreDirStatus");
    const clearBtn = document.getElementById("clearCoreDirBtn");
    if (data.path && data.active) {
        display.textContent = data.path;
        display.title       = data.path;
        status.textContent  = "✓ Active";
        status.className    = "core-status active";
        clearBtn.style.display = "inline-block";
    } else if (data.path && !data.active) {
        display.textContent = data.path + "  (directory not found)";
        status.textContent  = "⚠ Not found";
        status.className    = "core-status inactive";
        clearBtn.style.display = "inline-block";
    } else {
        display.textContent = "Not configured";
        status.textContent  = "";
        status.className    = "core-status";
        clearBtn.style.display = "none";
    }
}

async function browseCoreDir() {
    const res  = await fetch("/api/browse");
    const data = await res.json();
    if (!data.path) return;
    const res2 = await fetch("/api/settings/core-dir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: data.path }),
    });
    if (!res2.ok) {
        const err = await res2.json();
        showNotification(err.detail || "Could not set core directory.", "error");
        return;
    }
    const saved = await res2.json();
    _renderCoreDir(saved);
    showNotification("Core files directory saved. Schema-guided merge is now active.", "success");
}

async function clearCoreDir() {
    await fetch("/api/settings/core-dir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: "" }),
    });
    _renderCoreDir({ path: "", active: false });
    showNotification("Core files directory cleared.", "info");
}

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
    // Preview pane stays hidden until the user hovers a Keep button.
    previewPane.style.display = "none";
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

    // Show the relevant code section with an inline Apply/Cancel bar —
    // no popup, the preview at the bottom is the confirmation context.
    showStrategyPreview(strategy);
    document.getElementById("inlineConfirmMsg").textContent = info.text;
    // Keep the base style; btnClass supplies the strategy colour.
    document.getElementById("inlineConfirmBtn").className =
        "btn-preview-apply " + info.btnClass;
}

function cancelResolve() {
    pendingStrategy = null;
    document.getElementById("previewPane").style.display = "none";
}

async function confirmResolve() {
    document.getElementById("previewPane").style.display = "none";
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

// Switch the preview pane to show what the given strategy would produce.
// Full-block context (preview_block / local_block / repo_block) is preferred;
// falls back to the raw hunk content for older server responses.
const PREVIEW_LABELS = {
    local: "Keep Local — preview",
    repo:  "Keep Repo — preview",
    both:  "Keep Both — merged preview",
};

function showStrategyPreview(strategy) {
    const c = currentConflicts[currentIndex];
    if (!c) return;
    const content =
        strategy === "local" ? (c.local_block || c.local) :
        strategy === "repo"  ? (c.repo_block  || c.repo)  :
                               (c.preview_block || c.preview);
    if (!content) return;
    document.getElementById("previewCode").innerHTML = highlightCode(content);
    const label = document.getElementById("previewLabel");
    label.textContent = PREVIEW_LABELS[strategy];
    label.className = "pane-label preview-label preview-label-" + strategy;
    const pane = document.getElementById("previewPane");
    pane.className = strategy === "both" ? "" : "strategy-" + strategy;
    pane.style.display = "block";
    pane.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function openSourceFile() {
    if (!currentFile) return;
    const res = await fetch("/api/open-file", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file: currentFile })
    });
    if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        showNotification(d.detail || "Could not open the file.", "error");
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

// ── Syntax highlight for DSL / IFS Marble preview ────────────────────────────

// Dispatcher: pick the highlighter matching the content's shape.
function highlightCode(code) {
    if (/<\/?[A-Za-z_][\w.-]*>/.test(code)) return highlightXml(code);
    return highlightDsl(code);
}

// XML (.entity, .utility, .enumeration) highlighter
function highlightXml(code) {
    let safe = escapeHtml(code);
    const tokens = [];
    function ph(cls, text) {
        const id = `\x01${tokens.length}\x01`;
        tokens.push(`<span class="tok-${cls}">${text}</span>`);
        return id;
    }
    // XML comments
    safe = safe.replace(/&lt;!--[\s\S]*?--&gt;/g, m => ph("cmt", m));
    // IFS history/comment noise embedded in COMMENT_TEXT values
    safe = safe.replace(/^(\s*)(--[^\n]*|\/\/\(\+\)[^\n]*|-{10,}\*?\/?)$/gm,
        (_, ind, m) => ind + ph("cmt", m));
    // Tags: <NAME>, </NAME>, <NAME attr="v"/>
    safe = safe.replace(/&lt;\/?[A-Za-z_][\w.-]*(?:\s[^&<>\n]*?)?\/?&gt;/g,
        m => ph("tag", m));
    // Element text values (between a closed tag placeholder and the next one)
    safe = safe.replace(/\x01(\d+)\x01([^\x01\n]+)\x01(\d+)\x01/g,
        (_, a, val, b) => `\x01${a}\x01` + (val.trim() ? ph("val", val) : val) + `\x01${b}\x01`);
    safe = safe.replace(/\x01(\d+)\x01/g, (_, i) => tokens[+i]);
    return safe;
}

function highlightDsl(code) {
    // Process line-by-line so line structure is preserved exactly.
    // We apply a small set of token classes that match IFS Marble DSL patterns.
    const DSL_KEYWORDS = /\b(entity|entityset|query|action|function|structure|enumeration|virtual|summary|singleton|page|list|group|command|dialog|selector|navigator|attribute|field|fieldset|filtersection|filtergroup|orderby|aggregate|reference|array|variable|parameter|return|execute|ludependency|where|from|to|luname|keys|use|label|editable|required|fetch|default|searchable|lovswitch|format|size|maxlength|insertable|updatable|deletable|onlyoninsert|enumerationtrue|enumerationfalse|validate|insert|update|delete|navigate|enabled|visible|emphasis|keepdefault|lovcolumns)\b/gi;
    const ANNOTATIONS = /^(\s*)(@Override|@Overtake\s+Core|@DynamicComponentDependency\s+\S+|@CodeRegistration\s+\S+|@Overtake)/gm;
    const STRINGS = /"([^"\\]|\\.)*"/g;
    const COMMENTS = /(--.*)$/gm;
    const BLOCK_COMMENTS = /\/\*[\s\S]*?\*\//g;

    // Escape HTML first, then re-apply spans
    let safe = escapeHtml(code);

    // Apply in order (most specific first, least last) using placeholder tokens
    // to avoid double-escaping. We wrap each class in a unique delimiter.
    const tokens = [];
    function ph(cls, text) {
        const id = `\x01${tokens.length}\x01`;
        tokens.push(`<span class="tok-${cls}">${text}</span>`);
        return id;
    }

    // Block comments first (/* ... */)
    safe = safe.replace(/\/\*[\s\S]*?\*\//g, m => ph("cmt", m));
    // Line comments (-- ...)
    safe = safe.replace(/(--[^\n]*)/g, m => ph("cmt", m));
    // Annotations (@Override etc.)
    safe = safe.replace(/@(?:Override|Overtake(?:\s+Core)?|DynamicComponentDependency\s+\S+|CodeRegistration\s+\S+)/g, m => ph("ann", m));
    // Quoted strings
    safe = safe.replace(/&quot;([^&]|&(?!quot;))*&quot;/g, m => ph("str", m));
    // DSL keywords (only when not inside a token placeholder)
    safe = safe.replace(DSL_KEYWORDS, m => ph("kw", m));

    // Restore placeholders
    safe = safe.replace(/\x01(\d+)\x01/g, (_, i) => tokens[+i]);

    return safe;
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
