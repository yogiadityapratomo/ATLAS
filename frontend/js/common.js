/* ATLAS — util bersama semua menu (jQuery, tanpa build step). Dipindah apa adanya dari app.js V4. */

/* Warna status = token --color-good/warn/crit di frontend/src/app.css (hex, aman untuk html2canvas).
   grad tetap ada sebagai penanda tone untuk statTile(); tidak lagi digambar sebagai gradien. */
const STATUS = {
  good: { key: "good", label: "Good", color: "#138a5e", soft: "#e3f3eb", bright: "#3fd69b", grad: ["#11998e", "#38ef7d"], icon: "✅" },
  warning: { key: "warning", label: "Warning", color: "#c46d06", soft: "#fbefdc", bright: "#ffb547", grad: ["#f7971e", "#ffb347"], icon: "⚠️" },
  critical: { key: "critical", label: "Critical", color: "#cf3550", soft: "#fbe5e9", bright: "#ff6b81", grad: ["#eb3349", "#f45c43"], icon: "⛔" },
};

/* Penanda aksen lama per tile (purple/pink/orange). Tampilan baru: tile netral; hanya tile status yang berwarna. */
const THEME = {
  purple: ["#6a3093", "#3f1d5c"],
  pink: ["#e8368f", "#b91d73"],
  orange: ["#ff9966", "#ff5e62"],
};

/* Ikon SVG (stroke) pengganti emoji. Kunci = emoji lama yang dipakai pemanggil statTile(). */
const SVG_ATTR = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
const ICON_PATHS = {
  disk: '<ellipse cx="12" cy="5.5" rx="8" ry="2.8"/><path d="M4 5.5v6.2c0 1.6 3.6 2.8 8 2.8s8-1.2 8-2.8V5.5"/><path d="M4 11.7v6.5c0 1.6 3.6 2.8 8 2.8s8-1.2 8-2.8v-6.5"/>',
  box: '<path d="m12 3 8 4.5v9L12 21l-8-4.5v-9z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/>',
  free: '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.2 2.4 2.3 4.6-4.8"/>',
  tape: '<rect x="2.5" y="5.5" width="19" height="13" rx="2.2"/><circle cx="8.5" cy="12" r="2.2"/><circle cx="15.5" cy="12" r="2.2"/><path d="M8.5 14.2h7"/>',
  host: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8.5 20h7M12 16v4"/>',
  list: '<rect x="4" y="3.5" width="16" height="17" rx="2"/><path d="M8 8.5h8M8 12h8M8 15.5h5"/>',
  calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
  ok: '<circle cx="12" cy="12" r="8.5"/><path d="m8.5 12.2 2.4 2.3 4.6-4.8"/>',
  warn: '<path d="M12 3.5 21 19.5H3z"/><path d="M12 10v4.2M12 17h.01"/>',
  stop: '<circle cx="12" cy="12" r="8.5"/><path d="M8.5 15.5l7-7"/>',
  scroll: '<path d="M8.5 6.5h11.5M8.5 12h11.5M8.5 17.5h7.5"/><circle cx="4.5" cy="6.5" r="1.1"/><circle cx="4.5" cy="12" r="1.1"/><circle cx="4.5" cy="17.5" r="1.1"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7"/>',
  plug: '<path d="M9 3v5M15 3v5"/><path d="M6.5 8h11v3.5a5.5 5.5 0 0 1-11 0z"/><path d="M12 17v4"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M21 20H3"/>',
  updown: '<path d="m7 4-3.5 3.5M7 4l3.5 3.5M7 4v16M17 20l-3.5-3.5M17 20l3.5-3.5M17 20V4"/>',
};
const EMOJI_ICON = {
  "🗄️": "disk", "📦": "box", "🟢": "free", "💾": "tape", "🖥️": "host", "📋": "list", "🗓️": "calendar",
  "✅": "ok", "⚠️": "warn", "⛔": "stop", "📜": "scroll", "⚙️": "gear", "🔌": "plug", "📊": "chart", "↕️": "updown",
};

