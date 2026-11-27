/* ATLAS — menu Historical Capacity: ringkasan perbandingan + tren per hari/minggu/bulan/kuartal/semester/tahun.
   Appliance = host appliance (disk pool digabung: dp_disk_x07 + dp_disk_x7-worm → x7).
   Grafik: SVG tanpa library (server tanpa internet). Aturan: satu sumbu Y, maks 8 garis (pilihan > 8 →
   grafik menampilkan 8 tertinggi, tabel & ringkasan memuat semua), warna mengikuti entitas, legend,
   tooltip crosshair, tabel data. */

const HIST_PALETTE = ["#5b4bd6", "#e06a2c", "#0f9d7a", "#d29a0a", "#c2307a", "#2f7fd8", "#6f8a1f", "#d33a55"];
const HIST_METRICS = {
  usage_pct: { label: "Usage (%)", unit: "%", decimals: 1 },
  used_tb: { label: "Used (TB)", unit: "TB", decimals: 1 },
  free_tb: { label: "Free (TB)", unit: "TB", decimals: 1 },
};
const THRESHOLD_TARGET = 85; // batas "Critical" dashboard
const GROUP_LABEL = { site: "Site", master: "Master", appliance: "Appliance" };

const histState = {
  options: null,
  data: null,
  compare: null,
  period: "month",
  group: "site",
  metric: "usage_pct",
  compareMode: "week", // kunci periode, atau "range"
  selected: [], // nama appliance
  colorMap: {}, // key -> slot; warna mengikuti entitas
  applianceQuery: "",
};

function histColor(key, visibleKeys) {
  if (histState.colorMap[key] === undefined) {
    const used = new Set(visibleKeys.filter((k) => k !== key && histState.colorMap[k] !== undefined).map((k) => histState.colorMap[k]));
    let slot = 0;
    while (used.has(slot) && slot < HIST_PALETTE.length - 1) slot++;
    histState.colorMap[key] = slot;
  }
  return HIST_PALETTE[histState.colorMap[key]];
}

function niceTicks(min, max, count) {
  if (max === min) max = min + 1;
  const raw = (max - min) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => raw <= s) || 10 * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1000) / 1000);
  return ticks;
}

function fmtDateOnly(iso) {
  return new Date(iso + "T00:00:00").toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" });
}

function signed(v, decimals, unit) {
  if (v === null || v === undefined) return "–";
  const arrow = v > 0 ? "▲" : v < 0 ? "▼" : "•";
  return `${arrow} ${v > 0 ? "+" : ""}${fmtNum(v, decimals)}${unit ? " " + unit : ""}`;
}

function deltaClass(v) {
  return v > 0 ? "delta-up" : v < 0 ? "delta-down" : "delta-flat";
}

/* Perkiraan periode hingga 85% (regresi linear usage % per periode). */
function periodsToThreshold(points) {
  const xs = [];
  const vals = [];
  points.forEach((p, i) => {
    if (p) {
      xs.push(i);
      vals.push(p.usage_pct);
    }
  });
  if (vals.length < 3) return null;
  const n = xs.length;
  const mx = xs.reduce((a, b) => a + b, 0) / n;
  const my = vals.reduce((a, b) => a + b, 0) / n;
  const slope = xs.reduce((a, x, i) => a + (x - mx) * (vals[i] - my), 0) / xs.reduce((a, x) => a + (x - mx) ** 2, 0);
  const last = vals[vals.length - 1];
  if (last >= THRESHOLD_TARGET) return 0;
  if (!(slope > 0)) return null;
  return Math.ceil((THRESHOLD_TARGET - last) / slope);
}

/* ------------------------------------------------------------ perbandingan -- */

