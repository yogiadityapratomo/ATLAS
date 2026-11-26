/* NetBackup Capacity Report — frontend logic (jQuery, no build step) */

const STATUS = {
  good: { label: "Good", color: "#0ca678", grad: ["#11998e", "#38ef7d"], icon: "✅" },
  warning: { label: "Warning", color: "#e8770d", grad: ["#f7971e", "#ffb347"], icon: "⚠️" },
  critical: { label: "Critical", color: "#d6246e", grad: ["#eb3349", "#f45c43"], icon: "⛔" },
};

/* Card gradient palette — matches the purple/pink/orange dashboard theme */
const THEME = {
  purple: ["#6a3093", "#3f1d5c"],
  pink: ["#e8368f", "#b91d73"],
  orange: ["#ff9966", "#ff5e62"],
};

function usageStatus(pct) {
  if (pct >= 85) return STATUS.critical;
  if (pct >= 70) return STATUS.warning;
  return STATUS.good;
}

function esc(v) {
  return $("<div>").text(v === undefined || v === null ? "" : String(v)).html();
}

function fmtNum(v, decimals) {
  if (v === undefined || v === null || isNaN(v)) return "-";
  return Number(v).toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

let state = {
  diskPools: [],
  tapeLibrary: [],
  lastUpdated: null,
  dpQuery: "",
  tpQuery: "",
  dpDetailQuery: { BRN: "", BSD: "", TBS: "" },
};
let currentView = "diskpool";

/* ---------------------------------------------------------------- table -- */

function buildTable(rows, columns) {
  if (!rows.length) {
    return '<div class="empty-note">Tidak ada data.</div>';
  }
  const thead = columns
    .map((c) => `<th class="${c.type !== "text" ? "num" : ""}">${esc(c.label)}</th>`)
    .join("");
  const body = rows
    .map((row) => {
      const cells = columns
        .map((c) => {
          const v = row[c.key];
          if (c.type === "pct") {
            const s = usageStatus(v);
            return `<td class="num"><span class="pill" style="background:${s.color}17;color:${s.color}">${s.icon} ${fmtNum(v, 2)}%</span></td>`;
          }
          if (c.type === "num") {
            return `<td class="num">${fmtNum(v, c.decimals === undefined ? 2 : c.decimals)}</td>`;
          }
          if (c.type === "tag") {
            return `<td><span class="tag">${esc(v)}</span></td>`;
          }
          return `<td>${esc(v)}</td>`;
        })
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
  return `<div class="tbl-wrap"><table class="modern-table"><thead><tr>${thead}</tr></thead><tbody>${body}</tbody></table></div>`;
}

/* --------------------------------------------------------------- charts -- */

function barRowUsage(label, pct, trackWidthPct, valueText) {
  const s = usageStatus(pct);
  return `
    <div class="bar-row">
      <div class="bar-label">${esc(label)}</div>
      <div class="bar-track" style="width:${trackWidthPct}%">
        <div class="bar-fill solid" style="width:${Math.max(pct, 1.5)}%; background:${s.color}"></div>
      </div>
      <div class="bar-value" style="color:${s.color}">${valueText}</div>
    </div>`;
}

function barRowSolid(label, pct) {
  const s = usageStatus(pct);
  return `
    <div class="bar-row">
      <div class="bar-label">${esc(label)}</div>
      <div class="bar-track">
        <div class="bar-fill solid" style="width:${Math.max(pct, 1.5)}%; background:${s.color}"></div>
      </div>
      <div class="bar-value" style="color:${s.color}">${fmtNum(pct, 1)}%</div>
    </div>`;
}

function chartLegendStatus() {
  return `<div class="chart-legend">
    <span><i style="background:${STATUS.good.color}"></i>${STATUS.good.label} &lt;70%</span>
    <span><i style="background:${STATUS.warning.color}"></i>${STATUS.warning.label} 70–85%</span>
    <span><i style="background:${STATUS.critical.color}"></i>${STATUS.critical.label} ≥85%</span>
  </div>`;
}

/* ------------------------------------------------------------ disk pool -- */

function renderDiskPoolStats(rows) {
  const totalUsable = rows.reduce((a, r) => a + r["Usable (TB)"], 0);
  const totalUsed = rows.reduce((a, r) => a + r["Used (TB)"], 0);
  const totalAvail = rows.reduce((a, r) => a + r["Available (TB)"], 0);
  const pct = totalUsable ? (totalUsed / totalUsable) * 100 : 0;
  const s = usageStatus(pct);
  $("#dp-stats").html([
    statTile("🗄️", "Total Capacity", fmtNum(totalUsable, 2), "TB", THEME.purple[0], THEME.purple[1]),
    statTile("📦", "Used Capacity", fmtNum(totalUsed, 2), "TB", THEME.pink[0], THEME.pink[1]),
    statTile("🟢", "Free Capacity", fmtNum(totalAvail, 2), "TB", THEME.orange[0], THEME.orange[1]),
    statTile(s.icon, "Usage", fmtNum(pct, 2), "%", s.grad[0], s.grad[1]),
  ].join(""));
}

function shadeColor(hex, percent) {
  const n = parseInt(hex.slice(1), 16);
  const r = Math.max(0, Math.min(255, ((n >> 16) & 255) + percent));
  const g = Math.max(0, Math.min(255, ((n >> 8) & 255) + percent));
  const b = Math.max(0, Math.min(255, (n & 255) + percent));
  return `#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)}`;
}

function statTile(icon, label, value, unit, accent1, accent2) {
  const a2 = accent2 || shadeColor(accent1, -35);
  return `<div class="stat-tile" style="--accent-1:${accent1};--accent-2:${a2}">
      <div class="stat-icon">${icon}</div>
      <div class="stat-label">${esc(label)}</div>
      <div class="stat-value">${value}<span class="unit">${esc(unit)}</span></div>
    </div>`;
}

function diskPoolSummaryBySite(rows) {
  const grp = {};
  rows.forEach((r) => {
    if (!grp[r.Site]) grp[r.Site] = { Site: r.Site, total: 0, used: 0, free: 0 };
    grp[r.Site].total += r["Usable (TB)"];
    grp[r.Site].used += r["Used (TB)"];
    grp[r.Site].free += r["Available (TB)"];
  });
  return Object.values(grp)
    .map((g) => ({
      Site: g.Site,
      "Total Capacity (TB)": g.total,
      "Used Capacity (TB)": g.used,
      "Free Capacity (TB)": g.free,
      "Usage (%)": g.total ? (g.used / g.total) * 100 : 0,
    }))
    .sort((a, b) => a.Site.localeCompare(b.Site));
}

function renderDiskPoolSummary(rows) {
  const summary = diskPoolSummaryBySite(rows);
  $("#dp-summary-table").html(
    buildTable(summary, [
      { key: "Site", label: "Site", type: "text" },
      { key: "Total Capacity (TB)", label: "Total Capacity (TB)", type: "num" },
      { key: "Used Capacity (TB)", label: "Used Capacity (TB)", type: "num" },
      { key: "Free Capacity (TB)", label: "Free Capacity (TB)", type: "num" },
      { key: "Usage (%)", label: "Usage (%)", type: "pct" },
    ])
  );
  const maxTotal = Math.max(...summary.map((s) => s["Total Capacity (TB)"]), 1);
  const bars = summary
    .map((s) => {
      const trackWidthPct = Math.max((s["Total Capacity (TB)"] / maxTotal) * 100, 2);
      return barRowUsage(s.Site, s["Usage (%)"], trackWidthPct, `${fmtNum(s["Usage (%)"], 1)}%`);
    })
    .join("");
  $("#dp-summary-chart").html(chartLegendStatus() + (bars || '<div class="empty-note">Tidak ada data.</div>'));
}

function renderDiskPoolRanking(rows, query) {
  const q = (query || "").toLowerCase();
  const filtered = rows.filter(
    (r) =>
      !q ||
      r.Site.toLowerCase().includes(q) ||
      r.Master.toLowerCase().includes(q) ||
      r["Disk Pool Name"].toLowerCase().includes(q)
  );
  const rankingTargets = [
    { master: "BRN", elId: "dp-ranking-brn" },
    { master: "BSD", elId: "dp-ranking-bsd" },
    { master: "TBS", elId: "dp-ranking-tbs" },
  ];
  rankingTargets.forEach(({ master, elId }) => {
    const ranked = filtered.filter((r) => r.Master === master).sort((a, b) => b["Usage (%)"] - a["Usage (%)"]);
    $("#" + elId).html(
      ranked.length
        ? ranked.map((r) => barRowSolid(r["Disk Pool Name"], r["Usage (%)"])).join("")
        : '<div class="empty-note">Tidak ada data.</div>'
    );
  });
}

function renderDiskPoolDetailTables(rows) {
  const detailTargets = [
    { master: "BRN", elId: "dp-detail-brn" },
    { master: "BSD", elId: "dp-detail-bsd" },
    { master: "TBS", elId: "dp-detail-tbs" },
  ];
  const detailColumns = [
    { key: "Site", label: "Site", type: "text" },
    { key: "Disk Pool Name", label: "Disk Pool Name", type: "text" },
    { key: "Usable (TB)", label: "Usable (TB)", type: "num" },
    { key: "Available (TB)", label: "Available (TB)", type: "num" },
    { key: "Used (TB)", label: "Used (TB)", type: "num" },
    { key: "Usage (%)", label: "Usage (%)", type: "pct" },
  ];
  detailTargets.forEach(({ master, elId }) => {
    const q = (state.dpDetailQuery[master] || "").toLowerCase();
    const filtered = rows
      .filter((r) => r.Master === master)
      .filter((r) => !q || r.Site.toLowerCase().includes(q) || r["Disk Pool Name"].toLowerCase().includes(q))
      .sort((a, b) => b["Usage (%)"] - a["Usage (%)"]);
    $("#" + elId).html(buildTable(filtered, detailColumns));
  });
}

function renderDiskPoolTab() {
  $("#dp-cutoff").text(fmtCutoff(state.lastUpdated));
  renderDiskPoolStats(state.diskPools);
  renderDiskPoolSummary(state.diskPools);
  renderDiskPoolRanking(state.diskPools, state.dpQuery);
  renderDiskPoolDetailTables(state.diskPools);
}

/* ----------------------------------------------------------- tape library -- */

function renderTapeStats(rows) {
  const totalQty = rows.reduce((a, r) => a + r["Total Tape (Qty)"], 0);
  const usedQty = rows.reduce((a, r) => a + r["Tape Used (Qty)"], 0);
  const rawCap = rows.reduce((a, r) => a + r["Raw Capacity (TB)"], 0);
  const usedCap = rows.reduce((a, r) => a + r["Used Capacity (TB)"], 0);
  const pct = totalQty ? (usedQty / totalQty) * 100 : 0;
  const s = usageStatus(pct);
  $("#tp-stats").html([
    statTile("💾", "Total Tape", fmtNum(totalQty, 0), "pcs", THEME.purple[0], THEME.purple[1]),
    statTile("📦", "Tape Used", fmtNum(usedQty, 0), "pcs", THEME.pink[0], THEME.pink[1]),
    statTile("🗄️", "Raw Capacity", fmtNum(rawCap, 2), "TB", THEME.orange[0], THEME.orange[1]),
    statTile(s.icon, "Tape Used", fmtNum(pct, 2), "%", s.grad[0], s.grad[1]),
  ].join(""));
}

function renderTapeSummaryChart(rows) {
  if (!rows.length) {
    $("#tp-summary-chart").html('<div class="empty-note">Tidak ada data.</div>');
    return;
  }
  const maxTotal = Math.max(...rows.map((r) => r["Total Tape (Qty)"]), 1);
  const bars = rows
    .map((r) => {
      const total = r["Total Tape (Qty)"];
      const pct = total ? (r["Tape Used (Qty)"] / total) * 100 : 0;
      const trackWidthPct = Math.max((total / maxTotal) * 100, 2);
      return barRowUsage(`${r.Site} — ${r["Type Tape"]}`, pct, trackWidthPct, `${total} pcs`);
    })
    .join("");
  $("#tp-summary-chart").html(chartLegendStatus() + bars);
}

function renderTapeDetailTable(rows, query) {
  const q = (query || "").toLowerCase();
  const filtered = rows.filter(
    (r) => !q || r.Site.toLowerCase().includes(q) || r["Type Tape"].toLowerCase().includes(q) || r["Storage Name"].toLowerCase().includes(q)
  );
  const sorted = [...filtered].sort((a, b) => a.Site.localeCompare(b.Site) || a["Type Tape"].localeCompare(b["Type Tape"]));
  const numbered = sorted.map((r, i) => ({ ...r, No: i + 1 }));
  $("#tp-detail-table").html(
    buildTable(numbered, [
      { key: "No", label: "No", type: "num", decimals: 0 },
      { key: "Site", label: "Site", type: "text" },
      { key: "IP", label: "IP", type: "text" },
      { key: "Brand", label: "Brand", type: "tag" },
      { key: "Type", label: "Type", type: "text" },
      { key: "Model", label: "Model", type: "tag" },
      { key: "Serial Number", label: "Serial Number", type: "text" },
      { key: "Storage Name", label: "Storage Name", type: "text" },
      { key: "Domain", label: "Domain", type: "tag" },
      { key: "Type Tape", label: "Type Tape", type: "tag" },
      { key: "Total Tape (Qty)", label: "Total Tape (Qty)", type: "num", decimals: 0 },
      { key: "Tape Used (Qty)", label: "Tape Used (Qty)", type: "num", decimals: 0 },
      { key: "Tape Free (Qty)", label: "Tape Free (Qty)", type: "num", decimals: 0 },
      { key: "Raw Capacity (TB)", label: "Raw Capacity (TB)", type: "num" },
      { key: "Used Capacity (TB)", label: "Used Capacity (TB)", type: "num" },
      { key: "Tape Used %", label: "Tape Used %", type: "pct" },
      { key: "Tape Free %", label: "Tape Free %", type: "num" },
    ])
  );
}

function renderTapeTab() {
  $("#tp-cutoff").text(fmtCutoff(state.tapeLastUpdated));
  renderTapeStats(state.tapeLibrary);
  renderTapeSummaryChart(state.tapeLibrary);
  renderTapeDetailTable(state.tapeLibrary, state.tpQuery);
}

/* -------------------------------------------------------------- lifecycle -- */

function renderLastUpdated() {
  if (!state.lastUpdated) {
    $("#last-updated").text("Belum ada data. Data akan muncul otomatis setelah proses pengumpulan berikutnya selesai.");
    return;
  }
  const d = new Date(state.lastUpdated);
  $("#last-updated").text("Data terakhir di-generate: " + d.toLocaleString("id-ID", { dateStyle: "long", timeStyle: "medium" }));
}

function fmtCutoff(iso) {
  if (!iso) return "Belum ada data.";
  const d = new Date(iso);
  return "Data per " + d.toLocaleString("id-ID", { dateStyle: "long", timeStyle: "medium" });
}

function renderAll() {
  renderLastUpdated();
  renderDiskPoolTab();
  renderTapeTab();
}

function showAlert(type, message) {
  const cls = type === "error" ? "alert-error" : "alert-success";
  $("#alert-box").html(`<div class="alert ${cls}">${esc(message)}</div>`);
}

function clearAlert() {
  $("#alert-box").empty();
}

function loadData() {
  return $.getJSON("/api/data").done((data) => {
    state.diskPools = data.disk_pools || [];
    state.tapeLibrary = data.tape_library || [];
    state.lastUpdated = data.last_updated;
    state.tapeLastUpdated = data.tape_last_updated;
    renderAll();
  });
}


const SEARCH_PLACEHOLDER = {
  diskpool: "Cari disk pool / site / master...",
  tape: "Cari site / tipe tape...",
};

function switchView(view) {
  currentView = view;
  $(".side-btn").removeClass("active");
  $(`.side-btn[data-view="${view}"]`).addClass("active");
  $(".view").removeClass("active");
  $("#view-" + view).addClass("active");
  $("#global-search")
    .attr("placeholder", SEARCH_PLACEHOLDER[view])
    .val(view === "diskpool" ? state.dpQuery : state.tpQuery);
}

function downloadCanvas(canvas, filename) {
  const link = document.createElement("a");
  link.download = filename;
  link.href = canvas.toDataURL("image/png");
  link.click();
}

function timestampForFilename() {
  const p = (n) => String(n).padStart(2, "0");
  const d = new Date();
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}`;
}

/* Capture a horizontally-scrollable table wrapper (e.g. .tbl-wrap) at its true
   full content width instead of the clipped/scrolled visible width. Plain
   html2canvas(wrapEl) only grabs what's currently visible through the
   overflow:auto viewport; forcing a wider simulated browser window
   (windowWidth) lets the wrapper lay out at its natural full width so nothing
   past the scroll boundary gets cut off. The title is drawn separately with
   the Canvas API (simpler than compositing a second html2canvas capture with
   matching padding) and stacked above the table on the output canvas. */
async function captureWideTableWithTitle(titleText, wrapEl) {
  const chromeWidth = window.innerWidth - wrapEl.clientWidth;
  const desiredWrapWidth = wrapEl.scrollWidth + 16;
  const windowWidth = desiredWrapWidth + chromeWidth;
  const tableCanvas = await html2canvas(wrapEl, {
    backgroundColor: "#ffffff",
    scale: 2,
    width: desiredWrapWidth,
    windowWidth,
  });

  const pad = 40;
  const titleH = 64;
  const out = document.createElement("canvas");
  out.width = tableCanvas.width + pad * 2;
  out.height = titleH + tableCanvas.height + pad;
  const ctx = out.getContext("2d");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.fillStyle = "#14151a";
  ctx.font = "bold 38px system-ui, -apple-system, 'Segoe UI', sans-serif";
  ctx.textBaseline = "top";
  ctx.fillText(titleText, pad, pad * 0.5);
  ctx.drawImage(tableCanvas, pad, titleH + 8);
  return out;
}

async function captureCapacityImages() {
  const btn = $("#btn-capture");
  btn.prop("disabled", true);
  const originalView = currentView;
  try {
    const stamp = timestampForFilename();

    if (currentView !== "diskpool") switchView("diskpool");
    const summaryCanvas = await html2canvas(document.getElementById("card-summary-site"), {
      backgroundColor: "#ffffff",
      scale: 2,
    });
    downloadCanvas(summaryCanvas, `capacity-summary-by-site_${stamp}.png`);

    const rankingCanvas = await html2canvas(document.getElementById("ranking-grid-master"), {
      backgroundColor: "#ffffff",
      scale: 2,
    });
    downloadCanvas(rankingCanvas, `capacity-grouping-by-master-server_${stamp}.png`);

    switchView("tape");
    await new Promise((r) => setTimeout(r, 50));
    const tapeWrap = document.querySelector("#tp-detail-table .tbl-wrap");
    if (tapeWrap) {
      const tapeCanvas = await captureWideTableWithTitle("Detail Tape Library", tapeWrap);
      downloadCanvas(tapeCanvas, `detail-tape-library_${stamp}.png`);
    }

    showAlert(
      "success",
      "3 gambar berhasil disimpan: Capacity Summary by Site, Capacity Grouping by Master Server, & Detail Tape Library."
    );
  } catch (e) {
    showAlert("error", "Gagal capture gambar: " + e.message);
  } finally {
    switchView(originalView);
    btn.prop("disabled", false);
  }
}

$(function () {
  loadData();
  setInterval(loadData, 300000);

  $("#btn-export").on("click", () => {
    window.location = "/api/export";
  });
  $("#btn-capture").on("click", captureCapacityImages);

  $(".side-btn").on("click", function () {
    switchView($(this).data("view"));
  });

  $("#global-search").on("input", function () {
    const val = $(this).val();
    if (currentView === "diskpool") {
      state.dpQuery = val;
      renderDiskPoolRanking(state.diskPools, val);
    } else {
      state.tpQuery = val;
      renderTapeDetailTable(state.tapeLibrary, val);
    }
  });

  $(".dp-detail-search").on("input", function () {
    const master = $(this).data("master");
    state.dpDetailQuery[master] = $(this).val();
    renderDiskPoolDetailTables(state.diskPools);
  });
});
