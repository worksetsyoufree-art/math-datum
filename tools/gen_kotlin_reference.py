"""Генерирует эталонные данные для тестов Kotlin-модуля из Python-эталона (mathdatum + pyproj).

  python tools/gen_kotlin_reference.py

Пишет kmp/localization/src/commonTest/kotlin/ru/mathdatum/localization/ReferenceData.kt:
  - TM_CASES: прямые/обратные пересчёты поперечного Меркатора (pyproj) на разных эллипсоидах;
  - REGIONS: по каждому из 83 регионов — пары точек, датум по Python-эталону, прогноз
    в контрольных точках и обратный пересчёт, диагностика надёжности;
  - DIAG_CASES: особые случаи надёжности (грубые ошибки, нулевая избыточность, вырождение без
    точки, флаги use, неправдоподобные масштаб и разворот) и веса точек (взвешенный МНК).

и .../DatumReferenceData.kt (пересчёты между системами, mathdatum.datums — сам сверен с PROJ в tests/):
  - BLH_XYZ_CASES: BLH ↔ XYZ на всех эллипсоидах;
  - TRANSFORM_CASES: XYZ по всем упорядоченным парам систем (цепочки, обратные шаги);
  - GK_CASES / TM_PROJ_CASES: Гаусс–Крюгер (зоны 6°, принудительная зона) и свой поперечный Меркатор;
  - REGION_HELMERT: задачи helmert_7p 83 регионов (по 5 точек exact и noisy);
  - GNSS_DATUM_CASES: локализация с gnss_datum (ПЗ-90.11, СК-42, ГСК-2011) и пересчёт точек из другой системы.

и .../GeoidReferenceData.kt (сетки геоида, mathdatum.geoid — сам сверен с PROJ vgridshift в tests/):
  - GEOID_FILES: тестовые сетки tests/data/geoid (GGF, GTX, ISG) байтами и SHA-256;
  - GEOID_VALUES: N в точках (билинейная и бикубическая; NaN — ожидается GeoidException);
  - GEOID_LOC_CASES: локализация с моделями geoid / geoid_plane (параметры, диагностика, пересчёты);
  - PY_GEOID_DATUM_JSON: датум с геоидом, сохранённый Python-эталоном.
"""

import itertools
import json
import sys
from pathlib import Path

import numpy as np
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mathdatum import Pair, datums, localize, read_pairs, suggest_exclusions
from mathdatum.geoid import GeoidError, read_grid

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "kmp/localization/src/commonTest/kotlin/ru/mathdatum/localization/ReferenceData.kt"
OUT_DATUMS = OUT.with_name("DatumReferenceData.kt")
OUT_GEOID = OUT.with_name("GeoidReferenceData.kt")
GEOID_DIR = ROOT / "tests/data/geoid"
GEOID_FILES = ["RU-MOW_truth.ggf", "RU-MOW_truth.gtx", "RU-MOW_truth.isg", "RU-MOW_bump.ggf",
               "nodata.ggf", "nodata.gtx", "nodata.isg"]


def d(v):
    return "Double.NaN" if v is None or v != v else repr(float(v))


def resid_diag(dt):
    """По каждой невязке: qvvPlan, qvvHeight, wx, wy, wH, looDx, looDy, looDH, pPlan, pHeight, dx, dy, dH
    (NaN — null)."""
    return [[r.qvv_plan, r.qvv_height, r.wx, r.wy, r.wH, r.loo_dx, r.loo_dy, r.loo_dH, r.p_plan, r.p_height,
             r.dx, r.dy, r.dH] for r in dt.residuals]


def params(dt):
    """lat0, lon0, Nc, Ec, a, b, tx, ty, c0, c1, c2, rmsPlan, rmsHeight."""
    return [dt.lat0, dt.lon0, dt.Nc, dt.Ec, dt.a, dt.b, dt.tx, dt.ty, dt.c0, dt.c1, dt.c2, dt.rms_plan, dt.rms_height]


