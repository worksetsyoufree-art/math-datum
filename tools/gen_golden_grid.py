#!/usr/bin/env python3
"""Генерирует core/src/commonTest/.../GoldenGridData.kt: эталоны PROJ для набора СК (все эллипсоиды, большие вращения
Гельмерта, ЦМ ±90°, >180°, юг, lat_0 != 0) × сетка точек. Требуется pyproj. Запуск: python3 tools/gen_golden_grid.py"""
import pyproj, sys, pathlib

ELL = {  # id в Kotlin -> параметры PROJ
    "WGS84": "+ellps=WGS84", "KRASSOVSKY": "+ellps=krass", "BESSEL": "+ellps=bessel",
    "GSK2011": "+a=6378136.5 +rf=298.2564151", "PZ90_11": "+a=6378136 +rf=298.25784",
}
H0 = None
H_SK42 = (23.92, -141.27, -80.9, 0.0, -0.35, -0.82, -0.12)
H_BIG = (-120.0, 90.0, 410.0, 10.0, -9.0, 12.0, 5.0)            # большие вращения, ~10"
H_BESSEL = (598.1, 73.7, 418.2, 0.202, 0.045, -2.455, 6.7)      # порядок величин как у Москвы-Бесселя
CASES = [  # id, ellipsoid, helmert, lat0, lon0, k0, x0, y0, широты точек
    ("sk42-gk-cm39", "KRASSOVSKY", H_SK42, 0.0, 39.0, 1.0, 7500000.0, 0.0, [43, 55, 60, 69]),
    ("big-rot-cm33", "KRASSOVSKY", H_BIG, 0.0, 33.0, 1.0, 6500000.0, 0.0, [45, 56, 70]),
    ("bessel-cm37.5", "BESSEL", H_BESSEL, 55.66666666667, 37.5, 1.0, 1500000.0, -5000000.0, [54, 56, 58]),
    ("cm90", "KRASSOVSKY", H_SK42, 0.0, 90.0, 1.0, 15500000.0, 0.0, [52, 60, 72]),
    ("cm-90", "WGS84", None, 0.0, -90.0, 0.9996, 500000.0, 0.0, [-40, 10, 60]),
    ("cm180.45", "KRASSOVSKY", H_SK42, 0.0, 180.45, 1.0, 87000000.0, 0.0, [62, 66, 69]),
    ("cm186.45", "KRASSOVSKY", H_SK42, 0.0, 186.45, 1.0, 87000000.0, 0.0, [62, 66, 69]),
    ("south-utm", "WGS84", None, 0.0, 151.0, 0.9996, 500000.0, 10000000.0, [-45, -33.9, -20, -5]),
    ("gsk2011-cm60", "GSK2011", (0.013, -0.092, -0.03, 0.001738, -0.003559, 0.004263, 0.0074), 0.0, 60.0, 1.0, 2500000.0, 0.0, [45, 61, 75]),
    ("pz90-cm45", "PZ90_11", (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 0.0, 45.0, 1.0, 8500000.0, 0.0, [50, 63]),
    ("lat0-55-k0.9999", "WGS84", None, 55.0, 12.0, 0.9999, 100000.0, 200000.0, [50, 55, 60]),
]
OFFS = [0.0, 1.5, -3.0, 6.0, -9.0]
HEIGHTS = [0.0, 1000.0]

def norm(lon):
    while lon > 180: lon -= 360
    while lon <= -180: lon += 360
    return lon

out = ["// СГЕНЕРИРОВАНО tools/gen_golden_grid.py (PROJ %s, pyproj %s). Не править вручную." % (pyproj.proj_version_str, pyproj.__version__),
       "package mathdatum.core", "",
       "internal class GridCase(", "    val id: String, val ellipsoid: String, val helmert: DoubleArray?,",
       "    val lat0: Double, val lon0: Double, val k0: Double, val x0: Double, val y0: Double,",
       "    val points: List<DoubleArray>, // lat, lon, h, north, east, hOut",
       ")", "", "internal val GRID_CASES: List<GridCase> = listOf("]
for (cid, ell, hp, lat0, lon0, k0, x0, y0, lats) in CASES:
    e = ELL[ell]
    steps = f"+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step +proj=cart +ellps=WGS84 "
    if hp: steps += "+step +proj=helmert +x=%r +y=%r +z=%r +rx=%r +ry=%r +rz=%r +s=%r +convention=coordinate_frame +exact " % hp
    steps += f"+step +inv +proj=cart {e} +step +proj=tmerc +lat_0={lat0} +lon_0={lon0} +k={k0} +x_0={x0} +y_0={y0} {e}"
    T = pyproj.Transformer.from_pipeline(steps)
    pts = []
    for la in lats:
        for o in OFFS:
            for h in HEIGHTS:
                lo = norm(lon0 + o)
                east, north, hh = T.transform(lo, la, h)
                pts.append((la, lo, h, north, east, hh))
    hk = "doubleArrayOf(%s)" % ", ".join(repr(float(v)) for v in hp) if hp else "null"
    out.append(f'    GridCase("{cid}", "{ell}", {hk}, {float(lat0)!r}, {float(lon0)!r}, {float(k0)!r}, {float(x0)!r}, {float(y0)!r}, listOf(')
    for p in pts:
        out.append("        doubleArrayOf(" + ", ".join(repr(float(v)) for v in p) + "),")
    out.append("    )),")
out.append(")")
dst = pathlib.Path(__file__).resolve().parent.parent / "core/src/commonTest/kotlin/mathdatum/core/GoldenGridData.kt"
dst.write_text("\n".join(out) + "\n")
print("wrote", dst, sum(len(c) for c in CASES), "cases")
