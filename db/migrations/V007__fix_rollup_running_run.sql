-- V007 — perbaikan V006: rollup harian dipanggil job kapasitas DI DALAM transaksinya, saat run masih
-- berstatus 'running'. Filter lama (success/partial) membuat hari berjalan tidak pernah diringkas oleh job
-- (hanya oleh catch-up maintenance). Snapshot dari run 'failed' tidak mungkin ada (transaksi di-rollback),
-- jadi cukup kecualikan 'failed'. Ditemukan oleh test integrasi sebelum merge.

CREATE OR REPLACE FUNCTION capacity.rollup_disk_pool_daily(p_from date, p_to date)
RETURNS integer
LANGUAGE plpgsql
SET search_path = pg_catalog, pg_temp
SET timezone = 'Asia/Jakarta'
AS $fn$
DECLARE
    v_rows integer;
BEGIN
    INSERT INTO capacity.disk_pool_daily AS t
           (day, site, master, disk_pool_name, usable_tb, available_tb, used_tb, usage_pct,
            max_used_tb, max_usage_pct, samples, source, updated_at)
    SELECT x.day, x.site, x.master, x.disk_pool_name, x.usable_tb, x.available_tb, x.used_tb, x.usage_pct,
           x.max_used_tb, x.max_usage_pct, x.samples, 'collect', now()
      FROM (
            SELECT s.collected_at::date AS day, s.site, s.master, s.disk_pool_name,
                   s.usable_tb, s.available_tb, s.used_tb, s.usage_pct,
                   max(s.used_tb)   OVER w AS max_used_tb,
                   max(s.usage_pct) OVER w AS max_usage_pct,
                   count(*)         OVER w AS samples,
                   row_number() OVER (PARTITION BY s.collected_at::date, s.master, s.disk_pool_name
                                      ORDER BY s.collected_at DESC, s.id DESC) AS rn
              FROM capacity.disk_pool_snapshot s
              JOIN core.collect_run r ON r.id = s.run_id AND r.status <> 'failed'
             WHERE s.collected_at >= p_from::timestamptz
               AND s.collected_at <  (p_to + 1)::timestamptz
            WINDOW w AS (PARTITION BY s.collected_at::date, s.master, s.disk_pool_name)
           ) x
     WHERE x.rn = 1
    ON CONFLICT (master, disk_pool_name, day) DO UPDATE
       SET site = EXCLUDED.site, usable_tb = EXCLUDED.usable_tb, available_tb = EXCLUDED.available_tb,
           used_tb = EXCLUDED.used_tb, usage_pct = EXCLUDED.usage_pct, max_used_tb = EXCLUDED.max_used_tb,
           max_usage_pct = EXCLUDED.max_usage_pct, samples = EXCLUDED.samples, source = 'collect',
           updated_at = now()
     WHERE (t.used_tb, t.usable_tb, t.samples, t.source)
           IS DISTINCT FROM (EXCLUDED.used_tb, EXCLUDED.usable_tb, EXCLUDED.samples, 'collect');
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END
$fn$;
