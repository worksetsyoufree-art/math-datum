"""Генерирует эталонные данные для тестов Kotlin-модуля из Python-эталона (mathdatum + pyproj).

  python tools/gen_kotlin_reference.py

Пишет kmp/localization/src/commonTest/kotlin/ru/mathdatum/localization/ReferenceData.kt:
  - TM_CASES: прямые/обратные пересчёты поперечного Меркатора (pyproj) на разных эллипсоидах;
  - REGIONS: по каждому из 83 регионов — пары точек, датум по Python-эталону, прогноз
    в контрольных точках и обратный пересчёт.
"""

import json
from pathlib import Path

import numpy as np
from pyproj import Transformer

from mathdatum import Pair, localize

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "kmp/localization/src/commonTest/kotlin/ru/mathdatum/localization/ReferenceData.kt"


def d(v):
    return repr(float(v))


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
            f'  {arr(chk)},\n  {arr(np.column_stack([x, y, H]))},\n  {arr(loc)},\n  {arr(np.column_stack([B, L, h]))})')
    return out


def arr(m):
    return "listOf(" + ", ".join("doubleArrayOf(" + ", ".join(d(v) for v in row) + ")" for row in m) + ")"


def main():
    tm, rg = tm_cases(), regions()
    OUT.write_text(
        "// Сгенерировано tools/gen_kotlin_reference.py из Python-эталона. Не редактировать вручную.\n"
        "package ru.mathdatum.localization\n\n"
        "class TmCase(val ellipsoid: String, val lat0: Double, val lon0: Double, val lat: Double, val lon: Double,\n"
        "             val north: Double, val east: Double)\n\n"
        "/** expected: lat0, lon0, Nc, Ec, a, b, tx, ty, c0, c1, c2, rmsPlan, rmsHeight. */\n"
        "class RegionCase(val iso: String, val pairs: List<LocalizationPair>, val expected: DoubleArray,\n"
        "                 val checkWgs: List<DoubleArray>, val checkLocal: List<DoubleArray>,\n"
        "                 val catalogLocal: List<DoubleArray>, val catalogWgs: List<DoubleArray>)\n\n"
        "val TM_CASES = listOf(\n    " + ",\n    ".join(tm) + ",\n)\n\n"
        "// Функции вместо одного большого списка: так JVM не упирается в лимит размера метода.\n"
        + "".join(f"private fun region{i}() = {r}\n\n" for i, r in enumerate(rg))
        + "val REGIONS: List<RegionCase> by lazy { listOf(" + ", ".join(f"region{i}()" for i in range(len(rg))) + ") }\n",
        encoding="utf-8")
    print(f"{OUT}: {len(tm)} TM, {len(rg)} регионов")


if __name__ == "__main__":
    main()
