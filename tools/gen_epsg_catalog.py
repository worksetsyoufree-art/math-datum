#!/usr/bin/env python3
"""
Справочник СК из реестра EPSG (те же данные, что на epsg.io) через базу PROJ proj.db (pyproj).
Результат — каталог формата v2 (см. CatalogJson) со всеми актуальными проекционными СК EPSG:
эллипсоид, лучшая трансформация в WGS84 по зоне применимости, оси, единицы, bounds, регион.
Методы проекций, которых нет в ядре, и СК с нестандартными осями/нулевым меридианом — в блоке "unsupported".

Запуск: python3 tools/gen_epsg_catalog.py [выходной.json]   (нужен pyproj)
"""
import json, math, sqlite3, sys, pathlib, collections
import pyproj

DB = pyproj.datadir.get_data_dir() + "/proj.db"
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else
                   pathlib.Path(__file__).resolve().parent.parent / "app/src/commonMain/composeResources/files/epsg.json")
ARCSEC = math.pi / 180 / 3600

c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row
q = lambda sql, *a: c.execute(sql, a).fetchall()

epsg_version = q("select value from metadata where key='EPSG.VERSION'")[0][0]
uom = {(r["auth_name"], r["code"]): (r["type"], r["conv_factor"]) for r in q("select * from unit_of_measure")}
method_names = {}
for tbl in ("conversion_method", "coordinate_operation_method"):
    try:
        for r in q(f"select * from {tbl} where auth_name='EPSG'"):
            if str(r["code"]).isdigit():
                method_names.setdefault(int(r["code"]), r["name"])
    except sqlite3.OperationalError:
        pass
ellipsoid_rows = {r["code"]: r for r in q("select * from ellipsoid where auth_name='EPSG'")}
datum_rows = {r["code"]: r for r in q("select * from geodetic_datum where auth_name='EPSG'")}
geodetic = {r["code"]: r for r in q("select * from geodetic_crs where auth_name='EPSG'")}
extents = {r["code"]: r for r in q("select * from extent where auth_name='EPSG'")}
axes_by_cs = collections.defaultdict(list)
for r in q("select * from axis where auth_name='EPSG' order by coordinate_system_order"):
    axes_by_cs[r["coordinate_system_code"]].append(r)
conv = {r["code"]: r for r in q("select * from conversion_table where auth_name='EPSG'")}

usage = collections.defaultdict(list)   # (table, code) -> [extent rows]
for r in q("select * from usage where object_auth_name='EPSG'"):
    e = extents.get(r["extent_code"])
    if e is not None and r["extent_auth_name"] == "EPSG":
        usage[(r["object_table_name"], r["object_code"])].append(e)


def dms_to_deg(v):
    s = -1 if v < 0 else 1
    a = abs(v)
    d = int(a + 1e-12)
    rest = (a - d) * 100
    m = int(rest + 1e-9)
    sec = (rest - m) * 100
    return s * (d + m / 60 + sec / 3600)


def param_deg(value, uom_code):
    if uom_code == 9110:
        return dms_to_deg(value)
    t, f = uom[("EPSG", uom_code)]
    return math.degrees(value * f)


def param_m(value, uom_code):
    t, f = uom[("EPSG", uom_code)]
    return value * f


def conversion_params(code):
    r = conv[code]
    out = {}
    for i in range(1, 8):
        pc = r[f"param{i}_code"]
        if pc is None:
            continue
        v, u = r[f"param{i}_value"], r[f"param{i}_uom_code"]
        t, f = uom[("EPSG", u)]
        out[pc] = param_deg(v, u) if t == "angle" else (param_m(v, u) if t == "length" else v * f)
    return out


def projection_json(method, p):
    if method in (9807, 9808, 9801):
        return {"method": method, "lat0": p[8801], "lon0": p[8802], "k0": p[8805], "x0": p[8806], "y0": p[8807]}
    if method == 9802:
        return {"method": 9802, "latF": p[8821], "lonF": p[8822], "lat1": p[8823], "lat2": p[8824], "eF": p[8826], "nF": p[8827]}
    return None


SUPPORTED = {9807, 9808, 9801, 9802}

