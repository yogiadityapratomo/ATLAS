/* ATLAS — navigasi antar menu. Setiap menu mendaftar lewat registerView() di file js-nya sendiri.
   Dimuat SEBELUM file menu (lihat index.html), sehingga registerView/switchView sudah tersedia. */

const VIEWS = {};
let currentView = "diskpool";

function registerView(name, options) {
  VIEWS[name] = Object.assign(
    {
      title: "NetBackup Capacity Report",
      subtitle: null /* null = tampilkan "Data terakhir di-generate" milik menu kapasitas */,
      placeholder: "Cari...",
      getQuery: () => "",
      onSearch: () => {},
      onShow: () => {},
      globalSearch: true,
    },
    options
  );
}

function switchView(view) {
  if (!VIEWS[view]) return;
  currentView = view;
  $(".side-btn").removeClass("active");
  $(`.side-btn[data-view="${view}"]`).addClass("active");
  $(".view").removeClass("active");
  $("#view-" + view).addClass("active");
  const v = VIEWS[view];
  $("#page-title").text(v.title);
  $("#last-updated").toggle(v.subtitle === null);
  $("#page-subtitle").toggle(v.subtitle !== null).text(v.subtitle || "");
  document.title = v.title === "NetBackup Capacity Report" ? "NetBackup Capacity Report" : `${v.title} · ATLAS`;
  $("#global-search").attr("placeholder", v.placeholder).val(v.getQuery());
  $(".topbar-actions .search-box").toggle(v.globalSearch);
  $("#btn-export, #btn-capture").toggle(view === "diskpool" || view === "tape");
  const h1 = document.getElementById("page-title");
  h1.classList.remove("swap");
  void h1.offsetWidth; // restart animasi judul
  h1.classList.add("swap");
  moveSideIndicator();
  v.onShow();
  requestAnimationFrame(() => { if (typeof refreshSegThumbs === "function") refreshSegThumbs(); });
}

/* Indikator menu aktif yang bergeser halus ke tombol terpilih. */
function moveSideIndicator() {
  const ind = document.getElementById("side-indicator");
  const active = document.querySelector(".side-btn.active");
  if (!ind || !active) return;
  ind.style.height = active.offsetHeight + "px";
  ind.style.transform = `translateY(${active.offsetTop}px)`;
}

/* Sidebar bisa diciutkan; pilihan disimpan di browser. Layar sempit otomatis ciut. */
const SIDEBAR_KEY = "atlas.sidebar.collapsed";
function applySidebarState() {
  let saved = null;
  try { saved = localStorage.getItem(SIDEBAR_KEY); } catch (e) { /* storage tidak tersedia */ }
  const collapsed = saved === null ? window.innerWidth < 1100 : saved === "1";
  $("#shell").toggleClass("is-collapsed", collapsed);
  $("#side-collapse").attr({ "aria-label": collapsed ? "Lebarkan sidebar" : "Ciutkan sidebar", title: collapsed ? "Lebarkan sidebar" : "Ciutkan sidebar" })
    .find(".side-label").text(collapsed ? "Lebarkan" : "Ciutkan");
}

$(function () {
  applySidebarState();
  moveSideIndicator();
  $("#side-collapse").on("click", function () {
    const next = !$("#shell").hasClass("is-collapsed");
    try { localStorage.setItem(SIDEBAR_KEY, next ? "1" : "0"); } catch (e) { /* abaikan */ }
    applySidebarState();
    moveSideIndicator();
    setTimeout(() => { moveSideIndicator(); if (typeof refreshSegThumbs === "function") refreshSegThumbs(); }, 360);
  });
  $(window).on("resize", moveSideIndicator);
  $(".side-btn").on("click", function () {
    switchView($(this).data("view"));
  });
  $("#global-search").on("input", function () {
    VIEWS[currentView].onSearch($(this).val());
  });
});
