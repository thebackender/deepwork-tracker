"use strict";

// Data comes from data.js, which `dw stats` writes: { goalHours, generated, records: [...] }
const DATA = window.DEEPWORK;
const NS = "http://www.w3.org/2000/svg";
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
const hoursFmt = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
const intFmt = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
const hours = min => hoursFmt.format(min / 60);
const $ = id => document.getElementById(id);

// ---------- Dates (all in local time) ----------
const parseDate = s => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const dayKey = d =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const daysBetween = (a, b) => Math.round((b - a) / 864e5);
const weekStart = d => addDays(d, -((d.getDay() + 6) % 7)); // Monday
const today = () => { const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), n.getDate()); };
const longDay = d => d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
const shortDay = d => d.toLocaleDateString(undefined, { day: "numeric", month: "short" });

// ---------- Small helpers ----------
function svgEl(tag, attrs = {}, parent) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

function htmlEl(tag, attrs = {}, text) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  return node;
}

// Animate a number from `from` to `to`, formatting each frame.
function countTo(node, from, to, format, duration = 1600) {
  if (reduceMotion) { node.textContent = format(to); return; }
  const start = performance.now();
  const frame = now => {
    const p = Math.min(1, (now - start) / duration);
    const eased = 1 - Math.pow(1 - p, 3);
    node.textContent = format(from + (to - from) * eased);
    if (p < 1) requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

// Round an axis maximum up to a clean number (1, 2, 5 × 10^n steps).
function niceScale(max, ticks = 4) {
  if (max <= 0) return { top: ticks, step: 1 };
  const raw = max / ticks;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 5, 10].map(m => m * mag).find(s => s >= raw);
  return { top: step * Math.ceil(max / step), step };
}

// Bar path with 4px rounded top corners and a square base.
function barPath(x, y, w, h) {
  const r = Math.min(4, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

// ---------- Tooltip ----------
// Elements with data-tip="Title\nline\nline" show a tooltip on hover.
const tip = $("tooltip");
function showTip(text, x, y) {
  tip.replaceChildren();
  text.split("\n").forEach((line, i) => tip.appendChild(htmlEl(i ? "div" : "strong", {}, line)));
  tip.hidden = false;
  const { width, height } = tip.getBoundingClientRect();
  const left = x + 14 + width > innerWidth ? x - 14 - width : x + 14;
  const top = Math.max(4, Math.min(y - height - 10, innerHeight - height - 4));
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
}
const hideTip = () => { tip.hidden = true; };
document.addEventListener("pointermove", e => {
  if (e.target.closest?.(".hover-zone")) return; // charts with their own hover logic
  const target = e.target.closest?.("[data-tip]");
  if (target) showTip(target.dataset.tip, e.clientX, e.clientY);
  else hideTip();
});
document.addEventListener("pointerleave", hideTip);

// ---------- Statistics ----------
function computeStats(records, goalHours) {
  const byDay = new Map(); // "YYYY-MM-DD" -> { min, sessions }
  const byProject = new Map(); // project -> minutes
  const projectOrder = [];     // projects in order of first use (keeps colors stable)
  let totalMin = 0;
  for (const r of records) {
    totalMin += r.minutes;
    const day = byDay.get(r.date) || { min: 0, sessions: 0 };
    day.min += r.minutes;
    day.sessions += 1;
    byDay.set(r.date, day);
    if (!byProject.has(r.project)) projectOrder.push(r.project);
    byProject.set(r.project, (byProject.get(r.project) || 0) + r.minutes);
  }

  const now = today();
  const thisWeek = dayKey(weekStart(now));
  const thisMonth = dayKey(now).slice(0, 7);
  let weekMin = 0, monthMin = 0;
  for (const r of records) {
    if (r.date >= thisWeek) weekMin += r.minutes;
    if (r.date.startsWith(thisMonth)) monthMin += r.minutes;
  }

  // Streaks: consecutive days with at least one session.
  const days = [...byDay.keys()].sort();
  let longest = 0, run = 0, prev = null;
  for (const k of days) {
    const d = parseDate(k);
    run = prev && daysBetween(prev, d) === 1 ? run + 1 : 1;
    longest = Math.max(longest, run);
    prev = d;
  }
  let current = 0;
  let cursor = byDay.has(dayKey(now)) ? now : addDays(now, -1); // today not logged yet keeps the streak
  while (byDay.has(dayKey(cursor))) { current++; cursor = addDays(cursor, -1); }

  // Pace over the last 90 days (or since the first record, if newer).
  let paceDays = 90;
  if (records.length) paceDays = Math.min(90, daysBetween(parseDate(records[0].date), now) + 1);
  const since = dayKey(addDays(now, -(paceDays - 1)));
  const recentMin = records.filter(r => r.date >= since).reduce((s, r) => s + r.minutes, 0);
  const pacePerDay = recentMin / 60 / Math.max(1, paceDays);

  const doneHours = totalMin / 60;
  const leftHours = Math.max(0, goalHours - doneHours);

  return { byDay, byProject, projectOrder, totalMin, weekMin, monthMin, longest, current,
           paceDays, pacePerDay, doneHours, leftHours };
}

// Up to 8 projects get their own color; with more, the smaller ones fold into "Other".
function projectColors(stats) {
  const bySize = [...stats.byProject.entries()].sort((a, b) => b[1] - a[1]).map(([t]) => t);
  const shown = new Set(bySize.length > 8 ? bySize.slice(0, 7) : bySize);
  const colors = new Map();
  let slot = 1;
  for (const t of stats.projectOrder) colors.set(t, shown.has(t) ? `var(--s${slot++})` : "var(--other)");
  return { colors, shown };
}

// ---------- Sections ----------
function renderHero(stats, goal) {
  const pct = Math.min(100, (stats.doneHours / goal) * 100);
  const svg = svgEl("svg", { viewBox: "0 0 200 200", width: 200, height: 200, role: "img",
                             "aria-label": `${hoursFmt.format(pct)}% of ${intFmt.format(goal)} hours` });
  svgEl("circle", { cx: 100, cy: 100, r: 86, class: "ring-track" }, svg);
  if (pct > 0) {
    svgEl("circle", { cx: 100, cy: 100, r: 86, class: "ring-fill", pathLength: 100,
                      "stroke-dasharray": 100, "stroke-dashoffset": 100 - pct,
                      transform: "rotate(-90 100 100)" }, svg);
  }
  $("ring").appendChild(svg);

  $("heroLabel").textContent = `Hours left to ${intFmt.format(goal)}`;
  countTo($("ringPct"), 0, pct, v => `${v < 10 ? hoursFmt.format(v) : intFmt.format(v)}%`);
  countTo($("hoursLeft"), goal, stats.leftHours, v => hoursFmt.format(v));

  let sub = `${hoursFmt.format(stats.doneHours)} of ${intFmt.format(goal)} hours done.`;
  if (stats.leftHours === 0) {
    sub += " Goal reached!";
  } else if (stats.pacePerDay > 0) {
    const daysLeft = stats.leftHours / stats.pacePerDay;
    const finish = addDays(today(), Math.ceil(daysLeft));
    const span = daysLeft >= 365 ? `${hoursFmt.format(daysLeft / 365)} years` : `${intFmt.format(daysLeft)} days`;
    sub += ` At your pace of ${hoursFmt.format(stats.pacePerDay)} h/day (last ${stats.paceDays} days),` +
           ` you'll get there in about ${span}, around ${finish.toLocaleDateString(undefined, { month: "long", year: "numeric" })}.`;
  } else {
    sub += " Log some sessions to see when you'll get there.";
  }
  $("heroSub").textContent = sub;
}

function renderTiles(stats) {
  const tiles = [
    ["Total", stats.totalMin / 60, "h", hoursFmt],
    ["This week", stats.weekMin / 60, "h", hoursFmt],
    ["This month", stats.monthMin / 60, "h", hoursFmt],
    ["Current streak", stats.current, stats.current === 1 ? "day" : "days", intFmt],
    ["Longest streak", stats.longest, stats.longest === 1 ? "day" : "days", intFmt],
    ["Sessions", DATA.records.length, "", intFmt],
  ];
  tiles.forEach(([label, value, unit, fmt], i) => {
    const tile = htmlEl("div", { class: "card tile", style: `--i:${i + 1}` });
    tile.appendChild(htmlEl("div", { class: "label" }, label));
    const v = htmlEl("div", { class: "value" });
    const num = htmlEl("span", {}, "0");
    v.appendChild(num);
    if (unit) v.appendChild(htmlEl("span", { class: "unit" }, unit));
    tile.appendChild(v);
    $("tiles").appendChild(tile);
    countTo(num, 0, value, x => fmt.format(x));
  });
}

const HEAT_LEVELS = [
  [0, "0 h"], [60, "under 1 h"], [120, "1–2 h"], [240, "2–4 h"], [Infinity, "4 h+"],
];
const heatLevel = min => (min <= 0 ? 0 : HEAT_LEVELS.findIndex(([limit], i) => i > 0 && min < limit));

function renderHeatmap(stats) {
  const end = today();
  const start = weekStart(addDays(end, -364));
  const weeks = Math.floor(daysBetween(start, end) / 7) + 1;
  const cell = 15, step = 18, left = 30, top = 18;
  const width = left + weeks * step, height = top + 7 * step;
  const svg = svgEl("svg", { width, height, viewBox: `0 0 ${width} ${height}`, role: "img",
                             "aria-label": "Daily deep work hours over the last 12 months" });

  ["Mon", "Wed", "Fri"].forEach((name, i) =>
    svgEl("text", { x: 0, y: top + i * 2 * step + 12 }, svg).textContent = name);

  // Month label above the first week of each month, skipped when it would crowd its neighbour.
  let lastMonth = -1, lastLabelW = -10;
  for (let w = 0; w < weeks; w++) {
    const monday = addDays(start, w * 7);
    if (monday.getMonth() !== lastMonth) {
      const nextMonthSoon = w === 0 && addDays(monday, 14).getMonth() !== monday.getMonth();
      if (w - lastLabelW >= 3 && w < weeks - 2 && !nextMonthSoon) {
        svgEl("text", { x: left + w * step, y: 11 }, svg).textContent =
          monday.toLocaleDateString(undefined, { month: "short" });
        lastLabelW = w;
      }
      lastMonth = monday.getMonth();
    }
    for (let d = 0; d < 7; d++) {
      const date = addDays(monday, d);
      if (date > end) break;
      const info = stats.byDay.get(dayKey(date));
      const min = info ? info.min : 0;
      const tipText = info
        ? `${longDay(date)}\n${hours(min)} h in ${info.sessions} session${info.sessions > 1 ? "s" : ""}`
        : `${longDay(date)}\nNo deep work`;
      svgEl("rect", { x: left + w * step, y: top + d * step, width: cell, height: cell, rx: 2,
                      class: `cell l${heatLevel(min)}`, style: `--i:${w}`, "data-tip": tipText }, svg);
    }
  }
  $("heatmap").appendChild(svg);

  HEAT_LEVELS.forEach(([, label], i) => {
    const item = htmlEl("span");
    item.appendChild(htmlEl("i", { style: `background:var(--heat-${i})` }));
    item.appendChild(document.createTextNode(label));
    $("heatLegend").appendChild(item);
  });
}

function renderWeekly(records) {
  const N = 26;
  const first = addDays(weekStart(today()), -(N - 1) * 7);
  const perWeek = new Array(N).fill(0);
  for (const r of records) {
    const i = daysBetween(first, weekStart(parseDate(r.date))) / 7;
    if (i >= 0 && i < N) perWeek[i] += r.minutes / 60;
  }

  const W = 640, H = 240, m = { l: 34, r: 8, t: 18, b: 26 };
  const plotW = W - m.l - m.r, plotH = H - m.t - m.b;
  const { top, step } = niceScale(Math.max(...perWeek));
  const y = v => m.t + plotH - (v / top) * plotH;
  const band = plotW / N, bw = Math.min(24, band * 0.62);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img",
                             "aria-label": "Deep work hours per week, last 26 weeks" });

  for (let v = step; v <= top + 1e-9; v += step) {
    svgEl("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: "gridline" }, svg);
    svgEl("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }, svg).textContent = intFmt.format(v);
  }
  svgEl("text", { x: m.l - 6, y: y(0) + 4, "text-anchor": "end" }, svg).textContent = "0";

  const maxI = perWeek.indexOf(Math.max(...perWeek));
  perWeek.forEach((h, i) => {
    const monday = addDays(first, i * 7);
    const x = m.l + i * band;
    const g = svgEl("g", { class: "band",
      "data-tip": `Week of ${shortDay(monday)}\n${hoursFmt.format(h)} h` }, svg);
    svgEl("rect", { x, y: m.t, width: band, height: plotH, class: "hit" }, g);
    if (h > 0) {
      svgEl("path", { d: barPath(x + (band - bw) / 2, y(h), bw, y(0) - y(h)), class: "bar", style: `--i:${i}` }, g);
    }
    if ((N - 1 - i) % 4 === 0) {
      svgEl("text", { x: x + band / 2, y: H - 6, "text-anchor": "middle" }, svg).textContent = shortDay(monday);
    }
    if (i === maxI && h > 0) {
      svgEl("text", { x: x + band / 2, y: y(h) - 6, "text-anchor": "middle", class: "value-label" }, svg)
        .textContent = hoursFmt.format(h);
    }
  });
  svgEl("line", { x1: m.l, x2: W - m.r, y1: y(0), y2: y(0), class: "baseline" }, svg);
  $("weekly").appendChild(svg);
}

function renderProjects(stats) {
  const box = $("projects");
  if (!stats.byProject.size) { box.appendChild(htmlEl("p", { class: "empty" }, "No projects yet.")); return; }

  const { colors, shown } = projectColors(stats);
  const items = [...stats.byProject.entries()].filter(([t]) => shown.has(t))
    .map(([project, min]) => ({ project, min, color: colors.get(project) }))
    .sort((a, b) => b.min - a.min);
  const otherMin = [...stats.byProject.entries()].filter(([t]) => !shown.has(t)).reduce((s, [, m]) => s + m, 0);
  if (otherMin > 0) items.push({ project: "Other", min: otherMin, color: "var(--other)" });

  const wrap = htmlEl("div", { class: "donut-svg" });
  const svg = svgEl("svg", { viewBox: "0 0 200 200", role: "img", "aria-label": "Share of hours per project" });
  const r = 80;
  const gap = items.length > 1 ? (2 / (2 * Math.PI * r)) * 100 : 0; // 2px surface gap, in percent
  let offset = 0;
  items.forEach((item, i) => {
    const share = (item.min / stats.totalMin) * 100;
    const len = Math.max(0.1, share - gap);
    svgEl("circle", {
      cx: 100, cy: 100, r, class: "seg", pathLength: 100, stroke: item.color,
      "stroke-dasharray": `${len} ${100 - len}`, "stroke-dashoffset": -offset,
      transform: "rotate(-90 100 100)", style: `--i:${i}`,
      "data-tip": `${item.project}\n${hours(item.min)} h · ${hoursFmt.format(share)}%`,
    }, svg);
    offset += share;
  });
  wrap.appendChild(svg);
  const center = htmlEl("div", { class: "donut-center" });
  center.appendChild(htmlEl("strong", {}, hours(stats.totalMin)));
  center.appendChild(htmlEl("span", { class: "muted" }, "hours"));
  wrap.appendChild(center);
  box.appendChild(wrap);

  const legend = htmlEl("ul", { class: "legend" });
  for (const item of items) {
    const li = htmlEl("li");
    li.appendChild(htmlEl("span", { class: "swatch", style: `background:${item.color}` }));
    li.appendChild(htmlEl("span", {}, item.project));
    li.appendChild(htmlEl("span", { class: "num" }, `${hours(item.min)} h`));
    li.appendChild(htmlEl("span", { class: "num" }, `${intFmt.format((item.min / stats.totalMin) * 100)}%`));
    legend.appendChild(li);
  }
  box.appendChild(legend);
}

function renderCumulative(stats, records) {
  const box = $("cumulative");
  if (!records.length) { box.appendChild(htmlEl("p", { class: "empty" }, "No sessions yet.")); return; }

  // One point per day, starting at 0 the day before the first record.
  const start = addDays(parseDate(records[0].date), -1);
  const end = today() > start ? today() : addDays(start, 1);
  const points = [];
  let sum = 0;
  for (let d = start; d <= end; d = addDays(d, 1)) {
    const info = stats.byDay.get(dayKey(d));
    if (info) sum += info.min / 60;
    points.push({ date: d, total: sum });
  }

  const W = 900, H = 260, m = { l: 44, r: 56, t: 16, b: 26 };
  const plotW = W - m.l - m.r, plotH = H - m.t - m.b;
  const { top, step } = niceScale(sum);
  const x = i => m.l + (i / (points.length - 1)) * plotW;
  const y = v => m.t + plotH - (v / top) * plotH;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img",
                             "aria-label": "Cumulative deep work hours" });

  for (let v = step; v <= top + 1e-9; v += step) {
    svgEl("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), class: "gridline" }, svg);
    svgEl("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end" }, svg).textContent = intFmt.format(v);
  }
  svgEl("text", { x: m.l - 6, y: y(0) + 4, "text-anchor": "end" }, svg).textContent = "0";
  const ticks = Math.min(5, points.length - 1);
  for (let t = 0; t <= ticks; t++) {
    const i = Math.round((t / ticks) * (points.length - 1));
    svgEl("text", { x: x(i), y: H - 6, "text-anchor": t === 0 ? "start" : t === ticks ? "end" : "middle" }, svg)
      .textContent = shortDay(points[i].date);
  }

  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.total).toFixed(1)}`).join("");
  svgEl("path", { d: `${line}L${x(points.length - 1)},${y(0)}L${x(0)},${y(0)}Z`, class: "area" }, svg);
  svgEl("line", { x1: m.l, x2: W - m.r, y1: y(0), y2: y(0), class: "baseline" }, svg);
  svgEl("path", { d: line, class: "line", pathLength: 1 }, svg);

  const last = points.length - 1;
  const endMark = svgEl("g", { class: "end-mark" }, svg);
  svgEl("circle", { cx: x(last), cy: y(sum), r: 4, class: "dot" }, endMark);
  svgEl("text", { x: x(last) + 8, y: y(sum) + 4, class: "value-label" }, endMark).textContent = `${hoursFmt.format(sum)} h`;

  // Crosshair: vertical guide + dot + tooltip at the nearest day.
  const guide = svgEl("line", { y1: m.t, y2: y(0), class: "guide", visibility: "hidden" }, svg);
  const hoverDot = svgEl("circle", { r: 4, class: "dot", visibility: "hidden" }, svg);
  const zone = svgEl("rect", { x: m.l, y: m.t, width: plotW, height: plotH, class: "hit hover-zone" }, svg);
  zone.addEventListener("pointermove", e => {
    const pt = new DOMPoint(e.clientX, e.clientY).matrixTransform(svg.getScreenCTM().inverse());
    const i = Math.max(0, Math.min(last, Math.round(((pt.x - m.l) / plotW) * last)));
    const p = points[i];
    guide.setAttribute("x1", x(i)); guide.setAttribute("x2", x(i));
    hoverDot.setAttribute("cx", x(i)); hoverDot.setAttribute("cy", y(p.total));
    guide.setAttribute("visibility", "visible"); hoverDot.setAttribute("visibility", "visible");
    showTip(`${longDay(p.date)}\n${hoursFmt.format(p.total)} h total`, e.clientX, e.clientY);
  });
  zone.addEventListener("pointerleave", () => {
    guide.setAttribute("visibility", "hidden"); hoverDot.setAttribute("visibility", "hidden");
    hideTip();
  });
  box.appendChild(svg);
}

function renderRecent(stats, records) {
  const box = $("recent");
  if (!records.length) { box.appendChild(htmlEl("p", { class: "empty" }, "No sessions yet.")); return; }
  const { colors } = projectColors(stats);
  const table = htmlEl("table");
  const head = htmlEl("tr");
  ["Date", "Time", "Minutes", "Project", "Description"].forEach(h => head.appendChild(htmlEl("th", {}, h)));
  table.appendChild(head);
  for (const r of records.slice(-10).reverse()) {
    const tr = htmlEl("tr");
    tr.appendChild(htmlEl("td", { class: "num" }, longDay(parseDate(r.date))));
    tr.appendChild(htmlEl("td", { class: "num" }, r.time));
    tr.appendChild(htmlEl("td", { class: "num" }, String(r.minutes)));
    const project = htmlEl("td");
    project.appendChild(htmlEl("span", { class: "swatch", style: `background:${colors.get(r.project)}` }));
    project.appendChild(document.createTextNode(r.project));
    tr.appendChild(project);
    tr.appendChild(htmlEl("td", {}, r.description));
    table.appendChild(tr);
  }
  box.appendChild(table);
}

// ---------- Start ----------
function main() {
  if (!DATA) {
    const notice = $("notice");
    notice.hidden = false;
    notice.innerHTML = "No data found. Run <code>python dw.py stats</code> to generate it.";
    return;
  }
  const records = DATA.records;
  const stats = computeStats(records, DATA.goalHours);
  $("updated").textContent = `Data from ${new Date(DATA.generated).toLocaleString(undefined,
    { dateStyle: "medium", timeStyle: "short" })} · run dw stats to refresh`;
  if (!records.length) {
    const notice = $("notice");
    notice.hidden = false;
    notice.innerHTML = 'No sessions yet. Add one with <code>dw add 90 thesis "Wrote intro"</code>';
  }
  renderHero(stats, DATA.goalHours);
  renderTiles(stats);
  renderHeatmap(stats);
  renderWeekly(records);
  renderProjects(stats);
  renderCumulative(stats, records);
  renderRecent(stats, records);
}

main();
