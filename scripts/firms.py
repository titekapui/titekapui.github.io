#!/usr/bin/env python3
"""
TITEK APUI MONITOR - NASA FIRMS -> CSV statis (pengganti Google Apps Script).

Pemakaian:  python scripts/firms.py [folder_keluaran]      (bawaan: out)

Keluaran di <folder_keluaran>/firms/:
  aceh.csv, indonesia.csv, global.csv   format kolom sama dengan respons Apps Script lama
  titik_api.csv                         data Indonesia untuk diunduh (pengganti sheet "titik_api")
  places.json                           cache nama tempat per sel ~5 km (pengganti sheet "wilayah")
  meta.json                             waktu pembaruan

Hanya butuh Python standar (tanpa pip install).
"""
import csv
import io
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wilayah  # noqa: E402  (pencari wilayah offline; None bila berkas batas tidak ada)

URLS = {
    "terra_aqua": "https://firms2.modaps.eosdis.nasa.gov/data/active_fire/modis-c6.1/csv/MODIS_C6_1_Global_24h.csv",
    "suomi_npp":  "https://firms2.modaps.eosdis.nasa.gov/data/active_fire/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Global_24h.csv",
    "noaa20":     "https://firms2.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_Global_24h.csv",
    "noaa21":     "https://firms2.modaps.eosdis.nasa.gov/data/active_fire/noaa-21-viirs-c2/csv/J2_VIIRS_C2_Global_24h.csv",
}
SAT_LABEL = {"suomi_npp": "Suomi NPP", "noaa20": "NOAA-20", "noaa21": "NOAA-21", "terra_aqua": "Terra/Aqua (MODIS)"}

BOUNDS = {  # (lat_min, lat_max, lon_min, lon_max)
    "aceh":      (1.85, 6.10, 94.80, 98.30),
    "indonesia": (-11.0, 6.5, 95.0, 141.0),
    "global":    None,
}

MAX_ROWS = 5000          # batas titik per berkas (FRP tertinggi diprioritaskan)
RADIUS = 0.005           # derajat, sekitar 550 m
WINDOW_JAM = 3           # jendela waktu penggabungan (jam)
MIN_SAT_OK = int(os.environ.get("MIN_SAT_OK", "2"))   # minimal sumber FIRMS yang harus berhasil; di bawah ini data lama dipertahankan
GLOBAL_MIN_FRP = 0       # naikkan (mis. 5) bila global terlalu berat; 0 = tanpa saringan

GEO_CELL = 0.05          # ukuran sel nama tempat, derajat (~5 km)
GEO_DELAY = 1.1          # detik antar permintaan (aturan Nominatim: maks. 1/detik)
GEO_BUDGET = float(os.environ.get("GEO_BUDGET", "240"))   # detik maksimal pencarian per putaran
GEO_UA = "TitekApuiMonitor/1.0 (lonaliakbar@gmail.com)"   # Nominatim mewajibkan identitas aplikasi
SEA_LABEL = "(Laut / tanpa alamat)"

HEAD = ["latitude", "longitude", "frp", "confidence", "acq_date", "acq_time", "daynight",
        "satelit", "jumlah_deteksi", "kabupaten", "provinsi"]


# ---------- UNDUH & PARSE ----------
def fetch_text(url, tries=3):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": GEO_UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(5 * (i + 1))
    raise RuntimeError(f"gagal unduh {url}: {last}")


def parse_firms(text, key):
    rd = csv.reader(io.StringIO(text))
    try:
        h = next(rd)
    except StopIteration:
        return None
    idx = {n: (h.index(n) if n in h else -1) for n in
           ("latitude", "longitude", "frp", "confidence", "acq_date", "acq_time", "daynight")}
    if idx["latitude"] < 0 or idx["longitude"] < 0:
        return None

    def g(c, n):
        i = idx[n]
        return c[i].strip() if 0 <= i < len(c) else ""

    out = []
    for c in rd:
        if len(c) < len(h):
            continue
        try:
            lat, lon = float(c[idx["latitude"]]), float(c[idx["longitude"]])
        except ValueError:
            continue
        try:
            frp = float(g(c, "frp"))
        except ValueError:
            frp = 0.0
        out.append({"lat": lat, "lon": lon, "frp": frp, "confidence": g(c, "confidence"),
                    "acq_date": g(c, "acq_date"), "acq_time": g(c, "acq_time"),
                    "daynight": g(c, "daynight"), "sat": key})
    return out


def load_rows():
    keys = list(URLS)
    with ThreadPoolExecutor(max_workers=4) as ex:
        texts = list(ex.map(lambda k: _safe_fetch(URLS[k]), keys))
    rows, failed = [], []
    for k, t in zip(keys, texts):
        parsed = parse_firms(t, k) if t else None
        if parsed is None:
            failed.append(k)
            continue
        rows.extend(parsed)
    return rows, failed


