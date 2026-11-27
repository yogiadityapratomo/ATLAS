-- V004 — menu Audit Log & retensi partisi (design 05 §3–4, plan 04 PR-5).

-- Job maintenance tercatat di core.collect_run seperti job lain.
ALTER TABLE core.collect_run DROP CONSTRAINT collect_run_source_check;
ALTER TABLE core.collect_run ADD CONSTRAINT collect_run_source_check
    CHECK (source IN ('capacity', 'tape', 'backup_inventory', 'cmdb', 'maintenance'));

-- Retensi = DROP partisi bulanan yang seluruh isinya lebih tua dari batas (instan, tanpa DELETE besar).
-- SECURITY DEFINER milik atlas_owner: aplikasi tidak punya hak DROP; fungsi ini hanya bisa menghapus
-- partisi bulanan (bukan DEFAULT, bukan tabel lain) dari tabel yang ada di daftar izin.
CREATE FUNCTION core.drop_old_partitions(parent regclass, older_than timestamptz)
RETURNS SETOF text
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $fn$
DECLARE
    v_part  record;
    v_upper timestamptz;
    v_name  text;
BEGIN
    IF parent::text NOT IN ('audit.event', 'capacity.disk_pool_snapshot', 'capacity.tape_library_snapshot') THEN
        RAISE EXCEPTION 'tabel % tidak diizinkan untuk retensi', parent;
    END IF;
    IF older_than > now() - interval '28 days' THEN
        RAISE EXCEPTION 'batas retensi % terlalu baru (minimal 28 hari)', older_than;
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('atlas.partitions.' || parent::text, 0));
    FOR v_part IN
        SELECT c.oid::regclass AS rel, pg_get_expr(c.relpartbound, c.oid) AS bound
          FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
         WHERE i.inhparent = parent
    LOOP
        CONTINUE WHEN v_part.bound = 'DEFAULT';
        v_upper := substring(v_part.bound FROM $$TO \('([^']+)'\)$$)::timestamptz;
        IF v_upper IS NOT NULL AND v_upper <= older_than THEN
            v_name := v_part.rel::text;   -- simpan nama sebelum tabel hilang
            EXECUTE format('DROP TABLE %s', v_name);
            RETURN NEXT v_name;
        END IF;
    END LOOP;
END
$fn$;
COMMENT ON FUNCTION core.drop_old_partitions IS
    'Drop partisi bulanan yang batas atasnya <= older_than (hanya tabel di daftar izin, minimal 28 hari)';
REVOKE ALL ON FUNCTION core.drop_old_partitions FROM PUBLIC;
GRANT EXECUTE ON FUNCTION core.drop_old_partitions TO atlas_app;
