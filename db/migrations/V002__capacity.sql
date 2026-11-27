-- V002 — riwayat kapasitas disk pool & tape library (design 03 §4.1, plan 04 PR-3).
-- Setiap collect = 1 baris core.collect_run (source 'capacity' / 'tape') + snapshot baris.
-- Data lama tidak ditimpa (riwayat); retensi = drop partisi bulanan (PR-5).

CREATE SCHEMA capacity;
COMMENT ON SCHEMA capacity IS 'Riwayat kapasitas disk pool & tape library per collect';
REVOKE ALL ON SCHEMA capacity FROM PUBLIC;
GRANT USAGE ON SCHEMA capacity TO atlas_app, atlas_web, atlas_readonly;

-- ------------------------------------------------------------------ disk pool
CREATE TABLE capacity.disk_pool_snapshot (
    id             bigint        GENERATED ALWAYS AS IDENTITY,
    run_id         bigint        NOT NULL REFERENCES core.collect_run (id),
    collected_at   timestamptz   NOT NULL,
    site           text          NOT NULL CHECK (site <> ''),
    master         text          NOT NULL CHECK (master <> ''),
    disk_pool_name text          NOT NULL CHECK (disk_pool_name <> ''),
    usable_tb      numeric(14,2) NOT NULL CHECK (usable_tb >= 0),
    available_tb   numeric(14,2) NOT NULL CHECK (available_tb >= 0),
    used_tb        numeric(14,2) NOT NULL CHECK (used_tb >= 0),
    usage_pct      numeric(7,2)  NOT NULL CHECK (usage_pct >= 0),
    PRIMARY KEY (collected_at, id),
    UNIQUE (collected_at, run_id, master, disk_pool_name)
) PARTITION BY RANGE (collected_at);
COMMENT ON TABLE capacity.disk_pool_snapshot IS 'Snapshot disk pool (PureDisk) per collect; kolom = JSON V4';

CREATE TABLE capacity.disk_pool_snapshot_default PARTITION OF capacity.disk_pool_snapshot DEFAULT;
SELECT core.ensure_monthly_partitions('capacity.disk_pool_snapshot', 1, 3);
CREATE INDEX disk_pool_snapshot_run_ix ON capacity.disk_pool_snapshot (run_id);
CREATE INDEX disk_pool_snapshot_trend_ix ON capacity.disk_pool_snapshot (master, disk_pool_name, collected_at DESC);

-- ------------------------------------------------------------------ tape library
CREATE TABLE capacity.tape_library_snapshot (
    id               bigint        GENERATED ALWAYS AS IDENTITY,
    run_id           bigint        NOT NULL REFERENCES core.collect_run (id),
    collected_at     timestamptz   NOT NULL,
    site             text          NOT NULL CHECK (site <> ''),
    ip               text          NOT NULL,
    brand            text          NOT NULL,
    library_type     text          NOT NULL,
    model            text          NOT NULL,
    serial_number    text          NOT NULL,
    storage_name     text          NOT NULL,
    domain           text          NOT NULL,
    type_tape        text          NOT NULL CHECK (type_tape <> ''),
    total_qty        integer       NOT NULL CHECK (total_qty >= 0),
    used_qty         integer       NOT NULL CHECK (used_qty >= 0),
    free_qty         integer       NOT NULL CHECK (free_qty >= 0),
    raw_capacity_tb  numeric(14,2) NOT NULL CHECK (raw_capacity_tb >= 0),
    used_capacity_tb numeric(14,2) NOT NULL CHECK (used_capacity_tb >= 0),
    used_pct         numeric(7,2)  NOT NULL CHECK (used_pct BETWEEN 0 AND 100),
    free_pct         numeric(7,2)  NOT NULL CHECK (free_pct BETWEEN 0 AND 100),
    PRIMARY KEY (collected_at, id),
    UNIQUE (collected_at, run_id, site, type_tape),
    CHECK (used_qty + free_qty = total_qty)
) PARTITION BY RANGE (collected_at);
COMMENT ON TABLE capacity.tape_library_snapshot IS 'Snapshot tape library per site & tipe tape per collect; kolom = JSON V4';

CREATE TABLE capacity.tape_library_snapshot_default PARTITION OF capacity.tape_library_snapshot DEFAULT;
SELECT core.ensure_monthly_partitions('capacity.tape_library_snapshot', 1, 3);
CREATE INDEX tape_library_snapshot_run_ix ON capacity.tape_library_snapshot (run_id);

-- ------------------------------------------------------------------ data terbaru
-- Run terakhir yang menghasilkan data (success / partial) per source. Index parsial
-- core.collect_run_latest_ok_ix membuat pencarian ini instan.
CREATE VIEW capacity.latest_run AS
SELECT DISTINCT ON (r.source)
       r.source, r.id AS run_id, r.status, r.finished_at, r.details
  FROM core.collect_run r
 WHERE r.source IN ('capacity', 'tape') AND r.status IN ('success', 'partial')
 ORDER BY r.source, r.finished_at DESC, r.id DESC;
COMMENT ON VIEW capacity.latest_run IS 'Run kapasitas/tape terakhir yang berisi data (dasar data_version & "Data per ...")';

CREATE VIEW capacity.disk_pool_latest AS
SELECT s.*
  FROM capacity.disk_pool_snapshot s
  JOIN capacity.latest_run l ON l.source = 'capacity' AND l.run_id = s.run_id;

CREATE VIEW capacity.tape_library_latest AS
SELECT s.*
  FROM capacity.tape_library_snapshot s
  JOIN capacity.latest_run l ON l.source = 'tape' AND l.run_id = s.run_id;

-- ------------------------------------------------------------------ hak akses
GRANT SELECT, INSERT ON capacity.disk_pool_snapshot, capacity.tape_library_snapshot TO atlas_app;
GRANT SELECT ON capacity.latest_run, capacity.disk_pool_latest, capacity.tape_library_latest TO atlas_app;
GRANT EXECUTE ON FUNCTION core.ensure_monthly_partitions TO atlas_app;
GRANT SELECT ON ALL TABLES IN SCHEMA capacity TO atlas_web, atlas_readonly;
