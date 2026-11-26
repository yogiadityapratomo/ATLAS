-- pg_inventory_server.sql — READ-ONLY. Konfigurasi level server/cluster PostgreSQL.
-- Dijalankan oleh pg_inventory.ps1 terhadap database 'postgres'.
\set QUIET on
\pset pager off
\pset null '(null)'
\set QUIET off

\qecho '================================================================'
\qecho ' 1. SERVER'
\qecho '================================================================'
select version();
select pg_postmaster_start_time() as started,
       date_trunc('second', now() - pg_postmaster_start_time()) as uptime,
       pg_is_in_recovery() as is_standby,
       current_setting('data_directory') as data_directory,
       current_setting('config_file')    as config_file,
       current_setting('hba_file')       as hba_file;

\qecho '================================================================'
\qecho ' 2. SETTING PENTING'
\qecho '================================================================'
select name, setting, unit, source, pending_restart
from pg_settings
where name in ('listen_addresses','port','max_connections','superuser_reserved_connections',
               'shared_buffers','effective_cache_size','work_mem','maintenance_work_mem',
               'max_worker_processes','max_parallel_workers','max_parallel_workers_per_gather',
               'wal_level','max_wal_size','min_wal_size','checkpoint_timeout','archive_mode','archive_command',
               'max_wal_senders','hot_standby','synchronous_commit',
               'ssl','password_encryption','authentication_timeout',
               'statement_timeout','idle_in_transaction_session_timeout','idle_session_timeout','lock_timeout',
               'autovacuum','autovacuum_max_workers','autovacuum_naptime',
               'logging_collector','log_destination','log_directory','log_filename','log_rotation_age',
               'log_rotation_size','log_min_duration_statement','log_connections','log_disconnections',
               'log_line_prefix','log_timezone','timezone','datestyle','lc_messages',
               'shared_preload_libraries','default_transaction_isolation','server_encoding')
order by name;

\qecho '================================================================'
\qecho ' 3. SEMUA SETTING YANG DIUBAH DARI DEFAULT'
\qecho '================================================================'
select name, setting, unit, source, sourcefile, sourceline, pending_restart
from pg_settings
where source not in ('default','override','client','session')
order by name;

\qecho '================================================================'
\qecho ' 4. MASALAH DI FILE KONFIGURASI (tidak terapkan / error)'
\qecho '================================================================'
select sourcefile, sourceline, name, setting, applied, error
from pg_file_settings
where not applied or error is not null
order by sourcefile, sourceline;

\qecho '================================================================'
\qecho ' 5. ATURAN AKSES pg_hba.conf'
\qecho '================================================================'
select line_number, type, database, user_name, address, netmask, auth_method, options, error
from pg_hba_file_rules
order by line_number;

\qecho '================================================================'
\qecho ' 6. ROLE / USER (tanpa hash password)'
\qecho '================================================================'
select a.rolname, a.rolsuper as super, a.rolcanlogin as login, a.rolcreatedb as createdb,
       a.rolcreaterole as createrole, a.rolreplication as replication, a.rolbypassrls as bypassrls,
       a.rolconnlimit as connlimit, a.rolvaliduntil as valid_until,
       case when a.rolpassword is null then 'tidak ada'
            when a.rolpassword like 'SCRAM-SHA-256$%' then 'scram-sha-256'
            when a.rolpassword like 'md5%' then 'md5'
            else 'lain' end as password_type
from pg_authid a
where a.rolname !~ '^pg_'
order by a.rolname;

\qecho '--- Keanggotaan role'
select r.rolname as role, m.rolname as member, g.rolname as grantor, am.admin_option
from pg_auth_members am
join pg_roles r on r.oid = am.roleid
join pg_roles m on m.oid = am.member
left join pg_roles g on g.oid = am.grantor
order by 1, 2;

\qecho '--- Setting khusus per role / database'
select coalesce(d.datname, '(semua db)') as database, coalesce(r.rolname, '(semua role)') as role, s.setconfig
from pg_db_role_setting s
left join pg_database d on d.oid = s.setdatabase
left join pg_roles r on r.oid = s.setrole
order by 1, 2;

\qecho '================================================================'
\qecho ' 7. DATABASE'
\qecho '================================================================'
select d.datname, pg_get_userbyid(d.datdba) as owner, pg_encoding_to_char(d.encoding) as encoding,
       d.datlocprovider as loc_provider, d.datcollate as collate, d.datctype as ctype,
       d.datallowconn as allow_conn, d.datconnlimit as connlimit,
       pg_size_pretty(pg_database_size(d.oid)) as size, d.datacl as acl
from pg_database d
order by pg_database_size(d.oid) desc;

\qecho '--- Tablespace'
select spcname, pg_get_userbyid(spcowner) as owner, pg_tablespace_location(oid) as location,
       pg_size_pretty(pg_tablespace_size(oid)) as size
from pg_tablespace
order by 1;

\qecho '================================================================'
\qecho ' 8. KONEKSI SAAT INI (ringkasan, tanpa isi query)'
\qecho '================================================================'
select count(*) as total_koneksi, current_setting('max_connections') as max_connections
from pg_stat_activity where backend_type = 'client backend';

select datname, usename, application_name, client_addr, state, count(*) as jumlah
from pg_stat_activity
where backend_type = 'client backend'
group by 1, 2, 3, 4, 5
order by jumlah desc;

\qecho '--- Query/transaksi berjalan > 1 menit'
select pid, datname, usename, application_name, state,
       date_trunc('second', now() - xact_start) as umur_transaksi,
       date_trunc('second', now() - query_start) as umur_query, wait_event_type, wait_event
from pg_stat_activity
where backend_type = 'client backend' and state <> 'idle'
  and (now() - query_start > interval '1 minute' or now() - xact_start > interval '1 minute')
order by query_start;

\qecho '================================================================'
\qecho ' 9. REPLIKASI, WAL, CHECKPOINT'
\qecho '================================================================'
select application_name, client_addr, state, sync_state, write_lag, flush_lag, replay_lag from pg_stat_replication;
select slot_name, slot_type, database, active, wal_status from pg_replication_slots;
select archived_count, last_archived_time, failed_count, last_failed_time from pg_stat_archiver;
select * from pg_stat_checkpointer;

\qecho '================================================================'
\qecho ' SELESAI (server)'
\qecho '================================================================'