function renderCompare() {
  const c = histState.compare;
  if (!c) return;
  const t = c.total;
  const label = GROUP_LABEL[c.group];
  $("#cmp-title").text(`${c.base.label}  →  ${c.current.label}`);
  if (!t || !t.base || !t.current) {
    $("#cmp-stats").html('<div class="empty-note">Data salah satu periode belum ada untuk filter ini.</div>');
    $("#cmp-table").empty();
    return;
  }
  const tile = (icon, name, value, sub, cls) =>
    `<div class="cmp-tile"><div class="cmp-tile-head"><span class="cmp-icon">${iconSvg(icon)}</span>${esc(name)}</div><div class="cmp-tile-value ${cls}">${value}</div><div class="cmp-tile-sub">${sub}</div></div>`;
  $("#cmp-stats").html([
    tile("📦", "Used capacity", signed(t.used_change_pct, 2, "%"),
      `${fmtNum(t.base.used_tb, 1)} → ${fmtNum(t.current.used_tb, 1)} TB (${signed(t.used_delta_tb, 1, "TB")})`, deltaClass(t.used_change_pct)),
    tile("📊", "Usage", signed(t.usage_delta_pp, 2, "poin"),
      `${fmtNum(t.base.usage_pct, 2)}% → ${fmtNum(t.current.usage_pct, 2)}%`, deltaClass(t.usage_delta_pp)),
    tile("🟢", "Free capacity", signed(t.free_delta_tb, 1, "TB"),
      `${fmtNum(t.base.free_tb, 1)} → ${fmtNum(t.current.free_tb, 1)} TB`, deltaClass(-t.free_delta_tb)),
    tile("🗄️", "Usable (expansion)", signed(t.usable_delta_tb, 1, "TB"),
      `${fmtNum(t.base.usable_tb, 1)} → ${fmtNum(t.current.usable_tb, 1)} TB`, "delta-flat"),
    tile("↕️", `${label} naik / turun`, `${c.counts.naik} ▲ / ${c.counts.turun} ▼`,
      `${c.counts.tetap} tetap${c.counts.baru ? ` · ${c.counts.baru} baru` : ""}${c.counts.hilang ? ` · ${c.counts.hilang} tanpa data` : ""}`, "delta-flat"),
  ].join(""));

  const rows = c.rows
    .slice()
    .sort((x, y) => (y.used_change_pct ?? -1e9) - (x.used_change_pct ?? -1e9))
    .map((r) => {
      const a = r.base, b = r.current;
      if (!a || !b) {
        return `<tr><td><b>${esc(r.label)}</b></td><td colspan="8" class="muted">${r.trend === "baru" ? "Belum ada data di periode pembanding" : "Tidak ada data di periode sekarang"}</td></tr>`;
      }
      const expansion = r.usable_delta_tb ? `<span class="cmp-exp">${signed(r.usable_delta_tb, 1, "TB")}</span>` : "";
      return `<tr>
        <td><b>${esc(r.label)}</b></td>
        <td class="num">${fmtNum(a.used_tb, 1)}</td><td class="num">${fmtNum(b.used_tb, 1)}</td>
        <td class="num ${deltaClass(r.used_delta_tb)}">${signed(r.used_delta_tb, 1, "")}</td>
        <td class="num ${deltaClass(r.used_change_pct)}"><b>${signed(r.used_change_pct, 2, "%")}</b></td>
        <td class="num">${fmtNum(a.usage_pct, 1)}%</td><td class="num">${fmtNum(b.usage_pct, 1)}%</td>
        <td class="num ${deltaClass(r.usage_delta_pp)}">${signed(r.usage_delta_pp, 2, "")}</td>
        <td class="num">${expansion}</td></tr>`;
    })
    .join("");
  $("#cmp-table").html(`<div class="tbl-wrap cmp-table"><table class="modern-table"><thead><tr>
    <th>${esc(label)}</th><th class="num">Used awal (TB)</th><th class="num">Used akhir (TB)</th><th class="num">Δ TB</th>
    <th class="num">Δ %</th><th class="num">Usage awal</th><th class="num">Usage akhir</th><th class="num">Δ poin</th><th class="num">Expansion</th>
    </tr></thead><tbody>${rows}</tbody></table></div>`);
}

function compareParams() {
  const p = histFilterParams();
  if (histState.compareMode === "range") {
    p.mode = "range";
    p.a = $("#cmp-a").val();
    p.b = $("#cmp-b").val();
  } else {
    p.mode = "period";
    p.compare_period = histState.compareMode;
  }
  return p;
}

