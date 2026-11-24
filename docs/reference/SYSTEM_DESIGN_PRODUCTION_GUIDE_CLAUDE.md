# System Design & Production Deployment Guide

## Panduan membangun aplikasi dari development sampai production dengan Claude Code

Dokumen ini menjadi panduan kerja untuk merancang, membangun, menguji,
dan men-deploy aplikasi secara terstruktur. Contoh stack yang digunakan
adalah **FastAPI + PostgreSQL + HTML/CSS/JavaScript + GitLab CI/CD +
Docker + Linux + Nginx**. Stack dapat disesuaikan dengan kebutuhan
proyek.

------------------------------------------------------------------------

## 1. Tujuan dan prinsip utama

Tujuan: - Menghasilkan aplikasi yang stabil, aman, mudah dikembangkan,
dan mudah dioperasikan. - Mengurangi risiko perubahan yang merusak fitur
yang sudah berjalan. - Memastikan setiap perubahan melalui proses review
dan testing. - Membuat proses deployment dapat diulang dan memiliki
mekanisme rollback.

Prinsip: 1. Pahami aplikasi dan kebutuhan sebelum mengubah kode. 2. Buat
desain dan rencana implementasi sebelum coding. 3. Pisahkan konfigurasi
dan secret dari source code. 4. Gunakan Git untuk version control dan
code review. 5. Uji perubahan sebelum masuk production. 6. Lakukan
deployment dengan approval dan rollback plan. 7. Jangan mengklaim test
atau deployment berhasil jika belum benar-benar dijalankan dan
diverifikasi.

------------------------------------------------------------------------

## 2. Software Development Lifecycle (SDLC)

Alur kerja yang disarankan:

``` text
Business Requirement
        |
        v
Requirement Analysis
        |
        v
System Design & Architecture
        |
        v
Implementation Plan + Approval
        |
        v
Development (Local / DEV)
        |
        v
Code Review + Automated Tests
        |
        v
Build & CI Pipeline
        |
        v
QA / Staging + UAT
        |
        v
Approval for Production
        |
        v
Deployment + Health Check
        |
        v
Monitoring, Maintenance & Improvement
```

### Tahapan dan hasil yang harus tersedia

  -----------------------------------------------------------------------
  Tahap                   Aktivitas               Output
  ----------------------- ----------------------- -----------------------
  Requirement             Menggali kebutuhan,     PRD / requirement
                          user, proses bisnis,    
                          batasan                 

  Design                  Arsitektur, database,   Design document, ERD,
                          API, keamanan           API spec

  Planning                Pecah pekerjaan,        Implementation plan
                          risiko, urutan          
                          implementasi            

  Development             Coding sesuai desain    Source code

  Testing                 Unit, integration, API, Test report
                          UI, security,           
                          performance             

  CI/CD                   Build, test, scan,      Pipeline
                          package, deploy         

  Staging                 Validasi di lingkungan  UAT sign-off
                          mirip production        

  Production              Deploy, verifikasi,     Release record
                          rollback jika perlu     

  Operations              Monitoring, backup,     Runbook dan laporan
                          incident handling       operasional
  -----------------------------------------------------------------------

------------------------------------------------------------------------

## 3. Requirement dan analisis bisnis

Sebelum coding, pastikan hal berikut jelas:

-   Masalah apa yang ingin diselesaikan?
-   Siapa pengguna aplikasi dan apa peran masing-masing?
-   Fitur apa yang wajib ada dan apa yang tidak termasuk scope?
-   Bagaimana alur kerja pengguna dari awal sampai akhir?
-   Data apa yang dimasukkan, diproses, disimpan, dan ditampilkan?
-   Apakah ada integrasi dengan sistem lain?
-   Berapa perkiraan jumlah user, request, dan volume data?
-   Apa kebutuhan availability, response time, dan keamanan?
-   Bagaimana definisi keberhasilan dan acceptance criteria?

### Contoh use case NetBackup Dashboard

  Role         Contoh kewenangan
  ------------ --------------------------------------------------------------
  L1           Melihat status backup dan melakukan update sesuai kewenangan
  L2           Melakukan analisis dan menangani eskalasi
  Admin        Mengelola user, konfigurasi, dan master data
  Management   Melihat dashboard dan laporan

