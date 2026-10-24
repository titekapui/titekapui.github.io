#!/usr/bin/env python3
"""
Tambah nama wilayah detail (desa, kecamatan, kabupaten, provinsi) ke titik Himawari.

Pemakaian:
  python scripts/himawari_wilayah.py himawari/hotspots-ringan.json out/himawari/hotspots-wilayah.json out/himawari/places.json

Masukan : {base, data:[[lon,lat,frp,n,[jam]], ...]}
Keluaran: {base, data:[[lon,lat,frp,n,[jam],[desa,kec,kab,prov] atau null], ...]}
  - [desa,kec,kab,prov] semuanya "" = laut / tanpa alamat
  - null = belum dicari atau di luar Indonesia (peta mencari sendiri saat popup dibuka)

Sel pencarian ~1 km (lebih rapat dari FIRMS yang ~5 km) supaya desa/kecamatan lebih tepat.
Hasil disimpan permanen di places.json, jadi tiap titik hanya dicari sekali.
"""
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from firms import BOUNDS, GEO_UA, in_box  # noqa: E402

CELL = 0.01   # derajat, ~1 km
DELAY = 1.1   # detik antar permintaan (aturan Nominatim: maks. 1/detik)
BUDGET = float(os.environ.get("HW_GEO_BUDGET", "150"))   # detik maksimal pencarian per putaran


def key(lat, lon):
    def snap(v):
        return round(math.floor(v / CELL + 0.5) * CELL, 2) + 0.0
    return f"h{snap(lat):.2f},{snap(lon):.2f}"


def lookup(lat, lon):
    q = urllib.parse.urlencode({"format": "jsonv2", "zoom": 14, "addressdetails": 1,
                                "accept-language": "id", "lat": lat, "lon": lon})
    req = urllib.request.Request("https://nominatim.openstreetmap.org/reverse?" + q,
                                 headers={"User-Agent": GEO_UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.load(r)
    a = j.get("address")
    if not a:   # laut / tanpa alamat
        return {"desa": "", "kec": "", "kab": "", "prov": ""}
    return {
        "desa": a.get("village") or a.get("suburb") or a.get("hamlet") or a.get("neighbourhood") or "",
        "kec":  a.get("municipality") or a.get("city_district") or a.get("subdistrict") or "",
        "kab":  a.get("county") or a.get("city") or a.get("regency") or a.get("state_district") or a.get("town") or "",
        "prov": a.get("state") or a.get("region") or "",
    }


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "himawari/hotspots-ringan.json"
    dst = sys.argv[2] if len(sys.argv) > 2 else "out/himawari/hotspots-wilayah.json"
    cache = sys.argv[3] if len(sys.argv) > 3 else "out/himawari/places.json"
    if not os.path.exists(src):
        print(f"{src} tidak ada, dilewati.")
        return
    with open(src, encoding="utf-8") as f:
        j = json.load(f)
    pts = j.get("data")
    if not isinstance(pts, list):
        sys.exit("Format Himawari tidak dikenal: tidak ada data[].")

    try:
        with open(cache, encoding="utf-8") as f:
            places = json.load(f)
    except (OSError, ValueError):
        places = {}

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    # sel yang belum punya nama; Aceh didahulukan, lalu FRP tertinggi
    need = {}
    for p in pts:
        lon, lat = num(p[0]), num(p[1])
        if not in_box(lat, lon, BOUNDS["indonesia"]):
            continue
        k = key(lat, lon)
        if k in places:
            continue
        score = (1e6 if in_box(lat, lon, BOUNDS["aceh"]) else 0) + num(p[2])
        if k not in need or score > need[k][2]:
            need[k] = (lat, lon, score)
    todo = sorted(need.items(), key=lambda kv: -kv[1][2])

    t0, added, fails = time.time(), 0, 0
    for k, (lat, lon, _) in todo:
        if time.time() - t0 > BUDGET or fails >= 3:
            break
        try:
            places[k] = lookup(lat, lon)
            added += 1
            fails = 0
        except Exception as e:  # noqa: BLE001
            fails += 1
            print("Cari wilayah Himawari gagal:", e, file=sys.stderr)
        time.sleep(DELAY)
    print(f"Himawari wilayah ditambah: {added}, sisa: {len(todo) - added}")

    out = []
    for p in pts:
        lon, lat = num(p[0]), num(p[1])
        row = list(p[:5])
        pl = places.get(key(lat, lon)) if in_box(lat, lon, BOUNDS["indonesia"]) else None
        row.append([pl["desa"], pl["kec"], pl["kab"], pl["prov"]] if pl else None)
        out.append(row)

    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(cache) or ".", exist_ok=True)
    j["data"] = out
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, separators=(",", ":"))
    with open(cache, "w", encoding="utf-8") as f:
        json.dump(places, f, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


if __name__ == "__main__":
    main()