def _safe_fetch(url):
    try:
        return fetch_text(url)
    except Exception as e:  # noqa: BLE001
        print("ERROR:", e, file=sys.stderr)
        return None


# ---------- PENGGABUNGAN TITIK ----------
_day = {}


def epoch_hours(d, t):
    base = _day.get(d)
    if base is None:
        try:
            base = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() / 3600
        except ValueError:
            base = 0.0
        _day[d] = base
    s = str(t).zfill(4)
    try:
        return base + int(s[:2]) + int(s[2:4]) / 60
    except ValueError:
        return base


def dedup(rows, radius=RADIUS, window=WINDOW_JAM):
    """Gabungkan titik berdekatan (lokasi + waktu) lintas satelit memakai grid."""
    n = len(rows)
    t = [epoch_hours(r["acq_date"], r["acq_time"]) for r in rows]
    gy = [math.floor(r["lat"] / radius) for r in rows]
    gx = [math.floor(r["lon"] / radius) for r in rows]
    grid = {}
    for i in range(n):
        grid.setdefault((gy[i], gx[i]), []).append(i)

    used = bytearray(n)
    result = []
    for i in range(n):
        if used[i]:
            continue
        used[i] = 1
        cluster = [i]
        ri = rows[i]
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                for j in grid.get((gy[i] + dy, gx[i] + dx), ()):
                    if used[j]:
                        continue
                    rj = rows[j]
                    if abs(rj["lat"] - ri["lat"]) > radius or abs(rj["lon"] - ri["lon"]) > radius:
                        continue
                    if abs(t[j] - t[i]) > window:
                        continue
                    used[j] = 1
                    cluster.append(j)
        best = cluster[0]
        sats = []
        for j in cluster:
            if rows[j]["frp"] > rows[best]["frp"]:
                best = j
            if rows[j]["sat"] not in sats:
                sats.append(rows[j]["sat"])
        rep = rows[best]
        result.append({"lat": rep["lat"], "lon": rep["lon"], "frp": rep["frp"],
                       "confidence": rep["confidence"], "acq_date": rep["acq_date"],
                       "acq_time": rep["acq_time"], "daynight": rep["daynight"],
                       "sat_list": sats, "detect_count": len(cluster)})
    return result


# ---------- NAMA TEMPAT ----------
def in_box(lat, lon, b):
    return b is None or (b[0] <= lat <= b[1] and b[2] <= lon <= b[3])


def geo_key(lat, lon):
    def snap(v):
        return round(math.floor(v / GEO_CELL + 0.5) * GEO_CELL, 2) + 0.0   # +0.0 menghindari "-0.00"
    return f"k{snap(lat):.2f},{snap(lon):.2f}"


