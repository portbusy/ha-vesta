/**
 * Vesta Schedule Panel — vanilla LitElement-free custom element
 * Registers as <vesta-panel> in the Home Assistant sidebar.
 */

const MODES = {
  comfort: { label: "Comfort", color: "#FF8C00" },
  eco:     { label: "Eco",     color: "#0277BD" },   // darkened for WCAG AA contrast
  away:    { label: "Away",    color: "#2E7D32" },   // darkened for WCAG AA contrast
  frost:   { label: "Frost",   color: "#7C4DFF" },
  off:     { label: "Off",     color: "#757575" },   // darkened from #9E9E9E
  custom:  { label: "Custom",  color: "#C2185B" },   // darkened from #E91E63
};

const HOUR_HEIGHT = 40; // px per hour (24h = 960px total)

const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DAY_NAMES_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function pad(n) { return String(n).padStart(2, "0"); }
function minutesToTime(m) { return `${pad(Math.floor(m / 60))}:${pad(m % 60)}`; }
function timeToMinutes(t) {
  const [h, m] = t.split(":").map(Number);
  return h * 60 + m;
}
function modeFromBlock(block) {
  if (!block.mode) return "off";
  if (block.mode.startsWith("temp:")) return "custom";
  return block.mode;
}
function modeColor(block) {
  const m = modeFromBlock(block);
  return (MODES[m] || MODES.off).color;
}
function roundTo30Min(timeStr) {
  const [h, m] = timeStr.split(":").map(Number);
  const total = Math.round((h * 60 + (m || 0)) / 30) * 30;
  const hh = Math.floor(total / 60) % 24;
  const mm = total % 60;
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

class VestaPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._schedules = [];
    this._selectedId = null;
    this._selectedSchedule = null;
    this._rooms = [];
    this._templates = [];
    this._tab = "grid"; // "grid" | "rooms"
    this._mobileDayIndex = new Date().getDay() === 0 ? 6 : new Date().getDay() - 1;
    this._narrow = window.innerWidth < 700;
    this._sidebarOpen = false;
    this._resizeObserver = new ResizeObserver(() => {
      const wasNarrow = this._narrow;
      this._narrow = this.offsetWidth < 700;
      if (wasNarrow !== this._narrow) this._render();
    });
    this._resizeObserver.observe(this);
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._loaded) {
      this._loaded = true;
      this._load();
    }
  }

  connectedCallback() { this._render(); }
  disconnectedCallback() { this._resizeObserver.disconnect(); }

  async _ws(msg) {
    return this._hass.connection.sendMessagePromise(msg);
  }

  async _load() {
    this._loadError = null;
    try {
      const [schedules, rooms, templates] = await Promise.all([
        this._ws({ type: "vesta/schedules/list" }),
        this._ws({ type: "vesta/rooms/list" }),
        this._ws({ type: "vesta/schedules/templates" }),
      ]);
      this._schedules = schedules;
      this._rooms = rooms;
      this._templates = templates;
      if (this._schedules.length > 0 && !this._selectedId) {
        await this._selectSchedule(this._schedules[0].id);
      } else {
        this._render();
      }
    } catch (e) {
      console.error("Vesta: load error", e);
      this._loadError = "Could not connect to Vesta. Is the integration loaded?";
      this._render();
    }
  }

  async _selectSchedule(id) {
    this._selectedId = id;
    try {
      this._selectedSchedule = await this._ws({ type: "vesta/schedules/get", schedule_id: id });
    } catch (e) {
      this._selectedSchedule = null;
    }
    if (this._narrow) this._sidebarOpen = false;
    this._render();
  }

  // -----------------------------------------------------------------------
  // RENDER
  // -----------------------------------------------------------------------

  _render() {
    const root = this.shadowRoot;
    const sidebarClass = this._narrow
      ? (this._sidebarOpen ? "sidebar sidebar-drawer sidebar-open" : "sidebar sidebar-drawer")
      : "sidebar";

    root.innerHTML = `
      <style>${this._css()}</style>
      <div class="app">
        ${this._narrow && this._sidebarOpen ? `<div class="sidebar-scrim" id="sidebar-scrim"></div>` : ""}
        <div class="${sidebarClass}">
          <div class="sidebar-header">
            <span class="logo">🌡 Vesta</span>
            <div style="display:flex;gap:4px;align-items:center">
              <button class="btn-icon" id="btn-new" title="New schedule" aria-label="New schedule">+</button>
              ${this._narrow ? `<button class="btn-icon" id="btn-close-sidebar" aria-label="Close sidebar">✕</button>` : ""}
            </div>
          </div>
          <div class="schedule-list" role="listbox" aria-label="Schedules">
            ${this._schedules.length === 0
              ? `<div class="empty-list">No schedules yet.<br>Tap + to create your first one.</div>`
              : this._schedules.map(s => `
                <div class="schedule-item ${s.id === this._selectedId ? "active" : ""}" data-id="${s.id}"
                     role="option" aria-selected="${s.id === this._selectedId}" tabindex="0">
                  <span class="schedule-name" title="${this._escape(s.name)}">${this._escape(s.name)}</span>
                  <div class="schedule-actions">
                    <button class="btn-icon-sm" data-action="duplicate" data-id="${s.id}" aria-label="Duplicate ${this._escape(s.name)}">⧉</button>
                    <button class="btn-icon-sm danger" data-action="delete" data-id="${s.id}" aria-label="Delete ${this._escape(s.name)}">✕</button>
                  </div>
                </div>`).join("")}
          </div>
        </div>
        <div class="main">
          ${this._narrow ? `
            <div class="mobile-topbar">
              <button class="btn-icon" id="btn-open-sidebar" aria-label="Open schedules list">☰</button>
              <span class="mobile-topbar-title">${this._selectedSchedule ? this._escape(this._selectedSchedule.name) : "Vesta Schedules"}</span>
            </div>
          ` : ""}
          ${this._selectedSchedule ? this._renderMain() : this._renderEmpty()}
        </div>
      </div>
      ${this._renderDialogPlaceholder()}
    `;
    this._attachListeners();
  }

  _renderEmpty() {
    if (this._loadError) {
      return `<div class="main-empty">
        <div class="main-empty-icon">⚠️</div>
        <div class="main-empty-text" style="color:#e53935">${this._escape(this._loadError)}</div>
        <button class="btn-primary" id="btn-retry">Retry</button>
      </div>`;
    }
    if (this._schedules.length === 0) {
      return `<div class="main-empty">
        <div class="main-empty-icon">📅</div>
        <div class="main-empty-text">No schedules yet.</div>
        <button class="btn-primary" id="btn-new-empty">Create your first schedule</button>
      </div>`;
    }
    return `<div class="main-empty">
      <div class="main-empty-icon">📅</div>
      <div class="main-empty-text">Select a schedule to view or edit it.</div>
    </div>`;
  }

  _renderMain() {
    const s = this._selectedSchedule;
    return `
      <div class="main-header">
        <h2 class="schedule-title" id="main-title">${this._escape(s.name)}</h2>
        <div class="main-actions">
          <button class="btn-primary" id="btn-add-block">+ Add block</button>
          <button class="btn-secondary" id="btn-rename">Rename</button>
        </div>
      </div>
      <div class="tab-bar" role="tablist">
        <button class="tab ${this._tab === "grid" ? "active" : ""}" data-tab="grid"
                role="tab" aria-selected="${this._tab === "grid"}">Schedule Grid</button>
        <button class="tab ${this._tab === "rooms" ? "active" : ""}" data-tab="rooms"
                role="tab" aria-selected="${this._tab === "rooms"}">Room Assignments</button>
      </div>
      ${this._tab === "grid" ? this._renderGrid() : this._renderRoomsTab()}
    `;
  }

  _renderGrid() {
    if (this._narrow) return this._renderMobileGrid();
    const s = this._selectedSchedule;
    const blocks = s.blocks || [];
    const TOTAL_HEIGHT = 24 * HOUR_HEIGHT;

    const columns = DAY_NAMES.map((day, di) => {
      const dayBlocks = blocks.map((b, idx) => ({ b, idx })).filter(({ b }) => (b.days || []).includes(di));
      const blockHtml = dayBlocks.map(({ b: block, idx }) => {
        const startMin = timeToMinutes(block.start);
        const endMin = timeToMinutes(block.end);
        const top = (startMin / 60) * HOUR_HEIGHT;
        const height = ((endMin - startMin) / 60) * HOUR_HEIGHT;
        const label = this._blockLabel(block);
        return `<div class="block" style="top:${top}px;height:${height}px;background:${modeColor(block)}"
                     data-block-idx="${idx}" role="button" tabindex="0"
                     aria-label="Edit ${this._escape(label)} block, ${block.start}–${block.end}">
                  <span class="block-label">${this._escape(label)}</span>
                </div>`;
      }).join("");
      return `<div class="col">
        <div class="col-header">${day}</div>
        <div class="col-body" style="height:${TOTAL_HEIGHT}px" data-day="${di}">${blockHtml}</div>
      </div>`;
    }).join("");

    const timeAxis = Array.from({ length: 25 }, (_, i) =>
      `<div class="time-tick" style="top:${i * HOUR_HEIGHT}px">${pad(i)}:00</div>`
    ).join("");

    return `
      <div class="grid-legend" aria-label="Mode legend">${Object.entries(MODES).map(([, v]) =>
        `<span class="legend-item"><span class="legend-dot" style="background:${v.color}" aria-hidden="true"></span>${v.label}</span>`
      ).join("")}</div>
      <div class="grid-wrapper">
        <div class="time-axis" aria-hidden="true">${timeAxis}</div>
        <div class="grid-days">${columns}</div>
      </div>
    `;
  }

  _renderMobileGrid() {
    const s = this._selectedSchedule;
    const TOTAL_HEIGHT = 24 * HOUR_HEIGHT;
    const allBlocks = s.blocks || [];
    const blockHtml = allBlocks
      .map((b, idx) => ({ b, idx }))
      .filter(({ b }) => (b.days || []).includes(this._mobileDayIndex))
      .map(({ b: block, idx }) => {
        const startMin = timeToMinutes(block.start);
        const endMin = timeToMinutes(block.end);
        const top = (startMin / 60) * HOUR_HEIGHT;
        const height = ((endMin - startMin) / 60) * HOUR_HEIGHT;
        const label = this._blockLabel(block);
        return `<div class="block" style="top:${top}px;height:${height}px;background:${modeColor(block)}"
                     data-block-idx="${idx}" role="button" tabindex="0"
                     aria-label="Edit ${this._escape(label)} block, ${block.start}–${block.end}">
                  <span class="block-label">${this._escape(label)}</span>
                </div>`;
      }).join("");

    const dayButtons = DAY_NAMES.map((name, i) =>
      `<button class="btn-day-select ${i === this._mobileDayIndex ? "active" : ""}" data-day="${i}"
               aria-pressed="${i === this._mobileDayIndex}">${name}</button>`
    ).join("");

    return `
      <div class="mobile-nav">
        <button class="btn-icon btn-nav" id="btn-prev-day" aria-label="Previous day">‹</button>
        <span class="mobile-day-label">${DAY_NAMES_FULL[this._mobileDayIndex]}</span>
        <button class="btn-icon btn-nav" id="btn-next-day" aria-label="Next day">›</button>
      </div>
      <div class="day-select-row" role="group" aria-label="Select day">${dayButtons}</div>
      <div class="grid-legend">${Object.entries(MODES).map(([, v]) =>
        `<span class="legend-item"><span class="legend-dot" style="background:${v.color}" aria-hidden="true"></span>${v.label}</span>`
      ).join("")}</div>
      <div class="grid-wrapper mobile">
        <div class="time-axis" aria-hidden="true">${Array.from({ length: 25 }, (_, i) =>
          `<div class="time-tick" style="top:${i * HOUR_HEIGHT}px">${pad(i)}:00</div>`).join("")}</div>
        <div class="grid-days single">
          <div class="col" style="flex:1">
            <div class="col-header">${DAY_NAMES[this._mobileDayIndex]}</div>
            <div class="col-body" style="height:${TOTAL_HEIGHT}px" data-day="${this._mobileDayIndex}">${blockHtml}</div>
          </div>
        </div>
      </div>
    `;
  }

  _renderRoomsTab() {
    const sid = this._selectedId;
    return `
      <div class="rooms-tab">
        <p class="rooms-desc">Assign rooms to use this schedule instead of the global one.</p>
        ${this._rooms.length === 0
          ? `<p class="rooms-desc">No rooms found. Add rooms via the Vesta integration settings.</p>`
          : `<div class="rooms-table-wrap">
              <table class="rooms-table">
                <thead><tr><th>Room</th><th>Schedule Source</th><th></th></tr></thead>
                <tbody>
                  ${this._rooms.map(room => {
                    const usesThis = room.schedule_source === "vesta" && room.vesta_schedule_id === sid;
                    return `<tr>
                      <td>${this._escape(room.name)}</td>
                      <td class="room-source">${usesThis
                        ? `<span class="badge vesta">This schedule</span>`
                        : `<span class="badge inherit">Global / other</span>`}</td>
                      <td>
                        ${usesThis
                          ? `<button class="btn-secondary btn-sm" data-room-action="inherit"
                                     data-entry-id="${room.entry_id}"
                                     aria-label="Reset ${this._escape(room.name)} to global schedule">Reset to global</button>`
                          : `<button class="btn-primary btn-sm" data-room-action="assign"
                                     data-entry-id="${room.entry_id}"
                                     aria-label="Assign ${this._escape(room.name)} to this schedule">Assign</button>`}
                      </td>
                    </tr>`;
                  }).join("")}
                </tbody>
              </table>
            </div>`}
      </div>
    `;
  }

  _renderDialogPlaceholder() {
    return `<div id="dialog-overlay" class="dialog-overlay hidden" role="presentation"></div>
            <div id="dialog-container" class="dialog hidden" role="dialog" aria-modal="true" aria-labelledby="d-title"></div>`;
  }

  _blockLabel(block) {
    const m = modeFromBlock(block);
    if (m === "custom") return `${block.mode.split(":")[1]}°`;
    return (MODES[m] || MODES.off).label;
  }

  // -----------------------------------------------------------------------
  // ATTACH EVENTS
  // -----------------------------------------------------------------------

  _attachListeners() {
    const r = this.shadowRoot;

    r.getElementById("btn-new")?.addEventListener("click", () => this._showCreateDialog());
    r.getElementById("btn-new-empty")?.addEventListener("click", () => this._showCreateDialog());
    r.getElementById("btn-retry")?.addEventListener("click", () => this._load());

    r.getElementById("btn-open-sidebar")?.addEventListener("click", () => {
      this._sidebarOpen = true;
      this._render();
    });
    r.getElementById("btn-close-sidebar")?.addEventListener("click", () => {
      this._sidebarOpen = false;
      this._render();
    });
    r.getElementById("sidebar-scrim")?.addEventListener("click", () => {
      this._sidebarOpen = false;
      this._render();
    });

    r.querySelectorAll(".schedule-item").forEach(el => {
      const select = (e) => {
        if (e.target.closest("[data-action]")) return;
        this._selectSchedule(el.dataset.id);
      };
      el.addEventListener("click", select);
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); select(e); }
      });
    });

    r.querySelectorAll("[data-action=duplicate]").forEach(btn => {
      btn.addEventListener("click", (e) => { e.stopPropagation(); this._showDuplicateDialog(btn.dataset.id); });
    });
    r.querySelectorAll("[data-action=delete]").forEach(btn => {
      btn.addEventListener("click", (e) => { e.stopPropagation(); this._confirmDelete(btn.dataset.id); });
    });

    r.querySelectorAll(".tab").forEach(t => {
      t.addEventListener("click", () => { this._tab = t.dataset.tab; this._render(); });
    });

    r.getElementById("btn-add-block")?.addEventListener("click", () => this._showBlockDialog(null));
    r.getElementById("btn-rename")?.addEventListener("click", () => this._showRenameDialog());

    r.querySelectorAll(".block").forEach(el => {
      const open = () => {
        const idx = parseInt(el.dataset.blockIdx, 10);
        const block = this._selectedSchedule.blocks[idx];
        if (block !== undefined) this._showBlockDialog(block, idx);
      };
      el.addEventListener("click", open);
      el.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); }
      });
    });

    r.getElementById("btn-prev-day")?.addEventListener("click", () => {
      this._mobileDayIndex = (this._mobileDayIndex + 6) % 7;
      this._render();
    });
    r.getElementById("btn-next-day")?.addEventListener("click", () => {
      this._mobileDayIndex = (this._mobileDayIndex + 1) % 7;
      this._render();
    });
    r.querySelectorAll(".btn-day-select").forEach(btn => {
      btn.addEventListener("click", () => {
        this._mobileDayIndex = parseInt(btn.dataset.day, 10);
        this._render();
      });
    });

    r.querySelectorAll("[data-room-action]").forEach(btn => {
      btn.addEventListener("click", () => {
        const action = btn.dataset.roomAction;
        const entryId = btn.dataset.entryId;
        this._assignRoom(entryId, action === "assign" ? "vesta" : "inherit", this._selectedId, btn);
      });
    });

    r.getElementById("dialog-overlay")?.addEventListener("click", () => this._closeDialog());
  }

  // -----------------------------------------------------------------------
  // DIALOGS
  // -----------------------------------------------------------------------

  _showDialog(html, onSubmit) {
    const overlay = this.shadowRoot.getElementById("dialog-overlay");
    const container = this.shadowRoot.getElementById("dialog-container");
    overlay.classList.remove("hidden");
    container.classList.remove("hidden");
    container.innerHTML = `
      <button class="dialog-close" id="d-close" aria-label="Close">✕</button>
      ${html}
    `;
    container.querySelector("[data-dialog-submit]")?.addEventListener("click", () => onSubmit(container));
    container.querySelector("[data-dialog-cancel]")?.addEventListener("click", () => this._closeDialog());
    container.querySelector("#d-close")?.addEventListener("click", () => this._closeDialog());

    // Close on Escape, focus trap on Tab
    container.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { this._closeDialog(); return; }
      if (e.key !== "Tab") return;
      const focusable = Array.from(container.querySelectorAll(
        "button:not([disabled]), input:not([disabled]), select:not([disabled])"
      ));
      if (focusable.length < 2) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = this.shadowRoot.activeElement;
      if (e.shiftKey && active === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && active === last) { e.preventDefault(); first.focus(); }
    });

    // Auto-focus first input or the submit button
    const firstInput = container.querySelector("input, select");
    (firstInput || container.querySelector("[data-dialog-submit]"))?.focus();
  }

  _closeDialog() {
    this.shadowRoot.getElementById("dialog-overlay")?.classList.add("hidden");
    this.shadowRoot.getElementById("dialog-container")?.classList.add("hidden");
  }

  _showCreateDialog() {
    const templateOptions = [
      `<option value="">Blank schedule</option>`,
      ...this._templates.map(t => `<option value="${t.id}">${this._escape(t.name)} (${t.block_count} blocks)</option>`),
    ].join("");

    this._showDialog(`
      <h3 id="d-title">New Schedule</h3>
      <label>Name<br><input id="d-name" type="text" placeholder="My schedule" autocomplete="off" /></label>
      <label>Start from template<br><select id="d-template">${templateOptions}</select></label>
      <div class="dialog-error hidden" id="d-error" role="alert"></div>
      <div class="dialog-actions">
        <button data-dialog-cancel class="btn-secondary">Cancel</button>
        <button data-dialog-submit class="btn-primary">Create</button>
      </div>
    `, async (container) => {
      const name = container.querySelector("#d-name").value.trim();
      const template = container.querySelector("#d-template").value || null;
      if (!name) {
        const err = container.querySelector("#d-error");
        err.textContent = "Name is required.";
        err.classList.remove("hidden");
        container.querySelector("#d-name").focus();
        return;
      }
      try {
        const result = await this._ws({ type: "vesta/schedules/create", name, template });
        this._closeDialog();
        await this._load();
        await this._selectSchedule(result.id);
      } catch (e) {
        const err = container.querySelector("#d-error");
        err.textContent = "Error: " + (e.message || e);
        err.classList.remove("hidden");
      }
    });
  }

  _showDuplicateDialog(scheduleId) {
    const original = this._schedules.find(s => s.id === scheduleId);
    const defaultName = original ? `${original.name} (copy)` : "Copy";
    this._showDialog(`
      <h3 id="d-title">Duplicate Schedule</h3>
      <label>New name<br><input id="d-name" type="text" value="${this._escape(defaultName)}" autocomplete="off" /></label>
      <div class="dialog-error hidden" id="d-error" role="alert"></div>
      <div class="dialog-actions">
        <button data-dialog-cancel class="btn-secondary">Cancel</button>
        <button data-dialog-submit class="btn-primary">Duplicate</button>
      </div>
    `, async (container) => {
      const newName = container.querySelector("#d-name").value.trim();
      if (!newName) return;
      try {
        const result = await this._ws({ type: "vesta/schedules/duplicate", schedule_id: scheduleId, new_name: newName });
        this._closeDialog();
        await this._load();
        await this._selectSchedule(result.id);
      } catch (e) {
        const err = container.querySelector("#d-error");
        err.textContent = "Error: " + (e.message || e);
        err.classList.remove("hidden");
      }
    });
    this.shadowRoot.getElementById("dialog-container")?.querySelector("#d-name")?.select();
  }

  _showRenameDialog() {
    const current = this._selectedSchedule?.name || "";
    this._showDialog(`
      <h3 id="d-title">Rename Schedule</h3>
      <label>Name<br><input id="d-name" type="text" value="${this._escape(current)}" autocomplete="off" /></label>
      <div class="dialog-error hidden" id="d-error" role="alert"></div>
      <div class="dialog-actions">
        <button data-dialog-cancel class="btn-secondary">Cancel</button>
        <button data-dialog-submit class="btn-primary">Save</button>
      </div>
    `, async (container) => {
      const name = container.querySelector("#d-name").value.trim();
      if (!name) return;
      try {
        await this._ws({ type: "vesta/schedules/update", schedule_id: this._selectedId, name });
        this._closeDialog();
        await this._load();
        await this._selectSchedule(this._selectedId);
      } catch (e) {
        const err = container.querySelector("#d-error");
        err.textContent = "Error: " + (e.message || e);
        err.classList.remove("hidden");
      }
    });
    this.shadowRoot.getElementById("dialog-container")?.querySelector("#d-name")?.select();
  }

  _confirmDelete(scheduleId) {
    const s = this._schedules.find(x => x.id === scheduleId);
    const name = s ? s.name : scheduleId;
    this._showDialog(`
      <h3 id="d-title">Delete Schedule</h3>
      <p>Delete <strong>${this._escape(name)}</strong>? Rooms using it will revert to the global schedule.</p>
      <div class="dialog-error hidden" id="d-error" role="alert"></div>
      <div class="dialog-actions">
        <button data-dialog-cancel class="btn-secondary">Cancel</button>
        <button data-dialog-submit class="btn-primary danger">Delete</button>
      </div>
    `, async () => {
      try {
        await this._ws({ type: "vesta/schedules/delete", schedule_id: scheduleId });
        if (this._selectedId === scheduleId) { this._selectedId = null; this._selectedSchedule = null; }
        this._closeDialog();
        await this._load();
      } catch (e) {
        const err = this.shadowRoot.getElementById("dialog-container")?.querySelector("#d-error");
        if (err) { err.textContent = "Error: " + (e.message || e); err.classList.remove("hidden"); }
      }
    });
  }

  _showBlockDialog(existingBlock, existingIndex = -1) {
    const isEdit = existingBlock !== null;
    const b = existingBlock || { days: [0,1,2,3,4,5,6], start: "06:00", end: "08:00", mode: "comfort" };
    const currentMode = modeFromBlock(b);
    const currentTemp = currentMode === "custom" ? b.mode.split(":")[1] : "21";

    const modeOptions = Object.entries(MODES).map(([k, v]) =>
      `<option value="${k}" ${currentMode === k ? "selected" : ""}>${v.label}</option>`
    ).join("");
    const dayCheckboxes = DAY_NAMES.map((name, i) =>
      `<label class="day-cb"><input type="checkbox" value="${i}" ${(b.days || []).includes(i) ? "checked" : ""}> ${name}</label>`
    ).join("");

    this._showDialog(`
      <h3 id="d-title">${isEdit ? "Edit Block" : "Add Block"}</h3>
      <div class="form-row">
        <label>Start<br><input id="d-start" type="time" value="${b.start}" step="1800" /></label>
        <label>End<br><input id="d-end" type="time" value="${b.end}" step="1800" /></label>
      </div>
      <label>Mode<br><select id="d-mode">${modeOptions}</select></label>
      <div id="d-temp-row" style="display:${currentMode === "custom" ? "block" : "none"}">
        <label>Temperature (°C)<br><input id="d-temp" type="number" step="0.5" min="5" max="35" value="${currentTemp}" /></label>
      </div>
      <fieldset>
        <legend>Days</legend>
        <div class="day-quick-btns">
          <button type="button" class="btn-day-quick" data-days="0,1,2,3,4,5,6">All</button>
          <button type="button" class="btn-day-quick" data-days="0,1,2,3,4">Weekdays</button>
          <button type="button" class="btn-day-quick" data-days="5,6">Weekend</button>
        </div>
        <div class="day-checkboxes">${dayCheckboxes}</div>
      </fieldset>
      <div class="dialog-error hidden" id="d-error" role="alert"></div>
      <div class="dialog-actions">
        ${isEdit ? `<button class="btn-primary danger" id="d-delete-block">Delete block</button>` : ""}
        <button data-dialog-cancel class="btn-secondary">Cancel</button>
        <button data-dialog-submit class="btn-primary">Save</button>
      </div>
    `, async (container) => {
      const start = roundTo30Min(container.querySelector("#d-start").value);
      const end = roundTo30Min(container.querySelector("#d-end").value);
      const modeVal = container.querySelector("#d-mode").value;
      const temp = container.querySelector("#d-temp")?.value;
      const days = Array.from(container.querySelectorAll(".day-cb input:checked")).map(el => Number(el.value));

      const err = container.querySelector("#d-error");
      if (days.length === 0) {
        err.textContent = "Select at least one day."; err.classList.remove("hidden"); return;
      }
      if (timeToMinutes(start) >= timeToMinutes(end)) {
        err.textContent = "Start time must be before end time."; err.classList.remove("hidden"); return;
      }
      const mode = modeVal === "custom" ? `temp:${parseFloat(temp).toFixed(1)}` : modeVal;
      const newBlock = { days, start, end, mode };
      let blocks = [...(this._selectedSchedule.blocks || [])];
      if (isEdit && existingIndex >= 0) blocks.splice(existingIndex, 1, newBlock);
      else blocks.push(newBlock);
      try {
        await this._ws({ type: "vesta/schedules/update", schedule_id: this._selectedId, blocks });
        this._closeDialog();
        await this._selectSchedule(this._selectedId);
      } catch (e) {
        err.textContent = "Error: " + (e.message || (typeof e === "object" ? JSON.stringify(e) : String(e)));
        err.classList.remove("hidden");
      }
    });

    const dc = this.shadowRoot.getElementById("dialog-container");

    dc.querySelectorAll(".btn-day-quick").forEach(btn => {
      btn.addEventListener("click", () => {
        const selected = new Set(btn.dataset.days.split(",").map(Number));
        dc.querySelectorAll(".day-cb input").forEach(cb => { cb.checked = selected.has(Number(cb.value)); });
      });
    });

    dc.querySelector("#d-mode")?.addEventListener("change", (e) => {
      const tempRow = dc.querySelector("#d-temp-row");
      if (tempRow) tempRow.style.display = e.target.value === "custom" ? "block" : "none";
    });

    // Delete with inline confirmation (two-tap pattern)
    if (isEdit && existingIndex >= 0) {
      dc.querySelector("#d-delete-block")?.addEventListener("click", (e) => {
        const btn = e.currentTarget;
        if (btn.dataset.confirm === "1") {
          const blocks = [...(this._selectedSchedule.blocks || [])];
          blocks.splice(existingIndex, 1);
          this._ws({ type: "vesta/schedules/update", schedule_id: this._selectedId, blocks })
            .then(() => { this._closeDialog(); return this._selectSchedule(this._selectedId); })
            .catch(err => console.error(err));
        } else {
          btn.dataset.confirm = "1";
          btn.textContent = "Confirm delete?";
          btn.style.outline = "2px solid #e53935";
          setTimeout(() => {
            btn.dataset.confirm = "0";
            btn.textContent = "Delete block";
            btn.style.outline = "";
          }, 3000);
        }
      });
    }
  }

  async _assignRoom(entryId, source, scheduleId, triggerBtn) {
    if (triggerBtn) { triggerBtn.disabled = true; triggerBtn.textContent = "Saving…"; }
    const msg = { type: "vesta/rooms/assign", entry_id: entryId, schedule_source: source };
    if (source === "vesta") msg.vesta_schedule_id = scheduleId;
    try {
      await this._ws(msg);
      this._rooms = await this._ws({ type: "vesta/rooms/list" });
      this._render();
    } catch (e) {
      console.error("Assign room error", e);
      if (triggerBtn) {
        triggerBtn.disabled = false;
        triggerBtn.textContent = source === "vesta" ? "Assign" : "Reset to global";
      }
    }
  }

  _escape(str) {
    return String(str)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // -----------------------------------------------------------------------
  // CSS
  // -----------------------------------------------------------------------

  _css() {
    return `
      :host { display: block; height: 100%; font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif); }
      * { box-sizing: border-box; }
      .app { display: flex; height: 100%; background: var(--primary-background-color, #f5f5f5); overflow: hidden; }

      /* Sidebar */
      .sidebar { width: 240px; min-width: 200px; background: var(--card-background-color, #fff);
        border-right: 1px solid var(--divider-color, #e0e0e0); display: flex; flex-direction: column; overflow: hidden; }
      .sidebar-drawer { position: fixed; top: 0; left: 0; height: 100%; width: 280px; z-index: 200;
        box-shadow: 2px 0 16px rgba(0,0,0,0.25); transform: translateX(-100%); transition: transform 0.2s ease; }
      .sidebar-drawer.sidebar-open { transform: translateX(0); }
      .sidebar-scrim { position: fixed; inset: 0; background: rgba(0,0,0,0.45); z-index: 199; }
      .sidebar-header { display: flex; align-items: center; justify-content: space-between;
        padding: 12px 16px; border-bottom: 1px solid var(--divider-color, #e0e0e0); }
      .logo { font-size: 1.1em; font-weight: 600; color: var(--primary-color, #03a9f4); }
      .schedule-list { flex: 1; overflow-y: auto; padding: 8px 0; }
      .schedule-item { display: flex; align-items: center; justify-content: space-between;
        padding: 10px 12px; cursor: pointer; border-radius: 6px; margin: 2px 8px; transition: background 0.1s; }
      .schedule-item:hover { background: var(--secondary-background-color, #f0f0f0); }
      .schedule-item:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 1px; }
      .schedule-item.active { background: var(--primary-color, #03a9f4); color: #fff; }
      .schedule-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.95em; }
      .schedule-actions { display: flex; gap: 4px; opacity: 0; transition: opacity 0.15s; }
      .schedule-item:hover .schedule-actions,
      .schedule-item.active .schedule-actions,
      .schedule-item:focus-within .schedule-actions { opacity: 1; }
      .empty-list { padding: 24px 16px; color: var(--secondary-text-color, #888); font-size: 0.9em; text-align: center; line-height: 1.5; }

      /* Mobile top bar */
      .mobile-topbar { display: flex; align-items: center; gap: 12px; padding: 8px 16px;
        background: var(--card-background-color, #fff); border-bottom: 1px solid var(--divider-color, #e0e0e0); }
      .mobile-topbar-title { font-weight: 600; font-size: 1em; flex: 1;
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

      /* Main */
      .main { flex: 1; overflow-y: auto; display: flex; flex-direction: column; min-height: 0; min-width: 0; }
      .main-empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; }
      .main-empty-icon { font-size: 3em; }
      .main-empty-text { color: var(--secondary-text-color, #888); }
      .main-header { display: flex; align-items: center; justify-content: space-between;
        padding: 16px 24px 8px; border-bottom: 1px solid var(--divider-color, #e0e0e0);
        background: var(--card-background-color, #fff); flex-wrap: wrap; gap: 8px; }
      .schedule-title { margin: 0; font-size: 1.2em; font-weight: 600; }
      .main-actions { display: flex; gap: 8px; flex-wrap: wrap; }

      /* Tabs */
      .tab-bar { display: flex; padding: 0 24px;
        border-bottom: 2px solid var(--divider-color, #e0e0e0);
        background: var(--card-background-color, #fff); }
      .tab { background: none; border: none; padding: 10px 20px; cursor: pointer; font-size: 0.95em;
        color: var(--secondary-text-color, #888); border-bottom: 2px solid transparent; margin-bottom: -2px; }
      .tab:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: -2px; border-radius: 2px; }
      .tab.active { color: var(--primary-color, #03a9f4); border-bottom-color: var(--primary-color, #03a9f4); font-weight: 500; }

      /* Grid */
      .grid-legend { display: flex; gap: 12px; flex-wrap: wrap; padding: 12px 24px 8px; }
      .legend-item { display: flex; align-items: center; gap: 5px; font-size: 0.85em; }
      .legend-dot { width: 12px; height: 12px; border-radius: 3px; display: inline-block; flex-shrink: 0; }
      .grid-wrapper { display: flex; flex: 1; padding: 0 24px 24px; overflow: auto; min-height: 0; }
      .grid-wrapper.mobile { padding: 0 16px 24px; }
      .time-axis { width: 52px; min-width: 52px; position: relative; padding-top: 32px; flex-shrink: 0; }
      .time-tick { position: absolute; left: 0; right: 0; font-size: 0.75em;
        color: var(--secondary-text-color, #888); text-align: right; padding-right: 6px;
        transform: translateY(-50%); white-space: nowrap; }
      .grid-days { display: flex; flex: 1; gap: 2px; min-width: 0; }
      .grid-days.single { flex: 1; }
      .col { flex: 1; display: flex; flex-direction: column; min-width: 72px; }
      .col-header { text-align: center; font-size: 0.8em; font-weight: 600;
        color: var(--secondary-text-color, #888); padding: 4px 0 8px; height: 32px; }
      .col-body { position: relative; border-radius: 4px; border: 1px solid var(--divider-color, #e0e0e0);
        background: var(--secondary-background-color, #f9f9f9)
          repeating-linear-gradient(to bottom,
            transparent 0px, transparent ${HOUR_HEIGHT - 1}px,
            var(--divider-color, #e0e0e0) ${HOUR_HEIGHT - 1}px,
            var(--divider-color, #e0e0e0) ${HOUR_HEIGHT}px); }
      .block { position: absolute; left: 2px; right: 2px; border-radius: 4px; cursor: pointer;
        transition: filter 0.15s; overflow: hidden; display: flex; align-items: flex-start;
        padding: 2px 4px; min-height: 18px; }
      .block:hover { filter: brightness(0.88); }
      .block:focus-visible { outline: 2px solid #fff; outline-offset: -2px; filter: brightness(0.88); }
      .block-label { font-size: 0.72em; color: #fff; font-weight: 600; white-space: nowrap;
        text-overflow: ellipsis; overflow: hidden;
        text-shadow: 0 1px 2px rgba(0,0,0,0.5); pointer-events: none; }

      /* Mobile nav */
      .mobile-nav { display: flex; align-items: center; justify-content: center; gap: 16px; padding: 8px 24px 4px; }
      .mobile-day-label { font-weight: 600; font-size: 1.05em; min-width: 100px; text-align: center; }
      .btn-nav { font-size: 1.5em; min-width: 44px; min-height: 44px; }
      .day-select-row { display: flex; gap: 4px; padding: 0 16px 8px; flex-wrap: wrap; }
      .btn-day-select { background: var(--secondary-background-color, #eee);
        border: 1px solid var(--divider-color, #ccc); border-radius: 4px;
        padding: 6px 10px; font-size: 0.85em; cursor: pointer; min-height: 36px; min-width: 44px; }
      .btn-day-select:hover { background: var(--primary-color, #03a9f4); color: #fff; border-color: transparent; }
      .btn-day-select.active { background: var(--primary-color, #03a9f4); color: #fff; border-color: transparent; font-weight: 600; }

      /* Rooms tab */
      .rooms-tab { padding: 16px 24px; }
      .rooms-desc { color: var(--secondary-text-color, #888); margin: 0 0 16px; font-size: 0.9em; }
      .rooms-table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
      .rooms-table { width: 100%; border-collapse: collapse; font-size: 0.9em; min-width: 320px; }
      .rooms-table th, .rooms-table td { text-align: left; padding: 8px 12px;
        border-bottom: 1px solid var(--divider-color, #e0e0e0); }
      .rooms-table th { font-weight: 600; color: var(--secondary-text-color, #888); font-size: 0.85em; }
      .badge { padding: 2px 8px; border-radius: 12px; font-size: 0.8em; font-weight: 500; }
      .badge.vesta { background: var(--primary-color, #03a9f4); color: #fff; }
      .badge.inherit { background: var(--secondary-background-color, #e0e0e0); color: var(--secondary-text-color, #555); }
      .room-source { white-space: nowrap; }

      /* Buttons */
      .btn-primary { background: var(--primary-color, #03a9f4); color: #fff; border: none;
        padding: 8px 16px; border-radius: 6px; cursor: pointer; font-size: 0.9em; font-weight: 500; min-height: 36px; }
      .btn-primary:hover { filter: brightness(0.9); }
      .btn-primary:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 2px; }
      .btn-primary:disabled { opacity: 0.6; cursor: default; }
      .btn-primary.danger { background: #e53935; }
      .btn-secondary { background: none; border: 1px solid var(--divider-color, #ccc);
        color: var(--primary-text-color, #333); padding: 8px 16px; border-radius: 6px;
        cursor: pointer; font-size: 0.9em; min-height: 36px; }
      .btn-secondary:hover { background: var(--secondary-background-color, #f0f0f0); }
      .btn-secondary:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 2px; }
      .btn-secondary:disabled { opacity: 0.6; cursor: default; }
      .btn-icon { background: none; border: none; cursor: pointer; font-size: 1.2em;
        color: var(--primary-text-color, #333); padding: 8px; border-radius: 4px; line-height: 1;
        min-width: 36px; min-height: 36px; display: inline-flex; align-items: center; justify-content: center; }
      .btn-icon:hover { background: var(--secondary-background-color, #f0f0f0); }
      .btn-icon:focus-visible { outline: 2px solid var(--primary-color, #03a9f4); outline-offset: 2px; }
      .btn-icon-sm { background: none; border: none; cursor: pointer; font-size: 0.9em;
        padding: 4px 6px; border-radius: 3px; color: inherit; line-height: 1;
        min-width: 28px; min-height: 28px; display: inline-flex; align-items: center; justify-content: center; }
      .btn-icon-sm:hover { background: rgba(0,0,0,0.1); }
      .btn-icon-sm.danger { color: #e53935; }
      .btn-sm { padding: 6px 12px; font-size: 0.85em; min-height: 34px; }

      /* Dialog */
      .dialog-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); z-index: 100; }
      .dialog { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
        background: var(--card-background-color, #fff); border-radius: 12px; padding: 24px 28px;
        min-width: 300px; max-width: 480px; width: 92vw; z-index: 101;
        box-shadow: 0 8px 32px rgba(0,0,0,0.2); max-height: 90vh; overflow-y: auto; }
      .dialog-close { position: absolute; top: 10px; right: 10px; background: none; border: none;
        cursor: pointer; font-size: 1em; color: var(--secondary-text-color, #888);
        padding: 6px 8px; border-radius: 4px; line-height: 1; min-width: 32px; min-height: 32px;
        display: inline-flex; align-items: center; justify-content: center; }
      .dialog-close:hover { background: var(--secondary-background-color, #f0f0f0); }
      .dialog h3 { margin: 0 0 16px; font-size: 1.1em; padding-right: 36px; }
      .dialog label { display: block; margin-bottom: 12px; font-size: 0.9em; color: var(--secondary-text-color, #666); }
      .dialog input, .dialog select { width: 100%; margin-top: 4px; padding: 8px 10px;
        border: 1px solid var(--divider-color, #ccc); border-radius: 6px; font-size: 0.95em;
        background: var(--primary-background-color, #fff); color: var(--primary-text-color, #333);
        min-height: 38px; }
      .dialog input:focus, .dialog select:focus { outline: 2px solid var(--primary-color, #03a9f4); border-color: transparent; }
      .form-row { display: flex; gap: 12px; }
      .form-row label { flex: 1; }
      fieldset { border: 1px solid var(--divider-color, #ccc); border-radius: 6px;
        padding: 8px 12px; margin-bottom: 12px; }
      fieldset legend { font-size: 0.85em; color: var(--secondary-text-color, #666); padding: 0 4px; }
      .day-quick-btns { display: flex; gap: 6px; margin-bottom: 8px; flex-wrap: wrap; }
      .btn-day-quick { background: var(--secondary-background-color, #eee);
        border: 1px solid var(--divider-color, #ccc); border-radius: 4px;
        padding: 4px 12px; font-size: 0.8em; cursor: pointer; min-height: 30px; }
      .btn-day-quick:hover { background: var(--primary-color, #03a9f4); color: #fff; border-color: transparent; }
      .day-checkboxes { display: flex; flex-wrap: wrap; gap: 6px; }
      .day-cb { display: flex; align-items: center; gap: 4px; font-size: 0.9em; cursor: pointer;
        padding: 3px 0; min-height: 28px; }
      .dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; flex-wrap: wrap; }
      .dialog-error { color: #c62828; font-size: 0.85em; margin-top: 4px; padding: 6px 8px;
        background: #ffebee; border-radius: 4px; border-left: 3px solid #e53935; }
      .hidden { display: none !important; }

      @media (max-width: 480px) {
        .form-row { flex-direction: column; gap: 0; }
        .dialog { padding: 20px 16px; }
        .dialog-actions { justify-content: stretch; }
        .dialog-actions button { flex: 1; justify-content: center; }
        .main-header { padding: 12px 16px 8px; }
        .tab-bar { padding: 0 12px; }
        .tab { padding: 10px 12px; font-size: 0.9em; }
        .rooms-tab { padding: 12px 16px; }
        .grid-legend { padding: 8px 16px 6px; }
      }
    `;
  }
}

customElements.define("vesta-panel", VestaPanel);
