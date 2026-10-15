# INDO-COASTFLOOD: Indonesian Coastal Flood Catalogue & Auto-Tracker Web App

> **Platform Web Interaktif & Pelacak Otomatis Kejadian Banjir Rob Pesisir Indonesia (2015–2026)**  
> Berbasis Open-Source, Serverless, siap deploy ke **GitHub Pages**.

---

## 🌊 1. Deskripsi & Tujuan Proyek

Aplikasi web ini menyajikan visualisasi spasial interaktif, penelusuran, dan dasbor analitik kejadian banjir rob pesisir (*coastal flooding*) di seluruh kepulauan Indonesia dari periode November 2015 hingga 2026.

Proyek ini terisolasi di dalam folder `tools/web_catalogue/` untuk:
1. Membaca langsung data katalog beku disertasi (`data/processed/rob_events_v3c.csv`) dan koordinat pesisir (`data/processed/rob_places_latlon.csv`).
2. Memanfaatkan modul ilmiah `src.regions` untuk menyaring false-positives (`drop_excluded`), koreksi penamaan tempat (`rob_event_place_overrides.csv`), dan batasan regional pesisir (*Pantura Jawa, Jawa Selatan, Sumatera Timur, Sumatera Barat, Kalimantan, Indonesia Timur*).
3. Menjadi basis kode mandiri yang dapat di-push ke repositori GitHub terpisah untuk hosting **GitHub Pages** dan otomatisasi **GitHub Actions**.

---

## 🚀 2. Fitur Utama

- **🗺️ Interactive National Map (Leaflet.js & MarkerCluster)**:
  - Sebaran 1,219 titik kejadian banjir rob pesisir terverifikasi.
  - Marker clustering dinamis dengan pin berwarna sesuai *Confidence Tier* (Confirmed = Hijau Zamrud, Probable = Kuning Amber, Possible = Biru Slate).
  - Popup kaya informasi: Tanggal, durasi hari, nama lokasi pesisir, kabupaten, provinsi, wilayah oseanografi, estimasi tinggi genangan (cm), kutipan judul berita, jumlah media sumber, dan tombol langsung **"Buka Sumber Berita Asli ↗"**.
  - Pilihan basemap: *CartoDB Positron* (Terang), *Esri World Imagery* (Citra Satelit), dan *CartoDB Dark Matter* (Gelap).
  - Tombol *Quick Zoom*: Pantura Jawa, Sumatera Timur, DKI Jakarta & Teluk, dan Nasional.

- **🔍 Multi-Facet Filtering & Search**:
  - Pencarian teks bebas instan (kota, kabupaten, provinsi, atau kata kunci berita).
  - Filter tahun (2015–2026) dan filter bulan (Januari–Desember).
  - Filter tombol wilayah pesisir dengan indikator jumlah kejadian.
  - Filter dropdown 34 provinsi.
  - Filter tingkat keyakinan (Confirmed, Probable, Possible).
  - Filter jenis bahaya (Banjir Rob murni vs Gelombang Pasang) dan ambang tinggi genangan ($\ge 50\text{ cm}$, $\ge 100\text{ cm}$).
  - Tombol reset filter 1-klik.

- **📊 Analytics Dashboard (Chart.js)**:
  - **Tren Tahunan**: Distribusi jumlah rob per tahun dengan rincian tier.
  - **Siklus Musiman Bulanan**: Klimatologi Jan–Desember yang memperlihatkan konsentrasi puncak rob pesisir (misal puncak Mei–Juli di Pantura Jawa).
  - **Distribusi Regional**: Komposisi kejadian antar koridor pesisir utama Indonesia.
  - **Top 10 Hotspot Rob**: Peringkat kota/kabupaten dengan frekuensi rob tertinggi (Semarang, Demak, Belawan, Jakarta, Pekalongan, dsb.).

- **📋 Tabel Data & Fitur Ekspor**:
  - Tabel data komprehensif dengan paginasi (50 baris per halaman) dan tombol aksi cepat menuju titik di peta.
  - **Unduh CSV**: Ekspor seluruh baris data terfilter aktif ke format `.csv`.
  - **Unduh GeoJSON**: Ekspor seluruh data spasial terfilter ke format standar GIS `.geojson` siap buka di QGIS atau ArcGIS.

- **⚡ Zero-CORS & Offline-Ready**:
  - Dilengkapi berkas `data/events.js` sehingga halaman `index.html` dapat langsung dibuka via protokol `file://` di komputer lokal tanpa kendala CORS, serta mendukung pemanggilan `fetch('data/events.json')` saat dideploy ke web server.

---

## 📁 3. Struktur Berkas

```text
tools/web_catalogue/
├── index.html                     # Antarmuka web utama (Single Page Application murni)
├── README.md                      # Dokumentasi teknis aplikasi
├── data/
│   ├── events.json                # Dataset JSON untuk web (~1.4 MB)
│   ├── events.js                  # Dataset JavaScript bundle (window.ROB_EVENTS)
│   └── summary.json               # Metadata ringkasan dan statistik agregat
└── scripts/
    └── export_events_json.py      # Skrip konversi dari data/processed/rob_events_v3c.csv
```

---

## 💻 4. Cara Menjalankan & Menguji di Lokal

### Opsi 1: Langsung Buka di Peramban (Tanpa Webserver)
Cukup jalankan perintah berikut di terminal:
```bash
open tools/web_catalogue/index.html
```
Atau klik ganda berkas `tools/web_catalogue/index.html` dari Finder macOS.

### Opsi 2: Menggunakan HTTP Server Lokal
```bash
python3 -m http.server 8000
```
Lalu buka peramban ke:
`http://localhost:8000/tools/web_catalogue/`

---

## 🔄 5. Memperbarui Data dari Katalog v3c

Untuk mengenerate ulang `events.json` dan `events.js` dari katalog riset:
```bash
python3 tools/web_catalogue/scripts/export_events_json.py
```
Skrip ini secara otomatis memanggil fungsi `drop_excluded()` dan `apply_region_overrides()` dari `src.regions` untuk memastikan dataset yang diekspor konsisten dengan filter saintifik disertasi.

---

## 🛠️ 6. Rencana Tahap Selanjutnya (Roadmap)

1. **Tahap 2: Auto-Tracker Scraper (`scripts/tracker_harvest.py`)**:
   - Memanfaatkan modul yang sudah ada di `prep/rob_harvest/` (`gnews.py`, `queries.py`, `screen.py`, `events.py`).
   - Melakukan penelusuran RSS Google News Indonesia secara berkala dengan query kata kunci rob pesisir.
   - Menyaring artikel dengan classifier berbasis aturan (*rule-based impact screening*).
   - Melakukan geocoding otomatis ke titik pesisir terdekat (*coastal-snap*).
   - Menghindari duplikasi (*deduplication*) terhadap ID kejadian yang sudah ada di `events.json`.

2. **Tahap 3: Workflow GitHub Actions (`.github/workflows/auto_tracker.yml`)**:
   - Menjalankan tracker secara otomatis via cron terjadwal (misal mingguan atau harian).
   - Melakukan auto-commit dan push berkas `events.json` yang terbarui.
   - Memicu auto-deploy GitHub Pages.
