"""Check that the collected MSK definitions actually work.

For every MSK record and every test point (regional capital) of its region:
  1. WGS-84 -> MSK -> WGS-84 round trip must close to < 5 mm.
  2. The point is "inside the zone" if |E - false_easting| <= MAX_HALF_WIDTH_KM.
A region passes if each of its test points falls inside >= 1 zone of that region.

Plus two global checks:
  * sign convention of the Helmert rotations (MapInfo/GOST -> PROJ) against EPSG:5044
  * federal datums: shift to WGS-84 at reference points is plausible
"""
import csv, json, math, pathlib
from collections import defaultdict

from pyproj import CRS, Transformer
from pyproj.crs import CoordinateOperation

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ROUNDTRIP_TOL_MM = 5.0  # PROJ's linearised 7-parameter Helmert is not an exact inverse (~1 mm for MGGT, 8.45 ppm)
MAX_HALF_WIDTH_KM = 260.0  # 3 deg of longitude at 45N ~ 236 km; margin for 6 deg zones


def load_points():
    pts = defaultdict(list)
    for r in csv.DictReader(open(DATA / "region_capitals.csv", encoding="utf-8")):
        pts[r["region_code"]].append(r)
    return pts


def check_systems():
    systems = json.load(open(DATA / "msk_systems.json"))
    pts = load_points()
    wgs = CRS.from_epsg(4326)
    rows, per_system = [], defaultdict(list)
    for s in systems:
        crs = CRS.from_proj4(s["proj4"])
        fwd = Transformer.from_crs(wgs, crs, always_xy=True)
        inv = Transformer.from_crs(crs, wgs, always_xy=True)
        for p in pts.get(s["region_code"], []):
            lat, lon = float(p["lat"]), float(p["lon"])
            e, n = fwd.transform(lon, lat)
            lon2, lat2 = inv.transform(e, n)
            rt_mm = math.hypot((lon2 - lon) * 111319.49 * math.cos(math.radians(lat)), (lat2 - lat) * 111132.95) * 1000
            off_km = abs(e - s["false_easting"]) / 1000
            row = dict(id=s["id"], region_code=s["region_code"], variant=s["variant"], zone=s["zone"], lon0=s["lon0"],
                       city=p["city"], E=round(e, 3), N=round(n, 3), off_central_km=round(off_km, 1),
                       roundtrip_mm=round(rt_mm, 4), inside_zone=off_km <= MAX_HALF_WIDTH_KM)
            rows.append(row)
            per_system[(s["region_code"], p["city"], s["variant"])].append(row)
    return systems, rows, per_system, pts


def region_summary(per_system, pts, systems):
    have = {s["region_code"] for s in systems}
    out = []
    for code, plist in sorted(pts.items()):
        for p in plist:
            for variant in ("gost2008", "calc"):
                rows = per_system.get((code, p["city"], variant), [])
                if not rows:
                    continue
                best = min(rows, key=lambda r: r["off_central_km"])
                out.append(dict(region_code=code, city=p["city"], variant=variant, zones_tested=len(rows),
                                best_system=best["id"], best_zone=best["zone"], best_lon0=best["lon0"],
                                E=best["E"], N=best["N"], off_central_km=best["off_central_km"],
                                ok=best["inside_zone"] and best["roundtrip_mm"] < ROUNDTRIP_TOL_MM))
    missing = sorted(c for c in pts if c not in have)
    return out, missing


def check_rotation_sign():
    """Our towgs84 (flipped rotations) must reproduce EPSG:5044 (coordinate-frame, GOST) to < 1 cm."""
    gost = Transformer.from_pipeline(CoordinateOperation.from_epsg(5044).to_json())  # Pulkovo 1942 -> WGS 84, lon/lat
    mine = Transformer.from_crs(
        CRS.from_proj4("+proj=longlat +ellps=krass +towgs84=23.57,-140.95,-79.8,0,0.35,0.79,-0.22 +no_defs"),
        CRS.from_epsg(4326), always_xy=True)
    wrong = Transformer.from_crs(
        CRS.from_proj4("+proj=longlat +ellps=krass +towgs84=23.57,-140.95,-79.8,0,-0.35,-0.79,-0.22 +no_defs"),
        CRS.from_epsg(4326), always_xy=True)
    worst_ok = worst_wrong = 0.0
    for lat, lon in [(55.75, 37.6), (59.9, 30.3), (43.1, 131.9), (67.6, 53.0), (64.7, 177.5), (54.7, 20.45)]:
        a = gost.transform(lat, lon)  # EPSG pipeline is (lat, lon) ordered
        for tr, which in ((mine, "ok"), (wrong, "wrong")):
            b = tr.transform(lon, lat)
            d = math.hypot((a[1] - b[0]) * 111319.49 * math.cos(math.radians(lat)), (a[0] - b[1]) * 111132.95)
            if which == "ok":
                worst_ok = max(worst_ok, d)
            else:
                worst_wrong = max(worst_wrong, d)
    return worst_ok, worst_wrong


def check_federal():
    ref = [("Москва", 55.7558, 37.6173), ("Санкт-Петербург", 59.9343, 30.3351), ("Владивосток", 43.1155, 131.8855),
           ("Калининград", 54.7104, 20.4522)]
    res = []
    for epsg in (4284, 4178, 4179, 4200, 4740, 9475, 7683):
        t = Transformer.from_crs(CRS.from_epsg(epsg), CRS.from_epsg(4326), always_xy=True)
        shifts = []
        for name, lat, lon in ref:
            x, y = t.transform(lon, lat)
            d = math.hypot((x - lon) * 111319.49 * math.cos(math.radians(lat)), (y - lat) * 111132.95)
            shifts.append(round(d, 1))
        res.append(dict(epsg=epsg, name=CRS.from_epsg(epsg).name, shift_m=dict(zip([r[0] for r in ref], shifts))))
    return res


def main():
    systems, rows, per_system, pts = check_systems()
    summary, missing = region_summary(per_system, pts, systems)
    ok_rot, wrong_rot = check_rotation_sign()
    fed = check_federal()
    with open(DATA / "validation_points.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    with open(DATA / "validation_regions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0]))
        w.writeheader(); w.writerows(summary)
    json.dump(dict(rotation_sign=dict(max_diff_m_flipped_signs=ok_rot, max_diff_m_unflipped=wrong_rot),
                   federal_shifts=fed, regions_without_msk_data=missing), open(DATA / "validation_summary.json", "w"),
              ensure_ascii=False, indent=1)
    bad = [s for s in summary if not s["ok"]]
    print(f"zone-level rows: {len(rows)}; region/city/variant checks: {len(summary)}; failed: {len(bad)}")
    for b in bad:
        print("FAIL", b)
    print("max round-trip mm:", max(r["roundtrip_mm"] for r in rows))
    print(f"rotation sign vs EPSG:5044: flipped={ok_rot*100:.3f} cm, NOT flipped={wrong_rot:.1f} m")
    print("test points without MSK data:", missing)
    for f_ in fed:
        print(f_)


if __name__ == "__main__":
    main()
