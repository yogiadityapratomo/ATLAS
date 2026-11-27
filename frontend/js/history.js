/* ATLAS — menu Historical Capacity: tren disk pool per hari/minggu/bulan/kuartal/semester/tahun.
   Grafik: SVG tanpa library (server tanpa internet). Aturan: satu sumbu Y, maks 8 garis, warna mengikuti
   entitas (tidak berubah saat filter diganti), legend selalu ada, tooltip crosshair, tabel data. */

const HIST_PALETTE = ["#257de0", "#f47230", "#00b894", "#f2a600", "#ee7fac", "#008a17", "#6a4ce2", "#ec4647"];
const HIST_METRICS = {
  usage_pct: { label: "Usage (%)", unit: "%", decimals: 1 },
  used_tb: { label: "Used (TB)", unit: "TB", decimals: 1 },
  free_tb: { label: "Free (TB)", unit: "TB", decimals: 1 },
};
const THRESHOLD_TARGET = 85; // batas "Critical" dashboard

const histState = {
  options: null,
  data: null,
  period: "month",
  group: "site",
  metric: "usage_pct",
  selected: [], // appliance keys "MASTER/pool"
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

/* Perkiraan periode hingga 85% (regresi linear usage % per periode). Hanya untuk metrik usage. */
function periodsToThreshold(points) {
  const ys = points.map((p) => (p ? p.usage_pct : null));
  const xs = [];
  const vals = [];
  ys.forEach((y, i) => {
    if (y !== null) {
      xs.push(i);
      vals.push(y);
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

function renderHistoryChart() {
  const d = histState.data;
  const metric = HIST_METRICS[histState.metric];
  if (!d || !d.series.length || !d.buckets.length) {
    $("#hist-chart").html('<div class="empty-note">Tidak ada data untuk filter ini.</div>');
    $("#hist-legend").empty();
    return;
  }
  const W = 1000, H = 340, M = { top: 16, right: 24, bottom: 46, left: 58 };
  const iw = W - M.left - M.right, ih = H - M.top - M.bottom;
  const starts = d.buckets.map((b) => b.start);
  const keys = d.series.map((s) => s.key);
  const values = [];
  d.series.forEach((s) => starts.forEach((b) => s.points[b] && values.push(s.points[b][histState.metric])));
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
  d.series.forEach((s) => {
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
    svg += `<path d="${path}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    if (d.series.length <= 4) {
      const lastIdx = starts.map((b) => !!s.points[b]).lastIndexOf(true);
      if (lastIdx >= 0) {
        const v = s.points[starts[lastIdx]][histState.metric];
        svg += `<circle cx="${x(lastIdx)}" cy="${y(v)}" r="4" fill="${color}" stroke="#fff" stroke-width="2"/>`;
      }
    }
  });
  svg += `<line id="hist-cross" class="hist-cross" x1="0" x2="0" y1="${M.top}" y2="${M.top + ih}" style="display:none"/>`;
  svg += `<g id="hist-dots"></g>`;
  svg += `<rect x="${M.left}" y="${M.top}" width="${iw}" height="${ih}" fill="transparent" id="hist-hit"/>`;
  svg += "</svg>";
  $("#hist-chart").html(svg + '<div id="hist-tip" class="hist-tip" style="display:none"></div>');

  $("#hist-legend").html(
    d.series
      .map((s) => `<span class="hist-leg"><i style="background:${histColor(s.key, keys)}"></i>${esc(s.label)}</span>`)
      .join("")
  );

  const svgEl = document.querySelector("#hist-chart svg");
  $("#hist-hit")
    .on("mousemove", function (e) {
      const rect = svgEl.getBoundingClientRect();
      const px = ((e.clientX - rect.left) / rect.width) * W;
      const i = Math.max(0, Math.min(starts.length - 1, Math.round(((px - M.left) / iw) * (starts.length - 1))));
      const b = starts[i];
      $("#hist-cross").attr({ x1: x(i), x2: x(i) }).show();
      const rows = d.series
        .filter((s) => s.points[b])
        .map((s) => ({ s, p: s.points[b] }))
        .sort((a, c) => c.p[histState.metric] - a.p[histState.metric]);
      $("#hist-dots").html(
        rows.map(({ s, p }) => `<circle cx="${x(i)}" cy="${y(p[histState.metric])}" r="5" fill="${histColor(s.key, keys)}" stroke="#fff" stroke-width="2"/>`).join("")
      );
      const lines = rows
        .map(
          ({ s, p }) =>
            `<div class="hist-tip-row"><i style="background:${histColor(s.key, keys)}"></i><span>${esc(s.label)}</span><b>${fmtNum(p[histState.metric], metric.decimals)} ${metric.unit}</b></div>
             <div class="hist-tip-sub">used ${fmtNum(p.used_tb, 1)} / ${fmtNum(p.usable_tb, 1)} TB · puncak ${fmtNum(p.peak_pct, 1)}% · per ${esc(p.as_of)}</div>`
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
  const head = `<th>${esc({ site: "Site", master: "Master", appliance: "Appliance" }[d.group])}</th>` +
    `<th class="num">Perubahan</th><th class="num">Perkiraan 85%</th>` +
    d.buckets.map((b) => `<th class="num">${esc(b.label)}</th>`).join("");
  const body = d.series
    .map((s) => {
      const pts = starts.map((b) => s.points[b]);
      const vals = pts.filter(Boolean).map((p) => p[histState.metric]);
      const delta = vals.length > 1 ? vals[vals.length - 1] - vals[0] : null;
      const eta = periodsToThreshold(pts);
      const unit = { day: "hari", week: "minggu", month: "bulan", quarter: "kuartal", semester: "semester", year: "tahun" }[d.period];
      const etaText = eta === null ? "tidak naik" : eta === 0 ? "sudah ≥ 85%" : `±${eta} ${unit}`;
      const cells = pts.map((p) => `<td class="num">${p ? fmtNum(p[histState.metric], metric.decimals) : ""}</td>`).join("");
      const deltaText = delta === null ? "" : `${delta > 0 ? "+" : ""}${fmtNum(delta, metric.decimals)} ${metric.unit}`;
      return `<tr><td><i class="hist-dot" style="background:${histColor(s.key, d.series.map((x) => x.key))}"></i>${esc(s.label)}</td><td class="num"><b>${deltaText}</b></td><td class="num">${etaText}</td>${cells}</tr>`;
    })
    .join("");
  $("#hist-table").html(`<div class="tbl-wrap hist-table"><table class="modern-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`);
}

function renderApplianceList() {
  const o = histState.options;
  if (!o) return;
  const q = histState.applianceQuery.toLowerCase();
  const max = o.max_series;
  const full = histState.selected.length >= max;
  const groups = {};
  o.appliances
    .filter((a) => !q || a.name.toLowerCase().includes(q) || a.site.toLowerCase().includes(q))
    .forEach((a) => (groups[a.master] = groups[a.master] || []).push(a));
  const html = Object.keys(groups)
    .sort()
    .map(
      (m) =>
        `<div class="hist-app-group"><div class="hist-app-master">${esc(m)}</div>` +
        groups[m]
          .map((a) => {
            const on = histState.selected.includes(a.key);
            return `<label class="hist-app ${!on && full ? "disabled" : ""}"><input type="checkbox" value="${esc(a.key)}" ${on ? "checked" : ""} ${!on && full ? "disabled" : ""}>${esc(a.name)} <span class="muted">${esc(a.site)}</span></label>`;
          })
          .join("") +
        "</div>"
    )
    .join("");
  $("#hist-app-list").html(html || '<div class="empty-note">Tidak ada appliance.</div>');
  $("#hist-app-count").text(`${histState.selected.length}/${max} dipilih`);
}

function histParams() {
  const p = { period: histState.period, group: histState.group };
  if ($("#hist-from").val()) p.from = $("#hist-from").val();
  if ($("#hist-to").val()) p.to = $("#hist-to").val();
  if (histState.selected.length) p.appliances = histState.selected.join(",");
  return p;
}

function loadHistory() {
  if (histState.group === "appliance" && !histState.selected.length) {
    histState.data = null;
    renderHistoryChart();
    renderHistoryTable();
    $("#hist-chart").html('<div class="empty-note">Pilih 1–8 appliance di panel kiri.</div>');
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

function fmtDateOnly(iso) {
  return new Date(iso + "T00:00:00").toLocaleDateString("id-ID", { day: "numeric", month: "short", year: "numeric" });
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
    if (o.first_day) $("#hist-from, #hist-to").attr({ min: o.first_day, max: o.last_day });
    renderApplianceList();
  });
}

registerView("history", {
  title: "Historical Capacity",
  subtitle: "Tren kapasitas disk pool per hari, minggu, bulan, kuartal, semester, dan tahun",
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
  $("#hist-app-search").on("input", function () {
    histState.applianceQuery = $(this).val();
    renderApplianceList();
  });
  $("#hist-app-list").on("change", "input[type=checkbox]", function () {
    const key = $(this).val();
    histState.selected = this.checked ? histState.selected.concat(key) : histState.selected.filter((k) => k !== key);
    renderApplianceList();
    if (histState.group === "appliance" || !this.checked || histState.selected.length) loadHistory();
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
