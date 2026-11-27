-- V008 — Historical Capacity: gabungkan disk pool menjadi APPLIANCE (host NetBackup appliance).
-- Satu appliance bisa punya beberapa disk pool, mis. dp_disk_brnnbupapp07 + dp_disk_brnnbupapp7-worm
-- + stu_disk_brnnbupapp08. Aturan (satu tempat, dipakai grouping & filter):
--   1. buang awalan dp_disk_ / stu_disk_      2. buang akhiran -worm
--   3. buang nol di depan angka (app07 = app7)    4. huruf kecil

CREATE FUNCTION capacity.appliance_name(pool_name text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
RETURN lower(
    regexp_replace(
        regexp_replace(regexp_replace(btrim(pool_name), '^(dp|stu)_disk_', '', 'i'), '-worm$', '', 'i'),
        '([a-z])0+([0-9])', '\1\2', 'gi'
    )
);
COMMENT ON FUNCTION capacity.appliance_name IS
    'Nama appliance dari nama disk pool: tanpa dp_disk_/stu_disk_, tanpa -worm, tanpa nol di depan angka';

ALTER TABLE capacity.disk_pool_daily
    ADD COLUMN appliance text GENERATED ALWAYS AS (capacity.appliance_name(disk_pool_name)) STORED;
CREATE INDEX disk_pool_daily_appliance_ix ON capacity.disk_pool_daily (appliance, day);

GRANT EXECUTE ON FUNCTION capacity.appliance_name TO atlas_app, atlas_web, atlas_readonly;
