# Titik api Himawari otomatis

Skrip Python mengambil produk **Wild Fire (L2WLF)** dari FTP JAXA P-Tree, menggabungkannya menjadi
`himawari/hotspots.geojson`, dan peta `himawari/index.html` memuatnya. GitHub Actions menjalankannya
tiap 30 menit.

Semua file ada di satu subfolder agar tidak bentrok dengan isi repo lain:

```
.github/workflows/fetch-himawari.yml   jadwal otomatis (satu-satunya file di luar himawari/)
himawari/fetch_himawari.py             unduh FTP + gabung ke GeoJSON
himawari/index.html                    peta (Leaflet)
himawari/hotspots.geojson              dibuat oleh skrip
himawari/README.md                     file ini
```

## Menambahkan ke repo yang sudah ada

1. Salin folder `himawari/` dan file `.github/workflows/fetch-himawari.yml` ke akar repo.
   Kalau repo sudah punya folder `.github/workflows/`, cukup tambahkan satu file itu; workflow
   lain tidak terpengaruh.
2. Di **Settings > Secrets and variables > Actions > Secrets** tambahkan `FTP_USER` dan `FTP_PASS`
   (ID dan kata sandi FTP P-Tree).
3. Di **Settings > Actions > General > Workflow permissions**, pilih **Read and write permissions**
   (workflow perlu menyimpan `hotspots.geojson`). Workflow sudah meminta izin `contents: write`,
   tetapi pengaturan tingkat organisasi bisa menimpanya.
4. Buka **Actions > Ambil titik api Himawari > Run workflow** untuk uji pertama, lalu baca lognya.

## Hal yang perlu diperhatikan di repo yang sudah berisi

- **Riwayat commit.** Bot membuat satu commit tiap kali ada data baru (sampai tiap 30 menit).
  Kalau riwayat repo ingin tetap bersih, ubah jadwal di `cron` menjadi lebih jarang
  (misalnya `0 * * * *` untuk tiap jam).
- **Push bersamaan.** Jika Anda ikut mendorong commit ke cabang yang sama, workflow melakukan
  `git pull --rebase` dan mencoba lagi sampai 3 kali.
- **Cabang terlindungi.** Jika cabang utama memakai aturan perlindungan yang melarang push
  langsung, push bot akan ditolak. Solusinya: izinkan bot, atau ubah workflow agar menyimpan
  ke cabang khusus.
- **GitHub Pages.** Peta tampil di `.../himawari/` jika Pages disajikan dari akar repo. Jika
  Pages disajikan dari folder `docs/`, pindahkan folder `himawari/` ke `docs/himawari/` dan
  ubah jalur `himawari/...` di workflow dan di `OUT` pada skrip. Jika situs di-deploy lewat
  workflow Pages sendiri, push oleh bot (memakai `GITHUB_TOKEN`) tidak memicu workflow lain,
  jadi `hotspots.geojson` baru tampil di situs setelah deploy berikutnya.
- **Visibilitas.** Syarat P-Tree kemungkinan melarang membagikan ulang data. Jika repo ini
  publik, `hotspots.geojson` ikut publik. Baca kebijakan P-Tree dulu, atau simpan GeoJSON
  di repo privat saja.

## Memakai peta tanpa hosting

Unduh `himawari/hotspots.geojson`, buka `himawari/index.html` di browser, lalu pilih atau seret
file GeoJSON itu ke peta. CSV mentah dari P-Tree juga bisa dimuat langsung.

## Menjalankan di komputer sendiri

```
export FTP_USER=... FTP_PASS=...
python himawari/fetch_himawari.py
```

## Pengaturan (variabel lingkungan)

| Nama       | Bawaan                    | Arti                                              |
|------------|---------------------------|---------------------------------------------------|
| `FTP_BASE` | `/pub/himawari/L2/WLF`    | folder produk di FTP                              |
| `HOURS`    | `24`                      | berapa jam ke belakang yang disimpan              |
| `BBOX`     | `94,-12,142,7`            | barat,selatan,timur,utara (bawaan: Indonesia)     |
| `FTP_HOST` | `ftp.ptree.jaxa.jp`       | server                                            |
| `FTP_TLS`  | `0`                       | isi `1` jika server meminta FTPS                  |
| `OUT`      | `himawari/hotspots.geojson` | lokasi file keluaran                            |

Di GitHub, `FTP_BASE`, `HOURS`, dan `BBOX` bisa diubah lewat tab **Variables** tanpa mengubah kode.

## Yang perlu dicek setelah akun aktif

Skrip ditulis dari dokumentasi produk dan **belum diuji dengan server asli** (butuh akun).

- **Jalur folder.** `FTP_BASE` adalah perkiraan. Jika folder tidak ditemukan atau tidak ada file,
  skrip mencetak pesan dan isi folder dasar di log. Sesuaikan `FTP_BASE`.
- **Nama kolom CSV.** Skrip mencari kolom berawalan `lat` dan `lon`, serta kolom yang memuat
  `frp`, `firepower`, atau `power`. Jika galat menyebut kolom tidak ditemukan, kirim dua baris
  header (`#`) dari satu file untuk disesuaikan.
- **Penelusuran folder.** Folder bertanggal (`YYYY`, `YYYYMM`, `YYYYMMDD`, `MM`, `DD`, `hh`)
  di luar jendela waktu dilewati supaya tidak menelusuri seluruh arsip.

## Catatan

- Titik Himawari berukuran sekitar 2 km dan bisa mengandung alarm palsu: anggap sebagai
  peringatan dini, bukan konfirmasi kebakaran.
- Waktu dalam data adalah UTC; peta menampilkan UTC dan WIB.
- Kata sandi hanya disimpan di GitHub Secrets, jangan ditulis di kode atau di file HTML.
