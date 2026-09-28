(() => {
  "use strict";

  let state = {};
  let currentZone = null;
  let pollTimer = null;
  let editorDraft = null; // { origName, name, controllers: { [cname]: { mode: 'segments'|'preset', preset, segments: { [sname]: {included, power, col} } } } }
  let previewDebounce = null;
  let lastStateJSON = null;
  let stateFetchInFlight = false;

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function rgbToHex([r, g, b]) {
    const h = (n) => n.toString(16).padStart(2, "0");
    return `#${h(r)}${h(g)}${h(b)}`;
  }
  function hexToRgb(hex) {
    const n = parseInt(hex.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  function toast(msg) {
    const el = $("#toast");
    el.textContent = msg;
    el.classList.remove("hidden");
    requestAnimationFrame(() => el.classList.add("show"));
    clearTimeout(toast._t);
    toast._t = setTimeout(() => {
      el.classList.remove("show");
      setTimeout(() => el.classList.add("hidden"), 200);
    }, 1800);
  }

  async function api(path, opts) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok || body.ok === false) {
      toast(body.error || "Something went wrong");
      throw new Error(body.error || `request failed: ${path}`);
    }
    return body;
  }

  async function loadState(force) {
    // Skip overlapping polls (e.g. a slow request from the Pi to WLED
    // devices taking longer than the poll interval) - piling up concurrent
    // fetches only makes the re-render-mid-tap problem below worse.
    if (stateFetchInFlight) return;
    stateFetchInFlight = true;
    try {
      const data = await api("/api/state");
      const json = JSON.stringify(data);
      const changed = json !== lastStateJSON;
      lastStateJSON = json;
      state = data;
      if (!currentZone || !state[currentZone]) {
        currentZone = Object.keys(state)[0] || null;
      }
      const anyConnected = currentZone
        ? Object.values(state[currentZone].controllers).some((c) => c.connected)
        : false;
      const allConnected = currentZone
        ? Object.values(state[currentZone].controllers).every((c) => c.connected)
        : false;
      const dot = $("#conn-dot");
      dot.classList.toggle("ok", allConnected);
      dot.classList.toggle("bad", !anyConnected);
      // Only rebuild the DOM when something actually changed (or the caller
      // needs a guaranteed fresh render, e.g. after switching tabs) - a
      // periodic full rebuild would otherwise risk replacing a button out
      // from under an in-progress tap, silently swallowing it.
      if (changed || force) {
        renderDashboard();
        if (!$("#view-editor").classList.contains("hidden")) renderEditorList();
      }
    } catch (e) {
      $("#conn-dot").classList.add("bad");
      $("#conn-dot").classList.remove("ok");
    } finally {
      stateFetchInFlight = false;
    }
  }

  // ---------------- Dashboard ----------------

  function sceneSwatchColors(actions) {
    const cols = actions.map((a) => a.col).filter(Boolean);
    return cols.length ? cols : [[124, 158, 255]];
  }

  function renderDashboard() {
    if (!currentZone) return;
    $("#zone-title").textContent = currentZone[0].toUpperCase() + currentZone.slice(1);
    const zone = state[currentZone];

    const activeName = Object.entries(zone.scenes).find(([, s]) => s.active)?.[0];
    const nowPlaying = $("#now-playing");
    nowPlaying.classList.toggle("custom", !activeName);
    nowPlaying.innerHTML = activeName
      ? `<span class="dot"></span>${escapeHtml(activeName)}`
      : `<span class="dot"></span>Custom (no scene matches)`;

    const anyOn = Object.values(zone.controllers).some((c) => c.on);
    $("#power-toggle").classList.toggle("on", anyOn);

    const grid = $("#scene-grid");
    grid.innerHTML = "";
    for (const [name, scene] of Object.entries(zone.scenes)) {
      const cols = sceneSwatchColors(scene.actions);
      const card = document.createElement("button");
      card.className = "scene-card" + (scene.active ? " active" : "");
      const gradient =
        cols.length > 1
          ? `linear-gradient(135deg, ${cols.map(rgbToHex).join(", ")})`
          : `radial-gradient(circle at 30% 20%, ${rgbToHex(cols[0])}, transparent 70%)`;
      card.innerHTML = `
        <div class="swatch-bg" style="background:${gradient}"></div>
        ${scene.active ? '<div class="active-badge">&#10003; On</div>' : ""}
        <div class="scene-name">${escapeHtml(name)}</div>
      `;
      card.addEventListener("click", async () => {
        card.classList.add("applying");
        try {
          await api(`/api/zones/${currentZone}/scenes/${encodeURIComponent(name)}/apply`, {
            method: "POST",
          });
          toast(`${name} applied`);
        } finally {
          setTimeout(() => card.classList.remove("applying"), 400);
        }
      });
      grid.appendChild(card);
    }

    const list = $("#controller-list");
    list.innerHTML = "";
    for (const [cname, c] of Object.entries(zone.controllers)) {
      const card = document.createElement("div");
      card.className = "controller-card";
      const segChips = Object.entries(c.segments)
        .map(
          ([sname, seg]) => `
        <div class="segment-chip ${seg.on ? "" : "off"}" data-controller="${cname}" data-segment="${sname}" data-on="${seg.on ? "1" : "0"}">
          <span class="dot" style="background:${rgbToHex(seg.col)}"></span>
          ${escapeHtml(sname)}
        </div>`
        )
        .join("");
      card.innerHTML = `
        <div class="controller-head">
          <span class="controller-name">${escapeHtml(cname)}</span>
          <span class="controller-status ${c.connected ? "connected" : ""}">${c.connected ? "connected" : "offline"}</span>
        </div>
        <div class="segment-row">${segChips}</div>
      `;
      list.appendChild(card);
    }
    $$(".segment-chip", list).forEach((chip) => {
      chip.addEventListener("click", async () => {
        const controller = chip.dataset.controller;
        const segment = chip.dataset.segment;
        const on = chip.dataset.on === "1";
        await api(`/api/zones/${currentZone}/preview`, {
          method: "POST",
          body: JSON.stringify({ controller, segment, power: !on }),
        });
        loadState();
      });
    });
  }

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ---------------- Scene editor list ----------------

  function renderEditorList() {
    if (!currentZone) return;
    const zone = state[currentZone];
    const container = $("#editor-scene-list");
    container.innerHTML = "";
    for (const [name, scene] of Object.entries(zone.scenes)) {
      const cols = sceneSwatchColors(scene.actions);
      const row = document.createElement("div");
      row.className = "editor-row";
      row.innerHTML = `
        <div>
          <div>${escapeHtml(name)}${scene.active ? ' <span class="active-tag">On</span>' : ""}</div>
          <div class="swatch-strip">${cols
            .slice(0, 6)
            .map((c) => `<span style="background:${rgbToHex(c)}"></span>`)
            .join("")}</div>
        </div>
        <span class="chev">&#8250;</span>
      `;
      row.addEventListener("click", () => openSceneEditor(name));
      container.appendChild(row);
    }
    let fab = $("#add-scene-fab");
    if (!fab) {
      fab = document.createElement("button");
      fab.id = "add-scene-fab";
      fab.className = "fab";
      fab.textContent = "+";
      fab.addEventListener("click", () => openSceneEditor(null));
      document.body.appendChild(fab);
    }
  }

  // ---------------- Scene editor (full screen) ----------------

  function buildDraft(sceneName) {
    const zone = state[currentZone];
    const draft = { origName: sceneName, name: sceneName || "New Scene", controllers: {} };
    for (const [cname, c] of Object.entries(zone.controllers)) {
      draft.controllers[cname] = {
        mode: "segments",
        preset: 1,
        segments: {},
      };
      for (const sname of Object.keys(c.segments)) {
        draft.controllers[cname].segments[sname] = { included: false, power: true, col: [255, 180, 80] };
      }
    }
    if (sceneName) {
      for (const action of zone.scenes[sceneName].actions) {
        const cd = draft.controllers[action.controller];
        if (!cd) continue;
        if (action.preset !== undefined && action.preset !== null) {
          cd.mode = "preset";
          cd.preset = action.preset;
        } else if (action.segment) {
          cd.segments[action.segment] = {
            included: true,
            power: action.power !== false,
            col: action.col || [255, 180, 80],
          };
        }
      }
    }
    return draft;
  }

  function draftToActions(draft) {
    const actions = [];
    for (const [cname, cd] of Object.entries(draft.controllers)) {
      if (cd.mode === "preset") {
        actions.push({ controller: cname, preset: Number(cd.preset) });
        continue;
      }
      for (const [sname, sd] of Object.entries(cd.segments)) {
        if (!sd.included) continue;
        const action = { controller: cname, segment: sname, power: sd.power };
        if (sd.power) action.col = sd.col;
        actions.push(action);
      }
    }
    return actions;
  }

  function openSceneEditor(sceneName) {
    editorDraft = buildDraft(sceneName);
    renderSceneEditor();
    switchView("scene-editor");
  }

  function renderSceneEditor() {
    const zone = state[currentZone];
    const root = $("#scene-editor-content");
    const isNew = !editorDraft.origName;

    let controllersHtml = "";
    for (const [cname, cd] of Object.entries(editorDraft.controllers)) {
      const segRows = Object.entries(cd.segments)
        .map(([sname, sd]) => {
          return `
          <div class="se-segment ${sd.included ? "included" : ""}" data-controller="${cname}" data-segment="${sname}">
            <div class="se-segment-top">
              <span class="se-segment-name">${escapeHtml(sname)}</span>
              <button type="button" class="include-chip seg-include" aria-pressed="${sd.included}">
                ${sd.included ? "&#10003; In scene" : "Add to scene"}
              </button>
            </div>
            ${
              sd.included
                ? `<div class="color-row">
                    <input type="color" class="color-swatch-input seg-color" value="${rgbToHex(sd.col)}">
                    <span class="power-label">Power</span>
                    <label class="switch" style="margin-left:auto">
                      <input type="checkbox" class="seg-power" ${sd.power ? "checked" : ""}>
                      <span class="switch-track"></span>
                    </label>
                  </div>`
                : ""
            }
          </div>`;
        })
        .join("");

      controllersHtml += `
        <div class="se-controller" data-controller="${cname}">
          <div class="se-controller-head">${escapeHtml(cname)}</div>
          ${segRows}
        </div>`;
    }

    root.innerHTML = `
      <div class="editor-header">
        <button class="icon-btn" id="se-back">&#8592;</button>
        <input class="name-input" id="se-name" value="${escapeHtml(editorDraft.name)}">
      </div>
      ${controllersHtml}
      <div class="editor-footer">
        ${isNew ? "" : `<button class="btn btn-danger" id="se-delete">Delete</button>`}
        <button class="btn btn-secondary" id="se-preview">Preview</button>
        <button class="btn btn-primary" id="se-save">Save</button>
      </div>
    `;

    $("#se-back").addEventListener("click", () => switchView("editor"));
    $("#se-name").addEventListener("input", (e) => (editorDraft.name = e.target.value));

    $$(".seg-include", root).forEach((btn) =>
      btn.addEventListener("click", (e) => {
        const seg = e.target.closest(".se-segment");
        const cd = editorDraft.controllers[seg.dataset.controller].segments[seg.dataset.segment];
        cd.included = !cd.included;
        renderSceneEditor();
        if (cd.included) schedulePreview();
      })
    );
    $$(".seg-power", root).forEach((cb) =>
      cb.addEventListener("change", (e) => {
        const seg = e.target.closest(".se-segment");
        const cd = editorDraft.controllers[seg.dataset.controller].segments[seg.dataset.segment];
        cd.power = e.target.checked;
        schedulePreview();
      })
    );
    $$(".seg-color", root).forEach((inp) =>
      inp.addEventListener("input", (e) => {
        const seg = e.target.closest(".se-segment");
        const cd = editorDraft.controllers[seg.dataset.controller].segments[seg.dataset.segment];
        cd.col = hexToRgb(e.target.value);
        schedulePreview();
      })
    );

    $("#se-preview").addEventListener("click", () => sendPreview());
    $("#se-save").addEventListener("click", saveScene);
    const del = $("#se-delete");
    if (del) del.addEventListener("click", deleteScene);
  }

  function schedulePreview() {
    clearTimeout(previewDebounce);
    previewDebounce = setTimeout(sendPreview, 180);
  }

  async function sendPreview() {
    const actions = draftToActions(editorDraft);
    for (const action of actions) {
      await api(`/api/zones/${currentZone}/preview`, {
        method: "POST",
        body: JSON.stringify(action),
      }).catch(() => {});
    }
  }

  async function saveScene() {
    const name = editorDraft.name.trim();
    if (!name) return toast("Name can't be empty");
    const actions = draftToActions(editorDraft);
    if (!actions.length) return toast("Add at least one segment or preset");

    if (editorDraft.origName && editorDraft.origName !== name) {
      await api(`/api/zones/${currentZone}/scenes/${encodeURIComponent(editorDraft.origName)}/rename`, {
        method: "POST",
        body: JSON.stringify({ new_name: name }),
      });
    }
    await api(`/api/zones/${currentZone}/scenes/${encodeURIComponent(name)}`, {
      method: "POST",
      body: JSON.stringify({ actions }),
    });
    toast("Saved");
    await loadState();
    switchView("editor");
  }

  function confirmModal(message) {
    return new Promise((resolve) => {
      const overlay = document.createElement("div");
      overlay.className = "modal-overlay";
      overlay.innerHTML = `
        <div class="modal-card">
          <p class="modal-message">${escapeHtml(message)}</p>
          <div class="modal-actions">
            <button class="btn btn-secondary" id="modal-cancel">Cancel</button>
            <button class="btn btn-danger-solid" id="modal-confirm">Delete</button>
          </div>
        </div>`;
      document.body.appendChild(overlay);
      const cleanup = (result) => {
        overlay.remove();
        resolve(result);
      };
      $("#modal-cancel", overlay).addEventListener("click", () => cleanup(false));
      $("#modal-confirm", overlay).addEventListener("click", () => cleanup(true));
      overlay.addEventListener("click", (e) => {
        if (e.target === overlay) cleanup(false);
      });
    });
  }

  async function deleteScene() {
    if (!(await confirmModal(`Delete "${editorDraft.origName}"?`))) return;
    await api(`/api/zones/${currentZone}/scenes/${encodeURIComponent(editorDraft.origName)}`, {
      method: "DELETE",
    });
    toast("Deleted");
    await loadState();
    switchView("editor");
  }

  // ---------------- Navigation ----------------

  function switchView(name) {
    $$(".view").forEach((v) => v.classList.add("hidden"));
    $(`#view-${name}`).classList.remove("hidden");
    $$(".tab-btn").forEach((b) => b.classList.remove("active"));
    const tab = name === "scene-editor" ? "editor" : name;
    const btn = $(`.tab-btn[data-view="${tab}"]`);
    if (btn) btn.classList.add("active");
    const fab = $("#add-scene-fab");
    if (fab) fab.style.display = name === "editor" ? "flex" : "none";
    if (name === "editor") renderEditorList();
  }

  $$(".tab-btn").forEach((btn) =>
    btn.addEventListener("click", () => switchView(btn.dataset.view))
  );

  $("#power-toggle").addEventListener("click", async () => {
    if (!currentZone) return;
    const btn = $("#power-toggle");
    btn.disabled = true;
    try {
      const result = await api(`/api/zones/${currentZone}/toggle-power`, { method: "POST" });
      toast(result.on ? "Lights on" : "All lights off");
      await loadState(true);
    } finally {
      btn.disabled = false;
    }
  });

  loadState();
  pollTimer = setInterval(loadState, 4000);
})();
