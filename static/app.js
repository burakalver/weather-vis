const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];
const MAX_CITIES = 3;
// selected-year line, its forecast continuation, baseline average, baseline 10–90% band
const KINDS = ["actual", "forecast", "mean", "band"];
const KEYS = ["high", "low"].flatMap(k => KINDS.map(kind => `${k}.${kind}`));
const now = new Date();
const monthIndex = (y, m) => y * 12 + (m - 1);
// Latest navigable month: the one the forecast horizon (today + 15 days) reaches.
const horizon = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 15);
const MAX_INDEX = monthIndex(horizon.getFullYear(), horizon.getMonth() + 1);

const defaults = () => ({
  // slot = fixed color index, so a city keeps its color when another is removed
  cities: [{ city: "Cambridge", region: "Massachusetts", country: "United States", cc: "US", lat: 42.3751, lon: -71.1056, slot: 0 }],
  month: now.getMonth() + 1,
  year: now.getFullYear(),
  bstart: 2000, bend: 2020,
  mode: "smoothed", units: "F",  // 7-day mean: this app is about trends more than daily noise
  show: Object.fromEntries(KEYS.map(k => [k, true])),  // one set of toggles shared by all cities
});
const state = defaults();
// Set when adding a 2nd city auto-hid series; undone on going back to one city
// if the user hasn't touched the toggles since.
let autoHide = null;
let data = null;  // { req, series: [{ city, res }] } — temperatures in °C

const $ = id => document.getElementById(id);
const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const US_STATES = {
  Alabama: "AL", Alaska: "AK", Arizona: "AZ", Arkansas: "AR", California: "CA", Colorado: "CO", Connecticut: "CT",
  Delaware: "DE", "District of Columbia": "DC", Florida: "FL", Georgia: "GA", Hawaii: "HI", Idaho: "ID", Illinois: "IL",
  Indiana: "IN", Iowa: "IA", Kansas: "KS", Kentucky: "KY", Louisiana: "LA", Maine: "ME", Maryland: "MD",
  Massachusetts: "MA", Michigan: "MI", Minnesota: "MN", Mississippi: "MS", Missouri: "MO", Montana: "MT",
  Nebraska: "NE", Nevada: "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
  "North Carolina": "NC", "North Dakota": "ND", Ohio: "OH", Oklahoma: "OK", Oregon: "OR", Pennsylvania: "PA",
  "Rhode Island": "RI", "South Carolina": "SC", "South Dakota": "SD", Tennessee: "TN", Texas: "TX", Utah: "UT",
  Vermont: "VT", Virginia: "VA", Washington: "WA", "West Virginia": "WV", Wisconsin: "WI", Wyoming: "WY",
};
// Geocoder country names that are longer/more formal than everyday usage.
const COUNTRY_SHORT = { GB: "UK", TR: "Turkey", AE: "UAE" };
// "Cambridge, MA" in the US; "Cambridge, UK" / "Istanbul, Turkey" elsewhere.
const cityLabel = c => c.cc === "US"
  ? [c.city, US_STATES[c.region] || c.region].filter(Boolean).join(", ")
  : [c.city, COUNTRY_SHORT[c.cc] || c.country || c.cc].filter(Boolean).join(", ");
const sameShow = (a, b) => KEYS.every(k => a[k] === b[k]);

// ---- controls ----
MONTHS.forEach((m, i) => $("month").add(new Option(m, i + 1)));
$("year").max = horizon.getFullYear();
$("bstart").max = $("bend").max = now.getFullYear();

function syncControls() {
  $("month").value = state.month;
  $("year").value = state.year;
  $("bstart").value = state.bstart;
  $("bend").value = state.bend;
  for (const id of ["mode", "units"]) {
    const v = id === "mode" ? state.mode : state.units;
    $(id).querySelectorAll("button").forEach(x => x.classList.toggle("on", x.dataset.v === v));
  }
  renderChips();
}

// Keep month within [Jan 1941, last forecast month] and the baseline within [1941, this year].
function clampState() {
  const i = Math.min(Math.max(monthIndex(state.year, state.month), monthIndex(1941, 1)), MAX_INDEX);
  [state.year, state.month] = [Math.floor(i / 12), i % 12 + 1];
  state.bstart = Math.min(Math.max(state.bstart, 1941), now.getFullYear());
  state.bend = Math.min(Math.max(state.bend, state.bstart), now.getFullYear());
}

for (const id of ["month", "year", "bstart", "bend"]) {
  $(id).addEventListener("change", () => {
    const v = parseInt($(id).value, 10);
    if (Number.isFinite(v)) state[id] = v;
    clampState();
    syncControls();  // show the clamped values (or restore a cleared box)
    load();
  });
}

