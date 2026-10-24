#!/usr/bin/env python3
"""Ambil titik api Himawari (JAXA P-Tree, produk L2 Wild Fire) lewat FTP,
gabungkan menjadi GeoJSON lengkap (arsip) DAN JSON ringan untuk web.

Kredensial dibaca dari environment (jangan ditulis di kode):
  FTP_USER, FTP_PASS            wajib
  FTP_HOST   default ftp.ptree.jaxa.jp
  FTP_BASE   default /pub/himawari/L2/WLF   (cek struktur asli setelah login)
  HOURS      default 24                     (jendela waktu yang disimpan)
  BBOX       default 94,-12,142,7           (barat,selatan,timur,utara)
  OUT        default himawari/hotspots.geojson          (lengkap, juga penyimpan status)
  OUT_LIGHT  default himawari/hotspots-ringan.json      (ringan, untuk web)
  GRID       default 2  (jumlah desimal koordinat sel; 2 = sekitar 1 km)
  FTP_TLS    set 1 jika server meminta FTPS

Format hotspots-ringan.json:
  {"generated":..., "base":"jam ke-0 (UTC)",
   "fields":["lon","lat","frp","n","hrs"],
   "data":[[lon,lat,frp_tertinggi,jumlah_deteksi,[jam sejak base,...]], ...]}
  Jam asli sebuah deteksi = base + hrs jam (UTC). WIB = UTC + 7.
"""
import io
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from ftplib import FTP, FTP_TLS

HOST = os.environ.get("FTP_HOST", "ftp.ptree.jaxa.jp")
BASE = os.environ.get("FTP_BASE", "/pub/himawari/L2/WLF")
HOURS = int(os.environ.get("HOURS", "24"))
BBOX = [float(x) for x in os.environ.get("BBOX", "94,-12,142,7").split(",")]
OUT = os.environ.get("OUT", "himawari/hotspots.geojson")
OUT_LIGHT = os.environ.get("OUT_LIGHT", "himawari/hotspots-ringan.json")
GRID = int(os.environ.get("GRID", "2"))
USE_TLS = os.environ.get("FTP_TLS", "0") == "1"
MAX_DEPTH = 7
TFMT = "%Y-%m-%dT%H:%MZ"

# Contoh nama: H09_20261018_0310_L2WLF010_FLDK.06001_06001.csv
NAME_RE = re.compile(r"^H0\d_(\d{8})_(\d{4})_.*WLF.*\.csv$", re.I)


def time_from_name(name):
    m = NAME_RE.match(name)
    if not m:
        return None
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M").replace(tzinfo=timezone.utc)


# ---------- Penelusuran FTP ----------
def list_dir(ftp, path):
    """Kembalikan daftar (nama, apakah_folder)."""
    try:
        out = []
        for name, facts in ftp.mlsd(path):
            if name in (".", "..") or facts.get("type") in ("cdir", "pdir"):
                continue
            out.append((name, facts.get("type") == "dir"))
        return out
    except Exception:
        pass
    # Cadangan untuk server tanpa MLSD
    out = []
    here = ftp.pwd()
    for n in ftp.nlst(path):
        base = n.rstrip("/").split("/")[-1]
        if base in (".", ".."):
            continue
        is_dir = False
        try:
            ftp.cwd(path.rstrip("/") + "/" + base)
            is_dir = True
        except Exception:
            pass
        finally:
            ftp.cwd(here)
        out.append((base, is_dir))
    return out


def check_dir(name, ctx, start, end):
    """Pangkas folder bertanggal di luar jendela waktu.
    ctx = (bulan: date|None, hari: date|None). Mengembalikan (diizinkan, ctx_baru).
    Nama folder yang tidak dikenali selalu diizinkan."""
    ym, day = ctx
    if re.fullmatch(r"(19|20)\d{2}", name):
        return start.year <= int(name) <= end.year, ctx
    if re.fullmatch(r"\d{8}", name):
        try:
            d = datetime.strptime(name, "%Y%m%d").date()
        except ValueError:
            return True, ctx
        return start.date() <= d <= end.date(), (ym, d)
    if re.fullmatch(r"\d{6}", name):
        try:
            m = datetime.strptime(name, "%Y%m").date()
        except ValueError:
            return True, ctx
        ok = (start.year, start.month) <= (m.year, m.month) <= (end.year, end.month)
        return ok, (m, None)
    if re.fullmatch(r"\d{2}", name):
        n = int(name)
        if day is None and ym is not None:  # folder hari
            try:
                d = date(ym.year, ym.month, n)
            except ValueError:
                return False, ctx
            return start.date() <= d <= end.date(), (ym, d)
        if day is not None:  # folder jam
            slot = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(hours=n)
            return slot + timedelta(hours=1) > start and slot <= end, ctx
    return True, ctx


def walk(ftp, path, ctx, depth, start, end, found):
    if depth > MAX_DEPTH:
        return
    for name, is_dir in list_dir(ftp, path):
        full = path.rstrip("/") + "/" + name
        if is_dir:
            ok, nctx = check_dir(name, ctx, start, end)
            if ok:
                walk(ftp, full, nctx, depth + 1, start, end, found)
        else:
            t = time_from_name(name)
            if t and start <= t <= end:
                found.append((t, name, full))