function loadCompare() {
  const p = compareParams();
  if (p.mode === "range" && (!p.a || !p.b)) return;
  if (histState.group === "appliance" && !histState.selected.length) {
    $("#cmp-stats").html('<div class="empty-note">Pilih appliance di panel kiri (atau "Pilih semua").</div>');
    $("#cmp-table").empty();
    return;
  }
  $.getJSON("/api/capacity/history/compare", p)
    .done((c) => {
      histState.compare = c;
      renderCompare();
    })
    .fail((xhr) => showAlert("error", apiErrorMessage(xhr, "Gagal memuat perbandingan.")));
}

/* ----------------------------------------------------------------- tren -- */

function chartSeries() {
  /* > 8 seri: tampilkan 8 dengan nilai terakhir tertinggi untuk metrik terpilih (tabel tetap semua) */
  const d = histState.data;
  const lastStart = d.buckets.length ? d.buckets[d.buckets.length - 1].start : null;
  const val = (s) => {
    const keys = Object.keys(s.points).sort();
    const p = s.points[lastStart] || s.points[keys[keys.length - 1]];
    return p ? p[histState.metric] : -1;
  };
  const all = d.series.slice();
  if (all.length <= HIST_PALETTE.length) return { shown: all, hidden: 0 };
  const shown = all.sort((a, b) => val(b) - val(a)).slice(0, HIST_PALETTE.length).sort((a, b) => a.key.localeCompare(b.key));
  return { shown, hidden: d.series.length - shown.length };
}