function stepMonth(delta) {
  const i = monthIndex(state.year, state.month) + delta;
  if (i > MAX_INDEX || i < monthIndex(1941, 1)) return;
  state.year = Math.floor(i / 12);
  state.month = i % 12 + 1;
  $("year").value = state.year;
  $("month").value = state.month;
  load();
}
$("prev").addEventListener("click", () => stepMonth(-1));
$("next").addEventListener("click", () => stepMonth(1));
document.addEventListener("keydown", e => {
  if (e.target.matches("input:not([type=checkbox]), select") || e.metaKey || e.ctrlKey || e.altKey) return;
  if (e.key === "ArrowLeft") stepMonth(-1);
  if (e.key === "ArrowRight") stepMonth(1);
});
for (const id of ["mode", "units"]) {
  $(id).addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    state[id] = b.dataset.v;
    $(id).querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
    saveView(false);
    render();
  });
}

// ---- cities ----
function addCity(c) {
  if (state.cities.length >= MAX_CITIES) return;
  if (state.cities.some(x => Math.abs(x.lat - c.lat) < 1e-3 && Math.abs(x.lon - c.lon) < 1e-3)) return;
  const used = new Set(state.cities.map(x => x.slot));
  c.slot = [0, 1, 2].find(s => !used.has(s));
  state.cities.push(c);
  if (state.cities.length === 2 && KEYS.every(k => state.show[k])) {
    const before = { ...state.show };
    for (const k of KEYS) state.show[k] = k.endsWith(".mean");
    autoHide = { before, applied: { ...state.show } };
  }
  renderChips();
  load();
}

function removeCity(i) {
  if (state.cities.length <= 1) return;
  state.cities.splice(i, 1);
  if (state.cities.length === 1) {
    if (autoHide && sameShow(state.show, autoHide.applied)) state.show = autoHide.before;
    autoHide = null;
  }
  renderChips();
  load();
}

function renderChips() {
  const multi = state.cities.length > 1;
  $("chips").innerHTML = state.cities.map((c, i) =>
    `<span class="chip${multi ? "" : " solo"}">` +
      (multi ? `<i class="dot" style="background: var(--city-${c.slot})"></i>` : "") +
      esc(cityLabel(c)) +
      (multi ? `<button data-i="${i}" title="Remove">×</button>` : "") +
    `</span>`
  ).join("");
  const full = state.cities.length >= MAX_CITIES;
  $("loc").disabled = full;
  $("loc").placeholder = full ? "Max 3 cities" : state.cities.length ? "Add a city to compare…" : "Search a city…";
}
$("chips").addEventListener("click", e => {
  const b = e.target.closest("button[data-i]"); if (b) removeCity(+b.dataset.i);
});

// Location search (Open-Meteo geocoding, called directly from the browser)
let searchTimer, results = [];
$("loc").addEventListener("input", () => {
  clearTimeout(searchTimer);
  const q = $("loc").value.trim();
  if (q.length < 2) { $("results").style.display = "none"; return; }
  searchTimer = setTimeout(async () => {
    const r = await fetch(`https://geocoding-api.open-meteo.com/v1/search?name=${encodeURIComponent(q)}&count=8&language=en`);
    results = (await r.json()).results || [];
    $("results").innerHTML = results.map((p, i) =>
      `<li data-i="${i}">${esc(p.name)}<small> — ${esc([p.admin1, p.country].filter(Boolean).join(", "))}</small></li>`
    ).join("") || "<li><small>No matches</small></li>";
    $("results").style.display = "block";
  }, 250);
});
$("results").addEventListener("mousedown", e => {
  const li = e.target.closest("li[data-i]"); if (!li) return;
  const p = results[+li.dataset.i];
  $("loc").value = "";
  $("results").style.display = "none";
  addCity({ city: p.name, region: p.admin1, country: p.country, cc: p.country_code, lat: p.latitude, lon: p.longitude });
});
$("loc").addEventListener("blur", () => setTimeout(() => {
  $("results").style.display = "none";
  $("loc").value = "";
}, 150));

// ---- view state in the URL (bookmarkable, Back works) + last view remembered in localStorage ----
const STORE_KEY = "weather-vis:last-view";
const SHOW_CODE = Object.fromEntries(KEYS.map(k => [k, k[0] + k.split(".")[1][0]]));  // "high.actual" -> "ha"
const pad2 = n => String(n).padStart(2, "0");
const enc = v => encodeURIComponent(v ?? "").replace(/%20/g, "+");

