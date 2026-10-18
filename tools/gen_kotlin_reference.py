"""Генерирует эталонные данные для тестов Kotlin-модуля из Python-эталона (mathdatum + pyproj).

  python tools/gen_kotlin_reference.py

Пишет kmp/localization/src/commonTest/kotlin/ru/mathdatum/localization/ReferenceData.kt:
  - TM_CASES: прямые/обратные пересчёты поперечного Меркатора (pyproj) на разных эллипсоидах;
  - REGIONS: по каждому из 83 регионов — пары точек, датум по Python-эталону, прогноз
    в контрольных точках и обратный пересчёт, диагностика надёжности;
  - DIAG_CASES: особые случаи надёжности (грубые ошибки, нулевая избыточность, вырождение без
    точки, флаги use, неправдоподобные масштаб и разворот).
"""

import json
import sys
from pathlib import Path

import numpy as np
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mathdatum import Pair, localize, read_pairs, suggest_exclusions

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "kmp/localization/src/commonTest/kotlin/ru/mathdatum/localization/ReferenceData.kt"


def d(v):
    return "Double.NaN" if v is None or v != v else repr(float(v))


def resid_diag(dt):
    """По каждой невязке: qvvPlan, qvvHeight, wx, wy, wH, looDx, looDy, looDH (NaN — null)."""
    return [[r.qvv_plan, r.qvv_height, r.wx, r.wy, r.wH, r.loo_dx, r.loo_dy, r.loo_dH] for r in dt.residuals]


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
            f'  doubleArrayOf({", ".join(d(v) for v in (dt.lat0, dt.lon0, dt.Nc, dt.Ec, dt.a, dt.b, dt.tx, dt.ty, dt.c0, dt.c1, dt.c2, dt.rms_plan, dt.rms_height))}),\n'
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

    out = []
    for name, pairs in cases:
        dt = localize(pairs)
        pts = np.array([[p.B, p.L, p.h] for p in base])
        ex = [f"{n}:{part}" for n, part, _ in suggest_exclusions(pairs)]
        pairs_kt = ", ".join(
            f'LocalizationPair("{p.name}", {d(p.B)}, {d(p.L)}, {d(p.h)}, {d(p.x)}, {d(p.y)}, {d(p.H)}, Use.{p.use.upper()})'
            for p in pairs)
        out.append(
            f'DiagCase("{name}", listOf({pairs_kt}),\n'
            f'  doubleArrayOf({", ".join(d(v) for v in datum_diag(dt))}),\n  {arr(resid_diag(dt))},\n'
            f'  listOf({", ".join("true" if r.suspect else "false" for r in dt.residuals)}),\n'
            f'  listOf({", ".join(chr(34) + w.code + chr(34) for w in dt.warnings)}),\n'
            f'  listOf({", ".join(chr(34) + e + chr(34) for e in ex)}),\n'
            f'  {arr(pts)},\n  {arr(quality(dt, pts))})')
    return out


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
        "/** diag: redundancyPlan, redundancyHeight, s0Plan, s0Height; residDiag: qvvPlan, qvvHeight, wx, wy, wH,\n"
        " *  looDx, looDy, looDH; quality: outside, mPlan, mH (априори), mPlan, mH (апостериори). NaN — null. */\n"
        "class DiagCase(val name: String, val pairs: List<LocalizationPair>, val diag: DoubleArray,\n"
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


if __name__ == "__main__":
    main()
