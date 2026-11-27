-- V003 — backup inventory (design 03 §4, plan 04 PR-4).
-- Sumber: policy_cache.json (kontrak tidak berubah). Hanya data terbaru; riwayat lewat core.collect_run.
-- Penulisan berbasis diff: kunci alami (master, policy, host, schedule) + row_hash → hanya baris
-- yang berubah yang ditulis (pola lama dbbackup: TRUNCATE + 7.500 INSERT setiap run).

CREATE SCHEMA nbu;
COMMENT ON SCHEMA nbu IS 'Data NetBackup (backup inventory dari policy_cache.json)';
REVOKE ALL ON SCHEMA nbu FROM PUBLIC;
GRANT USAGE ON SCHEMA nbu TO atlas_app, atlas_web, atlas_readonly;

CREATE TABLE nbu.backup_inventory (
    id                bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    master_server     text        NOT NULL,
    policy_name       text        NOT NULL,
    policy_type       text        NOT NULL,
    client_host       text        NOT NULL,
    client_host_norm  text        GENERATED ALWAYS AS (lower(btrim(client_host))) STORED,
    client_os         text        NOT NULL,
    client_hw         text        NOT NULL,
    storage           text        NOT NULL,
    volume_pool       text        NOT NULL,
    backup_selections text        NOT NULL,
    schedule_name     text        NOT NULL,
    schedule_days     text        NOT NULL,
    backup_type       text        NOT NULL,
    start_times       text        NOT NULL,
    retention_period  text        NOT NULL,
    row_hash          text        NOT NULL CHECK (row_hash ~ '^[0-9a-f]{32}$'),
    run_id            bigint      NOT NULL REFERENCES core.collect_run (id),
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT backup_inventory_key_uq UNIQUE (master_server, policy_name, client_host_norm, schedule_name)
) WITH (fillfactor = 90);   -- ruang untuk HOT update
COMMENT ON TABLE nbu.backup_inventory IS
    'Satu baris per policy x client x schedule; hari 1 = Minggu (design 03 §2). run_id = run terakhir yang mengubah';

CREATE INDEX backup_inventory_host_trgm ON nbu.backup_inventory USING gin (client_host_norm public.gin_trgm_ops);
CREATE INDEX backup_inventory_master_type_ix ON nbu.backup_inventory (master_server, policy_type);

-- ------------------------------------------------------------------ view pencarian (dihitung sekali per load)
CREATE MATERIALIZED VIEW report.backup_inventory_search AS
SELECT b.id,
       b.client_host, b.client_host_norm,
       c.app_names, c.pics, c.app_priorities, c.environments, c.sites, c.vm_baremetal, c.ip_oam, c.ip_service,
       b.policy_name, b.policy_type, b.schedule_name, b.schedule_days, b.start_times, b.retention_period,
       b.backup_type, b.storage, b.volume_pool, b.backup_selections, b.client_os, b.client_hw, b.master_server
  FROM nbu.backup_inventory b
  LEFT JOIN report.cmdb_host c ON c.hostname_norm = b.client_host_norm
WITH DATA;
COMMENT ON MATERIALIZED VIEW report.backup_inventory_search IS
    'Backup inventory + CMDB (aplikasi digabung per host). Refresh CONCURRENTLY oleh job inventory & import CMDB';

CREATE UNIQUE INDEX backup_inventory_search_id_uq ON report.backup_inventory_search (id);   -- syarat CONCURRENTLY
CREATE INDEX backup_inventory_search_host_trgm ON report.backup_inventory_search
    USING gin (client_host_norm public.gin_trgm_ops);
CREATE INDEX backup_inventory_search_host_ix ON report.backup_inventory_search (client_host_norm);
CREATE INDEX backup_inventory_search_filter_ix ON report.backup_inventory_search (master_server, policy_type);

-- ------------------------------------------------------------------ hak akses
GRANT SELECT, INSERT, UPDATE, DELETE ON nbu.backup_inventory TO atlas_app;
GRANT MAINTAIN ON nbu.backup_inventory TO atlas_app;                    -- ANALYZE
GRANT SELECT, MAINTAIN ON report.backup_inventory_search TO atlas_app;  -- REFRESH MATERIALIZED VIEW
GRANT SELECT ON nbu.backup_inventory, report.backup_inventory_search TO atlas_web, atlas_readonly;
