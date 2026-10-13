"""Merge the two scraped MSK lists (msk_systems.json) with the Fieldworker export.

Result: data/systems_all.json - one entity per (region, projection geometry, datum) with the list of sources that
agree on it, plus data/datum_transforms.json for datum-only entries of the export.

Rules
* false northing: my (scraped, fractional) values are authoritative; the export truncates them to integers.
  For zones that exist only in the export the fraction is restored from a sibling zone of the same region
  if the sibling truncates to the exported integer; otherwise it is kept and flagged.
* export rotations are WGS84 -> local radians with no omega_y: convert to the GOST local -> WGS84 form;
  omega_y is restored only when the other six parameters equal a known GOST parameter set.
"""
import json, math, pathlib, re
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
AS = 180 * 3600 / math.pi
GEOM_LON_TOL_ARCSEC = 2.0
TOL_T = 0.05      # m  (export has e.g. 589.659 vs 589.650 for MGGT)
TOL_R = 0.01      # arcsec
TOL_S = 0.01      # ppm
ELLPS = {"Krassowsky_1940": "krass", "Bessel_1841": "bessel", "WGS_84": "WGS84"}
PREFIX_REGION = {
    "Astrakhanskaya": "30", "Habarovskiy": "27", "Kaliningradskaya": "39", "Krasnodarskiy": "23",
    "Krasnoyarskiy": "24", "Magadanskaya": "49", "Moskovskaya": "50", "Orenburgskaya": "56",
    "Respublika_Hakasiya": "19", "Respublika_Kareliya": "10", "Respublika_Komi": "11",
    "Respublika_Tatarstan": "16", "Tomskaya": "70", "Samarskaya": "63", "SPb": "78", "Moscow": "77",
    "MGGT": "77", "MOSCOW": "77", "MICKEY": "77", "METRO": "77", "MSK_78": "78", "Vladimirskaya": "33",
    "Tulskaya": "71",
}


def dms6(v):
    v = int(v)
    return v // 10000 + ((v // 100) % 100) / 60 + (v % 100) / 3600


def fe_prefix(fe):
    n = round(fe / 1e6)
    return n


def region_of_code(code):
    if code.startswith("SPb_"): return "78"
    if code.startswith("Moscow_"): return "77"
    m = re.search(r"MSK_(\d{2})(?:_|$)", code)
    if m: return m.group(1)
    for p, r in PREFIX_REGION.items():
        if code.startswith(p): return r
    return None


def datum_from_export(x):
    """export (WGS84->local, rad) -> GOST local->WGS84 tuple (dx,dy,dz,rx,ry,rz,ds) with ry None (not in export)."""
    p = x["parameters7"]
    return [-p["d_x"], -p["d_y"], -p["d_z"], -p["r_x"] * AS, None, -p["r_y"] * AS, -p["k"] * 1e6]


def datum_eq(a, b):
    """compare ignoring omega_y."""
    return (all(abs(a[i] - b[i]) <= TOL_T for i in range(3)) and abs(a[3] - b[3]) <= TOL_R
            and abs(a[5] - b[5]) <= TOL_R and abs(a[6] - b[6]) <= TOL_S)


def geom_eq(g, h):
    return (abs(g["lon0"] - h["lon0"]) * 3600 <= GEOM_LON_TOL_ARCSEC and abs(g["lat0"] - h["lat0"]) * 3600 <= 2
            and abs(g["fe"] - h["fe"]) <= 1 and abs(g["fn"] - h["fn"]) <= 1.0001)


def proj4(g, ellps, d):
    dx, dy, dz, rx, ry, rz, ds = d
    ry = 0.0 if ry is None else ry
    tw = ",".join(f"{v:.10g}" for v in (dx, dy, dz, -rx, -ry, -rz, ds))
    return (f"+proj=tmerc +lat_0={g['lat0']:.11g} +lon_0={g['lon0']:.11g} +k=1 +x_0={g['fe']:.6f} +y_0={g['fn']:.6f} "
            f"+ellps={ellps} +towgs84={tw} +units=m +no_defs")


def epsg_towgs84_sets(codes=(4284, 4200)):
    """All published EPSG Helmert sets (coordinate-frame, local -> WGS84) for the given geodetic CRS."""
    import json as _j
    from pyproj import CRS
    from pyproj.crs import CoordinateOperation
    from pyproj.transformer import TransformerGroup
    out = {}
    for code in codes:
        for t in TransformerGroup(CRS.from_epsg(code), CRS.from_epsg(4326)).transformers:
            ids = []
            def walk(x):
                if isinstance(x, dict):
                    if x.get("type") == "Transformation" and x.get("id", {}).get("authority") == "EPSG":
                        ids.append(x["id"]["code"])
                    for v in x.values(): walk(v)
                elif isinstance(x, list):
                    for v in x: walk(v)
            walk(_j.loads(t.to_json()))
            for c in ids:
                op = CoordinateOperation.from_epsg(c)
                tw = op.towgs84
                if tw and len(tw) == 7:
                    out[c] = (op.name, list(tw))
    return out


