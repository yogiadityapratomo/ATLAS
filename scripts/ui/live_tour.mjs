// Tur live di jendela Chrome yang TERLIHAT: kursor animasi berkeliling menu ATLAS, dan halaman otomatis
// reload setiap ada file di frontend/ berubah (untuk melihat desain berubah sambil dikerjakan). Hanya DEV.
// Pakai: node scripts/ui/live_tour.mjs [baseUrl]   (default http://127.0.0.1:8001). Tutup jendela untuk berhenti.
import { chromium } from "playwright-core";
import { watch } from "node:fs";

const base = process.argv[2] || "http://127.0.0.1:8001";
const browser = await chromium.launch({
  channel: "chrome",
  headless: false,
  args: ["--window-size=1480,960", "--window-position=40,20"],
});
const ctx = await browser.newContext({ viewport: null });
const page = await ctx.newPage();
const cdp = await ctx.newCDPSession(page);
await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });

// Kursor animasi (overlay, tidak menghalangi klik) + riak saat klik.
await ctx.addInitScript(() => {
  window.addEventListener("DOMContentLoaded", () => {
    const st = document.createElement("style");
    st.textContent = `
      #tour-cursor{position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;pointer-events:none;
        transform:translate(-3px,-2px);transition:transform .05s linear;filter:drop-shadow(0 3px 6px rgba(0,0,0,.35))}
      .tour-ripple{position:fixed;z-index:2147483646;pointer-events:none;width:14px;height:14px;margin:-7px 0 0 -7px;
        border-radius:999px;border:2px solid #5b4bd6;animation:tour-rip .55s ease-out forwards}
      @keyframes tour-rip{from{opacity:.9;transform:scale(.6)}to{opacity:0;transform:scale(3.2)}}
      #tour-badge{position:fixed;right:16px;bottom:16px;z-index:2147483647;pointer-events:none;background:#11162b;color:#fff;
        font:600 12px/1.2 system-ui;padding:8px 12px;border-radius:999px;box-shadow:0 6px 18px rgba(0,0,0,.25)}`;
    document.head.appendChild(st);
    const c = document.createElement("div");
    c.id = "tour-cursor";
    c.innerHTML = '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M4 2.5 19.5 13l-7 1.3L9 21z" fill="#fff" stroke="#11162b" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.appendChild(c);
    const b = document.createElement("div");
    b.id = "tour-badge";
    b.textContent = "Live preview: Claude sedang mendesain";
    document.body.appendChild(b);
    window.addEventListener("mousemove", (e) => { c.style.left = e.clientX + "px"; c.style.top = e.clientY + "px"; }, true);
    window.addEventListener("mousedown", (e) => {
      const r = document.createElement("div");
      r.className = "tour-ripple"; r.style.left = e.clientX + "px"; r.style.top = e.clientY + "px";
      document.body.appendChild(r); setTimeout(() => r.remove(), 600);
    }, true);
  });
});

let pos = { x: 700, y: 400 };
const wait = (ms) => page.waitForTimeout(ms);
async function glide(x, y, steps = 28) { await page.mouse.move(x, y, { steps }); pos = { x, y }; }
async function to(sel, opts = {}) {
  const el = page.locator(sel).first();
  if (!(await el.count()) || !(await el.isVisible())) return false;
  await el.scrollIntoViewIfNeeded().catch(() => {});
  const box = await el.boundingBox();
  if (!box) return false;
  await glide(box.x + box.width * (opts.fx ?? 0.5), box.y + box.height * (opts.fy ?? 0.5));
  await wait(opts.pause ?? 350);
  return true;
}
async function click(sel, opts = {}) {
  if (await to(sel, opts)) { await page.mouse.down(); await page.mouse.up(); await wait(opts.after ?? 900); return true; }
  return false;
}
async function scrollBy(dy) { await page.mouse.wheel(0, dy); await wait(700); }

let reloadPending = false;
watch("frontend", { recursive: true }, () => { reloadPending = true; });

async function maybeReload() {
  if (!reloadPending) return;
  reloadPending = false;
  await page.reload({ waitUntil: "networkidle" }).catch(() => {});
  await page.mouse.move(pos.x, pos.y);
  await wait(1200);
}

async function tour() {
  await click('.side-btn[data-view="diskpool"]', { after: 1600 });
  await to(".gauge-panel", { fx: 0.3, pause: 900 });
  await to("#card-summary-site", { pause: 700 });
  await to("#dp-summary-chart", { pause: 700 });
  await scrollBy(520);
  await to("#ranking-grid-master .card:nth-child(1)", { fy: 0.3, pause: 600 });
  await to("#ranking-grid-master .card:nth-child(3)", { fy: 0.3, pause: 600 });
  for (const m of ["bsd", "tbs", "brn"]) await click(`.dp-tab[data-master="${m}"]`, { after: 1000 });
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
  await wait(800);
  await maybeReload();

  await click('.side-btn[data-view="tape"]', { after: 1600 });
  await to(".gauge-panel", { fx: 0.6, pause: 800 });
  await scrollBy(400);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
  await maybeReload();

  await click('.side-btn[data-view="history"]', { after: 2200 });
  await click('.hist-seg[data-name="group"] button[data-value="master"]', { after: 1800 });
  await click('.hist-seg[data-name="metric"] button[data-value="used_tb"]', { after: 1800 });
  await to("#hist-chart", { fx: 0.55, pause: 400 });
  await glide(pos.x + 180, pos.y, 40); await wait(600);
  await click('.hist-seg[data-name="metric"] button[data-value="usage_pct"]', { after: 1400 });
  await click('.hist-seg[data-name="group"] button[data-value="site"]', { after: 1400 });
  await maybeReload();

  await click('.side-btn[data-view="inventory"]', { after: 1200 });
  if (await click("#inv-hostnames", { after: 300 })) {
    await page.fill("#inv-hostnames", "");
    await page.keyboard.type("app, db", { delay: 90 });
    await click("#inv-search-btn", { after: 2000 });
  }
  await click('.inv-mode-btn[data-mode="app"]', { after: 900 });
  await click('.inv-mode-btn[data-mode="hostname"]', { after: 900 });
  await maybeReload();

  await click('.side-btn[data-view="audit"]', { after: 1800 });
  if (await click(".aud-row", { after: 1400 })) {
    await click("#aud-detail-close", { after: 900 });
  }
  await click("#side-collapse", { after: 1100 });
  await click("#side-collapse", { after: 1100 });
  await maybeReload();
}

await page.goto(base + "/", { waitUntil: "networkidle" });
await wait(1500);
page.on("close", () => process.exit(0));
browser.on("disconnected", () => process.exit(0));
for (;;) {
  try { await tour(); } catch (e) { if (page.isClosed()) break; await wait(1000); }
}
