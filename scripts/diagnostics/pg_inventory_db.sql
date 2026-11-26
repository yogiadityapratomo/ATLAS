-- pg_inventory_db.sql — READ-ONLY. Struktur satu database (dijalankan per database oleh pg_inventory.ps1).
\set QUIET on
\pset pager off
\pset null '(null)'
\set QUIET off

\qecho '================================================================'
\qecho ' DATABASE:' :DBNAME
\qecho '================================================================'
select current_database() as database, pg_size_pretty(pg_database_size(current_database())) as size,
       pg_encoding_to_char(encoding) as encoding
from pg_database where datname = current_database();

\qecho '--- 1. Extension terpasang'
select e.extname, e.extversion, n.nspname as schema
from pg_extension e join pg_namespace n on n.oid = e.extnamespace
order by 1;

\qecho '--- 2. Schema'
select n.nspname as schema, pg_get_userbyid(n.nspowner) as owner, n.nspacl as acl
from pg_namespace n
where n.nspname !~ '^pg_' and n.nspname <> 'information_schema'
order by 1;

\qecho '--- 3. Jumlah objek per schema'
select n.nspname as schema,
       case c.relkind when 'r' then 'table' when 'p' then 'partitioned table' when 'v' then 'view'
                      when 'm' then 'materialized view' when 'S' then 'sequence' when 'f' then 'foreign table'
                      when 'i' then 'index' when 'I' then 'partitioned index' end as kind,
       count(*) as jumlah
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where n.nspname !~ '^pg_' and n.nspname <> 'information_schema'
  and c.relkind in ('r','p','v','m','S','f','i','I')
group by 1, 2 order by 1, 2;

\qecho '--- 4. Tabel: ukuran, jumlah baris, PK, statistik vacuum/analyze'
select n.nspname as schema, c.relname as tbl,
       case c.relkind when 'p' then 'partitioned' when 'f' then 'foreign' else 'table' end as kind,
       pg_get_userbyid(c.relowner) as owner,
       c.reltuples::bigint as est_rows, s.n_live_tup as live_rows, s.n_dead_tup as dead_rows,
       pg_size_pretty(pg_total_relation_size(c.oid)) as total_size,
       pg_size_pretty(pg_relation_size(c.oid)) as table_size,
       pg_size_pretty(pg_indexes_size(c.oid)) as index_size,
       exists (select 1 from pg_constraint k where k.conrelid = c.oid and k.contype = 'p') as has_pk,
       c.relispartition as is_partition,
       date_trunc('second', greatest(s.last_vacuum, s.last_autovacuum)) as last_vacuum,
       date_trunc('second', greatest(s.last_analyze, s.last_autoanalyze)) as last_analyze
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
left join pg_stat_user_tables s on s.relid = c.oid
where c.relkind in ('r','p','f') and n.nspname !~ '^pg_' and n.nspname <> 'information_schema'
order by pg_total_relation_size(c.oid) desc;

\qecho '--- 5. Kolom (tabel, view, materialized view)'
select n.nspname as schema, c.relname as tbl, a.attnum as ord, a.attname as col,
       format_type(a.atttypid, a.atttypmod) as data_type, a.attnotnull as not_null,
       pg_get_expr(d.adbin, d.adrelid) as default_value,
       nullif(a.attidentity, '') as identity, nullif(a.attgenerated, '') as generated
from pg_attribute a
join pg_class c on c.oid = a.attrelid
join pg_namespace n on n.oid = c.relnamespace
left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum
where a.attnum > 0 and not a.attisdropped
  and c.relkind in ('r','p','v','m','f')
  and n.nspname !~ '^pg_' and n.nspname <> 'information_schema'
order by 1, 2, 3;

\qecho '--- 6. Constraint (PK, FK, UNIQUE, CHECK, EXCLUDE)'
select n.nspname as schema, c.relname as tbl, k.conname as constraint_name,
       case k.contype when 'p' then 'PK' when 'f' then 'FK' when 'u' then 'UNIQUE'
                      when 'c' then 'CHECK' when 'x' then 'EXCLUDE' else k.contype::text end as type,
       pg_get_constraintdef(k.oid) as definition
from pg_constraint k
join pg_class c on c.oid = k.conrelid
join pg_namespace n on n.oid = c.relnamespace
where n.nspname !~ '^pg_' and n.nspname <> 'information_schema' and k.contype in ('p','f','u','c','x')
order by 1, 2, 4, 3;

