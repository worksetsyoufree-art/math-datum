"""Build the Russian datum dataset.

Outputs (data/):
  federal_datums.json      - national datums/CRS from the EPSG registry (via pyproj)
  msk_systems.json / .csv  - de-duplicated regional/city local coordinate systems (MSK)
"""
import csv, json, pathlib, re
from collections import defaultdict

from pyproj import CRS
from pyproj.database import query_crs_info
from pyproj.enums import PJType

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ELL = {3: "krass", 10: "bessel"}
GOST = (23.57, -140.95, -79.8, 0.0, -0.35, -0.79, -0.22)  # GOST R 51794-2008, SK-42 -> WGS-84


def region_of(rec):
    """Region key (МСК code) from system name / page title."""
    t = rec["name"] + " | " + rec["page_title"]
    if "МГГТ" in t or "Московская СК" in t:
        return "77", "Москва (МГГТ)"
    if "1964" in t:
        return "78", "Санкт-Петербург (МСК-1964)"
    m = re.search(r"МСК-(\d{2})\b", rec["page_title"]) or re.search(r"МСК-(\d{2})\b", rec["name"])
    code = m.group(1) if m else None
    title = re.sub(r"^МСК-\d{2}\s*", "", rec["page_title"]).strip()
    return code, title


def zone_of(name):
    m = re.search(r"зона\s*(\d+)", name, re.I)
    return int(m.group(1)) if m else None


def zone_width(name):
    m = re.search(r"(1\.5|\d)\s*градусная", name)
    return float(m.group(1)) if m else None


def proj4(rec):
    ell = ELL[rec["ellipsoid_id"]] if rec["ellipsoid_id"] else "krass"
    if rec["helmert_mapinfo"]:
        dx, dy, dz, rx, ry, rz, ds = rec["helmert_mapinfo"]
    else:  # MapInfo datum 1001: shift not stated by sources, GOST 51794-2008 assumed
        dx, dy, dz, rx, ry, rz, ds = GOST
    # MapInfo/GOST use coordinate-frame rotations, PROJ towgs84 uses position-vector: flip signs
    tw = ",".join(f"{v:g}" for v in (dx, dy, dz, -rx, -ry, -rz, ds))
    return (f"+proj=tmerc +lat_0={rec['lat0']:g} +lon_0={rec['lon0']:.11g} +k={rec['k0']:g} "
            f"+x_0={rec['fe']:.6g} +y_0={rec['fn']:.9g} +ellps={ell} +towgs84={tw} +units=m +no_defs")


