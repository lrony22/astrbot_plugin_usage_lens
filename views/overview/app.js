const bridge = window.AstrBotPluginView;
const byId = (id) => document.getElementById(id);
const state = { report: null, accounts: null, days: 7, chart: "tokens", busy: false, expanded: new Set() };
const fields = ["input_other", "input_cached", "cache_write", "output"];
const series = [
  { key: "input_other", label: "未缓存输入", color: "var(--uncached)" },
  { key: "input_cached", label: "缓存读取", color: "var(--cached)" },
  { key: "cache_write", label: "缓存写入", color: "var(--written)" },
  { key: "output", label: "输出", color: "var(--output)" },
];
const numeric = (value) => typeof value === "number" && Number.isFinite(value);
const number = (value, compact = false) => new Intl.NumberFormat("zh-CN", {
  maximumFractionDigits: compact ? 2 : 0, ...(compact ? { notation: "compact" } : {}),
}).format(value);
const money = (value) => new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", minimumFractionDigits: 2,
  maximumFractionDigits: value > 0 && value < 0.01 ? 4 : 2,
}).format(Number(value));
const percent = (value) => value == null ? "—" : `${Number(value).toFixed(1)}%`;
const tokenTotal = (item) => fields.reduce((total, key) => total + Number(item[key] || 0), 0);
const hitRate = (item) => {
  const known = item.input_other + item.input_cached + item.cache_write - item.cache_unknown;
  return known > 0 ? item.input_cached / known * 100 : null;
};
const element = (tag, className = "", text = null) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
};
const time = (value) => {
  if (!value || Number.isNaN(Date.parse(value))) return "未提供";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).format(new Date(value));
};

function quotaWindow(window) {
  const row = element("div", "quota-window");
  const name = { "5 hours": "5 小时", "7 days": "7 天", Month: "月度" }[window.name] || window.name || "额度窗口";
  const heading = element("div", "quota-title");
  const label = element("span", "name", name);
  label.title = name;
  heading.append(label);
  let remaining = numeric(window.remaining) ? window.remaining : numeric(window.used) ? Math.max(0, 100 - window.used) : null;
  let used = numeric(window.used) ? window.used : remaining == null ? null : Math.max(0, 100 - remaining);
  let value;
  if (window.unlimited) {
    value = "不限额"; remaining = null; used = null;
  } else if (window.balance != null) {
    value = `${number(window.balance, true)} ${window.unit || ""}`;
    remaining = null; used = null;
  } else if (window.text) {
    value = window.display || "未提供";
    remaining = null; used = null;
  } else value = remaining == null ? "未提供" : `${percent(remaining)} 剩余`;
  heading.append(element("span", "quota-value", value));
  row.append(heading);
  if (remaining != null) {
    const track = element("div", "quota-track");
    track.setAttribute("role", "progressbar");
    track.setAttribute("aria-label", `${name}剩余额度`);
    track.setAttribute("aria-valuemin", "0");
    track.setAttribute("aria-valuemax", "100");
    track.setAttribute("aria-valuenow", String(Math.max(0, Math.min(100, remaining))));
    const fill = element("div", `quota-fill${remaining <= 10 ? " danger" : remaining <= 25 ? " warning" : ""}`);
    fill.style.width = `${Math.max(0, Math.min(100, remaining))}%`;
    track.append(fill); row.append(track);
  }
  const meta = element("div", "quota-meta");
  meta.append(element("span", "", used == null ? "已用比例 —" : `已用 ${percent(used)}`));
  const reset = element("span", "reset");
  reset.dataset.reset = window.resetsAt || "";
  reset.title = `北京时间 ${time(window.resetsAt)}`;
  meta.append(reset); row.append(meta);
  if (window.limit > 0 && numeric(window.amount ?? 0)) {
    row.append(element("p", "quota-count", `剩余 ${number(Math.max(0, window.limit - (window.amount || 0)))} / ${number(window.limit)} ${window.unit || ""}`));
  }
  return row;
}

