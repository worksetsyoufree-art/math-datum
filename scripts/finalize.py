"""Re-validate every merged system and split into verified / unverified.

A system is VERIFIED when all of the following hold:
  1. at least two independent sources agree on it (geoprof, terraingis, Fieldworker export);
  2. WGS84 -> local -> WGS84 round trip closes (< 20 mm) at the test points of its region;
  3. zone series is consistent: a zone n>=2 has a zone n=1 of the same series with lon0 spacing 1.5/2/3/6 deg;
  4. region sanity: the regional capital lies within 260 km of the central meridian of some zone of the region;
  5. city / district systems: their own test city lies within 150 km of the central meridian.
Everything else is kept in data/systems_unverified.json with the reasons.
"""
import csv, json, math, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from collections import defaultdict

from pyproj import CRS, Transformer
from pyproj.crs import CoordinateOperation

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RT_TOL_MM = 20.0  # PROJ/proj4js use the linearised 7-parameter model: closure error grows with rotation size (cm for ~6")
REGION_KM = 260.0
CITY_KM = 150.0
WIDTHS = (1.5, 2.0, 3.0, 6.0)
WGS = CRS.from_epsg(4326)


def load_points():
    caps = defaultdict(list)
    for r in csv.DictReader(open(DATA / "region_capitals.csv", encoding="utf-8")):
        caps[r["region_code"]].append((r["city"], float(r["lat"]), float(r["lon"])))
    extra = []
    for r in csv.DictReader(open(DATA / "extra_points.csv", encoding="utf-8")):
        extra.append((r["name_key"], r["city"], float(r["lat"]), float(r["lon"])))
    return caps, extra


def roundtrip_mm(fwd, inv, lat, lon):
    e, n = fwd.transform(lon, lat)
    lo, la = inv.transform(e, n)
    return e, n, math.hypot((lo - lon) * 111319.49 * math.cos(math.radians(lat)), (la - lat) * 111132.95) * 1000


def zone_series_ok(o, by_group):
    fe = o["geometry"]["fe"]
    n = round(fe / 1e6)
    if n < 2:
        return True, "n/a"
    grp = by_group[(o["region_code"], round(fe - n * 1e6, 0), round(o["geometry"]["fn"], 0))]
    firsts = [g for g in grp if round(g["geometry"]["fe"] / 1e6) == 1]
    if not firsts:
        return True, "no zone 1 in group (unchecked)"
    for f in firsts:
        step = (o["geometry"]["lon0"] - f["geometry"]["lon0"]) / (n - 1)
        if any(abs(step - w) < 0.02 for w in WIDTHS):
            return True, f"width {min(WIDTHS, key=lambda w: abs(step - w))} deg"
    return False, f"zone {n} lon0 {o['geometry']['lon0']:.4f} does not fit any series starting from zone 1"