Setiap fitur sebaiknya memiliki: - Nama dan tujuan fitur. - Aktor/role
yang dapat mengakses. - Input dan output. - Business rules. - Validasi
dan pesan error. - Acceptance criteria. - Risiko dan dependensi.

------------------------------------------------------------------------

## 4. System architecture

### Komponen utama

  -----------------------------------------------------------------------
  Komponen                            Fungsi
  ----------------------------------- -----------------------------------
  Frontend                            Tampilan dan interaksi pengguna

  Backend/API                         Business logic, validasi, dan akses
                                      data

  Database                            Penyimpanan data terstruktur

  Authentication                      Verifikasi identitas pengguna

  Authorization/RBAC                  Pembatasan akses berdasarkan role

  Cache                               Mempercepat akses data yang sering
                                      dibaca

  Background worker                   Menjalankan proses berat atau
                                      terjadwal

  Reverse proxy                       Routing, TLS termination, dan
                                      proteksi dasar

  CI/CD                               Build, test, dan deployment
                                      otomatis

  Monitoring/logging                  Memantau kesehatan aplikasi dan
                                      investigasi masalah
  -----------------------------------------------------------------------

### Contoh arsitektur sederhana

``` text
Users / Browser
      |
      v
HTTPS
      |
      v
Nginx (Reverse Proxy)
      |
      v
Frontend -----> FastAPI Backend
                       |
             +---------+---------+
             |                   |
             v                   v
        PostgreSQL          Background Worker
             |                   |
             +---------+---------+
                       |
                 Logs / Metrics
                       |
                 Monitoring
```

Untuk aplikasi internal yang belum sangat besar, **modular monolith**
biasanya lebih sederhana untuk dibangun dan dioperasikan dibanding
langsung menggunakan microservices. Pisahkan modul berdasarkan domain
bisnis agar tetap mudah dikembangkan.

### Hal yang perlu diputuskan

-   Apakah aplikasi monolith, modular monolith, atau microservices?
-   Bagaimana alur komunikasi frontend, backend, dan database?
-   Bagaimana authentication dan authorization dilakukan?
-   Bagaimana integrasi dengan sistem eksternal?
-   Apa kebutuhan high availability?
-   Apa komponen yang menjadi single point of failure?
-   Bagaimana aplikasi menangani kegagalan dependency?

------------------------------------------------------------------------

## 5. Database design

Database harus dirancang sebelum implementasi fitur yang bergantung pada
data.

Checklist: - Buat ERD (Entity Relationship Diagram). - Tentukan primary
key dan foreign key. - Gunakan tipe data yang sesuai. - Hindari
duplikasi data yang tidak diperlukan. - Terapkan normalisasi secara
wajar. - Buat index berdasarkan pola query nyata. - Gunakan pagination
untuk data berjumlah besar. - Terapkan connection pooling. - Gunakan
migration tool, misalnya Alembic. - Tentukan kebijakan backup,
retention, dan restore test.

### Contoh tabel

``` text
users
- id
- username
- password_hash
- is_active
- created_at

roles
- id
- role_name

user_roles
- user_id
- role_id

applications
- id
- application_name
- owner
- status

servers
- id
- application_id
- hostname
- environment
- status

backup_jobs
- id
- server_id
- policy_name
- job_status
- start_time
- end_time

audit_logs
- id
- user_id
- action
- object_type
- object_id
- created_at
```

Contoh di atas hanya ilustrasi awal. Struktur final harus mengikuti
requirement dan hubungan data sebenarnya.

### Database operational readiness

-   Backup terjadwal dan terpantau.
-   Restore pernah diuji, bukan hanya memastikan file backup tersedia.
-   Database tidak diekspos langsung ke jaringan publik.
-   Akun aplikasi memiliki privilege minimum.
-   Migration diuji pada staging.
-   Perubahan schema kompatibel dengan versi aplikasi saat proses
    deployment.
-   Query lambat dan pertumbuhan storage dipantau.

