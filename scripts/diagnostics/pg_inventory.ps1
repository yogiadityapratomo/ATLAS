<#
.SYNOPSIS
  pg_inventory.ps1 — READ-ONLY inventory konfigurasi & struktur PostgreSQL.

.DESCRIPTION
  Mengumpulkan, TANPA mengubah apa pun:
    01_server.txt           setting, pg_hba, role (tanpa hash password), database, koneksi, replikasi
    02_*.conf               isi postgresql.conf, postgresql.auto.conf, pg_hba.conf, pg_ident.conf
    10_db_<nama>.txt        struktur per database: tabel, kolom, constraint, index, view, function,
                            trigger, sequence, grant, RLS, statistik
    20_schema_<nama>.sql    DDL lengkap per database (pg_dump --schema-only, TANPA data)
    30_globals.sql          role & tablespace (pg_dumpall --globals-only --no-role-passwords)
    run.log                 log eksekusi
  Hasil dikompres menjadi satu file .zip.

  Keamanan:
    - Setiap sesi dipaksa read-only (default_transaction_read_only=on).
    - Password ditanyakan saat jalan (tidak ditulis di skrip/file), lalu dihapus dari memori proses.
    - Tidak mengambil isi data tabel maupun teks query yang sedang berjalan.
    - Hash password role tidak diambil.

  Catatan lock: pg_dump --schema-only memegang lock ACCESS SHARE sebentar (hitungan detik).
  Jalankan di luar jadwal proses yang melakukan TRUNCATE/ALTER (mis. loader DB tiap menit ke-x0:50).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\pg_inventory.ps1
  powershell -ExecutionPolicy Bypass -File .\pg_inventory.ps1 -PgHost localhost -Port 5432 -User postgres
#>
param(
    [string]$PgHost  = 'localhost',
    [int]   $Port    = 5432,
    [string]$User    = 'postgres',
    [string]$OutRoot = '',
    [string]$PgBin   = ''
)

$ErrorActionPreference = 'Continue'
$here      = Split-Path -Parent $MyInvocation.MyCommand.Path
$serverSql = Join-Path $here 'pg_inventory_server.sql'
$dbSql     = Join-Path $here 'pg_inventory_db.sql'
if (-not $OutRoot) { $OutRoot = Join-Path $here 'pg_inventory_output' }

foreach ($f in @($serverSql, $dbSql)) {
    if (-not (Test-Path $f)) { Write-Host "ERROR: file $f tidak ditemukan (taruh di folder yang sama dengan skrip ini)"; exit 2 }
}

# --- Cari folder bin PostgreSQL (versi tertinggi) ---
if (-not $PgBin) {
    $cand = Get-ChildItem 'C:\Program Files\PostgreSQL\*\bin\psql.exe' -ErrorAction SilentlyContinue |
            Sort-Object { [int](($_.Directory.Parent.Name) -replace '\D', '0') } -Descending |
            Select-Object -First 1
    if ($cand) { $PgBin = $cand.DirectoryName }
}
$psql      = Join-Path $PgBin 'psql.exe'
$pgdump    = Join-Path $PgBin 'pg_dump.exe'
$pgdumpall = Join-Path $PgBin 'pg_dumpall.exe'
foreach ($exe in @($psql, $pgdump, $pgdumpall)) {
    if (-not (Test-Path $exe)) { Write-Host "ERROR: $exe tidak ditemukan. Isi parameter -PgBin, contoh: -PgBin 'C:\Program Files\PostgreSQL\18\bin'"; exit 2 }
}

$stamp  = Get-Date -Format 'yyyyMMdd_HHmmss'
$safeHost = $PgHost -replace '[^\w\.-]', '_'
$out    = Join-Path $OutRoot "pg_inventory_${safeHost}_$stamp"
New-Item -ItemType Directory -Force $out | Out-Null
$logFile = Join-Path $out 'run.log'

