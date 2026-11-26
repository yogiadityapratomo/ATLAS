# Capacity Bar Chart Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two-color (red/green, no gap) split bar in the "Kapasitas per Site" and "Summary per Tape Library" charts with a single status-colored bar (green/orange/red by usage %), matching the existing "Ranking Usage per Disk Pool" chart style, while keeping the proportional track-width sizing.

**Architecture:** Pure frontend change in `static/app.js` (new render function replacing the old split-bar function, two call-site updates) and `static/style.css` (delete now-dead CSS rules). No backend, no data-shape changes.

**Tech Stack:** Vanilla JS + jQuery, no build step, no test framework.

## Global Constraints

- No automated test suite exists in this project — every verification step below is a manual visual check in the browser, not a unit test (per the design doc's Testing section).
- Reuse existing theme colors only: `var(--good)` #0ca678, `var(--warning)` #e8770d, `var(--critical)` #d6246e (already defined in `style.css` and in the `STATUS` object in `app.js`). No new colors.
- Preserve current track-width proportional-sizing formula: `Math.max((total / maxTotal) * 100, 2)`.
- Preserve each chart's existing value-text content: disk-pool chart shows `%`, tape chart shows `pcs` count.

---

### Task 1: Replace split bar rendering with status-colored bar

**Files:**
- Modify: `static/app.js:69-102` (delete `barRowSplit` and `chartLegendSplit`, add `barRowUsage` and `chartLegendStatus`)
- Modify: `static/app.js:156-174` (`renderDiskPoolSummary`)
- Modify: `static/app.js:230-248` (`renderTapeSummaryChart`)
- Modify: `static/style.css:139-140` (delete dead rules)

**Interfaces:**
- Produces: `barRowUsage(label, pct, trackWidthPct, valueText)` → HTML string for one bar row. `pct` (0-100) drives fill width and status color via the existing `usageStatus(pct)`. `trackWidthPct` (0-100) sets the outer track's proportional width. `valueText` is the pre-formatted right-hand label, colored to match status.
- Produces: `chartLegendStatus()` → HTML string, no params, renders the Good/Warning/Critical legend using the existing `STATUS` object.
- Consumes: existing `usageStatus(pct)`, `esc(v)`, `fmtNum(v, decimals)`, `STATUS` (all already defined earlier in `static/app.js`, unchanged).

- [ ] **Step 1: Replace `barRowSplit` and `chartLegendSplit` with the new functions**

In `static/app.js`, find this block (current lines 69-102):

```javascript
function barRowSplit(label, usedVal, freeVal, maxTotal, valueText) {
  const total = usedVal + freeVal;
  const trackWidthPct = maxTotal > 0 ? Math.max((total / maxTotal) * 100, 2) : 2;
  const usedPct = total > 0 ? (usedVal / total) * 100 : 0;
  const freePct = total > 0 ? (freeVal / total) * 100 : 0;
  return `
    <div class="bar-row">
      <div class="bar-label">${esc(label)}</div>
      <div class="bar-track split" style="width:${trackWidthPct}%">
        <div class="bar-fill used" style="width:${usedPct}%"></div>
        <div class="bar-fill free" style="width:${freePct}%; left:${usedPct}%"></div>
      </div>
      <div class="bar-value">${valueText}</div>
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

function chartLegendSplit() {
  return `<div class="chart-legend">
    <span><i style="background:${STATUS.critical.color}"></i>Used</span>
    <span><i style="background:${STATUS.good.color}"></i>Free</span>
  </div>`;
}
```

Replace it with:

```javascript
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
```

(`barRowSolid` is unchanged — kept as-is, still used by the Ranking Usage chart.)

- [ ] **Step 2: Update `renderDiskPoolSummary` to use the new functions**

Find (current lines 156-174):

```javascript
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
    .map((s) =>
      barRowSplit(s.Site, s["Used Capacity (TB)"], s["Free Capacity (TB)"], maxTotal, `${fmtNum(s["Usage (%)"], 1)}%`)
    )
    .join("");
  $("#dp-summary-chart").html(chartLegendSplit() + (bars || '<div class="empty-note">Tidak ada data.</div>'));
}
```

Replace the `maxTotal`/`bars`/`.html(...)` tail with:

```javascript
  const maxTotal = Math.max(...summary.map((s) => s["Total Capacity (TB)"]), 1);
  const bars = summary
    .map((s) => {
      const trackWidthPct = Math.max((s["Total Capacity (TB)"] / maxTotal) * 100, 2);
      return barRowUsage(s.Site, s["Usage (%)"], trackWidthPct, `${fmtNum(s["Usage (%)"], 1)}%`);
    })
    .join("");
  $("#dp-summary-chart").html(chartLegendStatus() + (bars || '<div class="empty-note">Tidak ada data.</div>'));
}
```

(Only the `maxTotal`/`bars`/final `.html()` lines change — the function signature, `diskPoolSummaryBySite` call, and `$("#dp-summary-table").html(...)` block above stay exactly as they are.)

- [ ] **Step 3: Update `renderTapeSummaryChart` to use the new functions**

Find (current lines 230-248):

```javascript
function renderTapeSummaryChart(rows) {
  if (!rows.length) {
    $("#tp-summary-chart").html('<div class="empty-note">Tidak ada data.</div>');
    return;
  }
  const maxTotal = Math.max(...rows.map((r) => r["Total Tape (Qty)"]), 1);
  const bars = rows
    .map((r) =>
      barRowSplit(
        `${r.Site} — ${r["Type Tape"]}`,
        r["Tape Used (Qty)"],
        r["Tape Free (Qty)"],
        maxTotal,
        `${r["Total Tape (Qty)"]} pcs`
      )
    )
    .join("");
  $("#tp-summary-chart").html(chartLegendSplit() + bars);
}
```

Replace with:

```javascript
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
```

- [ ] **Step 4: Delete the dead split-fill CSS rules**

In `static/style.css`, find:

```css
.bar-track.split .bar-fill.used { background: var(--critical); }
.bar-track.split .bar-fill.free { background: var(--good); }
```

Delete these two lines entirely. Nothing in the codebase produces a `.bar-track.split`, `.bar-fill.used`, or `.bar-fill.free` element after Steps 1-3, so these rules are dead. The `.bar-track`, `.bar-fill`, `.bar-row`, `.bar-value`, `.chart-legend` base rules directly above/below stay untouched — `barRowUsage` and `barRowSolid` both still use those classes.

- [ ] **Step 5: Grep to confirm no leftover references**

Run: `grep -rn "barRowSplit\|chartLegendSplit\|bar-track.split\|bar-fill.used\|bar-fill.free" static/`

Expected: no output (empty result — everything was replaced/removed).

---

### Task 2: Manual verification and commit

**Files:** none (verification + git only)

**Interfaces:** none — this task only exercises Task 1's output through the browser.

- [ ] **Step 1: Confirm the dashboard server is running**

The dev server should already be running in the background on `http://127.0.0.1:8000` (started earlier this session with cached data, no VPN needed). If it's not running, start it:

