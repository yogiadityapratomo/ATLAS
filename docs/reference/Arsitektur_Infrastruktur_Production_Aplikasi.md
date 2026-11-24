# Arsitektur Infrastruktur Production untuk Aplikasi Web

## 1. Tujuan

Dokumen ini menjelaskan komponen infrastruktur dan alur deployment aplikasi web agar stabil, aman, dan mampu menangani banyak user serta request secara bersamaan.

Contoh konteks: aplikasi NetBackup Dashboard dengan:
- Frontend: HTML, CSS, JavaScript
- Backend: Python FastAPI
- Database: PostgreSQL

Istilah penting:
- **Production**: lingkungan aplikasi yang digunakan user sebenarnya.
- **Scalability**: kemampuan menambah kapasitas saat beban meningkat.
- **High Availability (HA)**: kemampuan layanan tetap tersedia ketika terjadi kegagalan komponen.
- **Disaster Recovery (DR)**: proses pemulihan layanan setelah gangguan besar.

---

## 2. Komponen infrastruktur

Berikut komponen yang perlu dipertimbangkan. Tidak semuanya harus menjadi server terpisah; beberapa layanan dapat digabungkan sesuai kebutuhan dan kapasitas.

| No. | Komponen | Fungsi | Contoh teknologi |
|---|---|---|---|
| 1 | Frontend | Tampilan aplikasi yang digunakan user | HTML, CSS, JavaScript, React, Vue |
| 2 | Backend / Application Server | Menjalankan business logic, API, autentikasi, dan pemrosesan request | Python FastAPI, Django, Node.js |
| 3 | Database | Menyimpan data aplikasi secara permanen | PostgreSQL, MySQL, SQL Server |
| 4 | Web Server / Reverse Proxy | Menerima koneksi HTTP/HTTPS dan meneruskan request ke backend | Nginx, HAProxy, Apache |
| 5 | Load Balancer | Membagi request ke beberapa application server | HAProxy, Nginx, F5, cloud load balancer |
| 6 | Cache | Menyimpan data sementara untuk mempercepat akses dan mengurangi query database | Redis |
| 7 | Message Queue / Worker | Menjalankan proses berat di background agar user tidak perlu menunggu | Celery, RabbitMQ, Redis Queue |
| 8 | Storage | Menyimpan file upload, export Excel, attachment, dan laporan | NAS, SAN, object storage |
| 9 | Authentication / Authorization | Mengelola login, role, permission, dan akses user | LDAP, Active Directory, SSO, OAuth2 |
| 10 | Monitoring & Logging | Memantau performa, error, CPU, RAM, request, dan kondisi service | Prometheus, Grafana, Loki, ELK |
| 11 | Security | Melindungi aplikasi dan komunikasi jaringan | TLS/SSL, WAF, firewall, secrets management |
| 12 | Backup & Disaster Recovery | Memulihkan aplikasi dan data jika terjadi kegagalan | Database backup, replication, DR site |

### Catatan

- Frontend static files dapat disajikan langsung oleh Nginx atau CDN.
- Backend dapat dijalankan pada satu atau beberapa instance.
- Database, cache, dan worker tidak selalu membutuhkan VM tersendiri pada tahap awal.
- Pemisahan server/service perlu mempertimbangkan kapasitas, keamanan, kemudahan operasional, dan biaya.

---

## 3. Gambaran arsitektur production

Alur konseptual request:

```text
                    USERS / CLIENT
                 Browser, laptop, mobile
                           |
                           v
                    DNS + FIREWALL
                       + WAF
                           |
                           v
                 LOAD BALANCER / PROXY
                    Nginx / HAProxy
                           |
             +-------------+-------------+
             |                           |
             v                           v
       APPLICATION SERVER 1        APPLICATION SERVER 2
           FastAPI                     FastAPI
             |                           |
             +-------------+-------------+
                           |
             +-------------+-------------+
             |             |             |
             v             v             v
        POSTGRESQL       REDIS       QUEUE / WORKER
        Database        Cache       Background jobs
             |
             v
       DATABASE REPLICA
       (bila diperlukan)

       FILE / OBJECT STORAGE
       Excel, CSV, reports

       MONITORING, LOGGING, BACKUP & DR
       Memantau dan melindungi seluruh komponen
```

