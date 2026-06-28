let currentFile = null;
let currentConflicts = [];
let currentIndex = 0;
let selectedPath = null;

async function browseFolder() {
    const res = await fetch("/api/browse");
    const data = await res.json();
    if (!data.path) return;
    selectedPath = data.path;
    document.getElementById("pathDisplay").textContent = selectedPath;
    document.getElementById("pathDisplay").classList.add("has-path");
    document.getElementById("scanBtn").disabled = false;
}

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
        const res = await fetch("/api/scan", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path: selectedPath })
        });
        const data = await res.json();
        if (!res.ok) {
            setLoader(false);
            return alert(data.detail || "Scan failed.");
        }
        renderFileList(data.files);
    } catch (err) {
        alert("Scan error: " + err.message);
    } finally {
        setLoader(false);
        document.getElementById("scanBtn").disabled = false;
    }
}

function renderFileList(files) {
    const section = document.getElementById("results");
    const list = document.getElementById("fileList");
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
    const res = await fetch("/api/conflicts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file: filePath })
    });
    setLoader(false);
    const data = await res.json();
    if (!res.ok) return alert(data.detail || "Failed to load file.");

    currentFile = filePath;
    currentConflicts = data.conflicts;
    currentIndex = 0;

    document.getElementById("currentFileName").textContent = relativePath;
    document.getElementById("resolver").style.display = "block";
    renderConflict();
}

function renderConflict() {
    if (currentConflicts.length === 0) {
        document.getElementById("resolver").style.display = "none";
        return;
    }

    const c = currentConflicts[currentIndex];
    document.getElementById("conflictCounter").textContent =
        `Conflict ${currentIndex + 1} of ${currentConflicts.length}`;
    // If server diff is empty but content exists, build a client-side fallback diff
    let diffData = c.diff && c.diff.length > 0 ? c.diff : buildFallbackDiff(c.local, c.repo);
    renderDiff(diffData);

    // Show merged preview if both sides have content
    const previewPane = document.getElementById("previewPane");
    if (c.preview && c.local && c.repo) {
        document.getElementById("previewCode").textContent = c.preview;
        previewPane.style.display = "block";
    } else {
        previewPane.style.display = "none";
    }

    setInfoMessage("", "");
}

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
    const c = currentConflicts[currentIndex];
    pendingStrategy = strategy;

    document.getElementById("modalTitle").textContent =
        strategy === "local" ? "Keep Local Changes" :
        strategy === "repo"  ? "Keep Repo Changes" : "Keep Both Changes";

    document.getElementById("modalMessage").textContent = info.text;

    const previewWrap = document.getElementById("modalPreviewWrap");
    const previewEl   = document.getElementById("modalPreview");

    // Show only the lines relevant to the chosen strategy
    const lines = strategy === "both"
        ? (c.preview || "").split("\n")
        : strategy === "local"
            ? (c.local || "").split("\n")
            : (c.repo  || "").split("\n");

    previewEl.textContent = lines.join("\n");
    previewWrap.style.display = lines.some(l => l.trim()) ? "block" : "none";

    const confirmBtn = document.getElementById("modalConfirmBtn");
    confirmBtn.className = info.btnClass;

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

    const info = STRATEGY_LABELS[strategy];
    setInfoMessage(
        strategy === "local" ? "✓ Local changes applied." :
        strategy === "repo"  ? "✓ Repo changes applied." :
                               "✓ Both changes merged.",
        info.type
    );

    const res = await fetch("/api/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            file: currentFile,
            resolutions: [{ index: currentConflicts[currentIndex].index, strategy }]
        })
    });
    if (!res.ok) {
        const data = await res.json();
        return alert(data.detail || "Resolve failed.");
    }

    const updated = await fetch("/api/conflicts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file: currentFile })
    });
    const data = await updated.json();
    currentConflicts = data.conflicts;
    currentIndex = 0;

    if (currentConflicts.length === 0) {
        document.getElementById("resolver").style.display = "none";
        showToast("All conflicts resolved in this file!");
        scanFolder();
    } else {
        renderConflict();
    }
}

function buildFallbackDiff(local, repo) {
    const result = [];
    const localLines = (local || "").split("\n");
    const repoLines  = (repo  || "").split("\n");
    localLines.forEach((text, i) => {
        result.push({ line_no_local: i + 1, line_no_repo: null, text, kind: "local" });
    });
    repoLines.forEach((text, i) => {
        result.push({ line_no_local: null, line_no_repo: i + 1, text, kind: "repo" });
    });
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
        const row = document.createElement("div");
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

        row.appendChild(localNo);
        row.appendChild(repoNo);
        row.appendChild(marker);
        row.appendChild(code);
        container.appendChild(row);
    });
}

function showToast(msg) {
    const t = document.createElement("div");
    t.className = "toast";
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3000);
}
