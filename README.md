# Indonesian Coastal Flood Catalogue - Interactive Web & Auto-Tracker (INDO-COASTFLOOD)

> **Platform Web Interaktif dan Pelacak Otomatis Kejadian Banjir Rob Pesisir Indonesia (2015–2026)**  
> Serverless, 100% Free Open-Source, siap dideploy ke **GitHub Pages**.

---

## 🌊 1. Ringkasan Proyek

Platform ini menyajikan katalog komprehensif kejadian banjir rob (*coastal flooding*) di seluruh wilayah pesisir Indonesia dari November 2015 hingga 2026. Data dihimpun melalui penelusuran sistematis artikel berita media daring (Google News RSS & verifikasi independen) yang kemudian diklasifikasikan ke dalam tiga tingkatan keyakinan (*confidence tiers*): **Confirmed**, **Probable**, dan **Possible**.

Aplikasi ini dibangun murni menggunakan teknologi web sisi-klien (*Client-Side Single Page Application* / SPA statis), sehingga tidak memerlukan backend server, biaya sewa server nol rupiah, dan dapat langsung dihosting melalui **GitHub Pages**.

---

## 🚀 2. Fitur Utama

1. **Interactive National Map (Peta Spasial Nasional)**:
   - Visualisasi sebaran titik banjir rob pesisir Indonesia menggunakan **Leaflet.js** dan **MarkerCluster**.
   - Pin warna otomatis berdasarkan tingkat keyakinan (*Confirmed*: Hijau Zamrud, *Probable*: Kuning Amber, *Possible*: Biru Slate).
   - Popup interaktif lengkap: ID kejadian, tanggal & durasi hari, nama kota/pesisir, kabupaten, provinsi, wilayah oseanografi, estimasi tinggi genangan air (cm), judul berita asli, jumlah sumber media, dan tautan langsung ke artikel berita asli.
   - Pilihan basemap instan: *CartoDB Positron* (Terang), *Esri World Imagery* (Citra Satelit), dan *CartoDB Dark Matter* (Gelap).
   - Tombol fokus cepat (*quick zoom*): Pantura Jawa, Sumatera Timur, DKI Jakarta, dan Nasional.

2. **Sistem Filter & Penelusuran Cepat**:
   - **Pencarian teks bebas**: Cari instan berdasarkan nama kota, kecamatan, kabupaten, provinsi, atau kata kunci dalam judul berita.
   - **Filter Waktu**: Pilihan tahun spesifik (2015–2026) dan filter bulan (Januari–Desember) untuk melihat dinamika musiman.
   - **Filter Wilayah**: Pantura Jawa, Sumatera Timur, Jawa Selatan, Kalimantan, Indonesia Timur, Sumatera Barat, serta dropdown 34 provinsi.
   - **Filter Tingkat Keyakinan (Tier)**: Checklist interaktif Confirmed, Probable, Possible.
   - **Filter Bahaya & Tinggi Genangan**: Pilihan banjir rob murni vs gelombang pasang, filter kejadian yang memiliki catatan tinggi genangan (≥ 50 cm, ≥ 100 cm).
   - **Reset Filter**: Tombol satu-klik untuk mengembalikan seluruh filter ke kondisi awal.

3. **Analytics Dashboard (Dasbor Analitik)**:
   - **Grafik Tren Tahunan (2015–2026)**: Menampilkan frekuensi kejadian per tahun dengan rincian tier (Confirmed / Probable / Possible).
   - **Grafik Siklus Musiman Bulanan (Klimatologi)**: Memvisualisasikan konsentrasi puncak rob (misal lonjakan rob di Pantura Jawa pada bulan Mei–Juli).
   - **Grafik Distribusi Regional**: Diagram donat perbandingan porsi kejadian antar koridor pesisir utama.
   - **Grafik Top 10 Lokasi Paling Rawan**: Peringkat kota/kabupaten dengan frekuensi banjir rob tertinggi (misal Semarang, Demak, Belawan, Jakarta, Pekalongan).