function iconSvg(name) {
  const key = EMOJI_ICON[name] || name;
  return ICON_PATHS[key] ? `<svg ${SVG_ATTR}>${ICON_PATHS[key]}</svg>` : esc(name);
}

function toneFromAccent(accent1) {
  const s = Object.values(STATUS).find((st) => st.grad[0] === accent1);
  return s ? { tone: s.color, soft: s.soft, ink: s.color } : null;
}

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
            return `<td class="num"><span class="pill pill-${s.key}" title="${s.label}">${fmtNum(v, 2)}%</span></td>`;
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

/* Tile angka. Tile status (accent = STATUS.*.grad) diberi warna status; tile lain netral.
   Angka dianimasikan menghitung naik oleh animateCounts() (lihat observer di bawah). */
function statTile(icon, label, value, unit, accent1) {
  const t = toneFromAccent(accent1);
  const style = t ? ` style="--tone:${t.tone};--tone-soft:${t.soft};--tone-ink:${t.ink}"` : "";
  return `<div class="stat-tile"${style}>
      <div class="stat-icon">${iconSvg(icon)}</div>
      <div class="stat-label">${esc(label)}</div>
      <div class="stat-value"><span class="count" data-final="${esc(value)}">${esc(value)}</span><span class="unit">${esc(unit)}</span></div>
    </div>`;
}

/* -------------------------------------------------------------- gauge -- */

/* Gauge kapasitas (elemen utama menu Disk Pool / Tape). Bila gauge sudah ada di target, nilainya
   di-update in place sehingga isian bergeser halus (transisi CSS) alih-alih digambar ulang. */
function renderGauge(target, opts) {
  const $t = $(target);
  const s = usageStatus(opts.pct);
  const width = Math.max(0, Math.min(100, opts.pct));
  const facts = opts.facts
    .map((f) => `<div class="gauge-fact"><dt>${esc(f.label)}</dt><dd><span class="count" data-final="${esc(f.value)}">${esc(f.value)}</span><small>${esc(f.unit)}</small></dd></div>`)
    .join("");
  const $existing = $t.children(".gauge-panel");
  if ($existing.length) {
    $existing.css("--g", s.bright);
    $existing.find(".gauge-pct .count").attr("data-final", fmtNum(opts.pct, 2)).text(fmtNum(opts.pct, 2));
    $existing.find(".gauge-status").text(s.label);
    $existing.find(".gauge-caption").html(opts.caption);
    $existing.find(".gauge-facts").html(facts);
    $existing.find(".gauge-fill").removeClass("is-new").css("width", width + "%");
    $existing.find(".gauge-track").attr("aria-valuenow", width.toFixed(1));
    animateCounts($existing.find(".gauge-pct")[0]); // fakta baru dianimasikan oleh observer
    return;
  }
  const ticks = [70, 85]
    .map((v) => `<div class="gauge-tick" style="left:${v}%"><span><b class="t-long">${v === 70 ? "Warning" : "Critical"} </b>${v}%</span></div>`)
    .join("");
  $t.html(`<div class="gauge-panel" style="--g:${s.bright}">
      <div class="gauge-top">
        <div class="gauge-figure">
          <div class="gauge-pct"><span class="count" data-final="${fmtNum(opts.pct, 2)}">${fmtNum(opts.pct, 2)}</span><small>%</small></div>
          <div class="gauge-meta">
            <span class="gauge-status">${s.label}</span>
            <div class="gauge-caption">${opts.caption}</div>
          </div>
        </div>
        <dl class="gauge-facts">${facts}</dl>
      </div>
      <div class="gauge-track" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${width.toFixed(1)}" aria-label="${esc(opts.label)}">
        <div class="gauge-fill is-new" style="width:${width}%"></div>${ticks}
      </div>
    </div>`);
}

/* --------------------------------------------------------------- rings -- */