def build_msk():
    recs = json.load(open(DATA / "raw/parsed_lines.json"))
    groups = defaultdict(list)
    for r in recs:
        code, title = region_of(r)
        r["region_code"], r["region_title"] = code, title
        r["variant"] = "gost2008" if r["mapinfo_datum"] == 9999 else "calc"
        r["zone"] = zone_of(r["name"])
        r["zone_width_deg"] = zone_width(r["name"])
        # identity: region + projection params + variant (names differ between sites)
        key = (code, r["variant"], round(r["lon0"], 6), round(r["lat0"], 6), round(r["k0"], 9),
               round(r["fe"], 2), round(r["fn"], 2))
        groups[key].append(r)
    out, conflicts = [], []
    for key, items in groups.items():
        base = items[0]
        srcs = sorted({i["source"] for i in items})
        names = sorted({i["name"] for i in items})
        out.append(dict(
            id=None, region_code=base["region_code"], region=base["region_title"],
            names=names, variant=base["variant"], zone=base["zone"], zone_width_deg=base["zone_width_deg"],
            projection="Transverse Mercator (Gauss-Krueger)", ellipsoid=ELL.get(base["ellipsoid_id"], "krass"),
            lon0=base["lon0"], lat0=base["lat0"], k0=base["k0"], false_easting=base["fe"], false_northing=base["fn"],
            helmert_mapinfo=base["helmert_mapinfo"],
            towgs84_basis="source (GOST 51794-2008 style)" if base["helmert_mapinfo"] else "assumed GOST 51794-2008 (source gives MapInfo datum 1001)",
            proj4=proj4(base), sources=srcs, source_urls=sorted({i["page_url"] for i in items}),
            source_lines=[i["raw"] for i in items],
        ))
    # same region + same lon0 but different FE/FN across sources -> flag
    by = defaultdict(list)
    for o in out:
        by[(o["region_code"], o["variant"], round(o["lon0"], 6), o["zone"])].append(o)
    for k, v in by.items():
        if len(v) > 1 and len({tuple(sorted(x["sources"])) for x in v}) > 1:
            conflicts.append(dict(key=list(k), variants=[dict(sources=x["sources"], lat0=x["lat0"], fe=x["false_easting"], fn=x["false_northing"]) for x in v]))
            for x in v:
                x["conflict"] = True
    # calc vs GOST variant of the same zone must differ only in the datum, never in projection parameters
    pair = defaultdict(list)
    for o in out:
        pair[(o["region_code"], round(o["lon0"], 4), round(o["false_easting"], 1))].append(o)
    for v in pair.values():
        c = [x for x in v if x["variant"] == "calc"]
        g = [x for x in v if x["variant"] == "gost2008"]
        if c and g and any(abs(c[0][f] - g[0][f]) > 1e-6 for f in ("lat0", "k0", "false_northing")):
            for x in c + g:
                x["flag"] = "calc/gost2008 variants disagree on lat0/k0/false_northing - one of them is likely a typo in the source"
    out.sort(key=lambda o: (o["region_code"] or "zz", o["variant"], o["lon0"]))
    for i, o in enumerate(out, 1):
        o["id"] = f"MSK{i:04d}"
    json.dump(out, open(DATA / "msk_systems.json", "w"), ensure_ascii=False, indent=1)
    json.dump(conflicts, open(DATA / "raw/source_conflicts.json", "w"), ensure_ascii=False, indent=1)
    cols = ["id", "region_code", "region", "names", "variant", "zone", "zone_width_deg", "ellipsoid", "lon0", "lat0", "k0",
            "false_easting", "false_northing", "towgs84_basis", "proj4", "sources", "conflict", "flag"]
    with open(DATA / "msk_systems.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for o in out:
            w.writerow([" / ".join(o[c]) if isinstance(o.get(c), list) else o.get(c, "") for c in cols])
    print("MSK records:", len(out), "regions:", len({o["region_code"] for o in out}), "conflicts:", len(conflicts))


def build_federal():
    from pyproj.transformer import TransformerGroup
    keep = []
    for r in query_crs_info("EPSG", pj_types=[PJType.GEOGRAPHIC_2D_CRS, PJType.GEODETIC_CRS, PJType.GEOGRAPHIC_3D_CRS]):
        if re.search(r"Pulkovo|PZ-90|GSK-2011", r.name):
            keep.append(r)
    out = []
    for r in sorted(keep, key=lambda r: int(r.code)):
        crs = CRS.from_epsg(r.code)
        ell = crs.ellipsoid
        ops = []
        try:
            g = TransformerGroup(crs, CRS.from_epsg(4326), always_xy=True)
            for t in g.transformers:
                d = t.description
                ops.append(dict(name=d, accuracy=t.accuracy, definition=t.definition))
        except Exception as e:  # pragma: no cover
            ops.append(dict(error=str(e)))
        out.append(dict(epsg=int(r.code), name=r.name, datum=crs.datum.name, type=crs.type_name, deprecated=r.deprecated,
                        ellipsoid=ell.name, a=ell.semi_major_metre, inv_f=ell.inverse_flattening,
                        area=(r.area_of_use.name if r.area_of_use else None)[:120],
                        to_wgs84=ops))
    json.dump(out, open(DATA / "federal_datums.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("federal CRS:", len(out))


if __name__ == "__main__":
    build_msk()
    build_federal()
