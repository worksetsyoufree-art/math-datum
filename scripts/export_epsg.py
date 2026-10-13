"""Export the world datums (geographic CRS) and projected CRS from the EPSG registry (via pyproj).

Output: build/world_candidates.json   (filtered later by scripts/pack_world.mjs, which checks proj4js vs PROJ)

Transformations to WGS84 are reduced to Helmert sets in PROJ `+towgs84` convention (position vector, local -> WGS84):
  * only geocentric-translation / position-vector / coordinate-frame operations are used
  * an operation defined WGS84 -> local is inverted, coordinate-frame rotations are sign-flipped
The best-accuracy operation whose area covers the datum's area centre is kept; the best accuracy of *any* operation
(grid based included) is stored separately so the UI can say "better accuracy needs grids".
"""
import json, math, pathlib, re, warnings
from pyproj import CRS, Transformer
from pyproj.crs import CoordinateOperation
from pyproj.database import query_crs_info
from pyproj.enums import PJType
from pyproj.transformer import TransformerGroup

warnings.filterwarnings("ignore")
ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "build"
OUT.mkdir(exist_ok=True)
WGS_FAMILY = {4326, 4979, 4978}
HELMERT = re.compile(r"Geocentric translations|Position Vector|Coordinate Frame", re.I)
SUPPORTED = {"tmerc", "utm", "lcc", "aea", "laea", "merc", "stere", "sterea", "omerc", "somerc", "cass", "krovak", "eqc",
             "poly", "nzmg", "aeqd", "cea", "eqdc", "gnom", "ortho", "sinu", "robin", "mill"}


def centre(b):
    w, s, e, n = b
    lon = (w + e) / 2 if w <= e else ((w + e + 360) / 2 + 180) % 360 - 180
    return lon, (s + n) / 2


def in_bounds(b, lon, lat):
    if not b:
        return True
    w, s, e, n = b
    return s <= lat <= n and ((w <= lon <= e) if w <= e else (lon >= w or lon <= e))


def pipeline_helmert(defn):
    """PROJ pipeline (local -> WGS84) -> (towgs84 position vector, kind) or None if it is not a plain Helmert/identity."""
    steps = re.split(r"\s+step\s+", defn)
    helm = [x for x in steps if re.search(r"(^|\s)proj=helmert", x)]
    if any(re.search(r"proj=(hgridshift|vgridshift|molodensky|deformation|xyzgridshift|gridshift|affine|tinshift|"
                     r"horner|set|push|pop)", x) and "proj=push" not in x and "proj=pop" not in x
           for x in steps):
        return None
    if not helm:  # pure datum change through geocentric coordinates with identical frames
        procs = set(re.findall(r"proj=(\w+)", defn))
        return ([0.0] * 7, "identity") if procs <= {"pipeline", "unitconvert", "axisswap", "push", "pop", "cart", "noop"} else None
    if len(helm) != 1:
        return None
    h = helm[0]
    inv = bool(re.search(r"(^|\s)inv(\s|$)", h.split("proj=helmert")[0]))
    kv = dict(re.findall(r"(\w+)=([^\s]+)", h))
    if "exact" in h or "transpose" in h or "t_epoch" in kv or "dx" in kv:
        return None
    tw = [float(kv.get(k, 0)) for k in ("x", "y", "z", "rx", "ry", "rz", "s")]
    if kv.get("convention") == "coordinate_frame":
        tw[3], tw[4], tw[5] = -tw[3], -tw[4], -tw[5]
    if inv:
        tw = [-v for v in tw]
    return tw, "helmert"


def transformations(crs, my_codes, ctr):
    group = TransformerGroup(crs, CRS.from_epsg(4326), always_xy=True)
    cands, any_acc, ballpark = [], [], None
    for t in group.transformers:
        acc = t.accuracy if t.accuracy is not None and t.accuracy > 0 else None
        if acc:
            any_acc.append(acc)
        name = re.sub(r" \(with axis order.*", "", t.description)
        if t.accuracy is not None and t.accuracy < 0:  # ballpark
            ballpark = ballpark or (None, ([0.0] * 7), None, name, "ballpark")
            continue
        r = pipeline_helmert(t.definition)
        if r is None:
            continue
        j = json.loads(t.to_json())
        code = j.get("id", {}).get("code")
        area = t.area_of_use.bounds if t.area_of_use else None
        if not in_bounds(area, *ctr):
            continue
        cands.append(((acc if acc else 999, str(code)), code, r[0], acc, name, r[1]))
    if cands:
        best = min(cands, key=lambda c: c[0])
        return best, (min(any_acc) if any_acc else None)
    if ballpark:
        return ((999, ""), None, ballpark[1], None, ballpark[3], "ballpark"), (min(any_acc) if any_acc else None)
    return None, (min(any_acc) if any_acc else None)


