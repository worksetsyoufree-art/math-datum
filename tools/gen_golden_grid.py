#!/usr/bin/env python3
"""Генерирует core/src/commonTest/.../GoldenGridData.kt: эталоны PROJ для набора СК (все эллипсоиды, большие вращения
Гельмерта, ЦМ ±90°, >180°, юг, lat_0 != 0) × сетка точек. Требуется pyproj. Запуск: python3 tools/gen_golden_grid.py"""
import pyproj, sys, pathlib

ELL = {  # id в Kotlin -> параметры PROJ
    "WGS84": "+ellps=WGS84", "GRS80": "+ellps=GRS80", "KRASSOVSKY": "+ellps=krass", "BESSEL": "+ellps=bessel",
    "GSK2011": "+a=6378136.5 +rf=298.2564151", "PZ90_11": "+a=6378136 +rf=298.25784",
}
H0 = None
H_SK42 = (23.92, -141.27, -80.9, 0.0, -0.35, -0.82, -0.12)
H_BIG = (-120.0, 90.0, 410.0, 10.0, -9.0, 12.0, 5.0)            # большие вращения, ~10"
H_BESSEL = (598.1, 73.7, 418.2, 0.202, 0.045, -2.455, 6.7)      # порядок величин как у Москвы-Бесселя
CASES = [  # id, ellipsoid, helmert, метод EPSG, параметры, широты точек, смещения долгот от ЦМ
    # TM 9807: [lat0, lon0, k0, x0(восток), y0(север)]
    ("sk42-gk-cm39", "KRASSOVSKY", H_SK42, 9807, [0.0, 39.0, 1.0, 7500000.0, 0.0], [43, 55, 60, 69], None),
    ("big-rot-cm33", "KRASSOVSKY", H_BIG, 9807, [0.0, 33.0, 1.0, 6500000.0, 0.0], [45, 56, 70], None),
    ("bessel-cm37.5", "BESSEL", H_BESSEL, 9807, [55.66666666667, 37.5, 1.0, 1500000.0, -5000000.0], [54, 56, 58], None),
    ("cm90", "KRASSOVSKY", H_SK42, 9807, [0.0, 90.0, 1.0, 15500000.0, 0.0], [52, 60, 72], None),
    ("cm-90", "WGS84", None, 9807, [0.0, -90.0, 0.9996, 500000.0, 0.0], [-40, 10, 60], None),
    ("cm180.45", "KRASSOVSKY", H_SK42, 9807, [0.0, 180.45, 1.0, 87000000.0, 0.0], [62, 66, 69], None),
    ("cm186.45", "KRASSOVSKY", H_SK42, 9807, [0.0, 186.45, 1.0, 87000000.0, 0.0], [62, 66, 69], None),
    ("south-utm", "WGS84", None, 9807, [0.0, 151.0, 0.9996, 500000.0, 10000000.0], [-45, -33.9, -20, -5], None),
    ("gsk2011-cm60", "GSK2011", (0.013, -0.092, -0.03, 0.001738, -0.003559, 0.004263, 0.0074), 9807, [0.0, 60.0, 1.0, 2500000.0, 0.0], [45, 61, 75], None),
    ("pz90-cm45", "PZ90_11", (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 9807, [0.0, 45.0, 1.0, 8500000.0, 0.0], [50, 63], None),
    ("lat0-55-k0.9999", "WGS84", None, 9807, [55.0, 12.0, 0.9999, 100000.0, 200000.0], [50, 55, 60], None),
    # TM South Orientated 9808: (западное, южное смещение) -> поля (east, north)
    ("tmso-lo19", "WGS84", None, 9808, [0.0, 19.0, 1.0, 0.0, 0.0], [-34, -30, -25], None),
    # LCC 2SP 9802: [latF, lonF, lat1, lat2, eF, nF]
    ("lcc2-france93", "GRS80", (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0), 9802, [46.5, 3.0, 49.0, 44.0, 700000.0, 6600000.0], [41.5, 46.5, 51], [0.0, 3.0, -6.0, 9.0, 11.0]),
    ("lcc2-south", "WGS84", None, 9802, [-20.0, 25.0, -10.0, -30.0, 100000.0, 200000.0], [-5, -22, -40], [0.0, 5.0, -10.0, 15.0]),
    ("lcc2-krass-helm", "KRASSOVSKY", H_SK42, 9802, [0.0, 105.0, 52.0, 64.0, 18500000.0, 0.0], [50, 58, 66, 74], [0.0, 10.0, -20.0, 30.0]),
    ("lcc2-equalpar", "WGS84", None, 9802, [40.0, -100.0, 40.0, 40.0, 0.0, 0.0], [35, 45], [0.0, 8.0, -8.0]),
    # LCC 1SP 9801: [lat0, lon0, k0, x0, y0]
    ("lcc1-bessel", "BESSEL", H_BESSEL, 9801, [49.5, 2.337229167, 0.99987734, 600000.0, 200000.0], [43, 49.5, 56], [0.0, 4.0, -7.0]),
    ("lcc1-south", "WGS84", None, 9801, [-25.0, 135.0, 0.9998, 1000000.0, 2000000.0], [-10, -25, -43], [0.0, 6.0, -9.0, 20.0]),
]
OFFS = [0.0, 1.5, -3.0, 6.0, -9.0]
HEIGHTS = [0.0, 1000.0]

def norm(lon):
    while lon > 180: lon -= 360
    while lon <= -180: lon += 360
    return lon

out = ["// СГЕНЕРИРОВАНО tools/gen_golden_grid.py (PROJ %s, pyproj %s). Не править вручную." % (pyproj.proj_version_str, pyproj.__version__),
       "package mathdatum.core", "",
       "internal class GridCase(", "    val id: String, val ellipsoid: String, val helmert: DoubleArray?, val method: Int,",
       "    val params: DoubleArray, // TM/TMS/LCC1: lat0, lon0, k0, x0, y0; LCC2: latF, lonF, lat1, lat2, eF, nF",
       "    val points: List<DoubleArray>, // lat, lon, h, north, east, hOut (поля north/east = первая/вторая ось PROJ при axis=enu / wsu)",
       ")", "", "internal val GRID_CASES: List<GridCase> = listOf("]

def proj_step(method, p, e):
    if method == 9807: return f"+proj=tmerc +lat_0={p[0]} +lon_0={p[1]} +k={p[2]} +x_0={p[3]} +y_0={p[4]} {e}"
    if method == 9808: return f"+proj=tmerc +axis=wsu +lat_0={p[0]} +lon_0={p[1]} +k={p[2]} +x_0={p[3]} +y_0={p[4]} {e}"
    if method == 9802: return f"+proj=lcc +lat_0={p[0]} +lon_0={p[1]} +lat_1={p[2]} +lat_2={p[3]} +x_0={p[4]} +y_0={p[5]} {e}"
    if method == 9801: return f"+proj=lcc +lat_1={p[0]} +lat_0={p[0]} +lon_0={p[1]} +k_0={p[2]} +x_0={p[3]} +y_0={p[4]} {e}"
    raise ValueError(method)

for (cid, ell, hp, method, prm, lats, offs) in CASES:
    e = ELL[ell]
    steps = "+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step +proj=cart +ellps=WGS84 "
    if hp: steps += "+step +proj=helmert +x=%r +y=%r +z=%r +rx=%r +ry=%r +rz=%r +s=%r +convention=coordinate_frame +exact " % hp
    steps += f"+step +inv +proj=cart {e} +step " + proj_step(method, prm, e)
    T = pyproj.Transformer.from_pipeline(steps)
    lon0 = prm[1]
    pts = []
    for la in lats:
        for o in (offs or OFFS):
            for h in HEIGHTS:
                lo = norm(lon0 + o)
                first, second, hh = T.transform(lo, la, h)
                if method == 9808:   # axis=wsu: (west, south)
                    east, north = first, second
                else:
                    east, north = first, second
                pts.append((la, lo, h, north, east, hh))
    hk = "doubleArrayOf(%s)" % ", ".join(repr(float(v)) for v in hp) if hp else "null"
    out.append(f'    GridCase("{cid}", "{ell}", {hk}, {method}, doubleArrayOf({", ".join(repr(float(v)) for v in prm)}), listOf(')
    for pt in pts:
        out.append("        doubleArrayOf(" + ", ".join(repr(float(v)) for v in pt) + "),")
    out.append("    )),")
out.append(")")
dst = pathlib.Path(__file__).resolve().parent.parent / "core/src/commonTest/kotlin/mathdatum/core/GoldenGridData.kt"
dst.write_text("\n".join(out) + "\n")
print("wrote", dst, len(CASES), "cases")