def pair_kt(p):
    sig = "" if p.sigma_plan is None and p.sigma_height is None else f", {d(p.sigma_plan)}, {d(p.sigma_height)}"
    return (f'LocalizationPair("{p.name}", {d(p.B)}, {d(p.L)}, {d(p.h)}, {d(p.x)}, {d(p.y)}, {d(p.H)}, '
            f'Use.{p.use.upper()}{sig})').replace("Double.NaN", "null")


def datum_diag(dt):
    """redundancyPlan, redundancyHeight, s0Plan, s0Height."""
    return [dt.redundancy_plan, dt.redundancy_height, dt.s0_plan, dt.s0_height]


def quality(dt, wgs):
    out, mp, mh = dt.quality_wgs(*np.asarray(wgs, float).T[:2])
    mp2, mh2 = dt.prediction_sigma(*np.asarray(wgs, float).T[:2], posterior=True)
    return np.column_stack([out, mp, mh, mp2, mh2])


def tm_cases():
    rng = np.random.default_rng(7)
    cases = []
    for ellps in ("+ellps=WGS84", "+ellps=krass", "+a=6378136 +rf=298.25784"):
        for lat0, lon0 in ((0.0, 39.0), (55.75, 37.62), (68.97, 33.07), (43.1, 131.9)):
            proj = Transformer.from_pipeline(
                f"+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad "
                f"+step +proj=tmerc +lat_0={lat0} +lon_0={lon0} +k=1 +x_0=0 +y_0=0 {ellps} +units=m")
            # От 0 до ~4.5° по долготе от осевого меридиана (≈ 300 км на широте 55°).
            lat = np.clip(lat0 + rng.uniform(-3, 3, 6), -80, 80)
            lon = lon0 + rng.uniform(-4.5, 4.5, 6)
            E, N = proj.transform(lon, lat)
            for la, lo, n, e in zip(lat, lon, N, E):
                cases.append(f'TmCase("{ellps}", {d(lat0)}, {d(lon0)}, {d(la)}, {d(lo)}, {d(n)}, {d(e)})')
    return cases


def regions():
    out = []
    for f in sorted((ROOT / "data/geodetic/regions").glob("*.json")):
        case = json.loads(f.read_text(encoding="utf-8"))
        site = next(t for t in case["tasks"] if t["type"] == "site_localization")
        pairs = [Pair(p["id"], *p["gnss_B_L_h"], *p["local_x_y_H"]) for p in site["control_points"]]
        dt = localize(pairs)
        chk = np.array([p["gnss_B_L_h"] for p in site["check_points"]])
        x, y, H = dt.to_local(*chk.T)
        loc = np.array([p["local_x_y_H"] for p in site["check_points"]])
        B, L, h = dt.to_wgs(*loc.T)
        pairs_kt = ", ".join(
            f'LocalizationPair("{p.name}", {d(p.B)}, {d(p.L)}, {d(p.h)}, {d(p.x)}, {d(p.y)}, {d(p.H)})' for p in pairs)
        out.append(
            f'RegionCase("{case["region"]["iso_3166_2"]}", listOf({pairs_kt}),\n'
            f'  doubleArrayOf({", ".join(d(v) for v in params(dt))}),\n'
            f'  {arr(chk)},\n  {arr(np.column_stack([x, y, H]))},\n  {arr(loc)},\n  {arr(np.column_stack([B, L, h]))},\n'
            f'  doubleArrayOf({", ".join(d(v) for v in datum_diag(dt))}),\n  {arr(resid_diag(dt))},\n'
            f'  {arr(quality(dt, chk))})')
    return out


