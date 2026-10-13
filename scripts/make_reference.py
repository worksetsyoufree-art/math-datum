"""Reference values from pyproj/PROJ for the browser (proj4js) parity test."""
import csv, json, pathlib
from pyproj import CRS, Transformer

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
WGS = CRS.from_epsg(4326)
systems = json.load(open(DATA / "systems.json")) + json.load(open(DATA / "systems_unverified.json"))
caps = {}
for r in csv.DictReader(open(DATA / "region_capitals.csv", encoding="utf-8")):
    caps.setdefault(r["region_code"], []).append((r["city"], float(r["lat"]), float(r["lon"])))
ref = []
for o in systems:
    pts = list(caps.get(o["region_code"], []))
    if not pts:
        continue
    t = Transformer.from_crs(WGS, CRS.from_proj4(o["proj4"]), always_xy=True)
    for city, lat, lon in pts:
        e, n = t.transform(lon, lat)
        ref.append(dict(id=o["id"], city=city, lat=lat, lon=lon, e=e, n=n))
json.dump(ref, open(ROOT / "tests/reference.json", "w"), ensure_ascii=False)
print(len(ref), "reference points for", len({r["id"] for r in ref}), "systems")
