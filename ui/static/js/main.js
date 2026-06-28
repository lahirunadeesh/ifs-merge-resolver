let currentFile = null;
let currentConflicts = [];
let currentIndex = 0;

async function scanFolder() {
    const path = document.getElementById("rootPath").value.trim();
    if (!path) return alert("Please enter a project root path.");

    document.getElementById("scanBtn").textContent = "Scanning...";

    try {
        const res = await fetch("/api/scan", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path })
        });
        const data = await res.json();
        if (!res.ok) return alert(data.detail || "Scan failed.");
        renderFileList(data.files);
    } finally {
        document.getElementById("scanBtn").textContent = "Scan for Conflicts";
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
    const res = await fetch("/api/conflicts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file: filePath })
    });
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
}

async function resolve(strategy) {
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
