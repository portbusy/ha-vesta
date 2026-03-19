/**
 * Vesta Schedule Card — Tado-like weekly schedule editor
 * Bundled within the Vesta custom integration.
 */

const DAYS = ['monday','tuesday','wednesday','thursday','friday','saturday','sunday'];
const DAY_SHORT = {monday:'Mon',tuesday:'Tue',wednesday:'Wed',thursday:'Thu',friday:'Fri',saturday:'Sat',sunday:'Sun'};
const DAY_LABELS = {monday:'Monday',tuesday:'Tuesday',wednesday:'Wednesday',thursday:'Thursday',friday:'Friday',saturday:'Saturday',sunday:'Sunday'};
const HOURS = Array.from({length:25}, (_,i) => i); // 0-24

class VestaScheduleCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:'open'});
    this._config = {};
    this._hass = null;
    this._schedule = {};
    this._selectedDay = null;
    this._editingBlock = null;
  }

  setConfig(config) {
    if (!config.entity) throw new Error('Please define an entity');
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    const entity = hass.states[this._config.entity];
    if (entity) {
      const newSchedule = entity.attributes.schedule_slots || {};
      if (JSON.stringify(newSchedule) !== JSON.stringify(this._schedule)) {
        this._schedule = JSON.parse(JSON.stringify(newSchedule));
        this._render();
      }
    }
  }

  _getBlocksForDay(day) {
    return this._schedule[day] || [];
  }

  _timeToPercent(timeStr) {
    const [h,m] = timeStr.split(':').map(Number);
    return ((h * 60 + m) / 1440) * 100;
  }

  _percentToTime(pct) {
    const totalMin = Math.round((pct / 100) * 1440);
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}`;
  }

  _tempToColor(temp) {
    // Blue (cold) → Orange (warm) → Red (hot)
    if (temp <= 15) return 'hsl(210, 80%, 55%)';
    if (temp <= 18) return 'hsl(200, 70%, 50%)';
    if (temp <= 20) return 'hsl(40, 85%, 55%)';
    if (temp <= 22) return 'hsl(25, 90%, 55%)';
    return 'hsl(5, 85%, 55%)';
  }

  _callService(service, data) {
    if (!this._hass) return;
    this._hass.callService('vesta', service, {
      entity_id: this._config.entity,
      ...data
    });
  }

  _saveDay(day, blocks) {
    const sorted = [...blocks].sort((a,b) => a.start.localeCompare(b.start));
    this._callService('set_schedule', {
      day,
      blocks: JSON.stringify(sorted)
    });
    // Optimistic update
    this._schedule[day] = sorted;
    this._render();
  }

  _clearDay(day) {
    this._callService('clear_schedule', { day });
    delete this._schedule[day];
    this._render();
  }

  _addBlock(day) {
    const blocks = this._getBlocksForDay(day);
    let nextStart = '06:00';
    if (blocks.length > 0) {
      const last = blocks[blocks.length - 1];
      const [h,m] = last.start.split(':').map(Number);
      const newMin = h * 60 + m + 120; // 2 hours after last
      if (newMin < 1440) {
        nextStart = `${String(Math.floor(newMin/60)).padStart(2,'0')}:${String(newMin%60).padStart(2,'0')}`;
      } else {
        nextStart = '23:00';
      }
    }
    const newBlocks = [...blocks, {start: nextStart, temp: 20.0}];
    this._saveDay(day, newBlocks);
  }

  _removeBlock(day, idx) {
    const blocks = [...this._getBlocksForDay(day)];
    blocks.splice(idx, 1);
    this._saveDay(day, blocks);
  }

  _updateBlock(day, idx, field, value) {
    const blocks = [...this._getBlocksForDay(day)].map(b => ({...b}));
    blocks[idx][field] = value;
    this._saveDay(day, blocks);
  }

  _copyDay(fromDay) {
    const blocks = this._getBlocksForDay(fromDay);
    if (!blocks.length) return;

    // Show copy dialog
    this._showCopyDialog(fromDay, blocks);
  }

  _showCopyDialog(fromDay, blocks) {
    this._copySource = {fromDay, blocks};
    this._render();
  }

  _confirmCopy(targetDays) {
    const blocks = this._copySource.blocks;
    for (const day of targetDays) {
      this._saveDay(day, [...blocks].map(b => ({...b})));
    }
    this._copySource = null;
    this._render();
  }

  _render() {
    const entityName = this._config.entity ? this._config.entity.replace('climate.','').replace(/_/g,' ') : 'Schedule';

    this.shadowRoot.innerHTML = `
      <style>${this._styles()}</style>
      <ha-card>
        <div class="card-header">
          <span class="title">🗓️ ${this._capitalize(entityName)}</span>
        </div>
        <div class="card-content">
          ${this._renderWeekView()}
          ${this._selectedDay ? this._renderDayEditor(this._selectedDay) : ''}
          ${this._copySource ? this._renderCopyDialog() : ''}
        </div>
      </ha-card>
    `;
    this._attachEvents();
  }

  _renderWeekView() {
    return `
      <div class="week-grid">
        <div class="time-header">
          <div class="day-label"></div>
          <div class="timeline-header">
            ${[0,3,6,9,12,15,18,21,24].map(h => `<span class="hour-mark" style="left:${(h/24)*100}%">${h}</span>`).join('')}
          </div>
        </div>
        ${DAYS.map(day => this._renderDayRow(day)).join('')}
      </div>
    `;
  }

  _renderDayRow(day) {
    const blocks = this._getBlocksForDay(day);
    const isSelected = this._selectedDay === day;

    let segments = '';
    if (blocks.length > 0) {
      blocks.forEach((block, i) => {
        const start = this._timeToPercent(block.start);
        const end = i < blocks.length - 1 ? this._timeToPercent(blocks[i+1].start) : 100;
        const width = end - start;
        const color = this._tempToColor(block.temp);
        segments += `<div class="block-segment" style="left:${start}%;width:${width}%;background:${color};" title="${block.start} — ${block.temp}°C">
          ${width > 8 ? `<span class="block-temp">${block.temp}°</span>` : ''}
        </div>`;
      });

      // Fill before first block with previous day's last temp
      const firstStart = this._timeToPercent(blocks[0].start);
      if (firstStart > 0) {
        const prevDay = DAYS[(DAYS.indexOf(day) - 1 + 7) % 7];
        const prevBlocks = this._getBlocksForDay(prevDay);
        const prevTemp = prevBlocks.length > 0 ? prevBlocks[prevBlocks.length-1].temp : blocks[blocks.length-1].temp;
        const color = this._tempToColor(prevTemp);
        segments = `<div class="block-segment prev-carry" style="left:0%;width:${firstStart}%;background:${color};opacity:0.6;">
          ${firstStart > 8 ? `<span class="block-temp">${prevTemp}°</span>` : ''}
        </div>` + segments;
      }
    }

    return `
      <div class="day-row ${isSelected ? 'selected' : ''}" data-day="${day}">
        <div class="day-label" data-action="select-day" data-day="${day}">
          ${DAY_SHORT[day]}
        </div>
        <div class="timeline" data-action="select-day" data-day="${day}">
          ${segments || '<div class="empty-day">No schedule</div>'}
        </div>
      </div>
    `;
  }

  _renderDayEditor(day) {
    const blocks = this._getBlocksForDay(day);

    return `
      <div class="day-editor">
        <div class="editor-header">
          <span class="editor-title">${DAY_LABELS[day]}</span>
          <div class="editor-actions">
            <button class="btn btn-sm btn-copy" data-action="copy-day" data-day="${day}">📋 Copy</button>
            <button class="btn btn-sm btn-clear" data-action="clear-day" data-day="${day}">🗑️ Clear</button>
            <button class="btn btn-sm btn-close" data-action="close-editor">✕</button>
          </div>
        </div>
        <div class="blocks-list">
          ${blocks.map((block, i) => this._renderBlockRow(day, block, i)).join('')}
        </div>
        <button class="btn btn-add" data-action="add-block" data-day="${day}">+ Add Time Block</button>
      </div>
    `;
  }

  _renderBlockRow(day, block, idx) {
    return `
      <div class="block-row">
        <div class="block-color" style="background:${this._tempToColor(block.temp)}"></div>
        <label class="block-field">
          <span class="field-label">Start</span>
          <input type="time" class="input-time" value="${block.start}"
                 data-action="edit-start" data-day="${day}" data-idx="${idx}" />
        </label>
        <label class="block-field">
          <span class="field-label">Temp</span>
          <div class="temp-control">
            <button class="btn-temp" data-action="temp-down" data-day="${day}" data-idx="${idx}">−</button>
            <span class="temp-value">${block.temp}°C</span>
            <button class="btn-temp" data-action="temp-up" data-day="${day}" data-idx="${idx}">+</button>
          </div>
        </label>
        <button class="btn btn-remove" data-action="remove-block" data-day="${day}" data-idx="${idx}">✕</button>
      </div>
    `;
  }

  _renderCopyDialog() {
    const fromDay = this._copySource.fromDay;
    return `
      <div class="copy-overlay">
        <div class="copy-dialog">
          <h3>Copy ${DAY_LABELS[fromDay]} to:</h3>
          <div class="copy-options">
            ${DAYS.filter(d => d !== fromDay).map(d => `
              <label class="copy-option">
                <input type="checkbox" value="${d}" class="copy-check" /> ${DAY_LABELS[d]}
              </label>
            `).join('')}
          </div>
          <div class="copy-presets">
            <button class="btn btn-sm" data-action="copy-preset" data-preset="weekdays">Weekdays</button>
            <button class="btn btn-sm" data-action="copy-preset" data-preset="weekends">Weekends</button>
            <button class="btn btn-sm" data-action="copy-preset" data-preset="all">All Days</button>
          </div>
          <div class="copy-actions">
            <button class="btn btn-confirm" data-action="confirm-copy">Apply</button>
            <button class="btn btn-cancel" data-action="cancel-copy">Cancel</button>
          </div>
        </div>
      </div>
    `;
  }

  _attachEvents() {
    this.shadowRoot.querySelectorAll('[data-action]').forEach(el => {
      const action = el.dataset.action;
      const day = el.dataset.day;
      const idx = el.dataset.idx !== undefined ? parseInt(el.dataset.idx) : null;

      if (action === 'select-day') {
        el.addEventListener('click', () => {
          this._selectedDay = this._selectedDay === day ? null : day;
          this._render();
        });
      }
      else if (action === 'add-block') {
        el.addEventListener('click', () => this._addBlock(day));
      }
      else if (action === 'remove-block') {
        el.addEventListener('click', () => this._removeBlock(day, idx));
      }
      else if (action === 'edit-start') {
        el.addEventListener('change', (e) => this._updateBlock(day, idx, 'start', e.target.value));
      }
      else if (action === 'temp-up') {
        el.addEventListener('click', () => {
          const blocks = this._getBlocksForDay(day);
          const newTemp = Math.min(30, blocks[idx].temp + 0.5);
          this._updateBlock(day, idx, 'temp', newTemp);
        });
      }
      else if (action === 'temp-down') {
        el.addEventListener('click', () => {
          const blocks = this._getBlocksForDay(day);
          const newTemp = Math.max(5, blocks[idx].temp - 0.5);
          this._updateBlock(day, idx, 'temp', newTemp);
        });
      }
      else if (action === 'copy-day') {
        el.addEventListener('click', () => this._copyDay(day));
      }
      else if (action === 'clear-day') {
        el.addEventListener('click', () => {
          this._clearDay(day);
          this._selectedDay = null;
          this._render();
        });
      }
      else if (action === 'close-editor') {
        el.addEventListener('click', () => {
          this._selectedDay = null;
          this._render();
        });
      }
      else if (action === 'copy-preset') {
        el.addEventListener('click', () => {
          const preset = el.dataset.preset;
          const checks = this.shadowRoot.querySelectorAll('.copy-check');
          checks.forEach(c => {
            if (preset === 'weekdays') c.checked = ['monday','tuesday','wednesday','thursday','friday'].includes(c.value);
            else if (preset === 'weekends') c.checked = ['saturday','sunday'].includes(c.value);
            else c.checked = true;
          });
        });
      }
      else if (action === 'confirm-copy') {
        el.addEventListener('click', () => {
          const checks = this.shadowRoot.querySelectorAll('.copy-check:checked');
          const targetDays = Array.from(checks).map(c => c.value);
          if (targetDays.length) this._confirmCopy(targetDays);
        });
      }
      else if (action === 'cancel-copy') {
        el.addEventListener('click', () => {
          this._copySource = null;
          this._render();
        });
      }
    });
  }

  _capitalize(str) {
    return str.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
  }

  _styles() {
    return `
      :host {
        --vs-bg: var(--ha-card-background, var(--card-background-color, #1c1c1e));
        --vs-fg: var(--primary-text-color, #e5e5ea);
        --vs-fg2: var(--secondary-text-color, #8e8e93);
        --vs-accent: var(--primary-color, #0a84ff);
        --vs-surface: rgba(255,255,255,0.06);
        --vs-border: rgba(255,255,255,0.1);
        --vs-radius: 12px;
      }
      ha-card {
        background: var(--vs-bg);
        border-radius: var(--vs-radius);
        overflow: hidden;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      }
      .card-header {
        padding: 16px 20px 8px;
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      .title {
        font-size: 16px;
        font-weight: 600;
        color: var(--vs-fg);
      }
      .card-content {
        padding: 8px 16px 16px;
      }

      /* Week Grid */
      .week-grid {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      .time-header {
        display: flex;
        align-items: flex-end;
        margin-bottom: 2px;
      }
      .time-header .day-label {
        width: 40px;
        flex-shrink: 0;
      }
      .timeline-header {
        flex: 1;
        position: relative;
        height: 16px;
        font-size: 10px;
        color: var(--vs-fg2);
      }
      .hour-mark {
        position: absolute;
        transform: translateX(-50%);
      }

      /* Day Row */
      .day-row {
        display: flex;
        align-items: center;
        cursor: pointer;
        border-radius: 8px;
        transition: background 0.15s;
        padding: 2px 0;
      }
      .day-row:hover {
        background: var(--vs-surface);
      }
      .day-row.selected {
        background: rgba(10,132,255,0.15);
      }
      .day-label {
        width: 40px;
        flex-shrink: 0;
        font-size: 12px;
        font-weight: 600;
        color: var(--vs-fg2);
        text-align: center;
        user-select: none;
      }
      .timeline {
        flex: 1;
        height: 32px;
        position: relative;
        background: var(--vs-surface);
        border-radius: 6px;
        overflow: hidden;
      }
      .block-segment {
        position: absolute;
        top: 0;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        border-right: 1px solid rgba(0,0,0,0.2);
        transition: opacity 0.2s;
      }
      .block-temp {
        font-size: 11px;
        font-weight: 700;
        color: rgba(255,255,255,0.95);
        text-shadow: 0 1px 2px rgba(0,0,0,0.4);
        pointer-events: none;
      }
      .empty-day {
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        font-size: 11px;
        color: var(--vs-fg2);
        font-style: italic;
      }

      /* Day Editor */
      .day-editor {
        margin-top: 12px;
        padding: 12px;
        background: var(--vs-surface);
        border-radius: var(--vs-radius);
        border: 1px solid var(--vs-border);
      }
      .editor-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 10px;
      }
      .editor-title {
        font-size: 14px;
        font-weight: 700;
        color: var(--vs-fg);
      }
      .editor-actions {
        display: flex;
        gap: 6px;
      }

      /* Block Row */
      .blocks-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .block-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px;
        background: rgba(255,255,255,0.04);
        border-radius: 8px;
      }
      .block-color {
        width: 6px;
        height: 32px;
        border-radius: 3px;
        flex-shrink: 0;
      }
      .block-field {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .field-label {
        font-size: 10px;
        color: var(--vs-fg2);
        text-transform: uppercase;
        letter-spacing: 0.5px;
      }
      .input-time {
        background: var(--vs-surface);
        border: 1px solid var(--vs-border);
        border-radius: 6px;
        color: var(--vs-fg);
        padding: 4px 8px;
        font-size: 14px;
        font-family: inherit;
        width: 90px;
      }
      .input-time::-webkit-calendar-picker-indicator {
        filter: invert(0.8);
      }

      /* Temp Control */
      .temp-control {
        display: flex;
        align-items: center;
        gap: 6px;
      }
      .btn-temp {
        background: var(--vs-surface);
        border: 1px solid var(--vs-border);
        border-radius: 6px;
        color: var(--vs-fg);
        width: 28px;
        height: 28px;
        font-size: 16px;
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.15s;
      }
      .btn-temp:hover {
        background: rgba(255,255,255,0.12);
      }
      .temp-value {
        font-size: 14px;
        font-weight: 600;
        color: var(--vs-fg);
        min-width: 44px;
        text-align: center;
      }

      /* Buttons */
      .btn {
        background: var(--vs-surface);
        border: 1px solid var(--vs-border);
        border-radius: 8px;
        color: var(--vs-fg);
        padding: 8px 14px;
        font-size: 13px;
        cursor: pointer;
        transition: background 0.15s;
        font-family: inherit;
      }
      .btn:hover {
        background: rgba(255,255,255,0.12);
      }
      .btn-sm {
        padding: 4px 10px;
        font-size: 12px;
      }
      .btn-add {
        width: 100%;
        margin-top: 8px;
        background: rgba(10,132,255,0.15);
        border-color: rgba(10,132,255,0.3);
        color: var(--vs-accent);
        font-weight: 600;
      }
      .btn-add:hover {
        background: rgba(10,132,255,0.25);
      }
      .btn-remove {
        background: rgba(255,59,48,0.15);
        border-color: rgba(255,59,48,0.3);
        color: #ff3b30;
        padding: 4px 8px;
        font-size: 12px;
        margin-left: auto;
      }
      .btn-clear {
        background: rgba(255,59,48,0.15);
        border-color: rgba(255,59,48,0.3);
        color: #ff3b30;
      }
      .btn-copy {
        background: rgba(10,132,255,0.15);
        border-color: rgba(10,132,255,0.3);
        color: var(--vs-accent);
      }
      .btn-confirm {
        background: var(--vs-accent);
        color: #fff;
        border: none;
        font-weight: 600;
      }
      .btn-cancel {
        background: transparent;
        border-color: var(--vs-border);
      }

      /* Copy Dialog */
      .copy-overlay {
        position: fixed;
        top: 0; left: 0; right: 0; bottom: 0;
        background: rgba(0,0,0,0.6);
        display: flex;
        align-items: center;
        justify-content: center;
        z-index: 100;
        backdrop-filter: blur(4px);
      }
      .copy-dialog {
        background: var(--vs-bg);
        border: 1px solid var(--vs-border);
        border-radius: var(--vs-radius);
        padding: 20px;
        min-width: 280px;
        box-shadow: 0 8px 32px rgba(0,0,0,0.4);
      }
      .copy-dialog h3 {
        margin: 0 0 12px;
        font-size: 15px;
        color: var(--vs-fg);
      }
      .copy-options {
        display: flex;
        flex-direction: column;
        gap: 6px;
        margin-bottom: 12px;
      }
      .copy-option {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 13px;
        color: var(--vs-fg);
        cursor: pointer;
      }
      .copy-check {
        accent-color: var(--vs-accent);
      }
      .copy-presets {
        display: flex;
        gap: 6px;
        margin-bottom: 12px;
      }
      .copy-actions {
        display: flex;
        gap: 8px;
        justify-content: flex-end;
      }
    `;
  }

  getCardSize() {
    return 5;
  }

  static getConfigElement() {
    return document.createElement('vesta-schedule-card-editor');
  }

  static getStubConfig() {
    return { entity: '' };
  }
}

// Simple editor for the card config
class VestaScheduleCardEditor extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode:'open'});
  }

  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass) return;
    const entities = Object.keys(this._hass.states).filter(e => e.startsWith('climate.'));

    this.shadowRoot.innerHTML = `
      <style>
        .editor { padding: 8px; }
        label { display: block; margin-bottom: 8px; font-size: 14px; color: var(--primary-text-color); }
        select { width: 100%; padding: 8px; border-radius: 6px; background: var(--card-background-color); color: var(--primary-text-color); border: 1px solid rgba(255,255,255,0.1); }
      </style>
      <div class="editor">
        <label>
          Entity
          <select id="entity">
            <option value="">Select entity...</option>
            ${entities.map(e => `<option value="${e}" ${e === this._config.entity ? 'selected' : ''}>${e}</option>`).join('')}
          </select>
        </label>
      </div>
    `;

    this.shadowRoot.getElementById('entity').addEventListener('change', (e) => {
      const event = new CustomEvent('config-changed', {
        detail: { config: { ...this._config, entity: e.target.value } },
        bubbles: true, composed: true
      });
      this.dispatchEvent(event);
    });
  }
}

customElements.define('vesta-schedule-card', VestaScheduleCard);
customElements.define('vesta-schedule-card-editor', VestaScheduleCardEditor);

window.customCards = window.customCards || [];
window.customCards.push({
  type: 'vesta-schedule-card',
  name: 'Vesta Schedule',
  description: 'Tado-like weekly temperature schedule editor for Vesta rooms.',
  preview: true
});
