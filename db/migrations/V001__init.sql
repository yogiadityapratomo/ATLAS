-- V001 — fondasi ATLAS: core (collect_run, partisi), audit (event log), cmdb, report.
-- Design: docs/03-design-db-dashboard.md §4, docs/05-design-audit-log.md §3.
-- Dijalankan oleh scripts/db/migrate.py sebagai atlas_owner, dalam satu transaksi.
-- Tabel capacity.* menyusul di V002 (PR-3), nbu.* di V003 (PR-4).

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;   -- index cari-sebagian (ILIKE '%x%')

CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA audit;
CREATE SCHEMA cmdb;
CREATE SCHEMA report;
COMMENT ON SCHEMA core   IS 'Status job (collect_run), migrasi, utilitas bersama';
COMMENT ON SCHEMA audit  IS 'Audit & event log (append-only bagi aplikasi)';
COMMENT ON SCHEMA cmdb   IS 'Data CMDB dari Excel OSPLA Master Inventory';
COMMENT ON SCHEMA report IS 'View siap pakai untuk web';

-- =====================================================================================
-- core.collect_run — satu baris per eksekusi job (capacity, tape, backup_inventory, cmdb)
-- =====================================================================================
CREATE TABLE core.collect_run (
    id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source        text        NOT NULL CHECK (source IN ('capacity', 'tape', 'backup_inventory', 'cmdb')),
    status        text        NOT NULL DEFAULT 'running'
                              CHECK (status IN ('running', 'success', 'partial', 'failed')),
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    rows_total    integer     CHECK (rows_total >= 0),
    rows_inserted integer     CHECK (rows_inserted >= 0),
    rows_updated  integer     CHECK (rows_updated >= 0),
    rows_deleted  integer     CHECK (rows_deleted >= 0),
    request_id    uuid,
    error_id      text        CHECK (error_id ~ '^ERR-[0-9A-F]{6}$'),
    error_message text,
    host          text,
    details       jsonb       NOT NULL DEFAULT '{}',
    CONSTRAINT collect_run_finished_ck CHECK ((status = 'running') = (finished_at IS NULL)),
    CONSTRAINT collect_run_error_ck    CHECK (status <> 'failed' OR error_id IS NOT NULL)
);
COMMENT ON TABLE core.collect_run IS 'Riwayat eksekusi job; data_version = id run sukses terakhir per source';

-- run sukses terakhir per source (dasar data_version, "Data per ...", /api/health)
CREATE INDEX collect_run_latest_ok_ix ON core.collect_run (source, finished_at DESC)
    WHERE status IN ('success', 'partial');
CREATE INDEX collect_run_started_ix ON core.collect_run (started_at DESC);

-- =====================================================================================
-- core.ensure_monthly_partitions — buat partisi bulanan (idempoten, aman dipanggil bersamaan)
-- Dipanggil migrasi, penulis audit saat start, dan job maintenance. Jika partisi DEFAULT
-- sudah menampung baris untuk bulan itu, baris dipindah ke partisi baru (tidak ada data hilang).
-- =====================================================================================
CREATE FUNCTION core.ensure_monthly_partitions(
    parent regclass, months_back integer DEFAULT 1, months_ahead integer DEFAULT 3
) RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET timezone = 'Asia/Jakarta'
AS $fn$
DECLARE
    v_nsp     text;
    v_rel     text;
    v_key     text;
    v_default regclass;
    v_month   date;
    v_part    text;
    v_moved   bigint;
    v_created integer := 0;
