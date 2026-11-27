/* ATLAS — menu Backup Inventory: cari konfigurasi backup per hostname (sebagian) atau per aplikasi (CMDB). */

const invState = {
  mode: "hostname",
  appExact: false,
  result: null,
  lastParams: null,
  filtersLoaded: false,
  tableQuery: "",
};

const INV_STATUS_CLASS = { not_found: "row-not-found", no_backup: "row-no-backup" };

function invParams() {
  const p = { master: $("#inv-master").val() || "", policy_type: $("#inv-ptype").val() || "" };
  if (invState.mode === "hostname") p.hostnames = $("#inv-hostnames").val();
  else {
    p.app = $("#inv-app").val();
    if (invState.appExact) p.app_exact = "true";
  }
  return p;
}

function invTable(rows, columns) {
  if (!rows.length) return '<div class="empty-note">Tidak ada data.</div>';
  const head = columns.map((c) => `<th>${esc(c.label)}</th>`).join("");
  const body = rows
    .map((r) => {
      const cells = columns
        .map((c) => {
          const v = r[c.key];
          if (c.key === "client_host") return `<td class="sticky-col"><b>${esc(v)}</b></td>`;
          if (c.key === "policy_type" || c.key === "master_server") return `<td>${v ? `<span class="tag">${esc(v)}</span>` : ""}</td>`;
          return `<td>${esc(v)}</td>`;
        })
        .join("");
      return `<tr class="${INV_STATUS_CLASS[r.status] || ""}">${cells}</tr>`;
    })
    .join("");
  return `<div class="tbl-wrap inv-table"><table class="modern-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function invAllRows() {
  const r = invState.result;
  if (!r) return [];
  return r.items.concat(r.no_backup_items, r.not_found_items);
}

function renderInventoryResult() {
  const r = invState.result;
  if (!r) return;
  const rows = invAllRows();
  const hosts = new Set(r.items.map((x) => x.client_host)).size;
  const policies = new Set(r.items.map((x) => x.master_server + "|" + x.policy_name)).size;
  const missing = r.mode === "hostname" ? r.not_found.length : r.no_backup_items.length;
  $("#inv-stats").html([
    statTile("🖥️", "Host ditemukan", fmtNum(hosts, 0), "host", THEME.purple[0], THEME.purple[1]),
    statTile("📋", "Policy", fmtNum(policies, 0), "policy", THEME.pink[0], THEME.pink[1]),
    statTile("🗓️", "Schedule", fmtNum(r.total, 0), "baris", THEME.orange[0], THEME.orange[1]),
    statTile(missing ? "⛔" : "✅", r.mode === "hostname" ? "Not Found" : "Tanpa Backup", fmtNum(missing, 0), "host",
      missing ? STATUS.critical.grad[0] : STATUS.good.grad[0], missing ? STATUS.critical.grad[1] : STATUS.good.grad[1]),
  ].join(""));

  let note = r.cutoff ? `Data inventory per ${fmtDateTime(r.cutoff)}` : "Data inventory belum tersedia.";
  if (r.mode === "app" && r.app_host_count !== null) note += ` · ${r.app_host_count} host aplikasi di CMDB`;
  if (r.truncated) note += ` · menampilkan ${r.items.length} dari ${fmtNum(r.total, 0)} baris (unduh Excel untuk semua)`;
  $("#inv-cutoff").text(note);
  if (r.last_run_status === "failed") {
    showAlert("warning", `Pemuatan inventory terakhir gagal${r.last_error_id ? ` (ID: ${r.last_error_id})` : ""}. Ditampilkan data terakhir yang berhasil.`);
  }

  const q = invState.tableQuery.toLowerCase();
  const filtered = q
    ? rows.filter((row) => Object.values(row).some((v) => v !== null && String(v).toLowerCase().includes(q)))
    : rows;
  $("#inv-table").html(invTable(filtered, r.columns));
  $("#inv-result").show();
}

function runInventorySearch() {
  const params = invParams();
  if (!(params.hostnames || "").trim() && !(params.app || "").trim()) {
    showAlert("error", invState.mode === "hostname" ? "Masukkan minimal satu hostname." : "Masukkan nama aplikasi.");
    return;
  }
  clearAlert();
  const btn = $("#inv-search-btn").prop("disabled", true).text("Mencari...");
  invState.lastParams = params;
  $.getJSON("/api/backup-inventory/search", params)
    .done((data) => {
      invState.result = data;
      renderInventoryResult();
    })
    .fail((xhr) => showAlert("error", apiErrorMessage(xhr, "Pencarian gagal.")))
    .always(() => btn.prop("disabled", false).text("Cari"));
}

function loadInventoryFilters() {
  if (invState.filtersLoaded) return;
  $.getJSON("/api/backup-inventory/filters").done((f) => {
    invState.filtersLoaded = true;
    const opt = (v) => `<option value="${esc(v)}">${esc(v)}</option>`;
    $("#inv-master").html('<option value="">Semua master</option>' + f.masters.map(opt).join(""));
    $("#inv-ptype").html('<option value="">Semua policy type</option>' + f.policy_types.map(opt).join(""));
  });
}

let invSuggestTimer = null;
function suggestApps() {
  clearTimeout(invSuggestTimer);
  invState.appExact = false;
  const q = $("#inv-app").val().trim();
  if (q.length < 2) return;
  invSuggestTimer = setTimeout(() => {
    $.getJSON("/api/backup-inventory/apps", { q }).done((apps) => {
      $("#inv-app-list").html(apps.map((a) => `<option value="${esc(a.app_name)}">${a.host_count} host</option>`).join(""));
      if (apps.some((a) => a.app_name === $("#inv-app").val())) invState.appExact = true;
    });
  }, 250);
}

function setInventoryMode(mode) {
  invState.mode = mode;
  $(".inv-mode-btn").removeClass("active");
  $(`.inv-mode-btn[data-mode="${mode}"]`).addClass("active");
  $("#inv-hostname-box").toggle(mode === "hostname");
  $("#inv-app-box").toggle(mode === "app");
}

registerView("inventory", {
  title: "Backup Inventory",
  subtitle: "Konfigurasi backup per hostname atau per aplikasi (gabungan NetBackup + CMDB)",
  globalSearch: false,
  onShow: loadInventoryFilters,
});

$(function () {
  $(".inv-mode-btn").on("click", function () {
    setInventoryMode($(this).data("mode"));
  });
  $("#inv-search-btn").on("click", runInventorySearch);
  $("#inv-hostnames").on("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) runInventorySearch();
  });
  $("#inv-app").on("input", suggestApps).on("change", function () {
    invState.appExact = $("#inv-app-list option").toArray().some((o) => o.value === $(this).val());
  }).on("keydown", (e) => {
    if (e.key === "Enter") runInventorySearch();
  });
  $("#inv-table-search").on("input", function () {
    invState.tableQuery = $(this).val();
    renderInventoryResult();
  });
  $("#inv-export-btn").on("click", () => {
    if (!invState.lastParams) {
      showAlert("error", "Lakukan pencarian dulu sebelum export.");
      return;
    }
    window.location = "/api/backup-inventory/export?" + $.param(invState.lastParams);
  });
});