def diag_cases():
    base = read_pairs(ROOT / "examples/pairs.csv")

    def copy(pairs):
        return [Pair(**vars(p)) for p in pairs]

    cases = [("example", copy(base))]
    c = copy(base[:6]); c[3].x += 0.10; cases.append(("blunder_plan_10cm", c))
    c = copy(base); c[1].H += 0.25; cases.append(("blunder_height_25cm", c))
    c = copy(base); c[7].x += 0.5; cases.append(("blunder_control", c))
    cases.append(("two_points", copy(base[:2])))
    cases.append(("three_points", copy(base[:3])))
    c = copy(base[:4])
    for q in c[:3]:
        q.L = c[0].L
    cases.append(("collinear_height", c))
    c = copy(base); c[2].use = "plan"; c[4].use = "height"; c[5].use = "none"; cases.append(("use_flags", c))
    c = copy(base[:6])
    xc, yc = np.mean([q.x for q in c]), np.mean([q.y for q in c])
    for q in c:
        q.x, q.y = xc + (q.x - xc) * 1.0005, yc + (q.y - yc) * 1.0005
    cases.append(("scale_500ppm", c))
    c = copy(base[:6])
    for q in c:
        q.x, q.y = q.y, q.x
    cases.append(("swapped_axes", c))
    cases.append(("one_point", copy(base[:1])))
    # Веса точек.
    c = copy(base)
    for q, sp, sh in zip(c, (0.005, 0.05, None, 0.01, 0.04, None, 0.03, None, 0.1, None),
                         (0.01, None, 0.08, 0.02, None, 0.05, 0.015, 0.2, None, None)):
        q.sigma_plan, q.sigma_height = sp, sh
    c[2].use = "plan"; c[4].use = "height"
    cases.append(("weighted", c))
    c = copy(base[:6])
    for q in c:
        q.sigma_plan, q.sigma_height = 0.05, 0.07
    cases.append(("weighted_equal", c))
    c = copy(base[:6]); c[3].x += 0.5; c[3].H += 0.5; c[3].sigma_plan = c[3].sigma_height = 10.0
    cases.append(("weighted_large_sigma_blunder", c))
    c = copy(base[:6]); c[3].x += 0.10; c[3].sigma_plan = 0.01
    cases.append(("weighted_small_sigma_blunder", c))
    c = copy(base[:4]); c[0].sigma_plan = 0.001; c[1].sigma_height = 0.002
    cases.append(("weighted_four_points", c))

    out = []
    for name, pairs in cases:
        dt = localize(pairs)
        pts = np.array([[p.B, p.L, p.h] for p in base])
        ex = [f"{n}:{part}" for n, part, _ in suggest_exclusions(pairs)]
        pairs_kt = ", ".join(pair_kt(p) for p in pairs)
        out.append(
            f'DiagCase("{name}", listOf({pairs_kt}),\n'
            f'  doubleArrayOf({", ".join(d(v) for v in params(dt))}),\n'
            f'  doubleArrayOf({", ".join(d(v) for v in datum_diag(dt))}),\n  {arr(resid_diag(dt))},\n'
            f'  listOf({", ".join("true" if r.suspect else "false" for r in dt.residuals)}),\n'
            f'  listOf({", ".join(chr(34) + w.code + chr(34) for w in dt.warnings)}),\n'
            f'  listOf({", ".join(chr(34) + e + chr(34) for e in ex)}),\n'
            f'  {arr(pts)},\n  {arr(quality(dt, pts))})')
    return out