\qecho '--- 7. Index (ukuran, dipakai berapa kali, valid)'
select n.nspname as schema, t.relname as tbl, i.relname as index_name,
       pg_size_pretty(pg_relation_size(i.oid)) as size, coalesce(s.idx_scan, 0) as scans,
       x.indisunique as uniq, x.indisprimary as pk, x.indisvalid as valid,
       pg_get_indexdef(i.oid) as definition
from pg_index x
join pg_class i on i.oid = x.indexrelid
join pg_class t on t.oid = x.indrelid
join pg_namespace n on n.oid = t.relnamespace
left join pg_stat_user_indexes s on s.indexrelid = i.oid
where n.nspname !~ '^pg_' and n.nspname <> 'information_schema'
order by 1, 2, 3;

\qecho '--- 8. View & materialized view (definisi lengkap ada di file schema_*.sql)'
select n.nspname as schema, c.relname as name,
       case c.relkind when 'v' then 'view' else 'materialized view' end as kind,
       pg_get_userbyid(c.relowner) as owner
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where c.relkind in ('v','m') and n.nspname !~ '^pg_' and n.nspname <> 'information_schema'
order by 1, 2;

\qecho '--- 9. Function & procedure (di luar extension)'
select n.nspname as schema, p.proname as name,
       case p.prokind when 'f' then 'function' when 'p' then 'procedure'
                      when 'a' then 'aggregate' when 'w' then 'window' end as kind,
       pg_get_function_identity_arguments(p.oid) as args, pg_get_function_result(p.oid) as returns,
       l.lanname as lang, p.prosecdef as security_definer, pg_get_userbyid(p.proowner) as owner
from pg_proc p
join pg_namespace n on n.oid = p.pronamespace
join pg_language l on l.oid = p.prolang
where n.nspname !~ '^pg_' and n.nspname <> 'information_schema'
  and not exists (select 1 from pg_depend d where d.objid = p.oid and d.deptype = 'e')
order by 1, 2;

\qecho '--- 10. Trigger'
select n.nspname as schema, c.relname as tbl, t.tgname as trigger_name, t.tgenabled as enabled,
       pg_get_triggerdef(t.oid) as definition
from pg_trigger t
join pg_class c on c.oid = t.tgrelid
join pg_namespace n on n.oid = c.relnamespace
where not t.tgisinternal
order by 1, 2, 3;

\qecho '--- 11. Sequence'
select schemaname, sequencename, sequenceowner, data_type, last_value, max_value, increment_by, cycle
from pg_sequences
order by 1, 2;

\qecho '--- 12. Hak akses tabel/view per role (GRANT)'
select table_schema, table_name, grantee,
       string_agg(privilege_type, ',' order by privilege_type) as privileges
from information_schema.role_table_grants
where table_schema not in ('pg_catalog','information_schema')
group by 1, 2, 3
order by 1, 2, 3;

\qecho '--- 13. Default privileges'
select pg_get_userbyid(d.defaclrole) as role, n.nspname as schema, d.defaclobjtype as obj_type, d.defaclacl as acl
from pg_default_acl d left join pg_namespace n on n.oid = d.defaclnamespace
order by 1, 2;

\qecho '--- 14. Row level security'
select n.nspname as schema, c.relname as tbl, c.relforcerowsecurity as forced
from pg_class c join pg_namespace n on n.oid = c.relnamespace
where c.relrowsecurity order by 1, 2;
select schemaname, tablename, policyname, permissive, roles, cmd from pg_policies order by 1, 2, 3;

\qecho '--- 15. Publication / subscription (logical replication)'
select pubname, pg_get_userbyid(pubowner) as owner, puballtables from pg_publication order by 1;
select subname, subenabled from pg_subscription
where subdbid = (select oid from pg_database where datname = current_database())
order by 1;

\qecho '--- 16. Pola akses tabel (30 teratas menurut sequential scan)'
select schemaname, relname as tbl, seq_scan, idx_scan, n_tup_ins, n_tup_upd, n_tup_del
from pg_stat_user_tables
order by seq_scan desc nulls last
limit 30;

\qecho '================================================================'
\qecho ' SELESAI (database)' :DBNAME
\qecho '================================================================'
