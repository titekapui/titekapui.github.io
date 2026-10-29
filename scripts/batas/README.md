# Berkas batas administrasi

Letakkan **`wilayah.geojson`** di folder ini. Selama berkasnya ada, nama wilayah dicari
secara lokal (point-in-polygon) dan **Nominatim tidak dipanggil sama sekali**.
Kalau berkas tidak ada, skrip jatuh kembali ke Nominatim seperti sebelumnya.

Syarat berkas:
- GeoJSON `FeatureCollection`, geometri `Polygon` atau `MultiPolygon`, koordinat WGS84 (lon, lat).
- Sederhanakan geometri (mis. mapshaper `-simplify 5%`) supaya ukuran berkas di bawah ~15 MB.
- Properti dikenali otomatis (tidak peka huruf besar/kecil), salah satu dari:
  - provinsi: `provinsi`, `WADMPR`, `NAME_1`, `prov`
  - kabupaten/kota: `kabupaten`, `KABKOT`, `WADMKK`, `NAME_2`, `kab`
  - kecamatan: `kecamatan`, `WADMKC`, `NAME_3`, `kec`
  - desa: `desa`, `WADMKD`, `NAME_4`, `village`
  Kalau nama kolom Anda berbeda, tambahkan ke daftar `KEYS` di `scripts/wilayah.py`.
- Disarankan satu poligon per **kecamatan atau desa** agar popup Himawari tetap menampilkan
  desa dan kecamatan. Kalau hanya tingkat kabupaten, kolom desa/kecamatan kosong.

Sumber yang lazim dipakai: batas BPS / Badan Informasi Geospasial (BIG), atau GADM level 2-4.
Periksa lisensi sumber yang Anda pilih sebelum menaruhnya di repo publik.