------------------------------------------------------------------------

## 6. Security architecture

Keamanan harus dirancang sejak awal, bukan ditambahkan setelah aplikasi
selesai.

Checklist minimum: - Authentication yang aman. - Authorization/RBAC pada
backend, bukan hanya menyembunyikan tombol di frontend. - Password
disimpan menggunakan password hashing yang kuat. - HTTPS/TLS untuk
komunikasi. - Validasi input di backend. - Proteksi SQL injection
menggunakan parameterized query/ORM. - Proteksi XSS dan CSRF sesuai pola
aplikasi. - Session/token memiliki masa berlaku dan mekanisme
pencabutan. - Secret/API key/password tidak disimpan di repository. -
Audit log untuk aktivitas penting. - Rate limiting untuk endpoint yang
berisiko. - Dependency dan image container diperiksa kerentanannya. -
Firewall hanya membuka port yang dibutuhkan. - Database dan service
internal tidak dibuka ke internet tanpa alasan yang kuat. - Gunakan
least privilege untuk user aplikasi dan service account.

Jangan pernah menampilkan password, token, private key, atau secret
dalam log maupun laporan Claude Code.

------------------------------------------------------------------------

## 7. Performance dan scalability

Hal yang harus diperhatikan: - Index database untuk query yang sering
digunakan. - Pagination dan filter di server-side untuk dataset besar. -
Hindari query berulang yang tidak diperlukan. - Gunakan cache jika pola
akses dan konsistensi data memungkinkan. - Pindahkan proses berat ke
background worker. - Terapkan timeout dan retry yang terkontrol untuk
integrasi eksternal. - Terapkan rate limit dan batas ukuran request. -
Ukur penggunaan CPU, RAM, disk, koneksi database, dan network. - Lakukan
load test berdasarkan pola akses yang realistis.

Jenis pengujian: - **Load test:** menguji beban normal dan target. -
**Stress test:** mencari batas kemampuan sistem. - **Spike test:**
menguji lonjakan request mendadak. - **Soak test:** menguji kestabilan
dalam periode panjang.

Jangan menambah kompleksitas seperti microservices atau Kubernetes
sebelum ada kebutuhan dan kapasitas tim untuk mengoperasikannya.

------------------------------------------------------------------------

## 8. Struktur project FastAPI

Contoh struktur modular:

``` text
project/
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   └── logging.py
│   ├── api/
│   │   └── routes/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   ├── repositories/
│   ├── db/
│   └── workers/
├── frontend/
│   ├── css/
│   ├── js/
│   └── pages/
├── migrations/
├── tests/
├── scripts/
├── docs/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

Jangan memaksakan pemindahan file besar-besaran jika aplikasi existing
sudah berjalan. Lakukan refactoring bertahap dan pastikan setiap
perubahan memiliki test yang memadai.

------------------------------------------------------------------------

## 9. Testing strategy

Minimal siapkan beberapa lapisan pengujian:

  Jenis test         Tujuan
  ------------------ -------------------------------------------------------
  Unit test          Menguji fungsi atau business logic secara terpisah
  Integration test   Menguji interaksi antar modul dan database
  API test           Menguji endpoint, status code, validasi, dan response
  UI test            Menguji alur pengguna di frontend
  Regression test    Memastikan fitur lama tetap berfungsi
  Security test      Memeriksa kerentanan dan kontrol akses
  Performance test   Mengukur response time dan kapasitas
  UAT                Memastikan kebutuhan bisnis terpenuhi

Sebelum release: - Semua test wajib lulus atau kegagalannya disetujui
secara eksplisit. - Tidak boleh ada bug kritis/high yang belum ditangani
tanpa risk acceptance. - Uji role dan permission. - Uji kondisi error,
timeout, dan data kosong. - Uji import/export jika aplikasi
memilikinya. - Simpan hasil test sebagai bukti release.

------------------------------------------------------------------------

## 10. Infrastructure dan environment

Pisahkan environment agar perubahan tidak langsung berdampak ke pengguna
production.

  Environment   Fungsi
  ------------- -------------------------------------
  DEV           Development dan pengujian awal
  QA/Test       Pengujian fungsional dan regression
  Staging       Simulasi production dan UAT
  PROD          Digunakan oleh pengguna sebenarnya

Komponen infrastructure yang umum: - Linux server atau VM. - CPU, RAM,
storage, dan network sesuai sizing. - Docker/Container runtime jika
digunakan. - Nginx atau reverse proxy. - FastAPI application server. -
PostgreSQL database. - TLS certificate. - Firewall dan network
segmentation. - Backup storage. - Monitoring dan log management. -
GitLab Runner untuk CI/CD.

DEV, staging, dan production sebaiknya memiliki konfigurasi serta
database yang terpisah. Jangan menggunakan data production sembarangan
di environment non-production; gunakan masking atau data sintetis bila
diperlukan.

------------------------------------------------------------------------

## 11. Git, GitLab, Docker, dan CI/CD

### Alur Git dan CI/CD

``` text
Developer
   |
   v