Arsitektur tersebut merupakan gambaran konseptual. Frontend dapat disajikan oleh web server/CDN, sementara request API diteruskan ke backend melalui reverse proxy atau load balancer.

---

## 4. Alur request ketika banyak user mengakses

Misalnya 500 user membuka dashboard dalam waktu berdekatan:

1. User membuka domain aplikasi.
2. DNS mengarahkan koneksi ke alamat layanan.
3. Firewall/WAF memeriksa dan memfilter koneksi.
4. Load balancer membagi request ke application server yang sehat.
5. Backend memproses permintaan dan business logic.
6. Jika data tersedia di Redis, backend dapat mengambilnya dari cache.
7. Jika data tidak tersedia atau perlu data terbaru, backend mengambilnya dari PostgreSQL.
8. Backend mengirim hasil ke browser.
9. Proses berat seperti export Excel dapat dipindahkan ke background worker.

### Mengapa pola ini membantu?

- Request tidak menumpuk pada satu backend.
- Cache mengurangi query database yang berulang.
- Worker memisahkan proses berat dari request interaktif.
- Health check membantu menghindari server yang sedang bermasalah.

**Catatan:** 500 user bersamaan tidak sama dengan 500 request per detik. Kapasitas perlu dihitung berdasarkan pola akses, ukuran data, kompleksitas query, dan beban setiap request.

---

## 5. Konsep untuk menangani traffic besar

| Teknologi / Konsep | Masalah yang ditangani |
|---|---|
| Load Balancing | Membagi beban request ke beberapa server |
| Horizontal Scaling | Menambah jumlah application server |
| Redis / Caching | Mengurangi query database berulang |
| Database Indexing | Mempercepat pencarian data |
| Connection Pooling | Mengontrol jumlah koneksi database |
| Async Processing | Memindahkan pekerjaan berat ke background |
| Rate Limiting | Membatasi request berlebihan |
| Health Check | Mendeteksi server atau service yang tidak sehat |
| High Availability | Mengurangi risiko single point of failure |

### Contoh sederhana

- Tanpa load balancer: request hanya dilayani satu backend.
- Dengan load balancer: request dapat dibagi ke tiga backend.
- Dengan Redis: data dashboard yang sering diminta tidak selalu dibaca ulang dari PostgreSQL.
- Dengan worker: export laporan besar tidak menghambat user lain yang sedang membuka dashboard.

Load balancer dan cache bukan jaminan kapasitas otomatis meningkat. Konfigurasi, kapasitas backend, database, dan pengujian tetap diperlukan.

---

## 6. Contoh pembagian server

Untuk deployment enterprise, fungsi dapat dipisahkan seperti berikut:

| Server / VM | Fungsi | Komponen |
|---|---|---|
| LB Server | Distribusi trafik | Nginx / HAProxy |
| Web Server | Menyajikan frontend | Nginx |
| App Server 1 | Backend aplikasi | FastAPI |
| App Server 2 | Backend aplikasi | FastAPI |
| DB Server | Database | PostgreSQL |
| Cache Server | Cache | Redis |
| Worker Server | Background job | Celery |
| Monitoring Server | Monitoring dan logging | Prometheus, Grafana, Loki |

Tidak harus ada delapan server fisik. Server dapat berupa VM atau container, dan beberapa service bisa digabung pada tahap awal.

---

## 7. High Availability (HA)

HA bertujuan menjaga layanan tetap tersedia ketika salah satu komponen mengalami kegagalan.

Contoh:
1. App Server 1 mengalami crash.
2. Load balancer mendeteksi server tidak sehat melalui health check.
3. Traffic dialihkan ke App Server 2.
4. User tetap dapat mengakses aplikasi selama komponen lain masih sehat.