function renderAccounts() {
  const root = byId("accounts");
  if (state.accounts == null) return;
  const query = byId("account-search").value.trim().toLowerCase();
  const cards = state.accounts.filter((card) => !query || [card.provider, card.name, card.alias, card.user, card.plan].some((value) => String(value || "").toLowerCase().includes(query)));
  root.replaceChildren();
  byId("account-count").textContent = `${cards.length} 个账号`;
  if (!cards.length) root.append(element("div", "empty", query ? "没有匹配的账号，试试其他关键词。" : "Magpie 暂无可查询的账号额度。"));
  cards.forEach((card) => {
    const panel = element("article", "account-card");
    const heading = element("div", "account-heading");
    const identity = element("div");
    identity.append(element("h3", "account-name", card.alias || card.name || card.provider || "未知账号"));
    identity.append(element("p", "account-user", card.user || card.provider || ""));
    heading.append(identity);
    const badge = card.plan || card.provider;
    if (badge) { const plan = element("span", "plan", badge); plan.title = badge; heading.append(plan); }
    panel.append(heading);
    if (card.balance) panel.append(element("p", "quota-value", `余额 ${card.balance}`));
    if (card.error) panel.append(element("p", "account-warning", card.error));
    if (card.readDeferred) panel.append(element("p", "account-warning", "暂缓刷新 · 显示上次读数"));
    const windows = card.windows || [];
    const visible = element("div", "windows");
    windows.slice(0, 2).forEach((window) => visible.append(quotaWindow(window)));
    panel.append(visible);
    if (windows.length > 2) {
      const more = element("details", "more-windows");
      const key = `${card.provider}|${card.user || card.alias || card.name}`;
      more.open = state.expanded.has(key);
      more.addEventListener("toggle", () => { if (more.open) state.expanded.add(key); else state.expanded.delete(key); });
      more.append(element("summary", "", `查看其他 ${windows.length - 2} 个额度窗口`));
      windows.slice(2).forEach((window) => more.append(quotaWindow(window)));
      panel.append(more);
    } else panel.append(element("p", "window-count", `全部 ${windows.length} 个额度窗口`));
    if (!windows.length && !card.balance) panel.append(element("p", "account-warning", "Magpie 未提供额度读数。"));
    const stamp = card.asOf || card.readAt;
    panel.append(element("p", "account-stamp", `${card.asOf ? "历史读数" : "额度读取"} · ${time(stamp)}`));
    root.append(panel);
  });
  updateResetClocks();
}

function updateResetClocks() {
  document.querySelectorAll("[data-reset]").forEach((node) => {
    const value = node.dataset.reset;
    if (!value || Number.isNaN(Date.parse(value))) { node.textContent = "重置时间未提供"; return; }
    const minutes = Math.ceil((Date.parse(value) - Date.now()) / 60000);
    let relative = "待更新";
    if (minutes > 0) {
      const days = Math.floor(minutes / 1440);
      const hours = Math.floor(minutes % 1440 / 60);
      const rest = minutes % 60;
      relative = days ? `${days}天${hours}小时后` : hours ? `${hours}小时${rest}分后` : `${rest}分钟后`;
    }
    node.textContent = `${time(value)} 重置 · ${relative}`;
  });
}

function renderUsage() {
  const report = state.report;
  if (!report) return;
  const totals = report.totals;
  byId("cost").textContent = totals.runs && totals.runs === totals.unpriced_runs ? "—" : money(totals.cost);
  byId("cost-note").textContent = totals.unpriced_runs ? `${number(totals.unpriced_runs)} 次未定价 · 已定价部分` : "Magpie 按模型价格估算";
  byId("calls").textContent = number(totals.runs);
  byId("tokens").textContent = number(tokenTotal(totals), true);
  byId("tokens").title = `${number(tokenTotal(totals))} Token`;
  byId("token-note").textContent = `非缓存 ${number(totals.input_other + totals.output, true)} Token`;
  byId("cache").textContent = percent(hitRate(totals));
  byId("cache-note").textContent = `读取 ${number(totals.input_cached, true)} · 写入 ${number(totals.cache_write, true)}`;
  byId("period-label").textContent = report.period;
  renderTrend(); renderRanking(); renderModels();
}

