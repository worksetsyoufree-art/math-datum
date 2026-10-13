"""Compare an external datum list (Fieldworker export, WGS84 -> local) with data/msk_systems.json."""
import csv, json, math, re, sys, pathlib
from collections import defaultdict, Counter
from pyproj import CRS, Transformer

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = pathlib.Path(sys.argv[1])
AS = 180 * 3600 / math.pi
GOST_INV = (-23.57, 140.95, 79.8, 0.22)  # WGS84 -> SK-42: translation and scale (ppm) = negated GOST 51794-2008


def dms6(v):
    """DDDMMSS integer -> degrees"""
    v = int(v); s = v % 100; m = (v // 100) % 100; d = v // 10000
    return d + m / 60 + s / 3600


ext = json.load(open(SRC))["data"]
mine = json.load(open(ROOT / "data/msk_systems.json"))
caps = {}
for r in csv.DictReader(open(ROOT / "data/region_capitals.csv", encoding="utf-8")):
    caps.setdefault(r["region_code"], (float(r["lat"]), float(r["lon"]), r["city"]))

by_region = defaultdict(list)
for o in mine:
    by_region[o["region_code"]].append(o)


def region_of(code):
    if code.startswith("SPb_"): return "78"
    if code.startswith("Moscow_"): return "77"
    m = re.search(r"MSK_(\d{2})(?:_|$)", code)
    if m: return m.group(1)
    if code.startswith(("MSK_78", "SPb_MSK_78")): return "78"
    if "MSK_77" in code: return "77"
    return None


def params_ext(x):
    p = x["parameters7"]
    return dict(dx=p["d_x"], dy=p["d_y"], dz=p["d_z"], rx=p["r_x"] * AS, ry=p["r_y"] * AS, rz=p["r_z"] * AS, ds=p["k"] * 1e6)


rows = []
stat = Counter()
for x in ext:
    code = x["coordinateSystem"]["csCode"]
    pr = x["projection"]
    p = params_ext(x)
    row = dict(csCode=code, ellipsoid=x["ellipsoid"]["type"], has_projection=bool(pr),
               dx=p["dx"], dy=p["dy"], dz=p["dz"], rx_as=round(p["rx"], 5), ry_as=round(p["ry"], 5), ds_ppm=round(p["ds"], 5))
    reg = region_of(code)
    row["region_code"] = reg
    if not pr:
        stat["no projection (datum only)"] += 1
        row["status"] = "datum_only"
        rows.append(row); continue
    lon0 = dms6(pr["center"]); fe, fn = pr["eastShift"], pr["northShift"]
    row.update(lon0=round(lon0, 6), fe=fe, fn=fn)
    if reg is None or reg not in by_region:
        stat["region not in my data"] += 1
        row["status"] = "no_region_in_mine" if reg else "no_region_code"
        rows.append(row); continue
    cands = [o for o in by_region[reg] if o["lat0"] == 0 or True]
    best = min(cands, key=lambda o: (abs(o["lon0"] - lon0) * 3600, abs(o["false_easting"] - fe)))
    dlon = (lon0 - best["lon0"]) * 3600  # arcsec
    de, dn = fe - best["false_easting"], fn - best["false_northing"]
    row.update(match_id=best["id"], d_lon0_arcsec=round(dlon, 3), d_fe_m=round(de, 3), d_fn_m=round(dn, 3))
    # positional effect of the projection difference at the regional capital (same datum, same ellipsoid)
    lat, lon, city = caps.get(reg, (None, None, None))
    if lat is not None:
        base = CRS.from_proj4(best["proj4"])
        alt = CRS.from_proj4(best["proj4"].replace(f"+lon_0={best['lon0']:.11g}", f"+lon_0={lon0:.11g}")
                             .replace(f"+x_0={best['false_easting']:.6g}", f"+x_0={fe}")
                             .replace(f"+y_0={best['false_northing']:.9g}", f"+y_0={fn}"))
        w = CRS.from_epsg(4326)
        e1, n1 = Transformer.from_crs(w, base, always_xy=True).transform(lon, lat)
        e2, n2 = Transformer.from_crs(w, alt, always_xy=True).transform(lon, lat)
        row["pos_diff_m_at_capital"] = round(math.hypot(e1 - e2, n1 - n2), 2)
    if abs(dlon) < 2 and abs(de) <= 1 and abs(dn) <= 1:
        row["status"] = "match"
    elif abs(dlon) < 2:
        row["status"] = "same_meridian_diff_shift"
    else:
        row["status"] = "different_meridian"
    stat[row["status"]] += 1
    rows.append(row)

cols = sorted({k for r in rows for k in r}, key=lambda k: (k not in ("csCode", "status"), k))
with open(ROOT / "data/compare_fieldworker.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
print(len(ext), "external records;", dict(stat))
tm = [r for r in rows if r["status"] in ("match", "same_meridian_diff_shift")]
print("matched to projection meridian:", len(tm), "of", len([r for r in rows if r.get("fe") is not None]))
pd = [r["pos_diff_m_at_capital"] for r in tm if "pos_diff_m_at_capital" in r]
print("position difference at capitals (m): median", sorted(pd)[len(pd)//2], "max", max(pd), ">1m:", sum(v > 1 for v in pd), ">10m:", sum(v > 10 for v in pd))


# ---- datum comparison -------------------------------------------------------------------------
# File = WGS84 -> local. For local -> WGS84 (MapInfo/GOST, coordinate-frame) it should hold
#   d_file = -d, k_file = -ds, r_x_file = -rx, r_y_file = -rz   (and nothing carries ry)
by_id = {o["id"]: o for o in mine}
ext_by_code = {x["coordinateSystem"]["csCode"]: x for x in ext}


def pipe(par, inverse_sign=1.0):
    dx, dy, dz, rx, ry, rz, ds = par
    return (f"+proj=pipeline +step +proj=cart +ellps=krass +step +proj=helmert +x={dx} +y={dy} +z={dz} "
            f"+rx={rx} +ry={ry} +rz={rz} +s={ds} +convention=coordinate_frame +step +inv +proj=cart +ellps=WGS84")


drows = []
for r in rows:
    if "match_id" not in r or r["status"] not in ("match", "same_meridian_diff_shift"):
        continue
    x = ext_by_code[r["csCode"]]
    o = by_id[r["match_id"]]
    g = [q for q in by_region[o["region_code"]] if q["variant"] == "gost2008" and abs(q["lon0"] - o["lon0"]) < 1e-6
         and abs(q["false_easting"] - o["false_easting"]) < 1] or [None]
    g = g[0]
    if g is None or not g["helmert_mapinfo"]:
        continue
    dx, dy, dz, rx, ry, rz, ds = g["helmert_mapinfo"]
    p = params_ext(x)
    exp = (-dx, -dy, -dz, -rx, -rz, -ds)
    got = (p["dx"], p["dy"], p["dz"], p["rx"], p["ry"], p["ds"])
    diff = [round(a - b, 4) for a, b in zip(got, exp)]
    # position effect at the capital of: file-derived local->WGS (omega_y lost) vs full mine
    lat, lon, city = caps.get(o["region_code"], (None, None, None))
    eff = None
    if lat is not None:
        full = Transformer.from_pipeline(pipe((dx, dy, dz, rx, ry, rz, ds)))
        # file as WGS->local cf rotations (r_x, 0, r_y); take inverse for local->WGS
        f = Transformer.from_pipeline(
            f"+proj=pipeline +step +proj=cart +ellps=WGS84 +step +proj=helmert +x={p['dx']} +y={p['dy']} +z={p['dz']} "
            f"+rx={p['rx']} +ry=0 +rz={p['ry']} +s={p['ds']} +convention=coordinate_frame +step +inv +proj=cart +ellps=krass")
        a = full.transform(lon, lat)
        b = f.transform(lon, lat, direction="INVERSE")
        eff = math.hypot((a[0] - b[0]) * 111319.49 * math.cos(math.radians(lat)), (a[1] - b[1]) * 111132.95)
    drows.append(dict(csCode=r["csCode"], match_id=o["id"], d_dx=diff[0], d_dy=diff[1], d_dz=diff[2], d_rx_as=diff[3],
                      d_rz_slot_as=diff[4], d_ds_ppm=diff[5], dropped_ry_as=round(abs(ry), 5),
                      position_effect_m=None if eff is None else round(eff, 2)))
with open(ROOT / "data/compare_fieldworker_datum.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(drows[0])); w.writeheader(); w.writerows(drows)
tr_ok = [d for d in drows if max(abs(d["d_dx"]), abs(d["d_dy"]), abs(d["d_dz"])) < 0.01 and abs(d["d_ds_ppm"]) < 0.01]
print("datum compared for", len(drows), "systems; translation+scale identical:", len(tr_ok))
pe = [d["position_effect_m"] for d in drows if d["position_effect_m"] is not None]
print("position effect of lost omega_y (m): median", sorted(pe)[len(pe)//2], "max", max(pe), ">1m:", sum(v > 1 for v in pe))
print("differing datum:", [(d["csCode"], d["d_dx"], d["d_dy"], d["d_dz"], d["d_rx_as"], d["d_rz_slot_as"], d["d_ds_ppm"]) for d in drows if d not in tr_ok][:15])
print("rx/ry-slot mismatches:", sum(1 for d in drows if abs(d["d_rx_as"]) > 0.01 or abs(d["d_rz_slot_as"]) > 0.01))