def datum_cases():
    rng = np.random.default_rng(32453)
    blh = np.column_stack([rng.uniform(41, 78, 12), rng.uniform(19, 190, 12), rng.uniform(-100, 3000, 12)])
    out = {}
    out["blh"] = []
    for key, e in datums.ELLIPSOIDS.items():
        pts = np.vstack([blh[:6], [[0.0, 0.0, 0.0], [89.9, 10.0, 5000.0], [-45.0, -170.0, -400.0]]])
        X, Y, Z = datums.blh_to_xyz(*pts.T, e)
        for b, x in zip(pts, np.column_stack([X, Y, Z])):
            out["blh"].append(f'XyzCase("{key}", {d(b[0])}, {d(b[1])}, {d(b[2])}, {d(x[0])}, {d(x[1])}, {d(x[2])})')
    out["tr"] = []
    for a, b in itertools.permutations(datums.SYSTEMS, 2):
        xyz = np.column_stack(datums.blh_to_xyz(*blh[:3].T, datums.SYSTEMS[a].ellipsoid))
        res = datums.transform_xyz(xyz, a, b)
        steps = len(datums.find_path(a, b))
        for x, y in zip(xyz, res):
            out["tr"].append(f'TransformCase("{a}", "{b}", {steps}, {", ".join(d(v) for v in (*x, *y))})')
    out["gk"] = []
    for key in ("krass", "gsk2011"):
        for (b, l, h), zone in zip(blh, [None] * 9 + [7, 8, 31]):
            l = l if zone is None else 6 * zone - 3 + 4.5
            x, y = datums.gk_forward(b, l, key, zone)
            out["gk"].append(f'GkCase("{key}", {zone or 0}, {d(b)}, {d(l)}, {d(x)}, {d(y)})')
    out["tm"] = []
    for key, lon0, lat0, k0, x0, y0 in (("krass", 38.48333, 0.0, 1.0, -5712900.566, 1250000.0),
                                        ("pz90", 131.9, 43.1, 0.9996, 100.0, 500000.0),
                                        ("wgs84", 39.0, 55.0, 1.0002, 0.0, 0.0)):
        tm = datums.TransverseMercator(key, lon0, lat0, k0, x0, y0)
        for _ in range(5):
            b = (lat0 or 55.0) + rng.uniform(-2, 2)
            l = lon0 + rng.uniform(-3, 3)
            x, y = tm.forward(b, l)
            out["tm"].append(f'TmProjCase("{key}", {", ".join(d(v) for v in (lon0, lat0, k0, x0, y0, b, l, x, y))})')
    out["reg"] = []
    for f in sorted((ROOT / "data/geodetic/regions").glob("*.json")):
        case = json.loads(f.read_text(encoding="utf-8"))
        rows = []
        for task in (t for t in case["tasks"] if t["type"] == "helmert_7p"):
            src = np.array(task["source_xyz"][:5])
            pred = datums.transform_xyz(src, "SK-42", "PZ-90.11")
            for b, x, t, pr in zip(task["source_geodetic_B_L_H"][:5], src, task["target_xyz"][:5], pred):
                rows.append(f'doubleArrayOf({", ".join(d(v) for v in (*b, *x, *t, *pr))})')
        out["reg"].append(f'RegionHelmert("{case["region"]["iso_3166_2"]}", listOf({", ".join(rows)}))')
    out["gnss"] = []
    regions = sorted((ROOT / "data/geodetic/regions").glob("*.json"))[::8]
    for f, system in zip(regions, itertools.cycle(("PZ-90.11", "SK-42", "GSK-2011"))):
        site = next(t for t in json.loads(f.read_text(encoding="utf-8"))["tasks"] if t["type"] == "site_localization")
        c = np.array([p["gnss_B_L_h"] for p in site["control_points"]])
        cc = np.column_stack(datums.transform_blh(*c.T, "PZ-90.11", system))
        pairs = [Pair(p["id"], *b, *p["local_x_y_H"]) for p, b in zip(site["control_points"], cc)]
        dt = localize(pairs, gnss_datum=system)
        k = np.array([p["gnss_B_L_h"] for p in site["check_points"]])
        loc = np.column_stack(dt.to_local(*k.T, datum="PZ-90.11"))
        back = np.column_stack(dt.to_wgs(*loc.T, datum="WGS-84"))
        pairs_kt = ", ".join(pair_kt(p) for p in pairs)
        out["gnss"].append(
            f'GnssDatumCase("{f.stem}", "{system}", "{dt.ellipsoid}", listOf({pairs_kt}),\n'
            f'  doubleArrayOf({", ".join(d(v) for v in params(dt))}),\n  {arr(k)},\n  {arr(loc)},\n  {arr(back)})')
    return out