Local Development
   |
   v
Git Commit
   |
   v
GitLab Repository
   |
   v
Merge Request + Code Review
   |
   v
GitLab CI Pipeline
   |
   +--> Lint
   +--> Unit / Integration Test
   +--> Security / Dependency Scan
   +--> Build Docker Image
   |
   v
Deploy to Staging
   |
   v
UAT + Approval
   |
   v
Deploy to Production
   |
   v
Health Check + Monitoring
```

### Fungsi masing-masing

-   **Git:** mencatat perubahan source code dan riwayat versi.
-   **GitLab Repository:** menyimpan source code secara terpusat.
-   **Merge Request:** tempat review dan approval perubahan.
-   **GitLab CI/CD:** menjalankan pipeline otomatis.
-   **GitLab Runner:** mesin/agent yang mengeksekusi job pipeline.
-   **Docker:** mengemas aplikasi dan dependency agar konsisten antar
    environment.
-   **Container Registry:** menyimpan image yang sudah dibangun.

### Contoh `.gitlab-ci.yml`

Contoh berikut adalah kerangka awal. Sesuaikan command, image, variable,
runner, dan mekanisme deployment dengan repository serta infrastructure
yang sebenarnya.

``` yaml
stages:
  - validate
  - test
  - build

variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"

validate:
  stage: validate
  image: python:3.12
  script:
    - pip install -r requirements.txt
    - python -m compileall app

test:
  stage: test
  image: python:3.12
  script:
    - pip install -r requirements.txt
    - pip install pytest
    - pytest -q

build:
  stage: build
  image: docker:cli
  services:
    - docker:dind
  script:
    - docker build -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA" .
    - docker push "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA"
  rules:
    - if: '$CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH'