def main():
    out_geo, out_proj = [], []
    codes_geo = {}
    for r in query_crs_info("EPSG", pj_types=[PJType.GEOGRAPHIC_2D_CRS]):
        if r.deprecated or not r.area_of_use:
            continue
        crs = CRS.from_epsg(r.code)
        b = r.area_of_use.bounds
        ctr = centre(b)
        my = {int(r.code)}
        ens = bool(getattr(crs.datum, "members", None)) if crs.datum else False
        best, best_any = (None, None)
        if int(r.code) in WGS_FAMILY:
            best = ((0, 0), 0, [0] * 7, 0, "identity", "identity")
            best_any = 0
        else:
            try:
                best, best_any = transformations(crs, my, ctr)
            except Exception as e:  # pragma: no cover
                best, best_any = None, None
        el = crs.ellipsoid
        out_geo.append(dict(
            code=int(r.code), name=r.name, datum=crs.datum.name if crs.datum else "", ell=el.name if el else "",
            a=el.semi_major_metre if el else None, rf=el.inverse_flattening if el else None,
            area=r.area_of_use.name, bbox=[round(v, 3) for v in b], ensemble=ens,
            tw=[round(v, 6) for v in best[2]] if best else None, acc=best[3] if best else None,
            opc=best[1] if best and isinstance(best[1], (int, str)) else None, opn=best[4] if best else None, kind=best[5] if best else None, best_any=best_any))
        codes_geo[int(r.code)] = out_geo[-1]
    print("geographic:", len(out_geo), "with Helmert to WGS84:", sum(1 for g in out_geo if g["tw"]))

    wgs = CRS.from_epsg(4326)
    skipped = {"method": 0, "proj4": 0}
    for r in query_crs_info("EPSG", pj_types=[PJType.PROJECTED_CRS]):
        if r.deprecated or not r.area_of_use:
            continue
        crs = CRS.from_epsg(r.code)
        base = crs.geodetic_crs.to_epsg() if crs.geodetic_crs else None
        try:
            p4 = crs.to_proj4().replace(" +type=crs", "")
        except Exception:
            skipped["proj4"] += 1
            continue
        m = re.search(r"\+proj=(\w+)", p4)
        if not m or m.group(1) not in SUPPORTED or "+nadgrids" in p4 or "+geoidgrids" in p4:
            skipped["method"] += 1
            continue
        g = codes_geo.get(base)
        if "+towgs84" not in p4 and "+datum=" not in p4 and g and g["tw"] and any(abs(v) > 0 for v in g["tw"]):
            p4 += " +towgs84=" + ",".join(f"{v:.10g}" for v in g["tw"])
        b = r.area_of_use.bounds
        ctr = centre(b)
        try:
            ref = Transformer.from_crs(wgs, CRS.from_proj4(p4), always_xy=True).transform(*ctr)
            try:
                epsg_ref = Transformer.from_crs(wgs, crs, always_xy=True).transform(*ctr)
                approx = math.hypot(ref[0] - epsg_ref[0], ref[1] - epsg_ref[1])
            except Exception:
                approx = None
        except Exception:
            skipped["proj4"] += 1
            continue
        if not all(math.isfinite(v) for v in ref):
            skipped["proj4"] += 1
            continue
        out_proj.append(dict(code=int(r.code), name=r.name, base=base, method=m.group(1), area=r.area_of_use.name,
                             bbox=[round(v, 3) for v in b], p4=p4, ref=[ref[0], ref[1]], ctr=[round(ctr[0], 6), round(ctr[1], 6)],
                             approx=None if approx is None else round(approx, 2)))
    print("projected:", len(out_proj), "skipped:", skipped)
    (OUT / "world_candidates.json").write_text(json.dumps(dict(geo=out_geo, proj=out_proj), ensure_ascii=False))


if __name__ == "__main__":
    main()
