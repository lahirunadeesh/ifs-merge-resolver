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
    document.getElementById("localPane").textContent = c.local || "(empty)";
    document.getElementById("repoPane").textContent = c.repo || "(empty)";

    // Show merged preview if both sides have content
    const previewPane = document.getElementById("previewPane");
    if (c.preview && c.local && c.repo) {
        document.getElementById("previewCode").textContent = c.preview;
        previewPane.style.display = "block";
    } else {
        previewPane.style.display = "none";
    }

    // Clear previous info message when moving to new conflict
    setInfoMessage("", "");
}

const STRATEGY_LABELS = {
    local: { text: "Local changes kept — incoming changes discarded.", type: "local" },
    repo:  { text: "Incoming changes kept — local changes discarded.", type: "repo" },
    both:  { text: "Both changes merged — comments placed in order.", type: "both" },
};

function setInfoMessage(text, type) {
    const el = document.getElementById("infoMessage");
    el.textContent = text;
    el.className = "info-message" + (type ? ` info-${type}` : "");
    el.style.display = text ? "block" : "none";
}

async function resolve(strategy) {
    const info = STRATEGY_LABELS[strategy];
    setInfoMessage(`Processing… ${info.text}`, info.type);

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

    // Re-fetch conflicts after each resolution so line positions stay accurate
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
        // Refresh the file list
        scanFolder();
    } else {
        renderConflict();
    }
}

function showToast(msg) {
    const t = document.createElement("div");
    t.className = "toast";
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3000);
}
