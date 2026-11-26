# Capacity Bar Chart Redesign

## Problem

The "Kapasitas per Site" (disk pool) and "Summary per Tape Library" (tape) charts on the dashboard use a two-color split bar (`barRowSplit` in `static/app.js`) where a red "used" segment and a green "free" segment are drawn directly adjacent with no gap. Visually this reads as one messy, alarming bar rather than a clean usage indicator, and it's inconsistent with the "Ranking Usage per Disk Pool" chart, which already uses a single status-colored bar (`barRowSolid`) driven by `usageStatus()` (good/warning/critical based on % thresholds).

## Goals

- Replace the two-color split fill with a single status-colored fill, consistent with the existing Ranking Usage chart and the status pills already used in the detail tables.
- Preserve the existing relative-size cue: track width stays proportional to each row's total capacity relative to the largest row in the same chart (unchanged `maxTotal` scaling logic).
- Use only colors already defined in the theme (`--good` #0ca678, `--warning` #e8770d, `--critical` #d6246e) — no new palette introduced.
- Keep each chart's existing value-text content (disk pool: `%` usage; tape: `pcs` count) but color that text to match the row's status, for consistency with `barRowSolid`.

## Non-goals

- No change to the `barRowSolid` / Ranking Usage chart — it's already the target style.
- No change to underlying data, API, or table rendering — this is purely the two summary bar charts' visual treatment.
- No new chart type (e.g., donut) — out of scope, rejected during brainstorming.

## Design

**Affected files:** `static/app.js`, `static/style.css`.

**`barRowSplit` → replaced by a new function `barRowUsage(label, pct, trackWidthPct, valueText)`:**
- `trackWidthPct` — same proportional-sizing math as today (`Math.max((total / maxTotal) * 100, 2)`), computed by the caller from that row's total vs. the chart's max total.
- Renders one `.bar-track` (light gray, unchanged background) at `width: trackWidthPct%`, containing one `.bar-fill` at `width: pct%`, colored via `usageStatus(pct).color`.
- `valueText` is rendered with `color: usageStatus(pct).color` (mirrors `barRowSolid`'s existing value coloring).

**Call sites:**
- `renderDiskPoolSummary` (disk pool per-site chart): passes `s["Usage (%)"]` as both the fill pct and keeps its existing `${fmtNum(usage,1)}%` value text.
- `renderTapeSummaryChart` (tape per-site/type chart): computes `pct = total ? (used/total)*100 : 0` for the fill/color, keeps existing `${total} pcs` value text.

**Legend:** `chartLegendSplit()` (currently "Used" red dot / "Free" green dot) is replaced by a status legend — three dots labeled Good (<70%), Warning (70–85%), Critical (≥85%), using the same colors/labels as `STATUS` in `app.js`. Reused for both charts.

**CSS (`style.css`):** `.bar-track.split`, `.bar-fill.used`, `.bar-fill.free` rules are removed (no longer referenced). No new classes needed — the redesigned bar reuses the existing `.bar-track` / `.bar-fill` base styles already used by `barRowSolid`.

## Edge cases

- **0 total (empty row):** `trackWidthPct` floors at 2% (unchanged behavior) so an empty row still renders a thin visible track; `pct` is 0 → colored good/green.
- **Single row in a chart:** `maxTotal` equals that row's own total, so `trackWidthPct` is 100% — same as today.

## Testing

Manual visual check only (no test suite in this project): run `run.bat`, load the dashboard, confirm both charts render single-color bars with correct status coloring and that track widths still look proportional across rows with different totals.