function renderTrend() {
  if (!state.report) return;
  const root = byId("chart");
  const days = state.report.daily;
  const costMode = state.chart === "cost";
  const values = days.map((day) => costMode ? Number(day.cost) : tokenTotal(day));
  const width = Math.max(240, root.clientWidth - 16), height = 218;
  const left = 44, right = width - 10, top = 20, bottom = 184;
  const maximum = Math.max(0, ...values);
  const raw = Math.max(maximum, 1) / 4;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  let step = [1, 2, 2.5, 5, 10].map((value) => value * magnitude).find((value) => value >= raw);
  if (!costMode) step = Math.max(1, step);
  let ceiling = Math.ceil(Math.max(maximum, 1) / step) * step;
  if (ceiling <= maximum) ceiling += step;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Magpie 最近 ${days.length} 天${costMode ? "费用" : "含缓存 Token"}趋势`);
  const shape = (tag, attrs, text = null, parent = svg) => {
    const node = document.createElementNS(svg.namespaceURI, tag);
    for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, String(value));
    if (text != null) node.textContent = text;
    parent.append(node); return node;
  };
  for (let tick = 0; tick <= ceiling + step / 100; tick += step) {
    const y = bottom - tick / ceiling * (bottom - top);
    shape("line", { x1: left, x2: right, y1: y, y2: y, class: "grid-line" });
    shape("text", { x: left - 8, y: y + 4, "text-anchor": "end" }, costMode ? money(tick) : number(tick, true));
  }
  const pitch = (right - left) / Math.max(days.length, 1);
  const barWidth = Math.min(36, pitch * 0.54);
  const labelStep = Math.max(1, Math.ceil(days.length / Math.max(3, Math.floor((right - left) / 52))));
  days.forEach((day, index) => {
    const x = left + pitch * (index + 0.5);
    const group = shape("g", { tabindex: "0", "aria-label": `${day.date}，${number(tokenTotal(day))} Token，缓存命中率 ${percent(hitRate(day))}，费用 ${money(day.cost)}` });
    const caption = `${day.date} · ${number(tokenTotal(day))} Token · 缓存 ${percent(hitRate(day))} · ${money(day.cost)}`;
    shape("title", {}, caption, group);
    shape("rect", { x: x - pitch / 2, y: top, width: pitch, height: bottom - top, class: "bar-target" }, null, group);
    let y = bottom;
    const marks = costMode ? [{ value: Number(day.cost), color: "var(--cached)" }] : series.map((item) => ({ value: day[item.key], color: item.color }));
    marks.forEach((mark) => {
      const size = Number(mark.value) / ceiling * (bottom - top);
      if (size > 0) shape("rect", { x: x - barWidth / 2, y: y - size, width: barWidth, height: size, fill: mark.color }, null, group);
      y -= size;
    });
    if (index % labelStep === 0) shape("text", { x, y: bottom + 22, "text-anchor": "middle" }, day.date.slice(5));
    for (const event of ["pointerenter", "focus"]) group.addEventListener(event, () => { byId("trend-unit").textContent = caption; });
    for (const event of ["pointerleave", "blur"]) group.addEventListener(event, () => { byId("trend-unit").textContent = costMode ? "美元估算 · USD" : "含缓存 Token"; });
  });
  root.replaceChildren(svg);
  byId("trend-unit").textContent = costMode ? "美元估算 · USD" : "含缓存 Token";
  const legend = byId("chart-legend"); legend.replaceChildren();
  if (!costMode) series.filter((item) => days.some((day) => day[item.key] > 0)).forEach((item) => {
    const label = element("span"), swatch = element("i"); swatch.style.background = item.color;
    label.append(swatch, document.createTextNode(item.label)); legend.append(label);
  });
}

function renderRanking() {
  const models = [...state.report.models].sort((a, b) => Number(b.cost) - Number(a.cost));
  const top = models.slice(0, 4);
  byId("model-count").textContent = `${top.length} / ${models.length} 模型`;
  const root = byId("ranking"); root.replaceChildren();
  if (!top.length) root.append(element("div", "empty", "本时段暂无模型调用。"));
  const maxCost = Math.max(0, ...top.map((row) => Number(row.cost)));
  top.forEach((model) => {
    const row = element("div", "rank-row"), head = element("div", "rank-heading");
    const name = element("span", "rank-name", model.model); name.title = model.model;
    head.append(name, element("span", "ranking-value", model.unpriced_runs === model.runs && model.runs ? "未定价" : money(model.cost)));
    row.append(head, element("p", "rank-subline", `${model.provider_id} · ${number(model.runs)} 次调用`));
    const track = element("div", "rank-track"), fill = element("div", "rank-fill");
    fill.style.width = `${maxCost ? Number(model.cost) / maxCost * 100 : 0}%`;
    track.append(fill); row.append(track); root.append(row);
  });
}

function renderModels() {
  if (!state.report) return;
  const query = byId("model-search").value.trim().toLowerCase();
  const models = state.report.models.filter((model) => `${model.provider_id} ${model.model}`.toLowerCase().includes(query));
  const root = byId("models"); root.replaceChildren();
  if (!models.length) {
    const row = element("tr"), cell = element("td", "empty", query ? "没有匹配的模型。" : "本时段暂无模型调用。");
    cell.colSpan = 5; row.append(cell); root.append(row);
  }
  models.forEach((model) => {
    const row = element("tr"), name = element("td");
    name.append(element("strong", "", model.model), element("span", "sub", model.provider_id));
    row.append(name, element("td", "", number(model.runs)), element("td", "", number(tokenTotal(model))), element("td", "", percent(hitRate(model))));
    const cost = element("td", "", model.runs && model.runs === model.unpriced_runs ? "未定价" : money(model.cost));
    if (model.unpriced_runs && model.runs !== model.unpriced_runs) cost.append(element("span", "sub", "部分已定价"));
    row.append(cost); root.append(row);
  });
}

async function loadData(includeQuotas = true) {
  if (state.busy) return;
  state.busy = true;
  byId("refresh").disabled = true;
  byId("refresh").lastChild.textContent = "更新中";
  document.querySelectorAll("[data-days]").forEach((button) => { button.disabled = true; });
  const requests = [bridge.apiGet("usage", { days: state.days })];
  if (includeQuotas) requests.push(bridge.apiGet("quotas"));
  const results = await Promise.allSettled(requests);
  const usage = results[0];
  const usageError = byId("usage-error");
  usageError.hidden = usage.status === "fulfilled";
  if (usage.status === "fulfilled") {
    state.report = usage.value.report; renderUsage();
    byId("updated").textContent = `${time(usage.value.updated_at)} 更新`;
  } else {
    usageError.textContent = usage.reason?.message || "用量读取失败，请重试。";
    state.days = state.report?.daily.length || state.days;
    document.querySelectorAll("[data-days]").forEach((button) => button.setAttribute("aria-pressed", String(Number(button.dataset.days) === state.days)));
  }
  if (includeQuotas) {
    const quotas = results[1];
    const error = byId("account-error"); error.hidden = quotas.status === "fulfilled";
    if (quotas.status === "fulfilled") { state.accounts = quotas.value.accounts; renderAccounts(); }
    else {
      error.textContent = quotas.reason?.message || "额度读取失败，请重试。";
      if (state.accounts == null) byId("accounts").replaceChildren(element("div", "empty", "暂时无法读取账号额度。"));
    }
  }
  const okay = usage.status === "fulfilled" && byId("account-error").hidden;
  byId("connection").classList.toggle("connected", okay);
  byId("connection").textContent = okay ? "Magpie 已连接" : "部分数据未更新";
  byId("refresh").disabled = false;
  byId("refresh").lastChild.textContent = "刷新数据";
  document.querySelectorAll("[data-days]").forEach((button) => { button.disabled = false; });
  state.busy = false;
}

byId("refresh").addEventListener("click", () => loadData());
byId("account-search").addEventListener("input", renderAccounts);
byId("model-search").addEventListener("input", renderModels);
document.querySelectorAll("[data-days]").forEach((button) => button.addEventListener("click", () => {
  state.days = Number(button.dataset.days);
  document.querySelectorAll("[data-days]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
  loadData(false);
}));
document.querySelectorAll("[data-chart]").forEach((button) => button.addEventListener("click", () => {
  state.chart = button.dataset.chart;
  document.querySelectorAll("[data-chart]").forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
  renderTrend();
}));
let chartWidth = 0;
const observer = new ResizeObserver((entries) => {
  const width = entries[0].contentRect.width;
  if (Math.abs(width - chartWidth) > 1) { chartWidth = width; renderTrend(); }
});
observer.observe(byId("chart"));
if (!bridge) {
  byId("notice").hidden = false;
  byId("notice").textContent = "请从 AstrBot 的插件可视化页面打开此看板。";
  byId("refresh").disabled = true;
} else {
  await bridge.ready();
  await loadData();
  const clock = setInterval(() => {
    updateResetClocks();
    if (!document.hidden && byId("auto").checked) loadData();
  }, 60000);
  window.addEventListener("pagehide", () => { clearInterval(clock); observer.disconnect(); });
}