def write_datums():
    c = datum_cases()
    ex = json.loads((ROOT / "data/geodetic/gost_32453_control_example.json").read_text(encoding="utf-8"))["steps"]
    gost = [ex["input_itrf2008_epoch_2005"]["xyz"], ex["input_itrf2008_epoch_2005"]["velocity"],
            ex["itrf2008_epoch_2010"]["xyz"], ex["pz9011_epoch_2010"]["xyz"], ex["pz9011_epoch_2013_9"]["xyz"]]
    pairs = read_pairs(ROOT / "examples/pairs.csv")
    dt = localize(pairs[:6], gnss_datum="PZ-90.11")
    OUT_DATUMS.write_text(
        "// Сгенерировано tools/gen_kotlin_reference.py из Python-эталона (mathdatum.datums). Не редактировать вручную.\n"
        "package ru.mathdatum.localization\n\n"
        "class XyzCase(val ellipsoid: String, val lat: Double, val lon: Double, val h: Double,\n"
        "              val x: Double, val y: Double, val z: Double)\n\n"
        "class TransformCase(val from: String, val to: String, val steps: Int, val x: Double, val y: Double, val z: Double,\n"
        "                    val ex: Double, val ey: Double, val ez: Double)\n\n"
        "/** zone = 0 — зона по долготе. */\n"
        "class GkCase(val ellipsoid: String, val zone: Int, val lat: Double, val lon: Double, val x: Double, val y: Double)\n\n"
        "class TmProjCase(val ellipsoid: String, val lon0: Double, val lat0: Double, val k0: Double, val x0: Double,\n"
        "                 val y0: Double, val lat: Double, val lon: Double, val x: Double, val y: Double)\n\n"
        "/** Строки: B, L, H (СК-42), XYZ СК-42, XYZ ПЗ-90.11 из задачи, XYZ ПЗ-90.11 по Python; первые 5 — exact, затем noisy. */\n"
        "class RegionHelmert(val iso: String, val rows: List<DoubleArray>)\n\n"
        "/** expected — как у RegionCase; check — контрольные пункты в ПЗ-90.11, local — их to_local(datum = ПЗ-90.11),\n"
        " *  back — to_wgs(local, datum = WGS-84). */\n"
        "class GnssDatumCase(val iso: String, val system: String, val ellipsoid: String, val pairs: List<LocalizationPair>,\n"
        "                    val expected: DoubleArray, val check: List<DoubleArray>, val local: List<DoubleArray>,\n"
        "                    val back: List<DoubleArray>)\n\n"
        "val BLH_XYZ_CASES = listOf(\n    " + ",\n    ".join(c["blh"]) + ",\n)\n\n"
        "val TRANSFORM_CASES: List<TransformCase> by lazy { transformCases() }\n\n"
        "private fun transformCases() = listOf(\n    " + ",\n    ".join(c["tr"]) + ",\n)\n\n"
        "val GK_CASES = listOf(\n    " + ",\n    ".join(c["gk"]) + ",\n)\n\n"
        "val TM_PROJ_CASES = listOf(\n    " + ",\n    ".join(c["tm"]) + ",\n)\n\n"
        + "".join(f"private fun regionHelmert{i}() = {r}\n\n" for i, r in enumerate(c["reg"]))
        + "val REGION_HELMERT: List<RegionHelmert> by lazy { listOf(" + ", ".join(f"regionHelmert{i}()" for i in range(len(c["reg"]))) + ") }\n\n"
        + "".join(f"private fun gnssCase{i}() = {r}\n\n" for i, r in enumerate(c["gnss"]))
        + "val GNSS_DATUM_CASES: List<GnssDatumCase> by lazy { listOf(" + ", ".join(f"gnssCase{i}()" for i in range(len(c["gnss"]))) + ") }\n\n"
        + "/** ГОСТ 32453-2017, прил. Е: XYZ ITRF-2008 2005.0, скорость, ITRF-2008 2010.0, ПЗ-90.11 2010.0, ПЗ-90.11 2013.9. */\n"
        + f"val GOST_EXAMPLE = {arr(gost)}\n\n"
        + "/** Датум по examples/pairs.csv (6 точек) с gnss_datum = ПЗ-90.11, сохранённый Python-эталоном. */\n"
        + "val PY_PZ_DATUM_JSON = " + json.dumps(json.dumps(dt.to_dict(), indent=1, ensure_ascii=False)).replace("$", "\\$") + "\n"
        + f"val PY_PZ_DATUM_PARAMS = doubleArrayOf({', '.join(d(v) for v in params(dt))})\n",
        encoding="utf-8")
    print(f"{OUT_DATUMS}: {len(c['blh'])} BLH/XYZ, {len(c['tr'])} пересчётов, {len(c['gk'])} ГК, {len(c['tm'])} ТМ, "
          f"{len(c['reg'])} регионов, {len(c['gnss'])} случаев gnss_datum")