function toQuery() {
  // Built by hand so the "|" field separators stay readable in the address bar.
  const parts = state.cities.map(c => "c=" + [c.city, c.region, c.country, c.cc, c.lat, c.lon, c.slot].map(enc).join("|"));
  parts.push(`m=${state.year}-${pad2(state.month)}`, `base=${state.bstart}-${state.bend}`,
             `view=${state.mode}`, `u=${state.units}`,
             `show=${KEYS.filter(k => state.show[k]).map(k => SHOW_CODE[k]).join(",") || "none"}`);
  return parts.join("&");
}

// Anything missing or malformed falls back to the default.
function fromQuery(qs) {
  const p = new URLSearchParams(qs), s = defaults();
  const cities = [];
  for (const raw of p.getAll("c").slice(0, MAX_CITIES)) {
    const [city, region, country, cc, lat, lon, slot] = raw.split("|");
    if (!city || !isFinite(parseFloat(lat)) || !isFinite(parseFloat(lon))) continue;
    cities.push({ city, region, country, cc, lat: parseFloat(lat), lon: parseFloat(lon), slot: +slot });
  }
  if (cities.length) {
    // Keep saved colors unless they're invalid or clash; then just number them in order.
    const slots = cities.map(c => c.slot);
    if (!slots.every(x => [0, 1, 2].includes(x)) || new Set(slots).size !== slots.length) cities.forEach((c, i) => c.slot = i);
    s.cities = cities;
  }
  const m = /^(\d{4})-(\d{2})$/.exec(p.get("m") || "");
  if (m && +m[2] >= 1 && +m[2] <= 12 && monthIndex(+m[1], +m[2]) <= MAX_INDEX && +m[1] >= 1941) [s.year, s.month] = [+m[1], +m[2]];
  const b = /^(\d{4})-(\d{4})$/.exec(p.get("base") || "");
  if (b && +b[1] >= 1941 && +b[1] <= +b[2] && +b[2] <= now.getFullYear()) [s.bstart, s.bend] = [+b[1], +b[2]];
  if (["daily", "smoothed"].includes(p.get("view"))) s.mode = p.get("view");
  if (["F", "C"].includes(p.get("u"))) s.units = p.get("u");
  if (p.has("show")) {
    const codes = new Set(p.get("show").split(","));
    for (const k of KEYS) s.show[k] = codes.has(SHOW_CODE[k]);
  }
  return s;
}

// push: a new Back-button step (cities/month/baseline); otherwise update the current entry (toggles).
function saveView(push) {
  const qs = toQuery();
  if (location.search.slice(1) !== qs) history[push ? "pushState" : "replaceState"](null, "", "?" + qs);
  try { localStorage.setItem(STORE_KEY, qs); } catch {}
}

function applyView(s) {
  Object.assign(state, s);
  autoHide = null;
  syncControls();
}

window.addEventListener("popstate", () => { applyView(fromQuery(location.search)); load({ push: false }); });
$("reset").addEventListener("click", () => { applyView(defaults()); load(); });

// ---- data ----
function setStatus(msg, isError = false) {
  $("status").textContent = msg || "";
  $("status").style.display = msg ? "block" : "none";
  $("status").classList.toggle("error", isError);
  $("chart").style.opacity = msg && !isError ? 0.4 : 1;
}

const responseCache = new Map();  // per page session; the server caches past years on disk
function fetchCity(c, req) {
  const p = new URLSearchParams({ lat: c.lat, lon: c.lon, year: req.year, month: req.month,
                                  base_start: req.bstart, base_end: req.bend });
  const key = p.toString();
  if (!responseCache.has(key)) {
    const promise = fetch(`/api/month?${p}`).then(async r => {
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.statusText);
      return j;
    });
    promise.catch(() => responseCache.delete(key));
    responseCache.set(key, promise);
  }
  return responseCache.get(key);
}

let loadSeq = 0;  // only the most recent request gets to render (fast Prev/Next clicking)

async function load({ push = true } = {}) {
  const seq = ++loadSeq;
  saveView(push);
  $("next").disabled = monthIndex(state.year, state.month) >= MAX_INDEX;
  setStatus("Loading…");
  // Snapshot what's being requested, so render() labels the data it actually has.
  const req = { cities: [...state.cities], year: state.year, month: state.month, bstart: state.bstart, bend: state.bend };
  const settled = await Promise.allSettled(req.cities.map(c => fetchCity(c, req)));
  if (seq !== loadSeq) return;
  const series = [], errors = [];
  settled.forEach((s, i) => s.status === "fulfilled"
    ? series.push({ city: req.cities[i], res: s.value })
    : errors.push(`${cityLabel(req.cities[i])}: ${s.reason.message}`));
  data = series.length ? { req, series } : null;
  setStatus(errors.length ? `Couldn't load data — ${errors.join("; ")}` : null, errors.length > 0);
  if (data) render(); else Plotly.purge("chart");
}

