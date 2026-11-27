/* ATLAS — menu Audit Log: semua event (web, DB, job, keamanan, sistem), detail per request_id. */

const auditState = { items: [], nextCursor: null, filters: {}, timer: null, active: false };
const LEVEL_COLOR = { debug: "#8a8f98", info: "#0ca678", warning: "#e8770d", error: "#d6246e", critical: "#a3123f" };

function auditFilters() {
  const id = ($("#aud-id").val() || "").trim();
  const f = {
    range: $("#aud-range").val(),
    category: $("#aud-category").val(),
    severity: $("#aud-severity").val(),
    component: $("#aud-component").val(),
    q: $("#aud-q").val().trim(),
  };
  if (/^ERR-/i.test(id)) f.error_id = id;
  else if (id) f.request_id = id;
  Object.keys(f).forEach((k) => !f[k] && delete f[k]);
  return f;
}

function levelBadge(sev) {
  const c = LEVEL_COLOR[sev] || "#888";
  return `<span class="pill" style="background:${c}17;color:${c}">${esc(sev)}</span>`;
}

function fmtTime(iso) {
  return new Date(iso).toLocaleString("id-ID", { dateStyle: "short", timeStyle: "medium" });
}

function renderAuditTable() {
  if (!auditState.items.length) {
    $("#aud-table").html('<div class="empty-note">Tidak ada event untuk filter ini.</div>');
  } else {
    const rows = auditState.items
      .map(
        (e, i) => `<tr data-idx="${i}" class="aud-row">
          <td>${esc(fmtTime(e.occurred_at))}</td><td>${levelBadge(e.severity)}</td>
          <td><span class="tag">${esc(e.category)}</span></td><td>${esc(e.component)}</td>
          <td><code>${esc(e.event_type)}</code></td>
          <td class="aud-msg">${esc(e.message)}${e.error_id ? ` <b class="aud-err">${esc(e.error_id)}</b>` : ""}</td>
          <td class="num">${e.duration_ms === null ? "" : fmtNum(e.duration_ms, 0) + " ms"}</td></tr>`
      )
      .join("");
    $("#aud-table").html(`<div class="tbl-wrap aud-table"><table class="modern-table"><thead><tr>
      <th>Waktu</th><th>Level</th><th>Kategori</th><th>Komponen</th><th>Event</th><th>Pesan</th><th class="num">Durasi</th>
      </tr></thead><tbody>${rows}</tbody></table></div>`);
  }
  $("#aud-more").toggle(!!auditState.nextCursor);
  $("#aud-count").text(`${fmtNum(auditState.items.length, 0)} event ditampilkan${auditState.nextCursor ? " (masih ada lagi)" : ""}`);
}

function loadAuditEvents(append) {
  const params = Object.assign({}, auditState.filters, { limit: 100 });
  if (append && auditState.nextCursor) params.cursor = auditState.nextCursor;
  return $.getJSON("/api/audit/events", params)
    .done((data) => {
      auditState.items = append ? auditState.items.concat(data.items) : data.items;
      auditState.nextCursor = data.next_cursor;
      renderAuditTable();
    })
    .fail((xhr) => showAlert("error", apiErrorMessage(xhr, "Gagal memuat audit log.")));
}

function loadAuditSummary() {
  return $.getJSON("/api/audit/summary", { range: "24h" }).done((s) => {
    const tile = (icon, label, value, filter, danger) =>
      `<div class="aud-tile" data-filter='${JSON.stringify(filter)}'>${statTile(icon, label, fmtNum(value, 0), "",
        danger && value ? STATUS.critical.grad[0] : THEME.purple[0], danger && value ? STATUS.critical.grad[1] : THEME.purple[1])}</div>`;
    $("#aud-stats").html([
      tile("📜", "Event 24 jam", s.events, {}, false),
      tile("⛔", "Error 24 jam", s.errors, { severity: "error" }, true),
      tile("⚙️", "Job gagal 24 jam", s.job_failed, { q: "", event: "job_failed" }, true),
      tile("🔌", "Koneksi DB gagal 24 jam", s.db_connect_failed, { category: "db", severity: "error" }, true),
    ].join(""));
    const current = $("#aud-component").val();
    $("#aud-component").html('<option value="">Semua komponen</option>' + s.components.map((c) => `<option>${esc(c)}</option>`).join(""));
    $("#aud-component").val(current);
  });
}

