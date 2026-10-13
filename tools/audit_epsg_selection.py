#!/usr/bin/env python3
"""Аудит выбора трансформации: сравнение каталога с тем, что PROJ выбирает сам (Transformer.from_crs(4326, EPSG:code)).
Не тест, а отчёт: расхождения > 1 м там, где у нас статус helmert/exact, указывают на ошибку выбора."""
import json, sys, pathlib, collections, math
import pyproj
sys.argv = [sys.argv[0]]
exec(open(pathlib.Path(__file__).resolve().parent / "gen_epsg_golden.py").read().split("groups = collections")[0])
rows = []
for e in cat["entries"]:
    b = e.get("bounds")
    if not b or b[2] > b[3] or "epsg" not in e:
        continue
    lat = (b[0] + b[1]) / 2; lon = (b[2] + b[3]) / 2
    try:
        mine = pyproj.Transformer.from_pipeline(pipeline(e)).transform(lon, lat, 0.0)
        ref = pyproj.Transformer.from_crs(4326, e["epsg"], always_xy=True).transform(lon, lat, 0.0)
    except Exception:
        continue
    if not all(map(math.isfinite, mine[:2] + ref[:2])) or abs(ref[0]) > 1e12:
        continue
    if e["projection"]["method"] == 9808:
        continue   # PROJ при always_xy отдаёт «запад/юг»; сравнение осей отдельно не делаем
    u = e["unit"]
    # always_xy: (E, N) в единицах CRS; наш конвейер — (E, N) в метрах
    d = math.hypot(mine[0] - ref[0] * u, mine[1] - ref[1] * u)
    rows.append((e["dt"], u, d, e))
bins = collections.defaultdict(lambda: collections.Counter())
for dt, unit, d, e in rows:
    k = "<=0.01 м" if d <= 0.01 else "<=1 м" if d <= 1 else "<=10 м" if d <= 10 else "<=100 м" if d <= 100 else ">100 м"
    bins[dt][k] += 1
order = ["<=0.01 м", "<=1 м", "<=10 м", "<=100 м", ">100 м"]
print(f"{'статус':16}" + "".join(f"{o:>10}" for o in order) + "   всего")
for dt in ("exact", "helmert", "helmert_partial", "approx_grid", "approx_unknown"):
    c = bins[dt]; print(f"{dt:16}" + "".join(f"{c[o]:>10}" for o in order) + f"   {sum(c.values())}")
bad = [(d, e["id"], e["name"], e["dt"]) for dt, u, d, e in rows if e["dt"] in ("exact", "helmert") and d > 1]
print("exact/helmert с расхождением > 1 м:", len(bad))
for d, i, n, dt in sorted(bad, reverse=True)[:15]:
    print(f"  {d:10.2f} м  {i}  {n}  [{dt}]")
