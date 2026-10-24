#!/usr/bin/env python3
"""
HIMAWARI GeoJSON -> CSV (pengganti imporHimawari di Apps Script).
Waktu ditulis dalam WIB (UTC+7), format DD/MM/YYYY HH:mm:ss.

Pemakaian:  python scripts/himawari_csv.py himawari/hotspots.geojson out/himawari/hotspots.csv
"""
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

WIB = timezone(timedelta(hours=7))


def to_wib(s):
    if not s:
        return ""
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(WIB).strftime("%d/%m/%Y %H:%M:%S")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "himawari/hotspots.geojson"
    dst = sys.argv[2] if len(sys.argv) > 2 else "out/himawari/hotspots.csv"
    if not os.path.exists(src):
        print(f"{src} tidak ada, dilewati.")
        return
    with open(src, encoding="utf-8") as f:
        gj = json.load(f)
    feats = gj.get("features")
    if not isinstance(feats, list):
        sys.exit("GeoJSON tidak valid: tidak ada features.")

    rows, skipped = [], 0
    for ft in feats:
        geo = ft.get("geometry") or {}
        pr = ft.get("properties") or {}
        c = geo.get("coordinates")
        if geo.get("type") != "Point" or not isinstance(c, list) or len(c) < 2:
            skipped += 1
            continue
        try:
            lon, lat = float(c[0]), float(c[1])   # urutan GeoJSON: longitude, latitude
        except (TypeError, ValueError):
            skipped += 1
            continue
        frp = pr.get("frp")
        rows.append([to_wib(pr.get("time")), f"{lat:.6f}", f"{lon:.6f}",
                     "" if frp is None else f"{float(frp):.2f}", "JAXA Himawari"])

    os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
    with open(dst, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["TGL/BULAN/TAHUN (WIB)", "Latitude", "Longitude", "FRP", "Sumber"])
        w.writerows(rows)
    print(f"Himawari: {len(rows)} titik ditulis, {skipped} dilewati.")


if __name__ == "__main__":
    main()