# ---------- Parsing CSV ----------
def parse_csv(text, t):
    """Baca satu file CSV Wild Fire -> daftar fitur GeoJSON."""
    lines = [l for l in text.splitlines() if l.strip()]
    head = [l for l in lines if l.startswith("#")]
    body = [l for l in lines if not l.startswith("#")]
    if not head:
        raise ValueError("header (#) tidak ditemukan")
    names = [s.strip().lower() for s in head[-1].lstrip("#").strip().split(",")]
    i_lat = next((i for i, n in enumerate(names) if n.startswith("lat")), -1)
    i_lon = next((i for i, n in enumerate(names) if n.startswith("lon")), -1)
    i_frp = next((i for i, n in enumerate(names) if re.search(r"frp|firepower|power", n)), -1)
    if i_lat < 0 or i_lon < 0:
        raise ValueError("kolom lat/lon tidak ditemukan; kolom: " + ", ".join(names))

    west, south, east, north = BBOX
    iso = t.strftime(TFMT)
    feats = []
    for row in body:
        c = row.split(",")
        try:
            lat, lon = float(c[i_lat]), float(c[i_lon])
        except (ValueError, IndexError):
            continue
        if not (west <= lon <= east and south <= lat <= north):
            continue
        frp = None
        if i_frp >= 0:
            try:
                frp = round(float(c[i_frp]), 1)
            except (ValueError, IndexError):
                pass
        feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 3), round(lat, 3)]},
            "properties": {"time": iso, "frp": frp},
        })
    return feats


# ---------- Versi ringan untuk web ----------
def build_light(feats, generated):
    """Gabungkan titik per sel GRID; simpan jam deteksi sebagai jam sejak base."""
    rows = []
    for ft in feats:
        p = ft["properties"]
        try:
            t = datetime.strptime(p["time"], TFMT).replace(tzinfo=timezone.utc, minute=0)
        except (KeyError, ValueError):
            continue
        lon, lat = ft["geometry"]["coordinates"]
        rows.append((round(lon, GRID), round(lat, GRID), p.get("frp") or 0, t))
    if not rows:
        print("Tidak ada titik untuk versi ringan.")
        return
    base = min(r[3] for r in rows)
    cells = {}
    for lon, lat, frp, t in rows:
        c = cells.setdefault((lon, lat), {"frp": 0, "n": 0, "h": set()})
        c["frp"] = max(c["frp"], frp)
        c["n"] += 1
        c["h"].add(int((t - base) / timedelta(hours=1)))
    data = [[k[0], k[1], round(v["frp"], 1), v["n"], sorted(v["h"])] for k, v in cells.items()]
    os.makedirs(os.path.dirname(OUT_LIGHT) or ".", exist_ok=True)
    with open(OUT_LIGHT, "w", encoding="utf-8") as f:
        json.dump({"generated": generated, "base": base.strftime(TFMT),
                   "fields": ["lon", "lat", "frp", "n", "hrs"], "data": data},
                  f, separators=(",", ":"))
    print("Versi ringan: %d titik unik (dari %d deteksi) di %s" % (len(data), len(rows), OUT_LIGHT))


# ---------- Utama ----------
def load_existing(start):
    try:
        with open(OUT, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return [], {}, None
    feats = []
    for ft in data.get("features", []):
        try:
            t = datetime.strptime(ft["properties"]["time"], TFMT).replace(tzinfo=timezone.utc)
        except (KeyError, ValueError):
            continue
        if t >= start:
            feats.append(ft)
    processed = {}
    for n in data.get("processed", []):
        t = time_from_name(n)
        if t and t >= start:
            processed[n] = True
    return feats, processed, data.get("generated")


def main():
    user, pw = os.environ.get("FTP_USER"), os.environ.get("FTP_PASS")
    if not user or not pw:
        sys.exit("FTP_USER dan FTP_PASS belum diatur")

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=HOURS)
    feats, processed, old_generated = load_existing(start)

    ftp = (FTP_TLS if USE_TLS else FTP)(HOST, timeout=60)
    ftp.login(user, pw)
    if USE_TLS:
        ftp.prot_p()
    ftp.set_pasv(True)

    found = []
    try:
        walk(ftp, BASE, (None, None), 0, start, end, found)
    except Exception as e:
        print("Gagal membuka folder %s: %s" % (BASE, e))
        print("Periksa FTP_BASE (struktur folder asli ada di panduan P-Tree atau lewat klien FTP).")
        try:
            ftp.quit()
        except Exception:
            pass
        sys.exit(1)
    if not found:
        print("Tidak ada file Wild Fire dalam jendela waktu. Isi folder %s:" % BASE)
        for name, is_dir in list_dir(ftp, BASE)[:30]:
            print("  %s%s" % (name, "/" if is_dir else ""))
        print("Periksa FTP_BASE dan struktur folder, lalu coba lagi.")
        ftp.quit()
        sys.exit(1)

    new_files = [x for x in sorted(found) if x[1] not in processed]
    print("Ditemukan %d file, %d baru." % (len(found), len(new_files)))
    errors = 0
    for t, name, full in new_files:
        try:
            buf = io.BytesIO()
            ftp.retrbinary("RETR " + full, buf.write)
            feats.extend(parse_csv(buf.getvalue().decode("utf-8", "replace"), t))
            processed[name] = True
        except Exception as e:  # satu file gagal tidak menghentikan yang lain
            errors += 1
            print("Gagal %s: %s" % (name, e))
    try:
        ftp.quit()
    except Exception:
        pass

    if not new_files:
        print("Tidak ada file baru; GeoJSON tidak diubah.")
        if not os.path.exists(OUT_LIGHT) and feats:  # buat sekali jika belum ada
            build_light(feats, old_generated)
        return
    if errors == len(new_files):
        sys.exit("Semua file baru gagal diproses; data lama tidak diubah.")

    generated = end.strftime(TFMT)
    os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({
            "type": "FeatureCollection",
            "generated": generated,
            "processed": sorted(processed),
            "features": feats,
        }, f, separators=(",", ":"))
    print("Tersimpan %d titik di %s" % (len(feats), OUT))
    build_light(feats, generated)


if __name__ == "__main__":
    main()
