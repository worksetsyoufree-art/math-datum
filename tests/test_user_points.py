"""Six control points (X north, Y east) must land inside the expected box through MSK-50 zone 2."""
import json, pathlib, sys
from pyproj import CRS, Transformer

ROOT = pathlib.Path(__file__).resolve().parent.parent
S, W, N, E = 55.619783, 38.304913, 55.623095, 38.310216
PTS = [(453594.207, 2238973.376), (453592.333, 2238975.140), (453585.483, 2238974.514), (453585.403, 2238972.128), (453571.586, 2238973.450), (453571.156, 2238971.407)]
systems = json.load(open(ROOT / "data/systems.json"))
s = next(o for o in systems if "МСК-50 зона 2" in o["names"])
T = Transformer.from_crs(CRS.from_proj4(s["proj4"]), "EPSG:4326", always_xy=True)
for x, y in PTS:
    lon, lat = T.transform(y, x)
    print(f"X={x} Y={y} -> {lat:.6f}, {lon:.6f}")
    assert S <= lat <= N and W <= lon <= E, "point outside the expected box"
print(s["id"], s["names"], "ok")
sys.exit(0)
