/**
 * Vesta Schedule Panel — vanilla LitElement-free custom element
 * Registers as <vesta-panel> in the Home Assistant sidebar.
 */

const MODES = {
  comfort: { label: "Comfort", color: "#FF8C00" },
  eco:     { label: "Eco",     color: "#039BE5" },
  away:    { label: "Away",    color: "#43A047" },
  frost:   { label: "Frost",   color: "#7C4DFF" },
  off:     { label: "Off",     color: "#9E9E9E" },
  custom:  { label: "Custom",  color: "#E91E63" },
};

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
    this._mobileDayIndex = new Date().getDay() === 0 ? 6 : new Date().getDay() - 1; // Mon=0
    this._narrow = window.innerWidth < 700;
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

  connectedCallback() {
    this._render();
  }

  disconnectedCallback() {
    this._resizeObserver.disconnect();
  }

  async _ws(msg) {
    return new Promise((resolve, reject) => {
      this._hass.connection.sendMessagePromise(msg).then(resolve).catch(reject);
    });
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
    this._render();
  }

  // -----------------------------------------------------------------------
  // RENDER
  // -----------------------------------------------------------------------

  _render() {
    const root = this.shadowRoot;
    root.innerHTML = `
      <style>${this._css()}</style>
      <div class="app">
        <div class="sidebar">
          <div class="sidebar-header">
            <span class="logo">🌡 Vesta</span>
            <button class="btn-icon" id="btn-new" title="New schedule">+</button>
          </div>
          <div class="schedule-list">
            ${this._schedules.length === 0
              ? `<div class="empty-list">No schedules yet.<br>Click + to create one.</div>`
              : this._schedules.map(s => `
                <div class="schedule-item ${s.id === this._selectedId ? "active" : ""}" data-id="${s.id}">
                  <span class="schedule-name" title="${this._escape(s.name)}">${this._escape(s.name)}</span>
                  <div class="schedule-actions">
                    <button class="btn-icon-sm" data-action="duplicate" data-id="${s.id}" title="Duplicate">⧉</button>
                    <button class="btn-icon-sm danger" data-action="delete" data-id="${s.id}" title="Delete">✕</button>
                  </div>
                </div>`).join("")}
          </div>
        </div>
        <div class="main">
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
      </div>`;
    }
    return `<div class="main-empty">
      <div class="main-empty-icon">📅</div>
      <div class="main-empty-text">Select or create a schedule to get started.</div>
    </div>`;
  }

  _renderMain() {
    const s = this._selectedSchedule;
    return `
      <div class="main-header">
        <h2 class="schedule-title">${this._escape(s.name)}</h2>
        <div class="main-actions">
          <button class="btn-primary" id="btn-add-block">+ Add block</button>
          <button class="btn-secondary" id="btn-rename">Rename</button>
        </div>
      </div>
      <div class="tab-bar">
        <button class="tab ${this._tab === "grid" ? "active" : ""}" data-tab="grid">Schedule Grid</button>
        <button class="tab ${this._tab === "rooms" ? "active" : ""}" data-tab="rooms">Room Assignments</button>
      </div>
      ${this._tab === "grid" ? this._renderGrid() : this._renderRoomsTab()}
    `;
  }

  _renderGrid() {
    if (this._narrow) {
      return this._renderMobileGrid();
    }
    const s = this._selectedSchedule;
    const blocks = s.blocks || [];
    const HOUR_HEIGHT = 48; // px per hour
    const TOTAL_HEIGHT = 24 * HOUR_HEIGHT;

    const columns = DAY_NAMES.map((day, di) => {
      const dayBlocks = blocks
        .map((b, idx) => ({ b, idx }))
        .filter(({ b }) => (b.days || []).includes(di));
      const blockHtml = dayBlocks.map(({ b: block, idx }) => {
        const startMin = timeToMinutes(block.start);
        const endMin = timeToMinutes(block.end);
        const top = (startMin / 60) * HOUR_HEIGHT;
        const height = ((endMin - startMin) / 60) * HOUR_HEIGHT;
        const color = modeColor(block);
        const label = this._blockLabel(block);
        return `<div class="block" style="top:${top}px;height:${height}px;background:${color}"
                     data-block-idx="${idx}">
                  <span class="block-label">${label}</span>
                </div>`;
      }).join("");
      return `<div class="col">
        <div class="col-header">${day}</div>
        <div class="col-body" style="height:${TOTAL_HEIGHT}px" data-day="${di}">
          ${blockHtml}
        </div>
      </div>`;
    }).join("");

    const timeAxis = Array.from({ length: 25 }, (_, i) => {
      const top = i * HOUR_HEIGHT;
      return `<div class="time-tick" style="top:${top}px">${pad(i)}:00</div>`;
    }).join("");

    return `
      <div class="grid-legend">${Object.entries(MODES).map(([k, v]) =>
        `<span class="legend-item"><span class="legend-dot" style="background:${v.color}"></span>${v.label}</span>`
      ).join("")}</div>
      <div class="grid-wrapper">
        <div class="time-axis">${timeAxis}</div>
        <div class="grid-days">${columns}</div>
      </div>
    `;
  }

  _renderMobileGrid() {
    const s = this._selectedSchedule;
    const blocks = (s.blocks || []).filter(b => (b.days || []).includes(this._mobileDayIndex));
    const HOUR_HEIGHT = 48;
    const TOTAL_HEIGHT = 24 * HOUR_HEIGHT;

    const allBlocks = s.blocks || [];
    const blockHtml = (allBlocks
      .map((b, idx) => ({ b, idx }))
      .filter(({ b }) => (b.days || []).includes(this._mobileDayIndex))
    ).map(({ b: block, idx }) => {
      const startMin = timeToMinutes(block.start);
      const endMin = timeToMinutes(block.end);
      const top = (startMin / 60) * HOUR_HEIGHT;
      const height = ((endMin - startMin) / 60) * HOUR_HEIGHT;
      const color = modeColor(block);
      return `<div class="block" style="top:${top}px;height:${height}px;background:${color}"
                   data-block-idx="${idx}">
                <span class="block-label">${this._blockLabel(block)}</span>
              </div>`;
    }).join("");

    return `
      <div class="mobile-nav">
        <button class="btn-icon" id="btn-prev-day">‹</button>
        <span class="mobile-day-label">${DAY_NAMES_FULL[this._mobileDayIndex]}</span>
        <button class="btn-icon" id="btn-next-day">›</button>
      </div>
      <div class="grid-legend">${Object.entries(MODES).map(([k, v]) =>
        `<span class="legend-item"><span class="legend-dot" style="background:${v.color}"></span>${v.label}</span>`
      ).join("")}</div>
      <div class="grid-wrapper mobile">
        <div class="time-axis">${Array.from({ length: 25 }, (_, i) =>
          `<div class="time-tick" style="top:${i * HOUR_HEIGHT}px">${pad(i)}:00</div>`).join("")}</div>
        <div class="grid-days single">
          <div class="col" style="flex:1">
            <div class="col-header">${DAY_NAMES[this._mobileDayIndex]}</div>
            <div class="col-body" style="height:${TOTAL_HEIGHT}px" data-day="${this._mobileDayIndex}">
              ${blockHtml}
            </div>
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
        <table class="rooms-table">
          <thead><tr><th>Room</th><th>Schedule Source</th><th></th></tr></thead>
          <tbody>
            ${this._rooms.map(room => {
              const usesThis = room.schedule_source === "vesta" && room.vesta_schedule_id === sid;
              const inherits = room.schedule_source !== "vesta" || !room.vesta_schedule_id;
              return `<tr>
                <td>${this._escape(room.name)}</td>
                <td class="room-source">${usesThis ? `<span class="badge vesta">This schedule</span>` : `<span class="badge inherit">Global / other</span>`}</td>
                <td>
                  ${usesThis
                    ? `<button class="btn-secondary btn-sm" data-room-action="inherit" data-entry-id="${room.entry_id}">Reset to global</button>`
                    : `<button class="btn-primary btn-sm" data-room-action="assign" data-entry-id="${room.entry_id}">Assign</button>`}
                </td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  _renderDialogPlaceholder() {
    return `<div id="dialog-overlay" class="dialog-overlay hidden"></div>
            <div id="dialog-container" class="dialog hidden"></div>`;
  }

  _blockLabel(block) {
    const m = modeFromBlock(block);
    if (m === "custom") {
      const temp = block.mode.split(":")[1];
      return `${temp}°`;
    }
    return (MODES[m] || MODES.off).label;
  }

  // -----------------------------------------------------------------------
  // ATTACH EVENTS
  // -----------------------------------------------------------------------

  _attachListeners() {
    const r = this.shadowRoot;

    r.getElementById("btn-new")?.addEventListener("click", () => this._showCreateDialog());

    r.querySelectorAll(".schedule-item").forEach(el => {
      el.addEventListener("click", (e) => {
        if (e.target.closest("[data-action]")) return;
        this._selectSchedule(el.dataset.id);
      });
    });

    r.querySelectorAll("[data-action=duplicate]").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._showDuplicateDialog(btn.dataset.id);
      });
    });

    r.querySelectorAll("[data-action=delete]").forEach(btn => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._confirmDelete(btn.dataset.id);
      });
    });

    r.querySelectorAll(".tab").forEach(t => {
      t.addEventListener("click", () => {
        this._tab = t.dataset.tab;
        this._render();
      });
    });

    r.getElementById("btn-add-block")?.addEventListener("click", () => this._showBlockDialog(null));
    r.getElementById("btn-rename")?.addEventListener("click", () => this._showRenameDialog());

    r.querySelectorAll(".block").forEach(el => {
      el.addEventListener("click", () => {
        const idx = parseInt(el.dataset.blockIdx, 10);
        const block = this._selectedSchedule.blocks[idx];
        if (block !== undefined) this._showBlockDialog(block, idx);
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

    r.querySelectorAll("[data-room-action]").forEach(btn => {
      btn.addEventListener("click", () => {
        const action = btn.dataset.roomAction;
        const entryId = btn.dataset.entryId;
        if (action === "assign") {
          this._assignRoom(entryId, "vesta", this._selectedId);
        } else {
          this._assignRoom(entryId, "inherit", null);
        }
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
    container.innerHTML = html;
    this._currentDialogSubmit = onSubmit;
    container.querySelector("[data-dialog-submit]")?.addEventListener("click", () => {
      onSubmit(container);
    });
    container.querySelector("[data-dialog-cancel]")?.addEventListener("click", () => this._closeDialog());
  }

  _closeDialog() {
    this.shadowRoot.getElementById("dialog-overlay")?.classList.add("hidden");
    this.shadowRoot.getElementById("dialog-container")?.classList.add("hidden");
  }

  _showCreateDialog() {
    const templateOptions = [
      `<option value="">Blank</option>`,
      ...this._templates.map(t => `<option value="${t.id}">${this._escape(t.name)}</option>`),
    ].join("");

    this._showDialog(`
      <h3>New Schedule</h3>
      <label>Name<br><input id="d-name" type="text" placeholder="My schedule" /></label>
      <label>Template<br>
        <select id="d-template">${templateOptions}</select>
      </label>
      <div class="dialog-error hidden" id="d-error"></div>
      <div class="dialog-actions">
        <button data-dialog-cancel class="btn-secondary">Cancel</button>
        <button data-dialog-submit class="btn-primary">Create</button>
      </div>
    `, async (container) => {
      const name = container.querySelector("#d-name").value.trim();
      const template = container.querySelector("#d-template").value || null;
      if (!name) {
        container.querySelector("#d-error").textContent = "Name is required.";
        container.querySelector("#d-error").classList.remove("hidden");
        return;
      }
      try {
        const result = await this._ws({ type: "vesta/schedules/create", name, template });
        this._closeDialog();
        await this._load();
        await this._selectSchedule(result.id);
      } catch (e) {
        container.querySelector("#d-error").textContent = "Error: " + (e.message || e);
        container.querySelector("#d-error").classList.remove("hidden");
      }
    });
    this.shadowRoot.getElementById("dialog-container").querySelector("#d-name")?.focus();
  }

  _showDuplicateDialog(scheduleId) {
    const original = this._schedules.find(s => s.id === scheduleId);
    const defaultName = original ? `${original.name} (copy)` : "Copy";
    this._showDialog(`
      <h3>Duplicate Schedule</h3>
      <label>New name<br><input id="d-name" type="text" value="${this._escape(defaultName)}" /></label>
      <div class="dialog-error hidden" id="d-error"></div>
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
        container.querySelector("#d-error").textContent = "Error: " + (e.message || e);
        container.querySelector("#d-error").classList.remove("hidden");
      }
    });
    this.shadowRoot.getElementById("dialog-container").querySelector("#d-name")?.select();
  }

  _showRenameDialog() {
    const current = this._selectedSchedule?.name || "";
    this._showDialog(`
      <h3>Rename Schedule</h3>
      <label>Name<br><input id="d-name" type="text" value="${this._escape(current)}" /></label>
      <div class="dialog-error hidden" id="d-error"></div>
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
        container.querySelector("#d-error").textContent = "Error: " + (e.message || e);
        container.querySelector("#d-error").classList.remove("hidden");
      }
    });
    this.shadowRoot.getElementById("dialog-container").querySelector("#d-name")?.select();
  }

  _confirmDelete(scheduleId) {
    const s = this._schedules.find(x => x.id === scheduleId);
    const name = s ? s.name : scheduleId;
    this._showDialog(`
      <h3>Delete Schedule</h3>
      <p>Delete <strong>${this._escape(name)}</strong>? Rooms using it will revert to the global schedule.</p>
      <div class="dialog-actions">
        <button data-dialog-cancel class="btn-secondary">Cancel</button>
        <button data-dialog-submit class="btn-primary danger">Delete</button>
      </div>
    `, async () => {
      try {
        await this._ws({ type: "vesta/schedules/delete", schedule_id: scheduleId });
        if (this._selectedId === scheduleId) {
          this._selectedId = null;
          this._selectedSchedule = null;
        }
        this._closeDialog();
        await this._load();
      } catch (e) {
        console.error("Delete error", e);
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
      <h3>${isEdit ? "Edit Block" : "Add Block"}</h3>
      <div class="form-row">
        <label>Start<br><input id="d-start" type="time" value="${b.start}" step="1800" /></label>
        <label>End<br><input id="d-end" type="time" value="${b.end}" step="1800" /></label>
      </div>
      <label>Mode<br>
        <select id="d-mode">${modeOptions}</select>
      </label>
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
      <div class="dialog-error hidden" id="d-error"></div>
      <div class="dialog-actions">
        ${isEdit ? `<button class="btn-primary danger" id="d-delete-block">Delete</button>` : ""}
        <button data-dialog-cancel class="btn-secondary">Cancel</button>
        <button data-dialog-submit class="btn-primary">Save</button>
      </div>
    `, async (container) => {
      const start = roundTo30Min(container.querySelector("#d-start").value);
      const end = roundTo30Min(container.querySelector("#d-end").value);
      const modeVal = container.querySelector("#d-mode").value;
      const temp = container.querySelector("#d-temp")?.value;
      const days = Array.from(container.querySelectorAll(".day-cb input:checked")).map(el => Number(el.value));

      if (days.length === 0) {
        container.querySelector("#d-error").textContent = "Select at least one day.";
        container.querySelector("#d-error").classList.remove("hidden");
        return;
      }
      if (timeToMinutes(start) >= timeToMinutes(end)) {
        container.querySelector("#d-error").textContent = "Start time must be before end time.";
        container.querySelector("#d-error").classList.remove("hidden");
        return;
      }

      const mode = modeVal === "custom" ? `temp:${parseFloat(temp).toFixed(1)}` : modeVal;
      const newBlock = { days, start, end, mode };

      let blocks = [...(this._selectedSchedule.blocks || [])];
      if (isEdit && existingIndex >= 0) {
        blocks.splice(existingIndex, 1, newBlock);
      } else {
        blocks.push(newBlock);
      }

      try {
        await this._ws({ type: "vesta/schedules/update", schedule_id: this._selectedId, blocks });
        this._closeDialog();
        await this._selectSchedule(this._selectedId);
      } catch (e) {
        const msg = e.message || (typeof e === "object" ? JSON.stringify(e) : String(e));
        container.querySelector("#d-error").textContent = "Error: " + msg;
        container.querySelector("#d-error").classList.remove("hidden");
      }
    });

    // Quick day selection buttons
    this.shadowRoot.getElementById("dialog-container").querySelectorAll(".btn-day-quick").forEach(btn => {
      btn.addEventListener("click", () => {
        const selected = new Set(btn.dataset.days.split(",").map(Number));
        this.shadowRoot.getElementById("dialog-container").querySelectorAll(".day-cb input").forEach(cb => {
          cb.checked = selected.has(Number(cb.value));
        });
      });
    });

    // Toggle custom temp field
    this.shadowRoot.getElementById("dialog-container").querySelector("#d-mode")?.addEventListener("change", (e) => {
      const tempRow = this.shadowRoot.getElementById("dialog-container").querySelector("#d-temp-row");
      if (tempRow) tempRow.style.display = e.target.value === "custom" ? "block" : "none";
    });

    // Delete block button
    if (isEdit && existingIndex >= 0) {
      this.shadowRoot.getElementById("dialog-container").querySelector("#d-delete-block")?.addEventListener("click", async () => {
        const blocks = [...(this._selectedSchedule.blocks || [])];
        blocks.splice(existingIndex, 1);
        try {
          await this._ws({ type: "vesta/schedules/update", schedule_id: this._selectedId, blocks });
          this._closeDialog();
          await this._selectSchedule(this._selectedId);
        } catch (e) {
          console.error(e);
        }
      });
    }
  }

  async _assignRoom(entryId, source, scheduleId) {
    const msg = {
      type: "vesta/rooms/assign",
      entry_id: entryId,
      schedule_source: source,
    };
    if (source === "vesta") msg.vesta_schedule_id = scheduleId;
    try {
      await this._ws(msg);
      this._rooms = await this._ws({ type: "vesta/rooms/list" });
      this._render();
    } catch (e) {
      console.error("Assign room error", e);
    }
  }

  _escape(str) {
    return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
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
      .sidebar-header { display: flex; align-items: center; justify-content: space-between;
        padding: 12px 16px; border-bottom: 1px solid var(--divider-color, #e0e0e0); }
      .logo { font-size: 1.1em; font-weight: 600; color: var(--primary-color, #03a9f4); }
      .schedule-list { flex: 1; overflow-y: auto; padding: 8px 0; }
      .schedule-item { display: flex; align-items: center; justify-content: space-between;
        padding: 8px 12px; cursor: pointer; border-radius: 6px; margin: 2px 8px; }
      .schedule-item:hover { background: var(--secondary-background-color, #f0f0f0); }
      .schedule-item.active { background: var(--primary-color, #03a9f4); color: #fff; }
      .schedule-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 0.95em; }
      .schedule-actions { display: flex; gap: 4px; opacity: 0; transition: opacity 0.15s; }
      .schedule-item:hover .schedule-actions, .schedule-item.active .schedule-actions { opacity: 1; }
      .empty-list { padding: 24px 16px; color: var(--secondary-text-color, #888); font-size: 0.9em; text-align: center; }

      /* Main */
      .main { flex: 1; overflow-y: auto; padding: 0; display: flex; flex-direction: column; }
      .main-empty { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; }
      .main-empty-icon { font-size: 3em; }
      .main-empty-text { color: var(--secondary-text-color, #888); }
      .main-header { display: flex; align-items: center; justify-content: space-between; padding: 16px 24px 8px;
        border-bottom: 1px solid var(--divider-color, #e0e0e0); background: var(--card-background-color, #fff); }
      .schedule-title { margin: 0; font-size: 1.2em; font-weight: 600; }
      .main-actions { display: flex; gap: 8px; }

      /* Tabs */
      .tab-bar { display: flex; gap: 0; padding: 0 24px;
        border-bottom: 2px solid var(--divider-color, #e0e0e0); background: var(--card-background-color, #fff); }
      .tab { background: none; border: none; padding: 10px 20px; cursor: pointer; font-size: 0.95em;
        color: var(--secondary-text-color, #888); border-bottom: 2px solid transparent; margin-bottom: -2px; }
      .tab.active { color: var(--primary-color, #03a9f4); border-bottom-color: var(--primary-color, #03a9f4); font-weight: 500; }

      /* Grid */
      .grid-legend { display: flex; gap: 12px; flex-wrap: wrap; padding: 12px 24px 8px; }
      .legend-item { display: flex; align-items: center; gap: 4px; font-size: 0.85em; }
      .legend-dot { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
      .grid-wrapper { display: flex; flex: 1; padding: 0 24px 24px; overflow-x: auto; min-height: 0; }
      .grid-wrapper.mobile { padding: 0 16px 24px; }
      .time-axis { width: 48px; min-width: 48px; position: relative; padding-top: 32px; }
      .time-tick { position: absolute; left: 0; right: 0; font-size: 0.75em; color: var(--secondary-text-color, #888);
        text-align: right; padding-right: 6px; transform: translateY(-50%); white-space: nowrap; }
      .grid-days { display: flex; flex: 1; gap: 2px; min-width: 0; }
      .grid-days.single { flex: 1; }
      .col { flex: 1; display: flex; flex-direction: column; min-width: 60px; }
      .col-header { text-align: center; font-size: 0.8em; font-weight: 600; color: var(--secondary-text-color, #888);
        padding: 4px 0 8px; height: 32px; }
      .col-body { position: relative; border-radius: 4px; border: 1px solid var(--divider-color, #e0e0e0);
        background: var(--secondary-background-color, #f9f9f9)
          repeating-linear-gradient(to bottom,
            transparent 0px, transparent 47px,
            var(--divider-color, #e0e0e0) 47px, var(--divider-color, #e0e0e0) 48px); }
      .block { position: absolute; left: 2px; right: 2px; border-radius: 4px; cursor: pointer;
        transition: filter 0.15s; overflow: hidden; display: flex; align-items: flex-start;
        padding: 2px 4px; }
      .block:hover { filter: brightness(0.9); }
      .block-label { font-size: 0.72em; color: #fff; font-weight: 600; white-space: nowrap;
        text-overflow: ellipsis; overflow: hidden; text-shadow: 0 1px 2px rgba(0,0,0,0.4); }

      /* Mobile nav */
      .mobile-nav { display: flex; align-items: center; justify-content: center; gap: 16px;
        padding: 12px 24px 4px; }
      .mobile-day-label { font-weight: 600; font-size: 1.05em; min-width: 100px; text-align: center; }

      /* Rooms tab */
      .rooms-tab { padding: 16px 24px; }
      .rooms-desc { color: var(--secondary-text-color, #888); margin: 0 0 16px; font-size: 0.9em; }
      .rooms-table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
      .rooms-table th, .rooms-table td { text-align: left; padding: 8px 12px;
        border-bottom: 1px solid var(--divider-color, #e0e0e0); }
      .rooms-table th { font-weight: 600; color: var(--secondary-text-color, #888); font-size: 0.85em; }
      .badge { padding: 2px 8px; border-radius: 12px; font-size: 0.8em; font-weight: 500; }
      .badge.vesta { background: var(--primary-color, #03a9f4); color: #fff; }
      .badge.inherit { background: var(--secondary-background-color, #e0e0e0); color: var(--secondary-text-color, #666); }
      .room-source { white-space: nowrap; }

      /* Buttons */
      .btn-primary { background: var(--primary-color, #03a9f4); color: #fff; border: none;
        padding: 6px 16px; border-radius: 6px; cursor: pointer; font-size: 0.9em; font-weight: 500; }
      .btn-primary:hover { filter: brightness(0.9); }
      .btn-primary.danger { background: #e53935; }
      .btn-secondary { background: none; border: 1px solid var(--divider-color, #ccc); color: var(--primary-text-color, #333);
        padding: 6px 16px; border-radius: 6px; cursor: pointer; font-size: 0.9em; }
      .btn-secondary:hover { background: var(--secondary-background-color, #f0f0f0); }
      .btn-icon { background: none; border: none; cursor: pointer; font-size: 1.2em;
        color: var(--primary-text-color, #333); padding: 4px 8px; border-radius: 4px; line-height: 1; }
      .btn-icon:hover { background: var(--secondary-background-color, #f0f0f0); }
      .btn-icon-sm { background: none; border: none; cursor: pointer; font-size: 0.9em;
        padding: 2px 5px; border-radius: 3px; color: inherit; line-height: 1; }
      .btn-icon-sm:hover { background: rgba(0,0,0,0.1); }
      .btn-icon-sm.danger { color: #e53935; }
      .btn-sm { padding: 4px 10px; font-size: 0.85em; }

      /* Dialog */
      .dialog-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.4); z-index: 100; }
      .dialog { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
        background: var(--card-background-color, #fff); border-radius: 12px; padding: 24px 28px;
        min-width: 320px; max-width: 480px; width: 90%; z-index: 101;
        box-shadow: 0 8px 32px rgba(0,0,0,0.2); }
      .dialog h3 { margin: 0 0 16px; font-size: 1.1em; }
      .dialog label { display: block; margin-bottom: 12px; font-size: 0.9em; color: var(--secondary-text-color, #666); }
      .dialog input, .dialog select { width: 100%; margin-top: 4px; padding: 7px 10px;
        border: 1px solid var(--divider-color, #ccc); border-radius: 6px; font-size: 0.95em;
        background: var(--primary-background-color, #fff); color: var(--primary-text-color, #333); }
      .form-row { display: flex; gap: 12px; }
      .form-row label { flex: 1; }
      fieldset { border: 1px solid var(--divider-color, #ccc); border-radius: 6px; padding: 8px 12px; margin-bottom: 12px; }
      fieldset legend { font-size: 0.85em; color: var(--secondary-text-color, #666); padding: 0 4px; }
      .day-quick-btns { display: flex; gap: 6px; margin-bottom: 8px; }
      .btn-day-quick { background: var(--secondary-background-color, #eee); border: 1px solid var(--divider-color, #ccc);
        border-radius: 4px; padding: 2px 10px; font-size: 0.8em; cursor: pointer; }
      .btn-day-quick:hover { background: var(--primary-color, #03a9f4); color: #fff; border-color: transparent; }
      .day-checkboxes { display: flex; flex-wrap: wrap; gap: 6px; }
      .day-cb { display: flex; align-items: center; gap: 4px; font-size: 0.9em; cursor: pointer; }
      .dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 16px; }
      .dialog-error { color: #e53935; font-size: 0.85em; margin-top: 4px; padding: 6px 8px;
        background: #ffebee; border-radius: 4px; }
      .hidden { display: none !important; }
    `;
  }
}

customElements.define("vesta-panel", VestaPanel);