Run: `python -m uvicorn app:app --host 127.0.0.1 --port 8000` (from the project root)

- [ ] **Step 2: Reload the dashboard in the browser and visually check both charts**

Open (or reload) `http://127.0.0.1:8000`. Check:
- "Kapasitas per Site" chart (Disk Pool tab): each site's bar is a single solid color (no red/green split), color matches its usage % (green <70%, orange 70-85%, red ≥85%), track widths still differ proportionally between sites with different total capacity, legend shows Good/Warning/Critical (not Used/Free).
- Switch to the Tape Library tab, check "Summary per Tape Library" chart: same single-color-bar behavior, value text still shows `N pcs` (not a percentage).
- Open browser dev tools console: confirm no JS errors logged on page load.

Expected: both charts render correctly with no console errors. If something looks wrong, fix it in Task 1's code before proceeding — do not commit broken output.

- [ ] **Step 3: Commit**

```bash
cd /d/NetbackupBotV3
git add static/app.js static/style.css
git commit -m "Redesign capacity bar charts to use status-colored bars

Replace the two-color used/free split bar with a single bar colored by
usage status (good/warning/critical), matching the existing Ranking
Usage chart. Track width stays proportional to each row's total
capacity, as before.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

(This assumes the initial commit from earlier in the session has already landed — if not, that commit must land first, in the same order it was created.)
