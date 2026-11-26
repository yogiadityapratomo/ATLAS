# Ranking Usage Chart Split by Master

## Problem

The "Ranking Usage per Disk Pool" chart (`#dp-ranking-chart` in `static/index.html`, rendered by `renderDiskPoolDetail` in `static/app.js`) shows every disk pool across all three masters (TBS, BSD, BRN) mixed into a single list, sorted only by usage %. This makes it hard to see usage patterns per master at a glance.

## Goals

- Split the single ranking list into 3 side-by-side columns, one per master (BRN, BSD, TBS — alphabetical, matching the sort order already used in `diskPoolSummaryBySite`).
- Within each column, keep the existing sort: usage % descending.
- Keep using the existing `barRowSolid` bar (status-colored, unchanged).
- Preserve the existing global-search filtering behavior (by site/master/disk pool name) — filtering happens first, then results are grouped into their master's column.
- Collapse to 1 stacked column on narrow screens (<900px), reusing the breakpoint already defined in `style.css` for `.stat-grid`/`.card-grid`.

## Non-goals

- No change to the "Detail per Disk Pool" table or the "Kapasitas per Site" chart.
- No change to `barRowSolid` itself or its status-color logic.

## Design

**Affected files:** `static/app.js`, `static/style.css`.

**`renderDiskPoolDetail(rows, query)`:** after the existing filter step, group `filtered` by `Master` into BRN/BSD/TBS buckets, sort each bucket by `Usage (%)` descending (same comparator as today), and render one `barRowSolid` list per bucket into 3 separate containers instead of one combined list. Empty buckets render the existing `empty-note` markup.

**`static/index.html`:** replace the single `<div class="card-body" id="dp-ranking-chart">` with a 3-column container, e.g. one `.card` per master with its own body id (`dp-ranking-brn`, `dp-ranking-bsd`, `dp-ranking-tbs`), wrapped in a new `.ranking-grid` div.

**`static/style.css`:** add `.ranking-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }` and add it to the existing `@media (max-width: 900px)` block as `grid-template-columns: 1fr`.

## Testing

Manual visual check: reload dashboard, confirm 3 columns show correct per-master disk pools sorted by usage descending, search box still filters correctly per column, and layout stacks to 1 column below 900px width.