function Log([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding UTF8
}

# --- Environment koneksi (berlaku untuk psql/pg_dump yang dipanggil skrip ini saja) ---
$promptedPw = $false
if (-not $env:PGPASSWORD) {
    $sec  = Read-Host "Password untuk user '$User' di $PgHost`:$Port" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec)
    $env:PGPASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    $promptedPw = $true
}
$env:PGHOST           = $PgHost
$env:PGPORT           = "$Port"
$env:PGUSER           = $User
$env:PGAPPNAME        = 'atlas-pg-inventory'
$env:PGCLIENTENCODING = 'UTF8'
$env:PGOPTIONS        = '-c default_transaction_read_only=on -c statement_timeout=120000'

$exitCode = 0
try {
    Log "Mulai inventory READ-ONLY -> $out"
    Log "Binary: $PgBin | target: $User@$PgHost`:$Port"

    # 1. Tes koneksi
    $ver = & $psql -X -d postgres -tAc "select current_setting('server_version') || ' | read_only=' || current_setting('default_transaction_read_only')"
    if ($LASTEXITCODE -ne 0 -or -not $ver) {
        Log 'ERROR: koneksi gagal (cek host/port/password/pg_hba).'
        throw 'koneksi gagal'
    }
    Log "Terhubung. Server version: $ver"

    # 2. Konfigurasi server
    & $psql -X -d postgres -v ON_ERROR_STOP=0 -f $serverSql -o (Join-Path $out '01_server.txt') 2>> $logFile
    Log "01_server.txt selesai (exit $LASTEXITCODE)"

    # 3. Isi file konfigurasi (dibaca via pg_read_file, butuh superuser / pg_read_server_files)
    $confs = [ordered]@{
        '02_postgresql.conf'      = "current_setting('config_file')"
        '02_postgresql.auto.conf' = "current_setting('data_directory') || '/postgresql.auto.conf'"
        '02_pg_hba.conf'          = "current_setting('hba_file')"
        '02_pg_ident.conf'        = "current_setting('ident_file')"
    }
    foreach ($k in $confs.Keys) {
        & $psql -X -d postgres -tA -c "select pg_read_file($($confs[$k]))" -o (Join-Path $out $k) 2>> $logFile
        Log "$k (exit $LASTEXITCODE)"
    }

    # 4. Daftar database
    $dbs = & $psql -X -d postgres -tAc "select datname from pg_database where datallowconn and not datistemplate order by 1"
    $dbs = @($dbs | Where-Object { $_ -and $_.Trim() })
    Log ("Database: " + ($dbs -join ', '))

    # 5. Per database: inventory + DDL
    foreach ($db in $dbs) {
        $safe = $db -replace '[^\w\-]', '_'
        & $psql -X -d $db -v ON_ERROR_STOP=0 -f $dbSql -o (Join-Path $out "10_db_$safe.txt") 2>> $logFile
        Log "10_db_$safe.txt (exit $LASTEXITCODE)"
        & $pgdump --schema-only --lock-wait-timeout=10000 -d $db -f (Join-Path $out "20_schema_$safe.sql") 2>> $logFile
        Log "20_schema_$safe.sql (exit $LASTEXITCODE)"
    }

    # 6. Role & tablespace (tanpa password)
    & $pgdumpall --globals-only --no-role-passwords -f (Join-Path $out '30_globals.sql') 2>> $logFile
    Log "30_globals.sql (exit $LASTEXITCODE)"

    # 7. Ringkasan + zip
    Get-ChildItem $out -File | Sort-Object Name | ForEach-Object { Log ("  {0,-34} {1,10:N0} bytes" -f $_.Name, $_.Length) }
    $zip = "$out.zip"
    Compress-Archive -Path (Join-Path $out '*') -DestinationPath $zip -Force
    Log "ZIP: $zip"
    Write-Host ""
    Write-Host "Selesai. Kirim file ini untuk dianalisis: $zip"
}
catch {
    Log "BERHENTI: $_"
    $exitCode = 1
}
finally {
    if ($promptedPw) { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
    Remove-Item Env:PGOPTIONS -ErrorAction SilentlyContinue
}
exit $exitCode