def geoid_value_cases():
    rng = np.random.default_rng(605)
    out = []
    for f in GEOID_FILES:
        g = read_grid(GEOID_DIR / f)
        pts = [(g.lat0, g.lon0), (g.lat1, g.lon1), (g.lat0 + 2 * g.dlat, g.lon0 + 3 * g.dlon), (g.lat1, g.lon0),
               (g.lat0 + 0.5 * g.dlat, g.lon0 + 2.5 * g.dlon), (g.lat1 - 1.5 * g.dlat, g.lon1 - 1.2 * g.dlon),
               (g.lat1 + 1e-6, g.lon0), (g.lat0, g.lon1 + 1e-6), (g.lat0 - 1, g.lon0 - 1)]
        pts += list(zip(rng.uniform(g.lat0, g.lat1, 25), rng.uniform(g.lon0, g.lon1, 25)))
        for lat, lon in pts:
            for interp in ("bilinear", "bicubic"):
                try:
                    v = g.value1(lat, lon, interp)
                except GeoidError:
                    v = None
                out.append(f'GeoidValueCase("{f}", {d(lat)}, {d(lon)}, "{interp}", {d(v)})')
    return out


def geoid_loc_cases():
    sys.path.insert(0, str(ROOT / "tools"))
    import make_geoid_test_grids as mg
    t = mg.site_task("RU-MOW")
    ctrl = [Pair(p["id"], *p["gnss_B_L_h"], *p["local_x_y_H"]) for p in t["control_points"]]
    ctl = [Pair(p["id"], *p["gnss_B_L_h"], *p["local_x_y_H"], use="none") for p in t["check_points"]]
    chk = np.array([p["gnss_B_L_h"] for p in t["check_points"]])
    bump = [Pair(p.name, p.B, p.L, p.h, p.x, p.y, p.H - float(mg.bump(t, p.B, p.L))) for p in ctrl]

    def copy(pairs):
        return [Pair(**vars(p)) for p in pairs]

    weighted = copy(ctrl)
    for q, sh in zip(weighted, (0.01, 0.05, None, 0.02, 0.08, 0.03)):
        q.sigma_height = sh
    weighted[1].sigma_plan = 0.04
    blunder = copy(ctrl)
    blunder[2].H += 0.3
    cases = [
        ("truth_geoid", "RU-MOW_truth.ggf", "geoid", "bilinear", ctrl + ctl),
        ("truth_geoid_plane", "RU-MOW_truth.ggf", "geoid_plane", "bilinear", ctrl + ctl),
        ("truth_geoid_plane_isg", "RU-MOW_truth.isg", "geoid_plane", "bicubic", copy(ctrl)),
        ("bump_geoid_plane_bicubic", "RU-MOW_bump.ggf", "geoid_plane", "bicubic", bump),
        ("wrong_grid_geoid", "RU-MOW_bump.ggf", "geoid", "bilinear", copy(ctrl)),
        ("two_points", "RU-MOW_truth.gtx", "geoid_plane", "bilinear", copy(ctrl[:2])),
        ("weighted", "RU-MOW_truth.ggf", "geoid_plane", "bilinear", weighted),
        ("blunder_height", "RU-MOW_truth.ggf", "geoid", "bilinear", blunder),
        ("plan_only", "RU-MOW_truth.ggf", "geoid", "bilinear", [Pair(**{**vars(p), "use": "plan"}) for p in ctrl]),
    ]
    out = []
    for name, f, model, interp, pairs in cases:
        g = read_grid(GEOID_DIR / f)
        kw = dict(gnss_datum="PZ-90.11", height_model=model, geoid=g, geoid_interpolation=interp)
        dt = localize(pairs, **kw)
        loc = np.column_stack(dt.to_local(*chk.T))
        back = np.column_stack(dt.to_wgs(*loc.T))
        ex = [f"{n}:{part}" for n, part, _ in suggest_exclusions(pairs, **kw)]
        out.append(
            f'GeoidLocCase("{name}", "{f}", "{model}", "{interp}", "{dt.height_model}", listOf({", ".join(pair_kt(p) for p in pairs)}),\n'
            f'  doubleArrayOf({", ".join(d(v) for v in params(dt))}),\n'
            f'  doubleArrayOf({", ".join(d(v) for v in datum_diag(dt))}),\n  {arr(resid_diag(dt))},\n'
            f'  listOf({", ".join(chr(34) + w.code + chr(34) for w in dt.warnings)}),\n'
            f'  listOf({", ".join(chr(34) + e + chr(34) for e in ex)}),\n'
            f'  {arr(chk)},\n  {arr(loc)},\n  {arr(back)},\n  {arr(quality(dt, chk))})')
    dt = localize(ctrl, gnss_datum="PZ-90.11", height_model="geoid_plane", geoid=read_grid(GEOID_DIR / "RU-MOW_truth.ggf"))
    js = json.dumps(dt.to_dict(), indent=1, ensure_ascii=False)
    return out, js, np.column_stack(dt.to_local(*chk.T)), chk