/* Kartu cincin donut: persentase di tengah, label & angka di bawah. Warna = status usage. */
function ringCard(opts) {
  const s = usageStatus(opts.pct);
  const p = Math.max(0, Math.min(100, opts.pct));
  return `<div class="donut-card">
      <div class="donut" role="img" aria-label="${esc(opts.label)} ${fmtNum(opts.pct, 1)}%">
        <svg viewBox="0 0 120 120">
          <circle class="donut-bg" cx="60" cy="60" r="50"/>
          <circle class="donut-fg" cx="60" cy="60" r="50" pathLength="100" style="stroke:${s.color};stroke-dasharray:${p.toFixed(2)} 100"/>
        </svg>
        <div class="donut-center"><b style="color:${s.color}">${fmtNum(opts.pct, 1)}<small>%</small></b><span>${s.label}</span></div>
      </div>
      <div class="donut-label">${opts.badge || ""}${opts.showLabel === false ? "" : esc(opts.label)}</div>
      <div class="donut-sub">${opts.sub}</div>
    </div>`;
}

/* ------------------------------------------------------- count-up anim -- */

const COUNT_PREV = {};
const REDUCED_MOTION = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* Animasikan setiap .count di dalam root dari nilai sebelumnya (atau 0) ke data-final, sehingga
   angka bergeser halus saat data/filter berubah. Teks akhir selalu persis data-final. */
function animateCounts(root) {
  $(root).find(".count").each(function () {
    const el = this;
    const finalText = el.getAttribute("data-final") || "";
    const target = parseFloat(finalText.replace(/,/g, ""));
    if (REDUCED_MOTION || !isFinite(target)) { el.textContent = finalText; return; }
    const decimals = (finalText.split(".")[1] || "").length;
    const owner = el.closest("[id]");
    const key = owner ? owner.id + "|" + $(owner).find(".count").index(el) : null;
    const from = key && COUNT_PREV[key] !== undefined ? COUNT_PREV[key] : 0;
    if (key) COUNT_PREV[key] = target;
    if (from === target) { el.textContent = finalText; return; }
    const start = performance.now();
    const dur = 900;
    const step = (now) => {
      const p = Math.min(1, (now - start) / dur);
      const e = 1 - Math.pow(1 - p, 4);
      el.textContent = p < 1 ? fmtNum(from + (target - from) * e, decimals) : finalText;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });
}

/* Jalankan count-up otomatis setiap ada .count baru yang dirender (tanpa mengubah pemanggil). */
$(function () {
  if (!window.MutationObserver) return;
  const obs = new MutationObserver((muts) => {
    const roots = new Set();
    muts.forEach((m) => m.addedNodes.forEach((n) => {
      if (n.nodeType === 1 && (n.classList.contains("count") || n.querySelector(".count"))) roots.add(n.parentNode || n);
    }));
    roots.forEach((r) => animateCounts(r));
  });
  obs.observe(document.querySelector(".main") || document.body, { childList: true, subtree: true });
});

/* ------------------------------------------------- segmented thumb anim -- */

/* Tambahkan "thumb" yang bergeser halus di bawah tombol aktif pada .hist-seg / .inv-mode. */
function initSegThumbs() {
  $(".hist-seg, .inv-mode").each(function () {
    const seg = this;
    if (seg.querySelector(".seg-thumb")) return;
    const thumb = document.createElement("span");
    thumb.className = "seg-thumb";
    seg.prepend(thumb);
    seg.classList.add("has-thumb");
    const place = () => {
      const active = seg.querySelector("button.active");
      if (!active || !active.offsetWidth) return;
      thumb.style.width = active.offsetWidth + "px";
      thumb.style.transform = `translateX(${active.offsetLeft}px)`;
    };
    place();
    new MutationObserver(place).observe(seg, { attributes: true, subtree: true, attributeFilter: ["class"] });
    $(window).on("resize", place);
    seg._placeThumb = place;
  });
}

function refreshSegThumbs() {
  $(".hist-seg, .inv-mode").each(function () { if (this._placeThumb) this._placeThumb(); });
}

$(initSegThumbs);

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