BEGIN
    SELECT n.nspname, c.relname INTO v_nsp, v_rel
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE c.oid = parent AND c.relkind = 'p';
    IF v_nsp IS NULL THEN
        RAISE EXCEPTION '% bukan tabel partisi', parent;
    END IF;

    SELECT a.attname INTO v_key
      FROM pg_partitioned_table pt
      JOIN pg_attribute a ON a.attrelid = pt.partrelid AND a.attnum = pt.partattrs[0]
     WHERE pt.partrelid = parent AND pt.partstrat = 'r';
    IF v_key IS NULL THEN
        RAISE EXCEPTION '% bukan partisi RANGE satu kolom', parent;
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended('atlas.partitions.' || parent::text, 0));

    SELECT i.inhrelid::regclass INTO v_default
      FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
     WHERE i.inhparent = parent AND pg_get_expr(c.relpartbound, c.oid) = 'DEFAULT';

    FOR v_month IN
        SELECT d::date
          FROM generate_series(date_trunc('month', now()) - make_interval(months => months_back),
                               date_trunc('month', now()) + make_interval(months => months_ahead),
                               interval '1 month') AS d
    LOOP
        v_part := format('%s_%s', v_rel, to_char(v_month, 'YYYY_MM'));
        CONTINUE WHEN to_regclass(format('%I.%I', v_nsp, v_part)) IS NOT NULL;

        v_moved := 0;
        IF v_default IS NOT NULL THEN
            EXECUTE format(
                'CREATE TEMP TABLE atlas_moved ON COMMIT DROP AS '
                'WITH d AS (DELETE FROM %s WHERE %I >= %L::timestamptz AND %I < %L::timestamptz RETURNING *) '
                'SELECT * FROM d',
                v_default, v_key, v_month, v_key, (v_month + interval '1 month')::date);
            GET DIAGNOSTICS v_moved = ROW_COUNT;
        END IF;

        EXECUTE format('CREATE TABLE %I.%I PARTITION OF %s FOR VALUES FROM (%L) TO (%L)',
                       v_nsp, v_part, parent,
                       v_month::timestamptz, (v_month + interval '1 month')::timestamptz);

        IF v_moved > 0 THEN
            EXECUTE format('INSERT INTO %s OVERRIDING SYSTEM VALUE SELECT * FROM atlas_moved', parent);
        END IF;
        DROP TABLE IF EXISTS atlas_moved;
        v_created := v_created + 1;
    END LOOP;
    RETURN v_created;
END
$fn$;
COMMENT ON FUNCTION core.ensure_monthly_partitions IS
    'Buat partisi bulanan [bulan ini - months_back, bulan ini + months_ahead]; return jumlah partisi baru';
REVOKE ALL ON FUNCTION core.ensure_monthly_partitions FROM PUBLIC;

-- =====================================================================================
-- audit.event — audit & event log (design 05 §3.1). Append-only untuk aplikasi.
-- PK (occurred_at, id) sekaligus index urutan waktu & pagination keyset, sehingga BRIN
-- terpisah tidak diperlukan.
-- =====================================================================================
CREATE TABLE audit.event (
    id          bigint      GENERATED ALWAYS AS IDENTITY,
    occurred_at timestamptz NOT NULL,
    category    text        NOT NULL CHECK (category IN ('web', 'app', 'db', 'job', 'security', 'system', 'bot')),
    event_type  text        NOT NULL CHECK (event_type ~ '^[a-z][a-z0-9_]{1,62}$'),
    severity    text        NOT NULL CHECK (severity IN ('debug', 'info', 'warning', 'error', 'critical')),
    component   text        NOT NULL CHECK (component <> ''),
    actor       text,
    request_id  uuid,
    error_id    text        CHECK (error_id ~ '^ERR-[0-9A-F]{6}$'),
    message     text        NOT NULL,
    duration_ms integer     CHECK (duration_ms >= 0),
    details     jsonb       NOT NULL DEFAULT '{}',
    host        text,
    pid         integer,
    app_version text,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (occurred_at, id)
) PARTITION BY RANGE (occurred_at);
COMMENT ON TABLE audit.event IS 'Audit & event log ATLAS; retensi = drop partisi bulanan (design 05 §3)';

CREATE TABLE audit.event_default PARTITION OF audit.event DEFAULT;   -- jaring pengaman
SELECT core.ensure_monthly_partitions('audit.event', 1, 3);

CREATE INDEX event_category_ix  ON audit.event (category, occurred_at DESC);
CREATE INDEX event_component_ix ON audit.event (component, occurred_at DESC);
CREATE INDEX event_errors_ix    ON audit.event (occurred_at DESC) WHERE severity IN ('error', 'critical');
CREATE INDEX event_request_ix   ON audit.event (request_id) WHERE request_id IS NOT NULL;
CREATE INDEX event_error_id_ix  ON audit.event (error_id)   WHERE error_id IS NOT NULL;
CREATE INDEX event_message_trgm ON audit.event USING gin (message public.gin_trgm_ops);

-- =====================================================================================
-- cmdb.server_inventory — Excel OSPLA "Master Inventory"
-- Tidak ada kombinasi kolom bisnis yang unik (hostname sama di beberapa site; 282 baris kembar
-- persis di data 2026-02-03), jadi kunci = row_hash isi baris + jumlah kemunculan (occurrences).
-- Impor ulang tanpa perubahan = 0 baris ditulis.
-- =====================================================================================
CREATE TABLE cmdb.server_inventory (
    id            bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    row_hash      text        NOT NULL CHECK (row_hash ~ '^[0-9a-f]{32}$'),
    occurrences   integer     NOT NULL DEFAULT 1 CHECK (occurrences >= 1),
    hostname      text        NOT NULL CHECK (btrim(hostname) <> ''),
    hostname_norm text        GENERATED ALWAYS AS (lower(btrim(hostname))) STORED,
    ip_oam        text,
    ip_service    text,
    app_name      text,
    pic           text,
    app_priority  text,
    environment   text,
    vm_baremetal  text,
    site          text,
    run_id        bigint      NOT NULL REFERENCES core.collect_run (id),
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT server_inventory_row_hash_uq UNIQUE (row_hash)
) WITH (fillfactor = 90);
COMMENT ON TABLE cmdb.server_inventory IS 'CMDB; satu baris per isi unik. run_id = run terakhir yang mengubah baris';
COMMENT ON COLUMN cmdb.server_inventory.occurrences IS 'Jumlah baris identik di Excel sumber';