4. **Tabel Data & Fitur Ekspor**:
   - Tab tabel data tabular lengkap dengan pencarian, penomoran halaman (*pagination*), dan tombol aksi.
   - **Unduh CSV**: Ekspor seluruh data yang sedang aktif terfilter langsung ke format spreadsheet `.csv`.
   - **Unduh GeoJSON**: Ekspor titik koordinat dan atribut ke format standar GIS `.geojson` untuk diolah di QGIS / ArcGIS / Python.

5. **Dukungan Offline & Zero-CORS**:
   - Menyertakan `data/events.js` sehingga file `index.html` dapat langsung dibuka dan dijalankan dengan klik ganda (*double click*) di komputer lokal tanpa terhalang kebijakan CORS peramban.

---

## 📁 3. Struktur Berkas Proyek

```text
indonesian-coastal-flood-catalogue/
├── index.html                  # Antarmuka web utama (Single Page Application)
├── README.md                   # Dokumentasi proyek
├── data/
│   ├── events.json             # Dataset lengkap katalog rob (v3c, 1,232 events)
│   ├── events.js               # Dataset bundle JavaScript (bypasses CORS untuk file://)
│   └── summary.json            # Ringkasan statistik agregat metadata
└── scripts/
    └── parse_catalogue_v3c.py  # Skrip parser ekstraksi katalog dari data riset
```

---

## 💻 4. Cara Menjalankan di Lokal (Tahap 1)

Anda dapat langsung mencoba prototipe ini di komputer lokal dengan dua cara:

### Cara 1: Langsung Buka di Peramban (Paling Mudah)
Cukup klik ganda berkas `index.html` atau jalankan via terminal macOS:
```bash
open /Users/randifirdaus/Documents/indonesian-coastal-flood-catalogue/index.html
```

### Cara 2: Menggunakan HTTP Server Lokal
Jalankan server sederhana menggunakan Python:
```bash
cd /Users/randifirdaus/Documents/indonesian-coastal-flood-catalogue
python3 -m http.server 8000
```
Lalu buka peramban dan akses alamat:
```
http://localhost:8000
```

---

## 🔄 5. Memperbarui Data dari Katalog v3c

Jika terdapat pembaruan pada data mentah katalog disertasi (`rob_events_v3c.csv` dan `rob_places_latlon.csv`), Anda dapat memperbarui berkas JSON dan JS web dengan menjalankan:

```bash
python3 scripts/parse_catalogue_v3c.py \
  --events /Users/randifirdaus/Documents/Data_Processing/data/processed/rob_events_v3c.csv \
  --places /Users/randifirdaus/Documents/Data_Processing/data/processed/rob_places_latlon.csv \
  --out /Users/randifirdaus/Documents/indonesian-coastal-flood-catalogue/data
```

---

## 🗺️ 6. Rencana Tahap Berikutnya (Roadmap)

- [x] **Tahap 1**: Prototipe web statis lengkap (`index.html`), parser data katalog v3c, visualisasi peta spasial Leaflet, dasbor Chart.js, filter dinamis, dan fitur ekspor CSV/GeoJSON.
- [ ] **Tahap 2 (Auto-Tracker)**: Pembuatan skrip pemantau otomatis harian/mingguan (`scripts/fetch_google_news.py`) yang mengikis RSS Google News Indonesia dengan kata kunci rob pesisir, menyaring judul dengan *rule-based classifier*, mencocokkan koordinat pesisir (*coastal snap*), menduplikasi/menggabungkan ke `events.json`.
- [ ] **Tahap 3 (CI/CD Otomatis)**: Pembuatan workflow **GitHub Actions** (`.github/workflows/update_catalogue.yml`) dengan penjadwalan *cron* terjadwal yang otomatis menjalankan skrip pelacak, memperbarui `events.json`, dan melakukan `git commit & push` otomatis.
- [ ] **Tahap 4 (Hosting & Publikasi)**: Inisialisasi repositori Git publik dan pengaktifan **GitHub Pages** (Settings → Pages → Branch: `main` → Folder: `/ (root)`).
