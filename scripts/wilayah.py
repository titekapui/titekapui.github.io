#!/usr/bin/env python3
"""
Pencari nama wilayah OFFLINE (point-in-polygon) dari berkas batas administrasi GeoJSON.
Pengganti panggilan Nominatim: tanpa batas permintaan, tanpa jaringan, hasil identik tiap putaran.

Berkas batas : scripts/batas/wilayah.geojson   (atau ubah lewat env BATAS_FILE)
Isi          : FeatureCollection, geometri Polygon / MultiPolygon, koordinat WGS84 (lon, lat).
Nama kolom   : dikenali otomatis dari daftar KEYS di bawah (tidak peka huruf besar/kecil).
               Cukup salah satu tingkat saja yang ada (mis. hanya kabupaten + provinsi).

Hanya memakai Python standar.

Pemakaian:
    import wilayah
    w = wilayah.load()            # None bila berkas batas tidak ada
    if w: hasil = w.lookup(lat, lon)
    # hasil = {"desa","kec","kab","prov","sea"}; sea=True bila titik tidak berada di poligon mana pun
"""
import json
import math
import os

BATAS_FILE = os.environ.get(
    "BATAS_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "batas", "wilayah.geojson"),
)

KEYS = {
    "desa": ["desa", "village", "wadmkd", "namobj_desa", "nama_desa", "name_4", "kel_desa"],
    "kec":  ["kec", "kecamatan", "district", "wadmkc", "nama_kec", "name_3"],
    "kab":  ["kab", "kabupaten", "kabkot", "kab_kota", "wadmkk", "nama_kab", "regency", "name_2"],
    "prov": ["prov", "provinsi", "province", "wadmpr", "nama_prov", "name_1"],
}

GRID = 0.5          # derajat, ukuran sel indeks ruang
TOLERANSI = 0.01    # derajat (~1 km): titik pesisir yang jatuh sedikit di luar poligon yang disederhanakan


def _pick(props, names):
    low = {str(k).lower(): v for k, v in (props or {}).items()}
    for n in names:
        v = low.get(n)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _ring_bbox(ring):
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _in_ring(x, y, ring):
    """Ray casting; True bila (x, y) berada di dalam cincin."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


class Wilayah:
    def __init__(self, gj):
        self.items = []      # (bbox, [poligon: [cincin_luar, lubang...]], atribut)
        self.grid = {}
        for ft in gj.get("features", []):
            g = ft.get("geometry") or {}
            if g.get("type") == "Polygon":
                polys = [g.get("coordinates") or []]
            elif g.get("type") == "MultiPolygon":
                polys = g.get("coordinates") or []
            else:
                continue
            polys = [p for p in polys if p and p[0]]
            if not polys:
                continue
            pr = ft.get("properties") or {}
            attr = {k: _pick(pr, v) for k, v in KEYS.items()}
            boxes = [_ring_bbox(p[0]) for p in polys]
            bbox = (min(b[0] for b in boxes), min(b[1] for b in boxes),
                    max(b[2] for b in boxes), max(b[3] for b in boxes))
            idx = len(self.items)
            self.items.append((bbox, polys, boxes, attr))
            for gx in range(math.floor(bbox[0] / GRID), math.floor(bbox[2] / GRID) + 1):
                for gy in range(math.floor(bbox[1] / GRID), math.floor(bbox[3] / GRID) + 1):
                    self.grid.setdefault((gx, gy), []).append(idx)
        self._memo = {}

    def _hit(self, lat, lon):
        for idx in self.grid.get((math.floor(lon / GRID), math.floor(lat / GRID)), ()):
            bbox, polys, boxes, attr = self.items[idx]
            if not (bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]):
                continue
            for poly, b in zip(polys, boxes):
                if not (b[0] <= lon <= b[2] and b[1] <= lat <= b[3]):
                    continue
                if _in_ring(lon, lat, poly[0]) and not any(_in_ring(lon, lat, h) for h in poly[1:]):
                    return attr
        return None

    def lookup(self, lat, lon):
        key = (round(lat, 3), round(lon, 3))
        if key in self._memo:
            return self._memo[key]
        a = self._hit(lat, lon)
        if a is None:   # toleransi pesisir: coba 4 arah sejauh ~1 km
            for dy, dx in ((TOLERANSI, 0), (-TOLERANSI, 0), (0, TOLERANSI), (0, -TOLERANSI)):
                a = self._hit(lat + dy, lon + dx)
                if a is not None:
                    break
        out = dict(a, sea=False) if a else {"desa": "", "kec": "", "kab": "", "prov": "", "sea": True}
        self._memo[key] = out
        return out


_cache = {}


def load(path=None):
    """Kembalikan objek Wilayah, atau None bila berkas batas tidak ada / tidak terbaca."""
    path = path or BATAS_FILE
    if path in _cache:
        return _cache[path]
    w = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                w = Wilayah(json.load(f))
            if not w.items:
                w = None
        except (OSError, ValueError) as e:
            print("Berkas batas tidak terbaca:", e)
            w = None
    _cache[path] = w
    return w
