-- V005 — selfcheck rilis (deployment-workflow §4.2 langkah 6) perlu membaca versi schema
-- dengan role aplikasi, tanpa memakai atlas_migrator.
GRANT SELECT ON core.schema_migrations TO atlas_app, atlas_web, atlas_readonly;