```

Catatan: - Contoh ini memerlukan konfigurasi Docker-in-Docker/runner dan
registry yang sesuai. - Variable registry harus disediakan oleh GitLab
atau konfigurasi CI yang benar. - Pipeline di atas belum melakukan
deployment. - Jangan memasukkan credential server ke file YAML. Simpan
sebagai protected/masked CI/CD variables atau gunakan mekanisme secret
management. - Tambahkan job deployment terpisah setelah mekanisme
staging, approval, dan rollback ditentukan.

------------------------------------------------------------------------

## 12. Deployment strategy dan rollback

Pilih strategi sesuai kebutuhan dan kemampuan infrastructure:

-   **Recreate:** hentikan versi lama lalu jalankan versi baru;
    sederhana tetapi dapat menyebabkan downtime.
-   **Rolling:** mengganti instance secara bertahap; membutuhkan lebih
    dari satu instance atau mekanisme yang mendukung.
-   **Blue-green:** menyiapkan environment baru lalu mengalihkan
    traffic; rollback dapat lebih cepat, tetapi membutuhkan resource
    tambahan.
-   **Canary:** merilis ke sebagian kecil pengguna/traffic terlebih
    dahulu; membutuhkan kontrol routing dan monitoring.

### Checklist sebelum deployment

1.  Pastikan release/version yang akan dipasang sudah jelas.
2.  Pastikan pipeline dan test lulus.
3.  Pastikan approval tersedia.
4.  Backup database dan konfigurasi yang relevan.
5.  Periksa kompatibilitas database migration.
6.  Siapkan langkah rollback yang sudah dipahami.
7.  Informasikan jadwal dan dampak ke stakeholder.
8.  Deploy sesuai runbook.
9.  Jalankan health check dan smoke test.
10. Pantau error, response time, resource, dan log.

### Database migration

-   Backup sebelum migration yang berisiko.
-   Uji migration di staging dengan data representatif.
-   Hindari perubahan schema yang membuat versi lama langsung tidak
    kompatibel.
-   Untuk perubahan besar, gunakan pola expand-and-contract.
-   Siapkan prosedur pemulihan data; rollback aplikasi saja belum tentu
    membatalkan perubahan database.

------------------------------------------------------------------------

## 13. Monitoring, logging, dan alerting

Monitoring bukan hanya memastikan aplikasi hidup. Pantau juga kualitas
layanan dan dependency.

  Area                Contoh metrik
  ------------------- -------------------------------------------
  Application         Request rate, error rate, response time
  Server              CPU, RAM, disk, network
  Database            Connection, query latency, storage, locks
  API                 HTTP 4xx/5xx, timeout
  Background worker   Queue length, failed jobs, execution time
  Security            Login gagal, aktivitas mencurigakan
  Availability        Health check dan uptime

Contoh tools: - Prometheus: pengumpulan metrics. - Grafana: dashboard
visualisasi. - Loki: pengelolaan log. - Alertmanager: pengiriman
alert. - Sentry: pelacakan application error.

Tentukan siapa penerima alert, tingkat severity, jam monitoring, dan
prosedur eskalasi. Jangan hanya mengumpulkan log; pastikan log memiliki
timestamp, level, request/correlation ID, dan tidak mengandung secret.

------------------------------------------------------------------------

## 14. Backup, disaster recovery, dan business continuity

Tentukan: - **RPO (Recovery Point Objective):** batas maksimum
kehilangan data yang dapat diterima. - **RTO (Recovery Time
Objective):** target waktu pemulihan layanan.

Contoh target awal untuk didiskusikan dengan owner aplikasi (bukan angka
universal): - RPO: 1 jam. - RTO: 4 jam. - Backup database: setiap jam
atau sesuai kebutuhan transaksi. - Retention backup: 30 hari. - Uji
restore: minimal bulanan.

Checklist: - Backup database dan file penting. - Backup disimpan
terpisah dari server utama. - Akses backup dibatasi. - Backup dienkripsi
bila sesuai kebijakan. - Kegagalan backup menghasilkan alert. - Restore
diuji dan didokumentasikan. - Runbook DR tersedia dan PIC ditentukan.

Backup yang belum pernah diuji restore belum dapat dianggap sebagai
strategi recovery yang terbukti.

------------------------------------------------------------------------

## 15. Dokumentasi operasional

Dokumen minimum yang sebaiknya tersedia: - PRD/requirement. - System
architecture. - ERD dan data dictionary. - API documentation. -
Installation guide. - Configuration guide. - Deployment guide. -
Rollback procedure. - Backup and restore procedure. - Monitoring and
alerting guide. - Troubleshooting guide. - Incident response dan
escalation matrix. - Change log/release notes. - Daftar PIC dan
ownership.

Dokumentasi harus diperbarui bersamaan dengan perubahan aplikasi.

------------------------------------------------------------------------

## 16. Production readiness checklist

### Requirement dan design

-   [ ] Scope dan acceptance criteria disetujui.
-   [ ] Arsitektur dan alur data terdokumentasi.
-   [ ] ERD dan API specification tersedia.
-   [ ] Risiko dan dependency telah diidentifikasi.

### Code dan quality

-   [ ] Perubahan masuk melalui Git/Merge Request.
-   [ ] Code review selesai.
-   [ ] Unit dan integration test lulus.
-   [ ] Regression test fitur penting lulus.
-   [ ] Tidak ada secret di source code.
-   [ ] Dependency diperiksa.

### Security

-   [ ] Authentication dan authorization diuji.
-   [ ] HTTPS aktif.
-   [ ] Firewall dan port sudah ditinjau.
-   [ ] Database tidak terbuka ke publik.
-   [ ] Audit log tersedia.
-   [ ] Secret dikelola dengan aman.

### Infrastructure dan deployment

-   [ ] DEV, staging, dan production dipisahkan.
-   [ ] Sizing CPU, RAM, storage, dan network ditinjau.
-   [ ] CI/CD pipeline berjalan.
-   [ ] Backup sebelum perubahan berisiko tersedia.
-   [ ] Rollback plan tersedia.
-   [ ] Health check dan smoke test tersedia.

### Operations

-   [ ] Dashboard monitoring tersedia.
-   [ ] Alert dan penerimanya ditentukan.
-   [ ] Backup dan restore diuji.
-   [ ] RPO/RTO disepakati.
-   [ ] Runbook dan PIC tersedia.
-   [ ] UAT dan production approval selesai.

------------------------------------------------------------------------

## 17. Roadmap implementasi yang disarankan

  Fase   Fokus                          Hasil
  ------ ------------------------------ -----------------------------------------
  1      Assessment aplikasi existing   Kondisi aktual, risiko, gap
  2      Requirement dan design         PRD, architecture, ERD, API
  3      Foundation                     Struktur project, config, logging, auth
  4      Core feature                   Fitur utama sesuai prioritas
  5      Quality                        Test, security review, performance
  6      CI/CD                          Pipeline build dan test
  7      Staging                        Deployment staging dan UAT
  8      Production                     Approval, deployment, health check
  9      Operations                     Monitoring, backup, maintenance

Kerjakan bertahap. Jangan sekaligus mengubah arsitektur, database,
frontend, dan deployment tanpa rencana serta validasi yang jelas.

------------------------------------------------------------------------

## 18. Workflow Claude Code

Gunakan Claude Code sebagai asisten engineering yang bekerja berdasarkan
tahapan dan approval.

### Phase 1 --- Discovery / Assessment

Claude harus: - Memeriksa struktur repository. - Mengidentifikasi
bahasa, framework, dependency, dan entry point. - Memahami alur
frontend, backend, dan database. - Mengidentifikasi fitur existing. -
Meninjau konfigurasi, test, deployment, dan dokumentasi. - Menandai
risiko dan area yang belum jelas.

**Output:** assessment report. Belum boleh mengubah source code.

### Phase 2 --- Requirement dan Design

Claude menyusun: - Requirement dan acceptance criteria. - Arsitektur
target. - ERD dan perubahan database. - API contract. - Security
design. - Testing strategy. - Deployment impact.

**Output:** design document untuk direview.

### Phase 3 --- Implementation Plan

Claude memecah pekerjaan menjadi task kecil: - File yang akan
dibuat/diubah. - Tujuan setiap perubahan. - Dependency dan risiko. -
Test yang harus dijalankan. - Dampak terhadap fitur existing. - Rencana
rollback jika diperlukan.

**Output:** implementation plan. Tunggu approval sebelum implementasi.

### Phase 4 --- Development

-   Implementasikan task sesuai urutan.
-   Hindari perubahan di luar scope.
-   Pertahankan behavior existing kecuali perubahan disetujui.
-   Jangan hardcode secret.
-   Perbarui dokumentasi dan test.

### Phase 5 --- Testing dan Review

-   Jalankan test yang relevan.
-   Periksa regression.
-   Periksa security dan error handling.
-   Laporkan command dan hasil test secara jujur.
-   Jangan menyatakan lulus jika test tidak dijalankan.

### Phase 6 --- CI/CD Preparation

-   Siapkan Dockerfile jika dibutuhkan.
-   Siapkan pipeline GitLab.
-   Pisahkan konfigurasi tiap environment.
-   Siapkan protected variables/secrets.
-   Siapkan deployment dan rollback script setelah mekanismenya
    disetujui.

### Phase 7 --- Staging

-   Deploy ke staging.
-   Jalankan smoke test dan UAT.
-   Catat bug dan perbaikannya.
-   Minta persetujuan release.

### Phase 8 --- Production

-   Production deployment hanya setelah approval eksplisit.
-   Jalankan backup dan pre-deployment check.
-   Deploy sesuai runbook.
-   Jalankan health check.
-   Pantau aplikasi dan dokumentasikan hasil release.

------------------------------------------------------------------------

## 19. Master prompt untuk Claude Code

Salin prompt berikut saat memulai pekerjaan di repository aplikasi:

``` text
Act as a Senior Software Architect, Senior Backend Engineer,
Database Engineer, Application Security Engineer, QA Engineer,
and DevOps Engineer.

