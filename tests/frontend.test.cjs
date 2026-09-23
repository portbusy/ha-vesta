const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const { test } = require("node:test");

function panelContext() {
  let Panel;
  let observations = 0;
  const context = vm.createContext({
    HTMLElement: class { attachShadow() { this.shadowRoot = {}; } },
    ResizeObserver: class { observe() { observations++; } disconnect() {} },
    customElements: { define(name, value) { Panel = value; } },
    window: { innerWidth: 1000 },
    setInterval: () => 1, clearInterval() {}, console,
  });
  vm.runInContext(fs.readFileSync("custom_components/vesta/frontend/vesta-panel.js", "utf8"), context);
  const panel = new Panel();
  const render = panel._render.bind(panel);
  panel._render = () => {};
  return { panel, context, render, observations: () => observations };
}

test("a late response cannot replace the user's latest selection", async () => {
  const { panel } = panelContext();
  const pending = {};
  panel._ws = ({ schedule_id }) => new Promise(resolve => { pending[schedule_id] = resolve; });
  const first = panel._selectSchedule("first");
  const second = panel._selectSchedule("second");
  pending.second({ id: "second", name: "Second" });
  await second;
  pending.first({ id: "first", name: "First" });
  await first;
  assert.equal(panel._selectedId, "second");
  assert.equal(panel._selectedSchedule.id, "second");
});

test("midnight is a valid exclusive end and minute precision is preserved", () => {
  const { context } = panelContext();
  assert.equal(vm.runInContext('blockTime("00:00", true)', context), "24:00");
  assert.equal(vm.runInContext('blockTime("23:59", true)', context), "23:59");
  assert.equal(vm.runInContext('blockTime("06:17")', context), "06:17");
  assert.equal(vm.runInContext('blockTime("")', context), null);
  assert.equal(vm.runInContext('blockTime("29:00")', context), null);
});

test("resize observation resumes after returning to the panel", () => {
  const { panel, observations } = panelContext();
  panel.connectedCallback();
  panel.disconnectedCallback();
  const previous = observations();
  panel.connectedCallback();
  assert.equal(observations(), previous + 1);
});

test("global assignment submits the selected schedule and refreshes", async () => {
  const { panel } = panelContext();
  panel._selectedId = "schedule";
  let message, refreshed = false;
  panel._ws = async value => { message = value; };
  panel._load = async () => { refreshed = true; };
  await panel._setGlobalSchedule("vesta");
  assert.equal(message.type, "vesta/global/set_schedule");
  assert.equal(message.vesta_schedule_id, "schedule");
  assert.equal(refreshed, true);
});

test("assignment failures are visible", async () => {
  const { panel } = panelContext();
  panel._ws = async () => { throw new Error("Connection lost"); };
  await panel._setGlobalSchedule("entity");
  assert.match(panel._actionError, /Connection lost/);
});

test("layout refreshes preserve an open form until the dialog closes", () => {
  const { panel, render } = panelContext();
  panel._dialogOpen = true;
  panel.shadowRoot.innerHTML = "unsaved form";
  render();
  assert.equal(panel.shadowRoot.innerHTML, "unsaved form");
  assert.equal(panel._renderPending, true);
  panel.shadowRoot.getElementById = () => null;
  let refreshed = false;
  panel._render = () => { refreshed = true; };
  panel._closeDialog();
  assert.equal(refreshed, true);
  assert.equal(panel._dialogOpen, false);
});

test("a list refresh respects selection changes made while waiting", async () => {
  const { panel } = panelContext();
  panel._selectedId = "first";
  let resolveList;
  panel._ws = async msg => {
    if (msg.type === "vesta/schedules/list") return new Promise(resolve => { resolveList = resolve; });
    if (msg.type === "vesta/schedules/get") return { id: msg.schedule_id, blocks: [] };
    return [];
  };
  const loading = panel._load();
  await panel._selectSchedule("second");
  resolveList([{ id: "first" }, { id: "second" }]);
  await loading;
  assert.equal(panel._selectedId, "second");
  assert.equal(panel._selectedSchedule.id, "second");
});

test("the panel recognises valid case-insensitive stored modes", () => {
  const { context } = panelContext();
  assert.equal(vm.runInContext('modeFromBlock({mode: " Comfort "})', context), "comfort");
  assert.equal(vm.runInContext('modeFromBlock({mode: "TEMP:22"})', context), "custom");
});