function applyAuditFilters() {
  auditState.filters = auditFilters();
  if (auditState.eventType) auditState.filters.event_type = auditState.eventType;
  clearAlert();
  loadAuditEvents(false);
}

function showAuditDetail(e) {
  const related = e.request_id
    ? `<h4>Event lain dengan request ID yang sama</h4><div id="aud-related" class="muted">Memuat...</div>`
    : "";
  $("#aud-detail-body").html(`
    <table class="aud-kv">
      <tr><th>Waktu</th><td>${esc(fmtDateTime(e.occurred_at))}</td></tr>
      <tr><th>Event</th><td>${levelBadge(e.severity)} <code>${esc(e.category)}/${esc(e.event_type)}</code></td></tr>
      <tr><th>Komponen</th><td>${esc(e.component)} · ${esc(e.host || "")} · pid ${esc(e.pid || "-")} · v${esc(e.app_version || "-")}</td></tr>
      <tr><th>Actor</th><td>${esc(e.actor || "-")}</td></tr>
      <tr><th>Request ID</th><td><code>${esc(e.request_id || "-")}</code></td></tr>
      <tr><th>Error ID</th><td><b class="aud-err">${esc(e.error_id || "-")}</b></td></tr>
      <tr><th>Pesan</th><td>${esc(e.message)}</td></tr>
    </table>
    <h4>Detail</h4><pre class="aud-json">${esc(JSON.stringify(e.details, null, 2))}</pre>${related}`);
  $("#aud-detail").addClass("open");
  if (e.request_id) {
    $.getJSON("/api/audit/events", { request_id: e.request_id, limit: 200 }).done((d) => {
      $("#aud-related").html(
        d.items
          .slice()
          .reverse()
          .map((x) => `<div class="aud-rel">${esc(fmtTime(x.occurred_at))} ${levelBadge(x.severity)} <code>${esc(x.event_type)}</code> ${esc(x.message)}</div>`)
          .join("") || "Tidak ada."
      );
    });
  }
}

function startAuditRefresh() {
  stopAuditRefresh();
  auditState.timer = setInterval(() => {
    if (auditState.active && !auditState.nextCursor) {
      loadAuditSummary();
      loadAuditEvents(false);
    }
  }, 30000);
}

function stopAuditRefresh() {
  if (auditState.timer) clearInterval(auditState.timer);
  auditState.timer = null;
}

registerView("audit", {
  title: "Audit Log",
  subtitle: "Semua kejadian ATLAS: akses web, koneksi database, job, keamanan, dan sistem",
  globalSearch: false,
  onShow: () => {
    auditState.active = true;
    loadAuditSummary();
    applyAuditFilters();
    startAuditRefresh();
  },
});

$(function () {
  $(".side-btn").on("click", function () {
    if ($(this).data("view") !== "audit") {
      auditState.active = false;
      stopAuditRefresh();
    }
  });
  $("#aud-apply").on("click", () => {
    auditState.eventType = null;
    applyAuditFilters();
  });
  $("#aud-q, #aud-id").on("keydown", (e) => {
    if (e.key === "Enter") applyAuditFilters();
  });
  $("#aud-range, #aud-category, #aud-severity, #aud-component").on("change", applyAuditFilters);
  $("#aud-more").on("click", () => loadAuditEvents(true));
  $("#aud-csv").on("click", () => {
    window.location = "/api/audit/export?" + $.param(auditFilters());
  });
  $("#aud-stats").on("click", ".aud-tile", function () {
    const f = $(this).data("filter");
    $("#aud-range").val("24h");
    $("#aud-category").val(f.category || "");
    $("#aud-severity").val(f.severity || "");
    auditState.eventType = f.event || null;
    applyAuditFilters();
  });
  $("#aud-table").on("click", ".aud-row", function () {
    showAuditDetail(auditState.items[$(this).data("idx")]);
  });
  $("#aud-detail-close, #aud-detail").on("click", function (e) {
    if (e.target === this) $("#aud-detail").removeClass("open");
  });
});