# ——— эллипсоиды ———
ellipsoids = {}
def ellipsoid_of(base_code):
    g = geodetic[base_code]
    d = datum_rows[g["datum_code"]]
    if d["prime_meridian_code"] != 8901:
        return None, "нулевой меридиан не Гринвич"
    e = ellipsoid_rows[d["ellipsoid_code"]]
    a = e["semi_major_axis"] * uom[("EPSG", e["uom_code"])][1]
    if e["inv_flattening"] is not None:
        invf = e["inv_flattening"]
    elif e["semi_minor_axis"] is not None:
        b = e["semi_minor_axis"] * uom[("EPSG", e["uom_code"])][1]
        invf = a / (a - b) if a != b else 0.0
    else:
        return None, "эллипсоид без сжатия"
    if invf == 0.0:
        return None, "сфера (1/f = 0)"
    key = f"EPSG:{e['code']}"
    ellipsoids[key] = {"name": e["name"], "a": a, "invF": invf}
    return key, None


# ——— трансформации в WGS84 ———
HELM_METHODS = {1031: (None, "t"), 9603: (None, "t"), 1032: ("coordinate_frame", "r"), 9607: ("coordinate_frame", "r"),
                1033: ("position_vector", "r"), 9606: ("position_vector", "r")}
helm_rows = collections.defaultdict(list)  # base code -> [(row, direction)]
for r in q("select * from helmert_transformation_table where deprecated=0"):
    if r["source_crs_auth_name"] == "EPSG" and r["target_crs_auth_name"] == "EPSG":
        if r["target_crs_code"] == 4326:
            helm_rows[r["source_crs_code"]].append((r, "local_to_wgs84"))
        elif r["source_crs_code"] == 4326:
            helm_rows[r["target_crs_code"]].append((r, "wgs84_to_local"))
other_to_wgs = set()
for tbl in ("grid_transformation", "other_transformation", "concatenated_operation"):
    for r in q(f"select * from {tbl} where deprecated=0"):
        if r["target_crs_code"] == 4326 and r["source_crs_auth_name"] == "EPSG":
            other_to_wgs.add(r["source_crs_code"])
        elif r["source_crs_code"] == 4326 and r["target_crs_auth_name"] == "EPSG":
            other_to_wgs.add(r["target_crs_code"])


def segments(e):
    """bbox -> список непересекающих антимеридиан сегментов (w, e, s, n); запад > восток — зона через ±180°."""
    w, ea, so, no = e["west_lon"], e["east_lon"], e["south_lat"], e["north_lat"]
    if w is None or so is None:
        return []
    if w <= ea:
        return [(w, ea, so, no)]
    return [(w, 180.0, so, no), (-180.0, ea, so, no)]


def overlap(ext_a, ext_b):
    """Доля площади лучшей зоны A, покрытая зонами B (bbox, с учётом антимеридиана)."""
    segs_b = [sg for b in ext_b for sg in segments(b)]
    best = 0.0
    for a in ext_a:
        sa = segments(a)
        area = sum(max(e_ - w_, 1e-6) * max(n_ - s_, 1e-6) for w_, e_, s_, n_ in sa)
        if not sa or area <= 0:
            continue
        cov = 0.0
        for (wa, ea, so, no) in sa:
            for (wb, eb, sb, nb) in segs_b:
                w, e_, s_, n_ = max(wa, wb), min(ea, eb), max(so, sb), min(no, nb)
                if e_ > w and n_ > s_:
                    cov += (e_ - w) * (n_ - s_)
        best = max(best, min(1.0, cov / area))
    return best


helmerts = {}
def datum_shift_of(base_code, crs_extents):
    """-> (helmert_key|None, direction|None, status, accuracy)"""
    if base_code == 4326:
        return None, None, "exact", 0.0
    cands = []
    for r, direction in helm_rows.get(base_code, []):
        m = int(r["method_code"])
        if m not in HELM_METHODS:
            continue
        ov = overlap(crs_extents, usage.get(("helmert_transformation", r["code"]), []))
        acc = r["accuracy"] if r["accuracy"] is not None else 1e9
        cands.append((-round(ov, 2), acc, -int(r["code"]), r, direction))
    if cands:
        cands.sort(key=lambda t: t[:3])
        ovneg, acc, _, r, direction = cands[0]
        partial = -ovneg < 0.5
        m = int(r["method_code"])
        key = f"EPSG:{r['code']}"
        if key not in helmerts:
            conv_name, kind = HELM_METHODS[m]
            tu = uom[("EPSG", r["translation_uom_code"])][1]
            tvec = [r["tx"] * tu, r["ty"] * tu, r["tz"] * tu]
            if kind == "t":
                rot, ppm = [0.0, 0.0, 0.0], 0.0
            else:
                rf = uom[("EPSG", r["rotation_uom_code"])][1] / ARCSEC
                rot = [r["rx"] * rf, r["ry"] * rf, r["rz"] * rf]
                ppm = r["scale_difference"] * uom[("EPSG", r["scale_difference_uom_code"])][1] * 1e6
            h = {"t": tvec, "r": rot, "ppm": ppm, "direction": direction, "op": key}
            if conv_name:
                h["convention"] = conv_name
            if r["accuracy"] is not None:
                h["acc"] = r["accuracy"]
            helmerts[key] = h
        zero = all(abs(v) == 0 for v in helmerts[key]["t"] + helmerts[key]["r"]) and helmerts[key]["ppm"] == 0
        status = "exact" if zero and not partial else "helmert_partial" if partial else "helmert"
        return key, direction, status, (acc if acc < 1e9 else None)
    if base_code in other_to_wgs:
        return None, None, "approx_grid", None
    return None, None, "approx_unknown", None


