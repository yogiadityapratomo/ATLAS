// Screenshot tiap menu + cek error console + uji Capture (html2canvas) memakai Microsoft Edge lokal.
// Hanya DEV. Pakai: npm run shots -- [baseUrl] [outDir]   (default http://127.0.0.1:8001 build/ui-shots)
import { chromium } from "playwright-core";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const base = process.argv[2] || "http://127.0.0.1:8001";
const out = process.argv[3] || join("build", "ui-shots");
mkdirSync(out, { recursive: true });

const browser = await chromium.launch({ channel: "msedge", headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true, deviceScaleFactor: 1 });
const page = await ctx.newPage();
const problems = [];
page.on("console", (m) => { if (m.type() === "error") problems.push(`console: ${m.text()}`); });
page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
page.on("download", (d) => d.saveAs(join(out, "capture-" + d.suggestedFilename())).catch(() => {}));

await page.goto(base + "/", { waitUntil: "networkidle" });
await page.waitForTimeout(1800);
await page.screenshot({ path: join(out, "01-diskpool.png"), fullPage: false });
await page.screenshot({ path: join(out, "01-diskpool-full.png"), fullPage: true });

// Capture (html2canvas): klik dan tunggu unduhan pertama atau pesan error.
const dl = page.waitForEvent("download", { timeout: 20000 }).then((d) => d.suggestedFilename()).catch(() => null);
await page.click("#btn-capture");
const name = await dl;
await page.waitForTimeout(1500);
const alertText = await page.locator("#alert-box").innerText().catch(() => "");
console.log("capture download:", name, "| alert:", JSON.stringify(alertText));

const views = [["tape", "02-tape"], ["history", "03-history"], ["inventory", "04-inventory"], ["audit", "05-audit"]];
for (const [view, file] of views) {
  await page.click(`.side-btn[data-view="${view}"]`);
  await page.waitForTimeout(view === "history" ? 2500 : 1500);
  if (view === "inventory") {
    await page.fill("#inv-hostnames", "app, db");
    await page.click("#inv-search-btn");
    await page.waitForTimeout(1800);
  }
  await page.screenshot({ path: join(out, `${file}.png`), fullPage: false });
}
// Drawer audit
const row = page.locator(".aud-row").first();
if (await row.count()) {
  await row.click();
  await page.waitForTimeout(700);
  await page.screenshot({ path: join(out, "06-audit-drawer.png") });
  await page.keyboard.press("Escape");
  await page.waitForTimeout(400);
}
// Sidebar diciutkan
await page.click("#side-collapse");
await page.waitForTimeout(600);
await page.click('.side-btn[data-view="diskpool"]');
await page.waitForTimeout(1500);
await page.screenshot({ path: join(out, "07-collapsed.png") });
await page.click("#side-collapse");

// Mobile
await page.setViewportSize({ width: 390, height: 844 });
await page.waitForTimeout(800);
await page.screenshot({ path: join(out, "08-mobile.png"), fullPage: false });

console.log(problems.length ? "PROBLEMS:\n" + problems.join("\n") : "no console errors");
await browser.close();