Namun, jika PostgreSQL hanya memiliki satu server dan server tersebut mati, aplikasi tetap dapat terganggu.

Untuk HA yang lebih lengkap, pertimbangkan:
- Database replication.
- Automatic failover.
- Backup database yang teruji.
- Redundant load balancer.
- Storage redundancy.
- Monitoring dan alerting.
- DR site serta prosedur pemulihan.

**HA bukan sekadar memiliki dua server.** Desain perlu mengidentifikasi dan mengurangi single point of failure pada seluruh komponen kritis.

Replication juga bukan pengganti backup: kesalahan atau penghapusan data dapat ikut tereplikasi.

---

## 8. Rekomendasi tahapan implementasi

### Tahap 1 — Production awal

Contoh pembagian:

**VM 1 — Application**
- Nginx
- FastAPI
- Frontend

**VM 2 — Database**
- PostgreSQL

**VM 3 — Supporting Services**
- Redis
- Background Worker
- Monitoring Agent

Tahap ini cocok sebagai titik awal, setelah kapasitas dan kebutuhan keamanan ditinjau.

### Tahap 2 — High Availability

- Minimal dua Application VM.
- Load balancer redundant.
- PostgreSQL primary dan standby.
- Redis dengan konfigurasi HA jika diperlukan.
- Storage redundant.
- Monitoring terpusat.
- Backup dan prosedur failover yang diuji.

### Tahap 3 — Enterprise Scale

- Containerization menggunakan Docker.
- Kubernetes atau OpenShift bila sesuai kebutuhan dan kemampuan operasional.
- Automated CI/CD.
- Centralized Logging.
- Centralized Monitoring.
- Automated Backup & DR.

Jika perusahaan sudah memiliki platform OpenShift, frontend, backend, dan worker dapat dipertimbangkan untuk dijalankan di sana. PostgreSQL dapat menggunakan layanan database terkelola atau deployment yang didukung tim platform.

---

## 9. Performance testing

Sebelum aplikasi dinyatakan siap production, lakukan pengujian performa dan ketahanan.

| Jenis pengujian | Tujuan |
|---|---|
| Load Testing | Simulasi beban user/request yang diharapkan |
| Stress Testing | Mengetahui batas kapasitas dan perilaku saat overload |
| Spike Testing | Menguji lonjakan request mendadak |
| Endurance Testing | Menguji kestabilan dalam waktu lama |
| Failover Testing | Menguji perilaku ketika server atau komponen gagal |

Contoh tools:
- **Apache JMeter** — load testing.
- **k6** — performance testing.
- **Prometheus + Grafana** — monitoring metrik dan visualisasi.

Metrik yang perlu dipantau:
- Request per second (RPS).
- Response time, termasuk p95 dan p99.
- Error rate.
- CPU dan memory utilization.
- Network throughput.
- Database connections.
- Query latency dan slow queries.
- Cache hit ratio.
- Queue length dan waktu tunggu worker.

Tentukan target layanan (misalnya response time dan error rate) berdasarkan kebutuhan bisnis, lalu uji dengan pola beban yang realistis.

---

## 10. CI/CD dan deployment

Alur sederhana pengembangan sampai production:

```text
Developer / Claude Code
          |
          v
     Git (commit)
          |
          v
   GitHub (push)
          |
          v
    CI/CD Pipeline
          |
          +---- Automated Test
          |
          +---- Build / Package
          |
          +---- Security Checks
          |
          v
   Approval (bila diperlukan)
          |
          v
      Deployment
          |
          v
   Production Server
          |
          v
   Health Check & Monitoring
```

Komponen yang dapat digunakan:
- Git untuk version control.
- GitHub untuk repository.
- GitHub Actions atau Jenkins untuk pipeline.
- Docker untuk packaging aplikasi.
- Ansible atau mekanisme konfigurasi lain untuk automation.
- Monitoring untuk memvalidasi hasil deployment.

Untuk server perusahaan, gunakan runner dan jalur deployment yang disetujui tim infrastruktur. Jangan membuka SSH production ke internet hanya untuk kebutuhan CI/CD. Simpan secret dan credential di secret manager, bukan di source code.

