/* ATLAS — util bersama semua menu (jQuery, tanpa build step). Dipindah apa adanya dari app.js V4. */

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

function fmtDateTime(iso) {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("id-ID", { dateStyle: "long", timeStyle: "medium" });
}

function fmtCutoff(iso) {
  if (!iso) return "Belum ada data.";
  return "Data per " + fmtDateTime(iso);
}

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

/* --------------------------------------------------------------- alerts -- */

function showAlert(type, message) {
  const cls = type === "error" ? "alert-error" : type === "warning" ? "alert-warning" : "alert-success";
  $("#alert-box").html(`<div class="alert ${cls}">${esc(message)}</div>`);
}

function clearAlert() {
  $("#alert-box").empty();
}

/* Pesan error API ATLAS: {"error": "...", "error_id": "ERR-XXXXXX"} */
function apiErrorMessage(xhr, fallback) {
  const body = xhr && xhr.responseJSON;
  if (body && body.error) return body.error_id ? `${body.error} (ID: ${body.error_id})` : body.error;
  return fallback || "Gagal menghubungi server.";
}

/* -------------------------------------------------------------- capture -- */

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

/* Capture tabel yang bisa di-scroll horizontal pada lebar penuhnya (bukan hanya bagian yang terlihat);
   judul digambar terpisah dengan Canvas API lalu ditumpuk di atas tabel. */
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