CREATE INDEX server_inventory_host_ix     ON cmdb.server_inventory (hostname_norm);
CREATE INDEX server_inventory_host_trgm   ON cmdb.server_inventory USING gin (hostname_norm public.gin_trgm_ops);
CREATE INDEX server_inventory_app_trgm    ON cmdb.server_inventory USING gin (lower(app_name) public.gin_trgm_ops);
CREATE INDEX server_inventory_run_ix      ON cmdb.server_inventory (run_id);

-- =====================================================================================
-- report — view untuk web
-- =====================================================================================
CREATE VIEW report.cmdb_host AS
SELECT s.hostname_norm,
       min(s.hostname)                                                        AS hostname,
       string_agg(DISTINCT s.app_name, ', ' ORDER BY s.app_name)             AS app_names,
       string_agg(DISTINCT s.pic, ', ' ORDER BY s.pic)                       AS pics,
       string_agg(DISTINCT s.app_priority, ', ' ORDER BY s.app_priority)     AS app_priorities,
       string_agg(DISTINCT s.environment, ', ' ORDER BY s.environment)       AS environments,
       string_agg(DISTINCT s.vm_baremetal, ', ' ORDER BY s.vm_baremetal)     AS vm_baremetal,
       string_agg(DISTINCT s.site, ', ' ORDER BY s.site)                     AS sites,
       string_agg(DISTINCT s.ip_oam, ', ' ORDER BY s.ip_oam)                 AS ip_oam,
       string_agg(DISTINCT s.ip_service, ', ' ORDER BY s.ip_service)         AS ip_service,
       sum(s.occurrences)::integer                                            AS source_rows
  FROM cmdb.server_inventory s
 GROUP BY s.hostname_norm;
COMMENT ON VIEW report.cmdb_host IS 'Satu baris per hostname; aplikasi/PIC/site digabung (tanpa baris ganda saat join)';

CREATE VIEW report.app_list AS
SELECT min(s.app_name)                    AS app_name,
       lower(s.app_name)                  AS app_name_norm,
       count(DISTINCT s.hostname_norm)    AS host_count
  FROM cmdb.server_inventory s
 WHERE s.app_name IS NOT NULL
 GROUP BY lower(s.app_name);
COMMENT ON VIEW report.app_list IS 'Daftar aplikasi CMDB + jumlah host (saran otomatis menu Backup Inventory)';

-- =====================================================================================
-- Hak akses (design 03 §4.3 + design 05 §5). Tidak ada UPDATE/DELETE pada audit.event
-- untuk role mana pun selain atlas_owner.
-- =====================================================================================
REVOKE ALL ON SCHEMA core, audit, cmdb, report FROM PUBLIC;
GRANT USAGE ON SCHEMA core, audit, cmdb, report TO atlas_app, atlas_web, atlas_readonly;

-- job / collector
GRANT SELECT, INSERT, UPDATE ON core.collect_run TO atlas_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON cmdb.server_inventory TO atlas_app;
GRANT MAINTAIN ON cmdb.server_inventory TO atlas_app;                 -- ANALYZE setelah impor
GRANT INSERT ON audit.event TO atlas_app;
GRANT SELECT ON ALL TABLES IN SCHEMA report TO atlas_app;
GRANT EXECUTE ON FUNCTION core.ensure_monthly_partitions TO atlas_app;

-- web: baca data dashboard + tulis & baca audit (menu Audit Log)
GRANT SELECT ON core.collect_run, cmdb.server_inventory TO atlas_web;
GRANT SELECT ON ALL TABLES IN SCHEMA report TO atlas_web;
GRANT SELECT, INSERT ON audit.event TO atlas_web;
GRANT EXECUTE ON FUNCTION core.ensure_monthly_partitions TO atlas_web;

-- pembaca lain (read-only)
GRANT SELECT ON core.collect_run, cmdb.server_inventory, audit.event TO atlas_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA report TO atlas_readonly;