function renderHistoryChart() {
  const d = histState.data;
  const metric = HIST_METRICS[histState.metric];
  if (!d || !d.series.length || !d.buckets.length) {
    $("#hist-chart").html('<div class="empty-note">Tidak ada data untuk filter ini.</div>');
    $("#hist-legend, #hist-chart-note").empty();
    return;
  }
  const { shown, hidden } = chartSeries();
  $("#hist-chart-note").text(hidden ? `Grafik menampilkan ${shown.length} ${GROUP_LABEL[d.group].toLowerCase()} dengan ${metric.label} tertinggi dari ${d.series.length} terpilih; semua ada di tabel.` : "");
  const W = 1000, H = 340, M = { top: 16, right: 24, bottom: 46, left: 58 };
  const iw = W - M.left - M.right, ih = H - M.top - M.bottom;
  const starts = d.buckets.map((b) => b.start);
  const keys = shown.map((s) => s.key);
  const values = [];
  shown.forEach((s) => starts.forEach((b) => s.points[b] && values.push(s.points[b][histState.metric])));
  let lo = histState.metric === "usage_pct" ? 0 : Math.min(...values);
  let hi = Math.max(...values, histState.metric === "usage_pct" ? THRESHOLD_TARGET + 5 : 0);
  if (histState.metric !== "usage_pct") lo = Math.max(0, lo - (hi - lo) * 0.1);
  if (histState.metric === "usage_pct") hi = Math.min(100, Math.max(hi, 50));
  const ticks = niceTicks(lo, hi, 5);
  const y0 = ticks[0], y1 = ticks[ticks.length - 1];
  const x = (i) => M.left + (starts.length === 1 ? iw / 2 : (i * iw) / (starts.length - 1));
  const y = (v) => M.top + ih - ((v - y0) / (y1 - y0)) * ih;

  let svg = `<svg viewBox="0 0 ${W} ${H}" class="hist-svg" role="img" aria-label="Grafik ${esc(metric.label)} ${esc(d.period_label)}">`;
  ticks.forEach((t) => {
    svg += `<line x1="${M.left}" x2="${W - M.right}" y1="${y(t)}" y2="${y(t)}" class="hist-grid"/>`;
    svg += `<text x="${M.left - 8}" y="${y(t) + 4}" class="hist-axis" text-anchor="end">${fmtNum(t, t % 1 ? 1 : 0)}</text>`;
  });
  if (histState.metric === "usage_pct") {
    [[70, STATUS.warning.color, "Warning 70%"], [85, STATUS.critical.color, "Critical 85%"]].forEach(([v, c, label]) => {
      if (v >= y0 && v <= y1) {
        svg += `<line x1="${M.left}" x2="${W - M.right}" y1="${y(v)}" y2="${y(v)}" stroke="${c}" class="hist-threshold"/>`;
        svg += `<text x="${M.left + 6}" y="${y(v) - 5}" class="hist-axis" text-anchor="start">${label}</text>`;
      }
    });
  }
  const every = Math.max(1, Math.ceil(starts.length / 12));
  d.buckets.forEach((b, i) => {
    const lastFits = i === starts.length - 1 && (starts.length - 1) % every >= every / 2;
    if (i % every === 0 || lastFits) {
      svg += `<text x="${x(i)}" y="${H - M.bottom + 20}" class="hist-axis" text-anchor="middle">${esc(b.label)}</text>`;
    }
  });
  shown.forEach((s) => {
    const color = histColor(s.key, keys);
    let path = "";
    let pen = false;
    starts.forEach((b, i) => {
      const p = s.points[b];
      if (!p) {
        pen = false;
        return;
      }
      path += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(p[histState.metric]).toFixed(1)} `;
      pen = true;
    });
    svg += `<path d="${path}" pathLength="1" class="hist-line" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    if (shown.length <= 4) {
      const lastIdx = starts.map((b) => !!s.points[b]).lastIndexOf(true);
      if (lastIdx >= 0) {
        const v = s.points[starts[lastIdx]][histState.metric];
        svg += `<circle class="hist-end" cx="${x(lastIdx)}" cy="${y(v)}" r="4" fill="${color}" stroke="#fff" stroke-width="2"/>`;
      }
    }
  });
  svg += `<line id="hist-cross" class="hist-cross" x1="0" x2="0" y1="${M.top}" y2="${M.top + ih}" style="display:none"/>`;
  svg += `<g id="hist-dots"></g>`;
  svg += `<rect x="${M.left}" y="${M.top}" width="${iw}" height="${ih}" fill="transparent" id="hist-hit"/>`;
  svg += "</svg>";
  $("#hist-chart").html(svg + '<div id="hist-tip" class="hist-tip" style="display:none"></div>');
  $("#hist-legend").html(shown.map((s) => `<span class="hist-leg"><i style="background:${histColor(s.key, keys)}"></i>${esc(s.label)}</span>`).join(""));

  const svgEl = document.querySelector("#hist-chart svg");
  $("#hist-hit")
    .on("mousemove", function (e) {
      const rect = svgEl.getBoundingClientRect();
      const px = ((e.clientX - rect.left) / rect.width) * W;
      const i = Math.max(0, Math.min(starts.length - 1, Math.round(((px - M.left) / iw) * (starts.length - 1))));
      const b = starts[i];
      $("#hist-cross").attr({ x1: x(i), x2: x(i) }).show();
      const rows = shown.filter((s) => s.points[b]).map((s) => ({ s, p: s.points[b] })).sort((a, c) => c.p[histState.metric] - a.p[histState.metric]);
      $("#hist-dots").html(rows.map(({ s, p }) => `<circle cx="${x(i)}" cy="${y(p[histState.metric])}" r="5" fill="${histColor(s.key, keys)}" stroke="#fff" stroke-width="2"/>`).join(""));
      const lines = rows
        .map(
          ({ s, p }) =>
            `<div class="hist-tip-row"><i style="background:${histColor(s.key, keys)}"></i><span>${esc(s.label)}</span><b>${fmtNum(p[histState.metric], metric.decimals)} ${metric.unit}</b></div>
             <div class="hist-tip-sub">used ${fmtNum(p.used_tb, 1)} / ${fmtNum(p.usable_tb, 1)} TB · puncak ${fmtNum(p.peak_pct, 1)}% · ${p.pools} pool · per ${esc(p.as_of)}</div>`
        )
        .join("");
      const tip = $("#hist-tip").html(`<div class="hist-tip-head">${esc(d.buckets[i].label)}</div>${lines}`).show();
      const left = (x(i) / W) * rect.width;
      tip.css({ left: left + 16 + tip.outerWidth() > rect.width ? left - tip.outerWidth() - 16 : left + 16, top: 12 });
    })
    .on("mouseleave", () => {
      $("#hist-cross").hide();
      $("#hist-dots").empty();
      $("#hist-tip").hide();
    });
}

function renderHistoryTable() {
  const d = histState.data;
  const metric = HIST_METRICS[histState.metric];
  if (!d || !d.series.length) {
    $("#hist-table").empty();
    return;
  }
  const starts = d.buckets.map((b) => b.start);
  const unit = { day: "hari", week: "minggu", month: "bulan", quarter: "kuartal", semester: "semester", year: "tahun" }[d.period];
  const shownKeys = chartSeries().shown.map((s) => s.key);
  const head = `<th>${esc(GROUP_LABEL[d.group])}</th><th class="num">Perubahan</th><th class="num">Perkiraan 85%</th>` +
    d.buckets.map((b) => `<th class="num">${esc(b.label)}</th>`).join("");
  const body = d.series
    .map((s) => {
      const pts = starts.map((b) => s.points[b]);
      const vals = pts.filter(Boolean).map((p) => p[histState.metric]);
      const delta = vals.length > 1 ? vals[vals.length - 1] - vals[0] : null;
      const eta = periodsToThreshold(pts);
      const etaText = eta === null ? "tidak naik" : eta === 0 ? "sudah ≥ 85%" : `±${eta} ${unit}`;
      const dot = shownKeys.includes(s.key) ? `<i class="hist-dot" style="background:${histColor(s.key, shownKeys)}"></i>` : '<i class="hist-dot hist-dot-off"></i>';
      const cells = pts.map((p) => `<td class="num">${p ? fmtNum(p[histState.metric], metric.decimals) : ""}</td>`).join("");
      return `<tr><td>${dot}${esc(s.label)}</td><td class="num ${deltaClass(delta)}"><b>${signed(delta, metric.decimals, metric.unit)}</b></td><td class="num">${etaText}</td>${cells}</tr>`;
    })
    .join("");
  $("#hist-table").html(`<div class="tbl-wrap hist-table"><table class="modern-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`);
}

/* ------------------------------------------------------------- appliance -- */

function renderApplianceList() {
  const o = histState.options;
  if (!o) return;
  const q = histState.applianceQuery.toLowerCase();
  const groups = {};
  o.appliances
    .filter((a) => !q || a.name.includes(q) || a.site.toLowerCase().includes(q) || a.pools.some((p) => p.toLowerCase().includes(q)))
    .forEach((a) => (groups[a.master] = groups[a.master] || []).push(a));
  const html = Object.keys(groups)
    .sort()
    .map((m) => {
      const allOn = groups[m].every((a) => histState.selected.includes(a.key));
      return (
        `<div class="hist-app-group"><div class="hist-app-master"><span>${esc(m)}</span>` +
        `<button class="hist-link" data-master="${esc(m)}">${allOn ? "batal semua" : "pilih semua"}</button></div>` +
        groups[m]
          .map((a) => {
            const on = histState.selected.includes(a.key);
            const pools = a.pools.length > 1 ? `<span class="hist-app-pools">${a.pools.length} pool</span>` : "";
            return `<label class="hist-app" title="${esc(a.pools.join(" + "))}"><input type="checkbox" value="${esc(a.key)}" ${on ? "checked" : ""}>${esc(a.name)} ${pools}<span class="muted">${esc(a.site)}</span></label>`;
          })
          .join("") +
        "</div>"
      );
    })
    .join("");
  $("#hist-app-list").html(html || '<div class="empty-note">Tidak ada appliance.</div>');
  $("#hist-app-count").text(`${histState.selected.length}/${o.appliances.length} dipilih`);
}

function histFilterParams() {
  const p = { group: histState.group };
  if (histState.selected.length) p.appliances = histState.selected.join(",");
  return p;
}

function histParams() {
  const p = Object.assign(histFilterParams(), { period: histState.period });
  if ($("#hist-from").val()) p.from = $("#hist-from").val();
  if ($("#hist-to").val()) p.to = $("#hist-to").val();
  return p;
}

function loadHistory() {
  loadCompare();
  if (histState.group === "appliance" && !histState.selected.length) {
    histState.data = null;
    renderHistoryChart();
    renderHistoryTable();
    $("#hist-chart").html('<div class="empty-note">Pilih appliance di panel kiri (atau "Pilih semua").</div>');
    return;
  }
  clearAlert();
  $.getJSON("/api/capacity/history", histParams())
    .done((data) => {
      histState.data = data;
      $("#hist-demo").toggle(!!data.has_demo);
      $("#hist-range").text(`${data.period_label} · ${fmtDateOnly(data.from)} s.d. ${fmtDateOnly(data.to)} · ${data.buckets.length} periode`);
      renderHistoryChart();
      renderHistoryTable();
    })
    .fail((xhr) => showAlert("error", apiErrorMessage(xhr, "Gagal memuat riwayat kapasitas.")));
}

function setSegment(name, value) {
  $(`.hist-seg[data-name="${name}"] button`).removeClass("active");
  $(`.hist-seg[data-name="${name}"] button[data-value="${value}"]`).addClass("active");
}

function loadHistoryOptions() {
  if (histState.options) return $.Deferred().resolve().promise();
  return $.getJSON("/api/capacity/history/options").done((o) => {
    histState.options = o;
    $("#hist-period").html(o.periods.map((p) => `<option value="${p.key}" ${p.key === histState.period ? "selected" : ""}>${esc(p.label)}</option>`).join(""));
    $("#cmp-mode").html(
      o.compare_periods.map((p) => `<option value="${p.key}" ${p.key === histState.compareMode ? "selected" : ""}>${esc(p.label)}</option>`).join("") +
        '<option value="range">Rentang tanggal (A vs B)</option>'
    );
    if (o.first_day) $("#hist-from, #hist-to, #cmp-a, #cmp-b").attr({ min: o.first_day, max: o.last_day });
    if (o.last_day) {
      const b = new Date(o.last_day + "T00:00:00");
      const a = new Date(b);
      a.setFullYear(a.getFullYear() - 1);
      const aIso = `${a.getFullYear()}-${String(a.getMonth() + 1).padStart(2, "0")}-${String(a.getDate()).padStart(2, "0")}`;
      $("#cmp-b").val(o.last_day);
      $("#cmp-a").val(o.first_day && aIso < o.first_day ? o.first_day : aIso);
    }
    renderApplianceList();
  });
}

registerView("history", {
  title: "Historical Capacity",
  subtitle: "Perbandingan & tren kapasitas per site, master, atau appliance",
  globalSearch: false,
  onShow: () => loadHistoryOptions().then(loadHistory),
});

$(function () {
  $("#hist-period").on("change", function () {
    histState.period = $(this).val();
    $("#hist-from, #hist-to").val(""); // rentang default mengikuti periode
    loadHistory();
  });
  $(".hist-seg").on("click", "button", function () {
    const name = $(this).parent().data("name");
    const value = $(this).data("value");
    setSegment(name, value);
    if (name === "group") {
      histState.group = value;
      $("#hist-app-panel").toggleClass("emphasis", value === "appliance");
      loadHistory();
    } else {
      histState.metric = value;
      renderHistoryChart();
      renderHistoryTable();
    }
  });
  $("#hist-apply").on("click", loadHistory);
  $("#cmp-mode").on("change", function () {
    histState.compareMode = $(this).val();
    $("#cmp-range").toggle(histState.compareMode === "range");
    loadCompare();
  });
  $("#cmp-a, #cmp-b").on("change", loadCompare);
  $("#hist-app-search").on("input", function () {
    histState.applianceQuery = $(this).val().toLowerCase();
    renderApplianceList();
  });
  $("#hist-app-list").on("change", "input[type=checkbox]", function () {
    const key = $(this).val();
    histState.selected = this.checked ? histState.selected.concat(key) : histState.selected.filter((k) => k !== key);
    renderApplianceList();
    loadHistory();
  });
  $("#hist-app-list").on("click", ".hist-link", function (e) {
    e.preventDefault();
    const keys = histState.options.appliances.filter((a) => a.master === $(this).data("master")).map((a) => a.key);
    const allOn = keys.every((k) => histState.selected.includes(k));
    histState.selected = allOn ? histState.selected.filter((k) => !keys.includes(k)) : [...new Set(histState.selected.concat(keys))];
    renderApplianceList();
    loadHistory();
  });
  $("#hist-app-all").on("click", () => {
    histState.selected = histState.options.appliances.map((a) => a.key);
    renderApplianceList();
    loadHistory();
  });
  $("#hist-app-clear").on("click", () => {
    histState.selected = [];
    renderApplianceList();
    loadHistory();
  });
  $("#hist-export").on("click", () => {
    window.location = "/api/capacity/history/export?" + $.param(histParams());
  });
});