Deployment juga sebaiknya memiliki prosedur rollback apabila release baru gagal.

---

## 11. Checklist production readiness

### Application
- [ ] Frontend dan backend terpisah dengan jelas.
- [ ] Konfigurasi environment development dan production terpisah.
- [ ] API memiliki autentikasi dan otorisasi.
- [ ] Error handling dan validasi input tersedia.
- [ ] Proses berat dijalankan melalui background worker bila sesuai.

### Infrastructure & Network
- [ ] DNS dan domain tersedia.
- [ ] Firewall hanya membuka port yang diperlukan.
- [ ] HTTPS/TLS aktif.
- [ ] Reverse proxy/load balancer dikonfigurasi.
- [ ] Health check tersedia.
- [ ] Kapasitas CPU, RAM, storage, dan network sudah dihitung.

### Database & Storage
- [ ] Database memiliki backup terjadwal.
- [ ] Restore backup sudah diuji.
- [ ] Index dan query database ditinjau.
- [ ] Connection pooling dikonfigurasi.
- [ ] Storage memiliki kapasitas dan proteksi yang memadai.

### Security
- [ ] Authentication dan authorization diterapkan.
- [ ] Role dan permission ditinjau.
- [ ] Secret tidak disimpan di source code.
- [ ] Patch OS dan dependency dikelola.
- [ ] Log akses dan aktivitas penting tersedia.

### Operations
- [ ] Monitoring dan alerting aktif.
- [ ] Log terpusat atau dapat dikumpulkan.
- [ ] Load test dilakukan.
- [ ] Failover dan rollback diuji.
- [ ] SOP incident, backup, restore, dan DR tersedia.

---

## 12. Informasi yang dibutuhkan untuk desain final

Sebelum menentukan jumlah VM, sizing CPU/RAM/storage, dan topologi network, kumpulkan kebutuhan berikut:

1. **Estimasi concurrent users**: 1–50, 50–100, 100–500, 500–1.000, atau lebih dari 1.000.
2. **Jenis aplikasi**: internal dashboard, web application dengan API, atau enterprise application.
3. **Platform**: VMware/Virtual Machine, OpenShift, bare metal, atau cloud.
4. **Availability**: single server/basic, HA, atau HA + DR.
5. **Database**: PostgreSQL, Microsoft SQL Server, MySQL, atau belum ditentukan.
6. **Pola workload**: request interaktif, dashboard dengan refresh berkala, upload/import file, export laporan, atau kombinasi.
7. **Target performa**: response time, jam operasional, dan toleransi downtime.
8. **Kapasitas data**: ukuran database saat ini, pertumbuhan data, dan retensi.

Dari informasi tersebut, desain final dapat mencakup:
- Diagram arsitektur production.
- Jumlah VM/server.
- Sizing vCPU, RAM, dan storage.
- Network flow dan port.
- Firewall matrix.
- Load balancing.
- HA dan DR.
- Security.
- Monitoring dan backup.
- CI/CD dan deployment flow.

---

## 13. Kesimpulan

Aplikasi production yang stabil bukan hanya membutuhkan frontend, backend, dan database. Komponen pendukung seperti reverse proxy, load balancer, cache, worker, storage, security, monitoring, backup, dan HA juga perlu dirancang sesuai kebutuhan.

Urutan belajar dan implementasi yang disarankan:

1. Frontend, backend, dan database.
2. Linux/server deployment dan Nginx.
3. Git dan GitHub.
4. CI/CD.
5. Docker.
6. Redis dan background worker.
7. Load balancing dan HA.
8. Monitoring, logging, backup, dan DR.
9. Kubernetes/OpenShift jika skala dan kebutuhan operasional membenarkannya.

**Prinsip utama:** desain berdasarkan kebutuhan dan hasil pengujian, bukan sekadar menambah jumlah server atau teknologi. Arsitektur yang baik harus terukur, aman, dapat dipantau, dan dapat dipulihkan ketika terjadi gangguan.
