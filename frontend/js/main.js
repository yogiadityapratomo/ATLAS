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
  v.onShow();
}

$(function () {
  $(".side-btn").on("click", function () {
    switchView($(this).data("view"));
  });
  $("#global-search").on("input", function () {
    VIEWS[currentView].onSearch($(this).val());
  });
});
