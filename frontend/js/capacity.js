/* ATLAS — menu Disk Pool & Tape Library (render dipindah apa adanya dari app.js V4). */

const capacityState = {
  diskPools: [],
  tapeLibrary: [],
  lastUpdated: null,
  tapeLastUpdated: null,
  collectStatus: {},
  dpQuery: "",
  tpQuery: "",
  dpDetailQuery: { BRN: "", BSD: "", TBS: "" },
};

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
  [
    { master: "BRN", elId: "dp-ranking-brn" },
    { master: "BSD", elId: "dp-ranking-bsd" },
    { master: "TBS", elId: "dp-ranking-tbs" },
  ].forEach(({ master, elId }) => {
    const ranked = filtered.filter((r) => r.Master === master).sort((a, b) => b["Usage (%)"] - a["Usage (%)"]);
    $("#" + elId).html(
      ranked.length
        ? ranked.map((r) => barRowSolid(r["Disk Pool Name"], r["Usage (%)"])).join("")
        : '<div class="empty-note">Tidak ada data.</div>'
    );
  });
}

function renderDiskPoolDetailTables(rows) {
  const detailColumns = [
    { key: "Site", label: "Site", type: "text" },
    { key: "Disk Pool Name", label: "Disk Pool Name", type: "text" },
    { key: "Usable (TB)", label: "Usable (TB)", type: "num" },
    { key: "Available (TB)", label: "Available (TB)", type: "num" },
    { key: "Used (TB)", label: "Used (TB)", type: "num" },
    { key: "Usage (%)", label: "Usage (%)", type: "pct" },
  ];
  [
    { master: "BRN", elId: "dp-detail-brn" },
    { master: "BSD", elId: "dp-detail-bsd" },
    { master: "TBS", elId: "dp-detail-tbs" },
  ].forEach(({ master, elId }) => {
    const q = (capacityState.dpDetailQuery[master] || "").toLowerCase();
    const filtered = rows
      .filter((r) => r.Master === master)
      .filter((r) => !q || r.Site.toLowerCase().includes(q) || r["Disk Pool Name"].toLowerCase().includes(q))
      .sort((a, b) => b["Usage (%)"] - a["Usage (%)"]);
    $("#" + elId).html(buildTable(filtered, detailColumns));
  });
}

function renderDiskPoolTab() {
  $("#dp-cutoff").text(fmtCutoff(capacityState.lastUpdated));
  renderDiskPoolStats(capacityState.diskPools);
  renderDiskPoolSummary(capacityState.diskPools);
  renderDiskPoolRanking(capacityState.diskPools, capacityState.dpQuery);
  renderDiskPoolDetailTables(capacityState.diskPools);
}

/* ----------------------------------------------------------- tape library -- */

function renderTapeStats(rows) {
  const totalQty = rows.reduce((a, r) => a + r["Total Tape (Qty)"], 0);
  const usedQty = rows.reduce((a, r) => a + r["Tape Used (Qty)"], 0);
  const rawCap = rows.reduce((a, r) => a + r["Raw Capacity (TB)"], 0);
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
  $("#tp-cutoff").text(fmtCutoff(capacityState.tapeLastUpdated));
  renderTapeStats(capacityState.tapeLibrary);
  renderTapeSummaryChart(capacityState.tapeLibrary);
  renderTapeDetailTable(capacityState.tapeLibrary, capacityState.tpQuery);
}

/* -------------------------------------------- peringatan status collect (baru) -- */

const SOURCE_LABEL = { capacity: "Disk pool", tape: "Tape library" };

function collectWarnings(collectStatus) {
  const lines = [];
  Object.entries(collectStatus || {}).forEach(([source, st]) => {
    const label = SOURCE_LABEL[source] || source;
    if (st.last_attempt_status === "failed") {
      const id = st.last_error_id ? ` (ID: ${st.last_error_id})` : "";
      lines.push(`${label}: pengumpulan terakhir (${fmtDateTime(st.last_attempt_at)}) gagal${id}. Ditampilkan data terakhir yang berhasil.`);
    }
    const failedMasters = Object.keys(st.errors || {});
    if (st.data_status === "partial" && failedMasters.length) {
      lines.push(`${label}: data dari ${failedMasters.join(", ")} tidak berhasil diambil pada pengumpulan ini.`);
    }
  });
  return lines;
}