# ——— проход по проекционным СК ———
entries, unsupported = [], []
stats = collections.Counter()
rows = q("select * from projected_crs where auth_name='EPSG' and deprecated=0 order by code")
for r in rows:
    code = r["code"]
    cv = conv.get(r["conversion_code"])
    method = int(cv["method_code"]) if cv else None
    ext = usage.get(("projected_crs", code), [])
    region = ext[0]["name"] if ext else None
    base = r["geodetic_crs_code"]
    item = {"id": f"EPSG:{code}", "name": r["name"], "method": method, "methodName": method_names.get(method), "region": region}
    if method not in SUPPORTED:
        item["reason"] = "метод проекции"
        unsupported.append(item); stats["unsupported:method"] += 1
        continue
    ell_key, why = ellipsoid_of(base)
    if ell_key is None:
        item["reason"] = why; unsupported.append(item); stats["unsupported:ellipsoid/pm"] += 1
        continue
    axs = axes_by_cs[r["coordinate_system_code"]]
    if len(axs) != 2:
        item["reason"] = "число осей"; unsupported.append(item); stats["unsupported:axes"] += 1
        continue
    o = (axs[0]["orientation"], axs[1]["orientation"])
    u0 = uom[("EPSG", axs[0]["uom_code"])][1]; u1 = uom[("EPSG", axs[1]["uom_code"])][1]
    if abs(u0 - u1) > 1e-12:
        item["reason"] = "разные единицы осей"; unsupported.append(item); stats["unsupported:units"] += 1
        continue
    if method == 9808:
        mapping = {("west", "south"): "EN", ("south", "west"): "NE"}
    else:
        mapping = {("north", "east"): "NE", ("east", "north"): "EN"}
    axes = mapping.get(o)
    if axes is None:
        item["reason"] = f"оси {o[0]}/{o[1]}"; unsupported.append(item); stats["unsupported:axes"] += 1
        continue
    pj = projection_json(method, conversion_params(r["conversion_code"]))
    hkey, hdir, status, acc = datum_shift_of(base, ext)
    e = {"id": f"EPSG:{code}", "name": r["name"], "ellipsoid": ell_key, "helmert": hkey, "projection": pj,
         "axes": axes, "unit": u0, "epsg": code, "base": f"EPSG:{base}", "dt": status}
    if acc is not None and status != "exact":
        e["dtAcc"] = acc
    if ext:
        w = [x for x in ext if x["west_lon"] is not None]
        if w:
            wrapped = [x for x in w if x["west_lon"] > x["east_lon"]]
            if wrapped:   # зона через линию смены дат: берём её как есть
                x = wrapped[0]
                e["bounds"] = [x["south_lat"], x["north_lat"], x["west_lon"], x["east_lon"]]
            else:
                e["bounds"] = [min(x["south_lat"] for x in w), max(x["north_lat"] for x in w),
                               min(x["west_lon"] for x in w), max(x["east_lon"] for x in w)]
    if region:
        e["region"] = region
    entries.append(e)
    stats[f"ok:{status}"] += 1

doc = {
    "format": 2,
    "version": f"EPSG {epsg_version}",
    "source": f"EPSG registry (as on epsg.io) via PROJ {pyproj.proj_version_str} proj.db",
    "ellipsoids": ellipsoids,
    "helmerts": helmerts,
    "entries": entries,
    "unsupported": unsupported,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print("wrote", OUT, f"{OUT.stat().st_size/1e6:.2f} MB")
print("EPSG", epsg_version, "| projected non-deprecated:", len(rows), "| entries:", len(entries), "| unsupported:", len(unsupported))
for k, v in sorted(stats.items()):
    print(f"  {k}: {v}")
byreason = collections.Counter((u.get("method"), u["reason"]) for u in unsupported)
print("unsupported by (method, reason):")
for (m, why), n in byreason.most_common(15):
    print(f"  {m} {method_names.get(m)} [{why}]: {n}")