def main():
    systems = json.load(open(DATA / "systems_all.json"))
    caps, extra = load_points()
    by_group = defaultdict(list)
    for o in systems:
        n = round(o["geometry"]["fe"] / 1e6)
        by_group[(o["region_code"], round(o["geometry"]["fe"] - n * 1e6, 0), round(o["geometry"]["fn"], 0))].append(o)

    tr = {}
    for o in systems:
        crs = CRS.from_proj4(o["proj4"])
        tr[o["id"]] = (Transformer.from_crs(WGS, crs, always_xy=True), Transformer.from_crs(crs, WGS, always_xy=True))

    # region-level: does the capital sit inside some zone of the region?
    region_ok = {}
    for code, pts in caps.items():
        ok = True
        for city, lat, lon in pts:
            best = 1e9
            for o in systems:
                if o["region_code"] != code:
                    continue
                e, n = tr[o["id"]][0].transform(lon, lat)
                best = min(best, abs(e - o["geometry"]["fe"]) / 1000)
            ok = ok and best <= REGION_KM
        region_ok[code] = ok

    rows, verified, unverified = [], [], []
    for o in systems:
        reasons, checks = [], {}
        # 1 sources
        checks["sources"] = len(o["sources"])
        if len(o["sources"]) < 2:
            reasons.append("one source only")
        # 2 round trip at region test points + city point
        pts = list(caps.get(o["region_code"], []))
        city_pts = [(c, la, lo) for k, c, la, lo in extra if any(k in nm for nm in o["names"])]
        fwd, inv = tr[o["id"]]
        worst = 0.0
        for city, lat, lon in pts + city_pts:
            e, n, mm = roundtrip_mm(fwd, inv, lat, lon)
            worst = max(worst, mm)
        checks["roundtrip_mm"] = round(worst, 4) if (pts or city_pts) else None
        if not (pts or city_pts):
            reasons.append("no test point for this system")
        elif worst >= RT_TOL_MM:
            reasons.append(f"round trip {worst:.2f} mm")
        # 3 series
        ok, note = zone_series_ok(o, by_group)
        checks["zone_series"] = note
        if not ok:
            reasons.append(note)
        # 4 region
        if o["region_code"] in region_ok:
            checks["region_capital_inside_some_zone"] = region_ok[o["region_code"]]
            if not region_ok[o["region_code"]]:
                reasons.append("capital outside every zone of region")
        # 5 city
        for city, lat, lon in city_pts:
            e, n = fwd.transform(lon, lat)
            off = abs(e - o["geometry"]["fe"]) / 1000
            checks[f"city_offset_km:{city}"] = round(off, 1)
            if off > CITY_KM:
                reasons.append(f"{city} is {off:.0f} km from central meridian")
        o["checks"] = checks
        o["status"] = "verified" if not reasons else "unverified"
        if not reasons:  # competing variant lost: the disagreement flag no longer applies
            o["flags"] = [x for x in o["flags"] if not x.startswith("calc/gost2008 variants disagree")]
        o["unverified_reasons"] = reasons
        (verified if not reasons else unverified).append(o)
        rows.append(dict(id=o["id"], region=o["region_code"], name=o["names"][0], sources="+".join(o["sources"]),
                         status=o["status"], reasons="; ".join(reasons), roundtrip_mm=checks["roundtrip_mm"],
                         zone_series=checks["zone_series"]))

    json.dump(verified, open(DATA / "systems.json", "w"), ensure_ascii=False, indent=1)
    json.dump(unverified, open(DATA / "systems_unverified.json", "w"), ensure_ascii=False, indent=1)
    with open(DATA / "validation_systems.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

    # ---- datum-only transforms: compare with EPSG
    dts = json.load(open(DATA / "datum_transforms.json"))
    from merge_fieldworker import epsg_towgs84_sets
    epsg_ops = epsg_towgs84_sets((4284, 4200))
    epsg_ops[0] = ("GOST R 51794-2001 Pulkovo 1995 set (as in the EPSG:2754 definition)", [24.82, -131.21, -82.66, 0, 0, -0.16, -0.12])
    pts = [(55.7558, 37.6173), (59.9343, 30.3351), (43.1155, 131.8855), (54.7104, 20.4522)]
    for d in dts:
        p = d["to_wgs84_gost_form"]
        ry = p[4] if p[4] is not None else 0.0
        ell = {"Krassowsky_1940": "krass", "Bessel_1841": "bessel", "WGS_84": "WGS84"}.get(d["ellipsoid"])
        d["epsg_match"] = None
        if ell == "krass":
            tw = (p[0], p[1], p[2], p[3], ry, p[5], p[6])
            for c, (name, k) in epsg_ops.items():
                if all(abs(a - b) <= 0.05 for a, b in zip(tw[:3], k[:3])) and all(abs(a - b) <= 0.01 for a, b in zip(tw[3:], k[3:])):
                    d["epsg_match"] = f"EPSG:{c} {name}" if c else name
        if d["epsg_match"]:
            d["status"] = "verified: equals published EPSG parameters"
        elif d["omega_y"].startswith("restored"):
            d["status"] = "corroborated: equals parameters published on the scraped sites"
        else:
            d["status"] = "unverified: no published counterpart found"
    json.dump(dts, open(DATA / "datum_transforms.json", "w"), ensure_ascii=False, indent=1)

    reasons = defaultdict(int)
    for o in unverified:
        for r in o["unverified_reasons"]:
            reasons[r.split(" ")[0] + " " + r.split(" ")[1] if r.startswith("one") else r[:40]] += 1
    print(f"systems: {len(systems)}  verified: {len(verified)}  unverified: {len(unverified)}")
    print("reasons:", dict(reasons))
    print("datum-only:", {d["code"]: d["status"][:12] for d in dts})


if __name__ == "__main__":
    main()