Your mission is to help assess, improve, test, and prepare this
application for a reliable production deployment.

MANDATORY WORKING RULES

1. Start by inspecting the existing repository and its documentation.
2. Do not modify source code during the initial assessment phase.
3. Do not assume how the application works; verify it from the code.
4. Identify the existing stack, architecture, entry points, modules,
   database, integrations, tests, and deployment process.
5. Preserve existing working functionality.
6. Avoid unnecessary refactoring and changes outside the approved scope.
7. Never expose, print, or commit passwords, tokens, private keys,
   or other secrets.
8. Identify security, performance, reliability, and data-loss risks.
9. Explain database schema changes and migration risks before applying them.
10. Create a step-by-step implementation plan before coding.
11. Wait for explicit approval before implementing significant changes.
12. Run relevant tests and report the actual commands and results.
13. Never claim that tests, builds, or deployments succeeded unless
    they were actually executed and verified.
14. Do not deploy to production without explicit approval.
15. Update documentation when approved changes affect system behavior.

PHASE 1: DISCOVERY AND ASSESSMENT ONLY

Inspect the repository and produce a report containing:

A. Repository structure
B. Technology stack and dependencies
C. Application architecture and request flow
D. Existing features and important business logic
E. Database structure and migration approach
F. Authentication and authorization
G. Security observations
H. Error handling and logging
I. Existing tests and test coverage observations
J. Infrastructure and deployment approach
K. Configuration and environment management
L. Performance and scalability risks
M. Backup, recovery, and operational readiness
N. Critical risks and recommended priorities