function renderCapacityHeader() {
  if (!capacityState.lastUpdated) {
    $("#last-updated").text("Belum ada data. Data akan muncul otomatis setelah proses pengumpulan berikutnya selesai.");
  } else {
    $("#last-updated").text("Data terakhir di-generate: " + fmtDateTime(capacityState.lastUpdated));
  }
  const warnings = collectWarnings(capacityState.collectStatus);
  if (warnings.length) showAlert("warning", warnings.join("\n"));
  else clearAlert();
}

/* ---------------------------------------------------------------- data -- */

function loadCapacityData() {
  return $.ajax({ url: "/api/data", dataType: "json", ifModified: false })
    .done((data, _status, xhr) => {
      if (xhr.status === 304 || !data) return; /* versi data sama: tidak perlu render ulang */
      capacityState.diskPools = data.disk_pools || [];
      capacityState.tapeLibrary = data.tape_library || [];
      capacityState.lastUpdated = data.last_updated;
      capacityState.tapeLastUpdated = data.tape_last_updated;
      capacityState.collectStatus = data.collect_status || {};
      renderCapacityHeader();
      renderDiskPoolTab();
      renderTapeTab();
    })
    .fail((xhr) => showAlert("error", apiErrorMessage(xhr, "Gagal memuat data kapasitas.")));
}

/* ------------------------------------------------------------- capture -- */

async function captureCapacityImages() {
  const btn = $("#btn-capture");
  btn.prop("disabled", true);
  const originalView = currentView;
  try {
    const stamp = timestampForFilename();
    if (currentView !== "diskpool") switchView("diskpool");
    const summaryCanvas = await html2canvas(document.getElementById("card-summary-site"), { backgroundColor: "#ffffff", scale: 2 });
    downloadCanvas(summaryCanvas, `capacity-summary-by-site_${stamp}.png`);

    const rankingCanvas = await html2canvas(document.getElementById("ranking-grid-master"), { backgroundColor: "#ffffff", scale: 2 });
    downloadCanvas(rankingCanvas, `capacity-grouping-by-master-server_${stamp}.png`);

    switchView("tape");
    await new Promise((r) => setTimeout(r, 50));
    const tapeWrap = document.querySelector("#tp-detail-table .tbl-wrap");
    if (tapeWrap) {
      const tapeCanvas = await captureWideTableWithTitle("Detail Tape Library", tapeWrap);
      downloadCanvas(tapeCanvas, `detail-tape-library_${stamp}.png`);
    }
    showAlert("success", "3 gambar berhasil disimpan: Capacity Summary by Site, Capacity Grouping by Master Server, & Detail Tape Library.");
  } catch (e) {
    showAlert("error", "Gagal capture gambar: " + e.message);
  } finally {
    switchView(originalView);
    btn.prop("disabled", false);
  }
}

/* --------------------------------------------------- pendaftaran menu -- */

registerView("diskpool", {
  placeholder: "Cari disk pool / site / master...",
  getQuery: () => capacityState.dpQuery,
  onSearch: (val) => {
    capacityState.dpQuery = val;
    renderDiskPoolRanking(capacityState.diskPools, val);
  },
});

registerView("tape", {
  placeholder: "Cari site / tipe tape...",
  getQuery: () => capacityState.tpQuery,
  onSearch: (val) => {
    capacityState.tpQuery = val;
    renderTapeDetailTable(capacityState.tapeLibrary, val);
  },
});

$(function () {
  loadCapacityData();
  setInterval(loadCapacityData, 300000);
  $("#btn-export").on("click", () => {
    window.location = "/api/export";
  });
  $("#btn-capture").on("click", captureCapacityImages);
  $(".dp-detail-search").on("input", function () {
    capacityState.dpDetailQuery[$(this).data("master")] = $(this).val();
    renderDiskPoolDetailTables(capacityState.diskPools);
  });
});
