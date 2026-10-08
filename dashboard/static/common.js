// Small helpers shared by every dashboard page. No framework on purpose.

async function getJSON(url, opts) {
  const resp = await fetch(url, opts);
  if (!resp.ok) throw new Error(`${url}: ${resp.status}`);
  return resp.json();
}

// el("td", {class: "num"}, "12") builds elements without innerHTML, so data can't inject HTML.
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined) continue;
    node.append(c instanceof Node ? c : String(c));
  }
  return node;
}

function table(headers, rows, emptyText = "Nothing yet.") {
  if (!rows.length) return el("div", { class: "empty" }, emptyText);
  const head = el("tr", {}, headers.map((h) => el("th", { class: h.num ? "num" : null }, h.label ?? h)));
  return el("div", { class: "table-wrap" }, el("table", {}, el("thead", {}, head), el("tbody", {}, rows)));
}

function pill(text, cls) {
  return el("span", { class: `pill ${cls || text}` }, text);
}

function ago(seconds) {
  if (seconds === null || seconds === undefined) return "never";
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h ago`;
  return `${(seconds / 86400).toFixed(1)}d ago`;
}

function clock(ts) {
  const d = new Date(ts);
  const today = new Date().toDateString() === d.toDateString();
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  return today ? time : `${d.toLocaleDateString([], { month: "short", day: "numeric" })} ${time}`;
}

function money(x) {
  if (x === null || x === undefined) return "–";
  const sign = x < 0 ? "-" : "";
  return `${sign}$${Math.abs(x).toFixed(2)}`;
}

function cents(x) {
  return x === null || x === undefined ? "–" : `${Math.round(x * 100)}¢`;
}

function fill(id, ...nodes) {
  const target = document.getElementById(id);
  target.replaceChildren(...nodes);
}

// Header with links to every hive. Call once per page.
async function renderHeader(active) {
  const header = el("header", {},
    el("div", { class: "brand" }, "Hive", el("span", {}, "work")),
    el("nav", { id: "nav" }),
    el("div", { class: "right" }, el("span", { id: "queen", class: "muted" }, "…")),
  );
  document.body.prepend(header);
  const links = [["Overview", "/"], ["Kalshi", "/kalshi"]];
  try {
    const o = await getJSON("/api/overview");
    for (const h of o.hives) if (h !== "kalshi") links.push([h, `/hive/${h}`]);
  } catch (e) { /* header still works without hive links */ }
  fill("nav", ...links.map(([label, href]) => el("a", { href, class: label === active ? "active" : null }, label)));
}

function renderQueen(o) {
  const q = o.queen;
  fill("queen",
    "queen ", pill(q.alive ? "alive" : "down", q.alive ? "alive" : "stale"),
    o.killswitch.length ? el("span", { class: "killed" }, `  kill switch: ${o.killswitch.join(", ")}`) : "",
  );
}

// Run fn now and every `ms`, showing errors in the console instead of breaking the page.
// Pauses while the tab is hidden: every poll through Vercel counts toward the free plan.
function every(ms, fn) {
  const tick = () => fn().catch((e) => console.error(e));
  tick();
  document.addEventListener("visibilitychange", () => { if (!document.hidden) tick(); });
  return setInterval(() => { if (!document.hidden) tick(); }, ms);
}

function botRows(bots) {
  return bots.map((b) => el("tr", {},
    el("td", {}, b.hive),
    el("td", {}, b.name),
    el("td", {}, pill(b.status)),
    el("td", {}, ago(b.heartbeat_age)),
    el("td", {}, b.every ? `${b.every}s` : "nonstop"),
    el("td", { class: "num" }, b.runs),
    el("td", { class: "num" }, b.errors),
    el("td", { class: "num" }, b.restarts),
    el("td", { class: "wrap muted" }, b.last_error),
  ));
}
const BOT_HEADERS = ["Hive", "Bot", "Status", "Heartbeat", "Every", { label: "Runs", num: 1 }, { label: "Errors", num: 1 }, { label: "Restarts", num: 1 }, "Last error"];

function logRows(rows) {
  return rows.map((r) => el("tr", {},
    el("td", {}, clock(r.ts)),
    el("td", {}, pill(r.kind)),
    el("td", {}, r.hive + (r.bot ? `/${r.bot}` : "")),
    el("td", { class: "wrap" }, r.detail),
  ));
}