def write_geoid():
    vals = geoid_value_cases()
    loc, js, js_local, chk = geoid_loc_cases()
    files = []
    for f in GEOID_FILES:
        raw = (GEOID_DIR / f).read_bytes()
        g = read_grid(GEOID_DIR / f)
        files.append(f'GeoidFile("{f}", "{raw.hex()}", "{g.sha256}", {g.rows}, {g.cols}, {d(g.lat0)}, {d(g.lon0)}, '
                     f'{d(g.dlat)}, {d(g.dlon)}, {int(np.isnan(g.values).sum())})')
    OUT_GEOID.write_text(
        "// Сгенерировано tools/gen_kotlin_reference.py из Python-эталона (mathdatum.geoid). Не редактировать вручную.\n"
        "package ru.mathdatum.localization\n\n"
        "/** Тестовая сетка tests/data/geoid: содержимое файла (hex), SHA-256 и заголовок по Python. */\n"
        "class GeoidFile(val name: String, val hex: String, val sha256: String, val rows: Int, val cols: Int,\n"
        "                val lat0: Double, val lon0: Double, val dlat: Double, val dlon: Double, val nodata: Int)\n\n"
        "/** expected = NaN — ожидается GeoidException (вне сетки, NODATA, край для бикубической). */\n"
        "class GeoidValueCase(val file: String, val lat: Double, val lon: Double, val interpolation: String, val expected: Double)\n\n"
        "/** expected, diag, residDiag, quality — как у DiagCase; check — контрольные пункты (ПЗ-90.11), local — их to_local,\n"
        " *  back — to_wgs(local). */\n"
        "class GeoidLocCase(val name: String, val file: String, val model: String, val interpolation: String,\n"
        "                   val heightModel: String, val pairs: List<LocalizationPair>, val expected: DoubleArray,\n"
        "                   val diag: DoubleArray, val residDiag: List<DoubleArray>, val warnings: List<String>,\n"
        "                   val exclusions: List<String>, val check: List<DoubleArray>, val local: List<DoubleArray>,\n"
        "                   val back: List<DoubleArray>, val quality: List<DoubleArray>)\n\n"
        "val GEOID_FILES = listOf(\n    " + ",\n    ".join(files) + ",\n)\n\n"
        "val GEOID_VALUES: List<GeoidValueCase> by lazy { geoidValues() }\n\n"
        "private fun geoidValues() = listOf(\n    " + ",\n    ".join(vals) + ",\n)\n\n"
        + "".join(f"private fun geoidLoc{i}() = {c}\n\n" for i, c in enumerate(loc))
        + "val GEOID_LOC_CASES: List<GeoidLocCase> by lazy { listOf(" + ", ".join(f"geoidLoc{i}()" for i in range(len(loc))) + ") }\n\n"
        + "/** Датум RU-MOW (6 опорных, ПЗ-90.11, geoid_plane, RU-MOW_truth.ggf), сохранённый Python-эталоном. */\n"
        + "val PY_GEOID_DATUM_JSON = " + json.dumps(js).replace("$", "\\$") + "\n"
        + f"val PY_GEOID_DATUM_CHECK = {arr(chk)}\n"
        + f"val PY_GEOID_DATUM_LOCAL = {arr(js_local)}\n",
        encoding="utf-8")
    print(f"{OUT_GEOID}: {len(files)} сеток, {len(vals)} значений, {len(loc)} случаев локализации")