def main():
    mine = json.load(open(DATA / "msk_systems.json"))
    ext = json.load(open(DATA / "raw/fieldworker_datum_from_geod_wgs84.json"))["data"]
    ents = []

    # ---- 1. entities from the two scraped sites (gost2008 lines first, calc lines attach by geometry)
    def mk(o, datum, basis):
        return dict(region_code=o["region_code"], region=o["region"], names=set(o["names"]), zone=o["zone"],
                    geom=dict(lon0=o["lon0"], lat0=o["lat0"], fe=o["false_easting"], fn=o["false_northing"]),
                    ellipsoid=o["ellipsoid"], datum=datum, datum_basis=basis, sources=set(o["sources"]),
                    source_urls=set(o["source_urls"]), flags=[o["flag"]] if o.get("flag") else [], origin="scraped")
    for o in mine:
        if o["variant"] != "gost2008":
            continue
        d = [float(v) for v in o["helmert_mapinfo"]]
        hit = next((e for e in ents if e["region_code"] == o["region_code"] and geom_eq(e["geom"], dict(
            lon0=o["lon0"], lat0=o["lat0"], fe=o["false_easting"], fn=o["false_northing"]))
            and e["ellipsoid"] == o["ellipsoid"] and datum_eq(e["datum"], d) and abs(e["datum"][4] - d[4]) <= TOL_R), None)
        if hit:
            hit["sources"] |= set(o["sources"]); hit["source_urls"] |= set(o["source_urls"]); hit["names"] |= set(o["names"])
        else:
            ents.append(mk(o, d, "scraped (GOST 51794-2008 line)"))
    gost_default = [23.57, -140.95, -79.8, 0.0, -0.35, -0.79, -0.22]
    for o in mine:
        if o["variant"] != "calc":
            continue
        g = dict(lon0=o["lon0"], lat0=o["lat0"], fe=o["false_easting"], fn=o["false_northing"])
        hit = next((e for e in ents if e["region_code"] == o["region_code"] and geom_eq(e["geom"], g)), None)
        if hit:
            hit["sources"] |= set(o["sources"]); hit["source_urls"] |= set(o["source_urls"]); hit["names"] |= set(o["names"])
            if o.get("flag"): hit["flags"].append(o["flag"])
        else:
            ents.append(mk(o, list(gost_default), "assumed GOST 51794-2008 (site gives only MapInfo datum 1001)"))

    # known GOST parameter sets (to restore omega_y): from all scraped lines + federal
    known = {tuple(round(v, 3) for v in (e["datum"][0], e["datum"][1], e["datum"][2], e["datum"][3], e["datum"][5], e["datum"][6])): e["datum"][4]
             for e in ents if e["datum_basis"].startswith("scraped")}
    for fed in ([23.57, -140.95, -79.8, 0, -0.35, -0.79, -0.22],):
        known[(23.57, -140.95, -79.8, 0.0, -0.79, -0.22)] = -0.35
    # published EPSG sets (SK-42 variants incl. the Trimble set, SK-95); (24.82,-131.21,-82.66,..) is the GOST R 51794-2001 set
    for c, (nm, tw) in epsg_towgs84_sets().items():
        known.setdefault(tuple(round(v, 3) for v in (tw[0], tw[1], tw[2], tw[3], tw[5], tw[6])), tw[4])
    known[(24.82, -131.21, -82.66, 0.0, -0.16, -0.12)] = 0.0

    def restore_ry(d):
        k = tuple(round(v, 3) for v in (d[0], d[1], d[2], d[3], d[5], d[6]))
        for kk, ry in known.items():
            if all(abs(a - b) <= TOL_T for a, b in zip(k[:3], kk[:3])) and abs(k[3] - kk[3]) <= TOL_R \
                    and abs(k[4] - kk[4]) <= TOL_R and abs(k[5] - kk[5]) <= TOL_S:
                return ry
        return None

    # ---- 2. merge export records
    stats = defaultdict(int)
    dt = []
    for x in ext:
        code = x["coordinateSystem"]["csCode"]
        ellps = ELLPS.get(x["ellipsoid"]["type"])
        d = datum_from_export(x)
        pr = x["projection"]
        if not pr:
            ry = restore_ry(d)
            dd = list(d)
            dd[4] = ry
            dt.append(dict(code=code, ellipsoid=x["ellipsoid"]["type"], ellipsoid_a=x["ellipsoid"]["paramA"],
                           ellipsoid_1f=x["ellipsoid"]["param1f"], to_wgs84_gost_form=dd,
                           omega_y="restored from matching GOST parameter set" if ry is not None else "unknown (not in source)",
                           source="fieldworker"))
            continue
        reg = region_of_code(code)
        g = dict(lon0=dms6(pr["center"]), lat0=dms6(pr["startLat"]) if pr["startLat"] else 0.0,
                 fe=float(pr["eastShift"]), fn=float(pr["northShift"]))
        # export truncates FN (toward zero); compare with that tolerance
        cand = [e for e in ents if (reg is None or e["region_code"] == reg) and geom_eq(e["geom"], g)
                and e["ellipsoid"] == ELLPS.get(x["ellipsoid"]["type"], e["ellipsoid"])]
        # a calc-only entity has assumed datum -> a match upgrades it
        same = [e for e in cand if datum_eq(e["datum"], d)]
        if same:
            e = same[0]
            e["sources"].add("fieldworker"); e["names"].add(code)
            if e["datum_basis"].startswith("assumed"):
                e["datum_basis"] = "assumed GOST, confirmed by Fieldworker (translation/scale/omega_x/omega_z)"
            if any(abs(e["datum"][i] - d[i]) > 1e-6 for i in range(3)):
                e["flags"].append(f"fieldworker differs slightly in translation (max {max(abs(e['datum'][i]-d[i]) for i in range(3)):.3f} m) - site value kept")
            stats["merged into existing"] += 1
            continue
        # new entity
        ry = restore_ry(d)
        flags = []
        dd = list(d); dd[4] = ry if ry is not None else None
        if ry is None:
            flags.append("omega_y not in source and no matching GOST set: assumed 0")
        elif ry != 0:
            flags.append("omega_y restored from matching GOST parameter set")
        fn = g["fn"]
        sib = [e for e in ents if reg is not None and e["region_code"] == reg and abs(e["geom"]["fn"] - fn) < 1
               and math.trunc(e["geom"]["fn"]) == int(fn) and e["geom"]["fn"] != int(e["geom"]["fn"])]
        if sib:
            g["fn"] = sib[0]["geom"]["fn"]
            flags.append(f"false northing fraction restored from sibling zone {sorted(sib[0]['names'])[0]}")
        else:
            flags.append("false northing is truncated to integer in source, fraction unknown (error < 1 m)")
        if cand:
            flags.append("same projection as " + ", ".join(sorted(next(iter(c["names"])) for c in cand)[:2]) + " but different datum")
        rname = reg
        ents.append(dict(region_code=reg, region=None, names={code}, zone=None, geom=g, ellipsoid=ELLPS.get(x["ellipsoid"]["type"], "krass"),
                         datum=dd, datum_basis="fieldworker export", sources={"fieldworker"}, source_urls=set(), flags=flags, origin="fieldworker"))
        stats["new from export"] += 1

    # ---- 3. fill region names, ids, proj4
    names = {}
    for e in ents:
        if e["region"]:
            names.setdefault(e["region_code"], e["region"])
    names.update({"77": "Москва", "78": "Санкт-Петербург"})
    out = []
    for e in sorted(ents, key=lambda e: (e["region_code"] or "zz", e["geom"]["lon0"], e["geom"]["fe"], sorted(e["names"])[0])):
        e["region"] = e["region"] or names.get(e["region_code"])
        out.append(dict(
            region_code=e["region_code"], region=e["region"], names=sorted(e["names"]), geometry=e["geom"],
            ellipsoid=e["ellipsoid"], datum_gost_form=e["datum"], datum_basis=e["datum_basis"],
            sources=sorted(e["sources"]), source_urls=sorted(e["source_urls"]), flags=sorted(set(e["flags"])),
            origin=e["origin"], proj4=proj4(e["geom"], e["ellipsoid"], [v if v is not None else (0.0 if i == 4 else 0) for i, v in enumerate(e["datum"])])))
    for i, o in enumerate(out, 1):
        o["id"] = f"S{i:04d}"
    json.dump(out, open(DATA / "systems_all.json", "w"), ensure_ascii=False, indent=1)
    json.dump(dt, open(DATA / "datum_transforms.json", "w"), ensure_ascii=False, indent=1)
    print(dict(stats), "entities:", len(out), "datum-only:", len(dt))
    print("sources count:", {k: sum(1 for o in out if len(o["sources"]) == k) for k in (1, 2, 3)})
    print("no region:", [o["names"][0] for o in out if not o["region_code"]])


if __name__ == "__main__":
    main()
