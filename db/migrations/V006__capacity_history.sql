-- V006 — Historical Capacity: ringkasan harian per disk pool (appliance).
-- Grafik riwayat (harian … tahunan) membaca tabel ini, bukan jutaan snapshot 10-menitan:
-- 35 pool × 365 hari ≈ 13 ribu baris/tahun. Diisi dari snapshot oleh capacity.rollup_disk_pool_daily
-- (dipanggil job kapasitas setiap collect dan job maintenance untuk catch-up).

CREATE TABLE capacity.disk_pool_daily (
    day            date          NOT NULL,
    site           text          NOT NULL,
    master         text          NOT NULL,
    disk_pool_name text          NOT NULL,
    usable_tb      numeric(14,2) NOT NULL CHECK (usable_tb >= 0),
    available_tb   numeric(14,2) NOT NULL CHECK (available_tb >= 0),
    used_tb        numeric(14,2) NOT NULL CHECK (used_tb >= 0),
    usage_pct      numeric(7,2)  NOT NULL CHECK (usage_pct >= 0),
    max_used_tb    numeric(14,2) NOT NULL CHECK (max_used_tb >= 0),
    max_usage_pct  numeric(7,2)  NOT NULL CHECK (max_usage_pct >= 0),
    samples        integer       NOT NULL CHECK (samples >= 1),
    source         text          NOT NULL DEFAULT 'collect' CHECK (source IN ('collect', 'demo')),
    updated_at     timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (master, disk_pool_name, day)
);
COMMENT ON TABLE capacity.disk_pool_daily IS
    'Per disk pool per hari (Asia/Jakarta): nilai akhir hari + puncak. source=demo = data contoh DEV';
COMMENT ON COLUMN capacity.disk_pool_daily.source IS 'collect = dari snapshot asli; demo = data contoh (scripts/dev)';

CREATE INDEX disk_pool_daily_day_ix ON capacity.disk_pool_daily (day);
CREATE INDEX disk_pool_daily_site_day_ix ON capacity.disk_pool_daily (site, day);

-- Ringkas snapshot run sukses/parsial menjadi baris harian. Idempoten; data asli menimpa data contoh.
CREATE FUNCTION capacity.rollup_disk_pool_daily(p_from date, p_to date)
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
              JOIN core.collect_run r ON r.id = s.run_id AND r.status IN ('success', 'partial')
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
COMMENT ON FUNCTION capacity.rollup_disk_pool_daily IS
    'Snapshot → ringkasan harian untuk rentang tanggal (Asia/Jakarta); return jumlah baris yang berubah';

GRANT SELECT, INSERT, UPDATE, DELETE ON capacity.disk_pool_daily TO atlas_app;   -- DELETE: hapus data contoh
REVOKE ALL ON FUNCTION capacity.rollup_disk_pool_daily FROM PUBLIC;
GRANT EXECUTE ON FUNCTION capacity.rollup_disk_pool_daily TO atlas_app;
GRANT SELECT ON capacity.disk_pool_daily TO atlas_web, atlas_readonly;