def geo_nominatim(lat, lon):
    q = urllib.parse.urlencode({"format": "jsonv2", "zoom": 10, "addressdetails": 1,
                                "accept-language": "id", "lat": lat, "lon": lon})
    req = urllib.request.Request("https://nominatim.openstreetmap.org/reverse?" + q,
                                 headers={"User-Agent": GEO_UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.load(r)
    a = j.get("address")
    if not a:   # "Unable to geocode": laut / tanpa alamat
        return {"kab": "", "prov": "", "sea": True}
    return {"kab": a.get("county") or a.get("city") or a.get("regency") or a.get("state_district") or a.get("town") or "",
            "prov": a.get("state") or a.get("region") or a.get("country") or "",
            "sea": False}


def fill_places(rows, places):
    """Cari nama tempat lewat Nominatim untuk sel yang belum ada (hanya bila berkas batas tidak tersedia).
    Aceh didahulukan, lalu FRP tertinggi."""
    if wilayah.load():
        print("Berkas batas tersedia: Nominatim tidak dipakai.")
        return
    need = {}
    for r in rows:
        if not in_box(r["lat"], r["lon"], BOUNDS["indonesia"]):
            continue
        k = geo_key(r["lat"], r["lon"])
        if k in places:
            continue
        score = (1e6 if in_box(r["lat"], r["lon"], BOUNDS["aceh"]) else 0) + r["frp"]
        cur = need.get(k)
        if cur is None or score > cur[2]:
            need[k] = (r["lat"], r["lon"], score)
    todo = sorted(need.items(), key=lambda kv: -kv[1][2])

    t0, added, fails = time.time(), 0, 0
    for k, (lat, lon, _) in todo:
        if time.time() - t0 > GEO_BUDGET or fails >= 3:
            break
        try:
            places[k] = geo_nominatim(lat, lon)
            added += 1
            fails = 0
        except Exception as e:  # noqa: BLE001
            fails += 1
            print("Cari nama tempat gagal:", e, file=sys.stderr)
        time.sleep(GEO_DELAY)
    print(f"Nama tempat ditambah: {added}, sisa: {len(todo) - added}")


# ---------- SUSUN & TULIS ----------
def build_rows(all_rows, region, places):
    b = BOUNDS[region]
    rows = [r for r in all_rows if in_box(r["lat"], r["lon"], b)] if b else all_rows
    if region == "global" and GLOBAL_MIN_FRP > 0:
        rows = [r for r in rows if r["frp"] >= GLOBAL_MIN_FRP]
    merged = dedup(rows)
    merged.sort(key=lambda r: -r["frp"])
    capped = merged[:MAX_ROWS]
    w = wilayah.load()
    for r in capped:
        p = w.lookup(r["lat"], r["lon"]) if w else places.get(geo_key(r["lat"], r["lon"]))
        r["kabupaten"] = p["kab"] if p and not p["sea"] else ""
        r["provinsi"] = (SEA_LABEL if p["sea"] else p["prov"]) if p else ""
    print(f"{region}: {len(rows)} mentah -> {len(merged)} gabungan -> {len(capped)} ditulis")
    return capped


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEAD)
        for r in rows:
            w.writerow([r["lat"], r["lon"], r["frp"], r["confidence"], r["acq_date"], r["acq_time"],
                        r["daynight"], "+".join(r["sat_list"]), r["detect_count"],
                        r["kabupaten"], r["provinsi"]])


def conf_label(c):
    try:
        n = float(c)
    except ValueError:
        n = None
    if c == "h" or (n is not None and n > 80):
        return "Tinggi"
    if c == "n" or (n is not None and n >= 30):
        return "Sedang"
    return "Rendah"


def wib_parts(d, t):
    s = str(t).zfill(4)
    try:
        dt = datetime.strptime(f"{d} {s[:2]}:{s[2:4]}", "%Y-%m-%d %H:%M") + timedelta(hours=7)
    except ValueError:
        return "", ""
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def write_titik_api(path, rows):
    head = ["Tanggal", "Jam (WIB)", "Latitude", "Longitude", "Kabupaten/Kota", "Provinsi", "Satelit",
            "Kepercayaan", "Energi (MW)", "Jumlah Deteksi", "Google Maps"]
    data = sorted(rows, key=lambda r: (r["acq_date"] + str(r["acq_time"]).zfill(4), r["frp"]), reverse=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:   # BOM agar Excel membaca UTF-8
        w = csv.writer(f)
        w.writerow(head)
        for r in data:
            tgl, jam = wib_parts(r["acq_date"], r["acq_time"])
            w.writerow([tgl, jam, r["lat"], r["lon"], r["kabupaten"], r["provinsi"],
                        " + ".join(SAT_LABEL.get(k, k) for k in r["sat_list"]),
                        conf_label(r["confidence"]), r["frp"], r["detect_count"],
                        f"https://www.google.com/maps?q={r['lat']},{r['lon']}"])


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "out"
    d = os.path.join(out, "firms")
    os.makedirs(d, exist_ok=True)

    rows, failed = load_rows()
    ok = len(URLS) - len(failed)
    if ok < MIN_SAT_OK:
        print(f"Dibatalkan: hanya {ok} dari {len(URLS)} sumber berhasil (minimal {MIN_SAT_OK}), gagal: "
              + ", ".join(failed) + ". Data lama tetap dipakai.", file=sys.stderr)
        sys.exit(1)
    if failed:
        # Lanjutkan dengan sumber yang berhasil; catat di meta.json agar UI bisa memberi peringatan.
        print("PERINGATAN: sumber gagal dan dilewati: " + ", ".join(failed), file=sys.stderr)

    pp = os.path.join(d, "places.json")
    try:
        with open(pp, encoding="utf-8") as f:
            places = json.load(f)
    except (OSError, ValueError):
        places = {}

    fill_places(rows, places)
    with open(pp, "w", encoding="utf-8") as f:
        json.dump(places, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    for region in ("aceh", "indonesia", "global"):
        capped = build_rows(rows, region, places)
        write_csv(os.path.join(d, region + ".csv"), capped)
        if region == "indonesia":
            write_titik_api(os.path.join(d, "titik_api.csv"), capped)

    with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
        json.dump({"diperbarui": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "titik_mentah": len(rows),
                   "satelit_ok": [k for k in URLS if k not in failed],
                   "satelit_gagal": failed,
                   "wilayah": "poligon" if wilayah.load() else "nominatim"}, f)


if __name__ == "__main__":
    main()