For each finding, distinguish:
- Verified facts from repository evidence
- Assumptions that need confirmation
- Missing information

Do not edit, create, delete, or move source files in Phase 1.
Do not run destructive commands or modify the database.

At the end, provide:
1. Executive summary
2. Current architecture diagram (Mermaid)
3. Findings and risk list, prioritized by severity
4. Recommended target architecture
5. Proposed implementation phases
6. Questions that require the project owner's decision

STOP after Phase 1 and wait for approval.
```

### Prompt untuk melanjutkan fase berikutnya

Setelah assessment direview, gunakan instruksi sesuai kebutuhan,
misalnya:

``` text
Proceed to Phase 2 only.
Prepare the requirement, target architecture, database design,
API contract, security design, and testing strategy.
Do not implement source code yet.
Present the design for approval.
```

Setelah design disetujui:

``` text
Proceed to Phase 3 only.
Create a detailed implementation plan with affected files,
expected behavior, risks, tests, and rollback considerations.
Do not implement until I approve the plan.
```

Lanjutkan ke development, testing, CI/CD, staging, dan production satu
fase pada satu waktu.

------------------------------------------------------------------------

## 20. Definition of Done

Sebuah fitur dianggap selesai jika: - Requirement dan acceptance
criteria terpenuhi. - Implementasi sesuai design yang disetujui. - Tidak
merusak fitur existing. - Validasi dan error handling tersedia. - Test
relevan lulus. - Security dan permission diperiksa. - Dokumentasi
diperbarui. - Code review selesai. - Perubahan siap dipromosikan ke
environment berikutnya. - Bukti hasil test dan catatan perubahan
tersedia.

Sebuah aplikasi belum dapat disebut production-ready hanya karena bisa
dijalankan di laptop developer. Aplikasi harus memiliki kontrol
keamanan, deployment yang dapat diulang, monitoring, backup/restore,
dokumentasi operasional, dan prosedur pemulihan yang sudah diuji.