def arr(m):
    return "listOf(" + ", ".join("doubleArrayOf(" + ", ".join(d(v) for v in row) + ")" for row in m) + ")"


def main():
    tm, rg, dc = tm_cases(), regions(), diag_cases()
    OUT.write_text(
        "// Сгенерировано tools/gen_kotlin_reference.py из Python-эталона. Не редактировать вручную.\n"
        "package ru.mathdatum.localization\n\n"
        "class TmCase(val ellipsoid: String, val lat0: Double, val lon0: Double, val lat: Double, val lon: Double,\n"
        "             val north: Double, val east: Double)\n\n"
        "/** expected: lat0, lon0, Nc, Ec, a, b, tx, ty, c0, c1, c2, rmsPlan, rmsHeight. */\n"
        "class RegionCase(val iso: String, val pairs: List<LocalizationPair>, val expected: DoubleArray,\n"
        "                 val checkWgs: List<DoubleArray>, val checkLocal: List<DoubleArray>,\n"
        "                 val catalogLocal: List<DoubleArray>, val catalogWgs: List<DoubleArray>,\n"
        "                 val diag: DoubleArray, val residDiag: List<DoubleArray>, val checkQuality: List<DoubleArray>)\n\n"
        "/** expected — как у RegionCase; diag: redundancyPlan, redundancyHeight, s0Plan, s0Height;\n"
        " *  residDiag: qvvPlan, qvvHeight, wx, wy, wH, looDx, looDy, looDH, pPlan, pHeight, dx, dy, dH;\n"
        " *  quality: outside, mPlan, mH (априори), mPlan, mH (апостериори). NaN — null. */\n"
        "class DiagCase(val name: String, val pairs: List<LocalizationPair>, val expected: DoubleArray, val diag: DoubleArray,\n"
        "               val residDiag: List<DoubleArray>, val suspect: List<Boolean>, val warnings: List<String>,\n"
        "               val exclusions: List<String>, val points: List<DoubleArray>, val quality: List<DoubleArray>)\n\n"
        "val TM_CASES = listOf(\n    " + ",\n    ".join(tm) + ",\n)\n\n"
        "// Функции вместо одного большого списка: так JVM не упирается в лимит размера метода.\n"
        + "".join(f"private fun region{i}() = {r}\n\n" for i, r in enumerate(rg))
        + "val REGIONS: List<RegionCase> by lazy { listOf(" + ", ".join(f"region{i}()" for i in range(len(rg))) + ") }\n\n"
        + "".join(f"private fun diag{i}() = {c}\n\n" for i, c in enumerate(dc))
        + "val DIAG_CASES: List<DiagCase> by lazy { listOf(" + ", ".join(f"diag{i}()" for i in range(len(dc))) + ") }\n\n"
        + "/** examples/datum.json — датум, сохранённый Python-эталоном по examples/pairs.csv. */\n"
        + "val PY_DATUM_JSON = " + json.dumps((ROOT / "examples/datum.json").read_text(encoding="utf-8")).replace("$", "\\$") + "\n",
        encoding="utf-8")
    print(f"{OUT}: {len(tm)} TM, {len(rg)} регионов, {len(dc)} случаев надёжности")
    write_datums()
    write_geoid()


if __name__ == "__main__":
    main()
