#!/usr/bin/env python3
"""
Эталоны PROJ для справочника EPSG: стратифицированная выборка СК каталога (метод × статус датума × оси × единицы),
для каждой — 3 точки внутри зоны применимости. Конвейер PROJ строится ИЗ ЗАПИСИ КАТАЛОГА (независимо от Kotlin), поэтому
тест проверяет и разбор каталога, и математику. Выход: core/src/desktopTest/resources/epsg-golden.json.
Запуск: python3 tools/gen_epsg_golden.py [каталог.json]   (нужен pyproj)
"""
import json, random, sys, pathlib, collections
import pyproj

root = pathlib.Path(__file__).resolve().parent.parent
cat = json.loads(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else root / "app/src/commonMain/composeResources/files/epsg.json").read_text(encoding="utf-8"))
ELL, HEL = cat["ellipsoids"], cat["helmerts"]
rnd = random.Random(20260101)

def ellps(key):
    e = ELL[key]
    return f"+a={e['a']!r} +rf={e['invF']!r}"

def pipeline(e):
    p = e["projection"]; el = ellps(e["ellipsoid"])
    steps = "+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step +proj=cart +ellps=WGS84 "
    if e["helmert"]:
        h = HEL[e["helmert"]]
        conv = f" +convention={h['convention']}" if "convention" in h else ""
        rot = f" +rx={h['r'][0]!r} +ry={h['r'][1]!r} +rz={h['r'][2]!r} +s={h['ppm']!r}" if "convention" in h else ""
        inv = "+inv " if h["direction"] == "local_to_wgs84" else ""
        steps += f"+step {inv}+proj=helmert +x={h['t'][0]!r} +y={h['t'][1]!r} +z={h['t'][2]!r}{rot}{conv} +exact "
    steps += f"+step +inv +proj=cart {el} +step "
    m = p["method"]
    if m == 9807:
        steps += f"+proj=tmerc +lat_0={p['lat0']!r} +lon_0={p['lon0']!r} +k={p['k0']!r} +x_0={p['x0']!r} +y_0={p['y0']!r} {el}"
    elif m == 9808:
        steps += f"+proj=tmerc +axis=wsu +lat_0={p['lat0']!r} +lon_0={p['lon0']!r} +k={p['k0']!r} +x_0={p['x0']!r} +y_0={p['y0']!r} {el}"
    elif m == 9801:
        steps += f"+proj=lcc +lat_1={p['lat0']!r} +lat_0={p['lat0']!r} +lon_0={p['lon0']!r} +k_0={p['k0']!r} +x_0={p['x0']!r} +y_0={p['y0']!r} {el}"
    elif m == 9802:
        steps += f"+proj=lcc +lat_0={p['latF']!r} +lon_0={p['lonF']!r} +lat_1={p['lat1']!r} +lat_2={p['lat2']!r} +x_0={p['eF']!r} +y_0={p['nF']!r} {el}"
    else:
        raise ValueError(m)
    return steps

groups = collections.defaultdict(list)
for e in cat["entries"]:
    b = e.get("bounds")
    if not b or b[2] > b[3]:
        continue
    groups[(e["projection"]["method"], e["dt"], e["axes"], e["unit"] == 1.0)].append(e)
sample = []
for k, lst in sorted(groups.items()):
    rnd.shuffle(lst)
    sample += lst[:25 if k[3] else 40]
extra = [e for g in groups.values() for e in g if e not in sample]
rnd.shuffle(extra)
sample += extra[:300]

out, skipped = [], 0
for e in sample:
    s, n, w, ea = e["bounds"]
    try:
        T = pyproj.Transformer.from_pipeline(pipeline(e))
    except Exception as ex:   # PROJ отказался строить: пропускаем и считаем
        skipped += 1; continue
    pts = []
    for fx, fy in ((0.5, 0.5), (0.2, 0.8), (0.85, 0.3)):
        lat = s + (n - s) * fy; lon = w + (ea - w) * fx
        a, b, h = T.transform(lon, lat, 100.0)
        if not all(map(lambda v: v == v and abs(v) < 1e12, (a, b, h))):
            continue
        x, y = (a, b) if e["axes"] == "EN" else (b, a)
        pts.append([lat, lon, 100.0, x / e["unit"], y / e["unit"], h / e["unit"]])
    if pts:
        out.append({"id": e["id"], "points": pts})
dst = root / "core/src/desktopTest/resources/epsg-golden.json"
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(json.dumps({"proj": pyproj.proj_version_str, "catalog": cat["version"], "crs": out}, separators=(",", ":")), encoding="utf-8")
print("wrote", dst, f"{dst.stat().st_size/1e3:.0f} KB;", len(out), "CRS,", sum(len(c['points']) for c in out), "points; skipped by PROJ:", skipped)