// ---- legend (show/hide checkboxes; one set for all cities) ----
function swatch(kind, color) {
  const band = css("--band-alpha");
  const body = kind === "band"
    ? `<rect x="1" y="1" width="24" height="12" rx="2" fill="${rgba(color, Math.min(1, band * 2.2))}"/>`
    : kind === "forecast"
    ? `<line x1="2" y1="7" x2="25" y2="7" stroke="${color}" stroke-width="2" stroke-dasharray="0.1 4" stroke-linecap="round"/>` +
      `<circle cx="13" cy="7" r="3.5" fill="${css("--surface")}" stroke="${color}" stroke-width="1.5"/>`
    : `<line x1="1" y1="7" x2="25" y2="7" stroke="${color}" stroke-width="2"${kind === "mean" ? ' stroke-dasharray="4 3"' : ""}/>`;
  return `<svg width="26" height="14" aria-hidden="true">${body}</svg>`;
}

function renderLegend(q, multi, hasForecast) {
  const labels = { actual: String(q.year), forecast: "Forecast", mean: `${q.bstart}–${q.bend} avg`, band: "Baseline 10–90%" };
  const neutral = css("--text-secondary");
  let html = "";
  if (multi) {
    html += `<h3>Cities</h3>` + q.cities.map(c =>
      `<div class="key">${swatch("actual", css(`--city-${c.slot}`))}<span>${esc(cityLabel(c))}</span></div>`).join("");
  }
  for (const [k, title] of [["high", "Highs"], ["low", "Lows"]]) {
    const color = multi ? neutral : css(`--${k}`);
    html += `<h3>${title}</h3>` + KINDS.filter(kind => kind !== "forecast" || hasForecast).map(kind =>
      `<label><input type="checkbox" data-k="${k}.${kind}"${state.show[`${k}.${kind}`] ? " checked" : ""}>` +
      `${swatch(kind, color)}<span>${labels[kind]}</span></label>`).join("");
  }
  $("legend").innerHTML = html;
}
$("legend").addEventListener("change", e => {
  const k = e.target.dataset.k; if (!k) return;
  state.show[k] = e.target.checked;
  saveView(false);
  render();
});

// ---- chart ----
const conv = v => v == null ? null : (state.units === "F" ? v * 9 / 5 + 32 : v);
const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };

function render() {
  if (!data) return;
  const q = data.req;
  const multi = data.series.length > 1;
  const monthName = MONTHS[q.month - 1];
  const lastDates = data.series.map(s => s.res.last_date).filter(Boolean).sort();
  const fcDates = data.series.map(s => s.res.forecast_through).filter(Boolean).sort();
  const hasForecast = fcDates.length > 0;
  const showForecast = hasForecast && (state.show["high.forecast"] || state.show["low.forecast"]);
  const anyBand = state.show["high.band"] || state.show["low.band"];
  const fmtDay = iso => `${MONTHS[+iso.slice(5, 7) - 1].slice(0, 3)} ${+iso.slice(8, 10)}`;
  $("title").textContent = `${monthName} ${q.year} vs ${q.bstart}–${q.bend} average`;
  $("subtitle").textContent = [
    data.series.map(s => cityLabel(s.city)).join(" · "),
    lastDates.length ? `data through ${fmtDay(lastDates[lastDates.length - 1])}` : "no data yet for this month",
    showForecast ? `forecast through ${fmtDay(fcDates[fcDates.length - 1])}` : "",
    anyBand ? `band = 10th–90th percentile of ${state.mode === "smoothed" ? "7-day means" : "daily values"} in baseline years` : "",
  ].filter(Boolean).join(" · ");
  renderLegend(q, multi, hasForecast);

  const u = `°${state.units}`;
  const days = data.series[0].res.days.map(d => `${q.year}-${pad2(q.month)}-${pad2(d)}`);
  const band = css("--band-alpha");
  const traces = [];

  for (const { city, res } of data.series) {
    const m = res[state.mode];
    const who = multi ? `${cityLabel(city)} ` : "";
    for (const [key, label] of [["high", "high"], ["low", "low"]]) {
      const color = css(multi ? `--city-${city.slot}` : `--${key}`);
      const b = m[key].baseline, a = m[key].actual, f = m[key].forecast || [];
      const mean = b.mean.map(conv);
      const vsAvg = vals => vals.map((v, i) => v == null || mean[i] == null ? null : conv(v) - mean[i]);
      if (state.show[`${key}.band`]) traces.push(
        { x: days, y: b.p10.map(conv), mode: "lines", line: { width: 0 }, hoverinfo: "skip" },
        { x: days, y: b.p90.map(conv), mode: "lines", line: { width: 0 }, fill: "tonexty",
          fillcolor: rgba(color, band), hoverinfo: "skip" },
      );
      if (state.show[`${key}.mean`]) traces.push(
        { x: days, y: mean, mode: "lines", line: { color, width: 2, dash: "dash" },
          hovertemplate: `${who}avg ${label} %{y:.0f}${u}<extra></extra>` },
      );
      if (state.show[`${key}.actual`]) traces.push(
        { x: days, y: a.map(conv), mode: state.mode === "daily" ? "lines+markers" : "lines",
          line: { color, width: 2 }, marker: { size: 6 },
          customdata: vsAvg(a),
          hovertemplate: `<b>${who}${label} %{y:.0f}${u}</b> (%{customdata:+.0f}° vs avg)<extra></extra>` },
      );
      const k0 = f.findIndex(v => v != null);  // first forecast day
      if (state.show[`${key}.forecast`] && k0 >= 0) {
        // Dotted join from the last observed point, so the lines read as one series.
        if (state.show[`${key}.actual`] && k0 > 0 && a[k0 - 1] != null) traces.push(
          { x: [days[k0 - 1], days[k0]], y: [conv(a[k0 - 1]), conv(f[k0])], mode: "lines",
            line: { color, width: 2, dash: "dot" }, hoverinfo: "skip" },
        );
        traces.push(
          { x: days, y: f.map(conv), mode: state.mode === "daily" ? "lines+markers" : "lines",
            line: { color, width: 2, dash: "dot" },
            marker: { size: 7, symbol: "circle-open", line: { width: 1.5, color } },
            customdata: vsAvg(f),
            hovertemplate: `${who}${label} <i>forecast</i> %{y:.0f}${u} (%{customdata:+.0f}° vs avg)<extra></extra>` },
        );
      }
    }
  }

  // Shade the days that are forecast (by date, not by 7-day windows that merely touch them).
  const shapes = [], annotations = [];
  if (showForecast) {
    const firstFc = Math.min(...data.series.map(s => s.res.daily.high.forecast.findIndex(v => v != null)).filter(i => i >= 0));
    const lastFc = Math.max(...data.series.map(s => s.res.daily.high.forecast.findLastIndex(v => v != null)));
    const at = (k, hour) => new Date(Date.UTC(q.year, q.month - 1, k + 1, hour)).toISOString().replace("T", " ").slice(0, 16);
    shapes.push({ type: "rect", xref: "x", yref: "paper", x0: at(firstFc - 1, 12), x1: at(lastFc, 12), y0: 0, y1: 1,
                  fillcolor: css("--fc-shade"), line: { width: 0 }, layer: "below" });
    annotations.push({ xref: "x", yref: "paper", x: at(firstFc - 1, 12), y: 1, xanchor: "left", yanchor: "bottom",
                       text: "Forecast", showarrow: false, font: { size: 11, color: css("--text-secondary") } });
  }

  const ink = css("--text-primary"), ink2 = css("--text-secondary"), grid = css("--grid");
  Plotly.react("chart", traces, {
    shapes, annotations,
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: getComputedStyle(document.body).fontFamily, color: ink2, size: 12 },
    margin: { l: 50, r: 10, t: 22, b: 50 },
    showlegend: false,
    hovermode: "x unified",
    hoverlabel: { bgcolor: css("--surface"), bordercolor: css("--border"), font: { color: ink } },
    xaxis: { type: "date", title: { text: monthName }, dtick: 86400000, tickformat: "%-d", hoverformat: "%a %b %-d",
             // half a day of padding on each side so the first/last points aren't on the edge
             range: [Date.UTC(q.year, q.month - 1, 0, 12), Date.UTC(q.year, q.month - 1, days.length, 12)]
                      .map(t => new Date(t).toISOString().replace("T", " ").slice(0, 16)),
             gridcolor: grid, zeroline: false, tickfont: { size: 11 } },
    yaxis: { title: { text: `Temperature (${u})` }, gridcolor: grid, zeroline: false, ticksuffix: "°" },
  }, { responsive: true, displaylogo: false });
}

window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", render);

// Start from the URL if it has a view, else where the user left off, else defaults.
let startQuery = location.search.slice(1);
if (!startQuery) { try { startQuery = localStorage.getItem(STORE_KEY) || ""; } catch {} }
applyView(startQuery ? fromQuery(startQuery) : defaults());
load({ push: false });
