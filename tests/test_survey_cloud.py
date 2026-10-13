"""Regression: a real survey (point cloud in MSK-78(5), SPb) must contain the ENU origin converted through my system.

Fixtures: tests/fixtures/surface_m11_ring.txt (SURFACE_V1, local X(north) Y(east) Z) and msk78_5_datum.json
(WGS84 -> local, coordinate frame, three rotations in arcsec). ENU origin in WGS84 ECEF is from the survey header.
"""
import json, math, pathlib, sys
from pyproj import CRS, Transformer

ROOT = pathlib.Path(__file__).resolve().parent.parent
L = open(ROOT / "tests/fixtures/surface_m11_ring.txt", encoding="utf-8", errors="replace").read().split("\n")
n = int(L[2])
pts = [tuple(map(float, l.split())) for l in L[4:4 + n]]
xs, ys = [p[0] for p in pts], [p[1] for p in pts]
cx, cy = sum(xs) / n, sum(ys) / n
X, Y, Z = 2772743.0666661696, 1631247.7534042243, 5488981.23905303  # enuOriginInWGS

# ECEF -> geodetic (WGS84)
a, f = 6378137.0, 1 / 298.257223563
e2 = f * (2 - f)
lon = math.atan2(Y, X); p = math.hypot(X, Y); lat = math.atan2(Z, p * (1 - e2))
for _ in range(10):
    N = a / math.sqrt(1 - e2 * math.sin(lat) ** 2); h = p / math.cos(lat) - N
    lat = math.atan2(Z, p * (1 - e2 * N / (N + h)))
lat, lon = math.degrees(lat), math.degrees(lon)


def locate(p4):
    e, n_ = Transformer.from_crs("EPSG:4326", CRS.from_proj4(p4), always_xy=True).transform(lon, lat)
    return n_, e, math.hypot(n_ - cx, e - cy), min(xs) <= n_ <= max(xs) and min(ys) <= e <= max(ys)


systems = json.load(open(ROOT / "data/systems.json")) + json.load(open(ROOT / "data/systems_unverified.json"))
s = next(o for o in systems if "МСК_78(5)" in o["names"])
north, east, dist, inside = locate(s["proj4"])
print(f"{s['id']} {s['names']}: X={north:.3f} Y={east:.3f}  {dist:.1f} m from cloud centroid, inside bbox: {inside}")
assert inside and dist < 25, "ENU origin must fall inside the survey surface"
# guard: without omega_y (as in the first export) the origin misses the surface by ~180 m
d = json.load(open(ROOT / "tests/fixtures/msk78_5_datum.json"))["parameters7"]
tw = [-d["d_x"], -d["d_y"], -d["d_z"], d["r_x"], 0.0, d["r_z"], -d["k"]]
bad = locate("+proj=tmerc +lat_0=0 +lon_0=30 +k=1 +x_0=95900 +y_0=-6552800 +ellps=WGS84 +towgs84=" + ",".join(map(str, tw)) + " +units=m +no_defs")
print(f"without omega_y: {bad[2]:.1f} m from centroid, inside: {bad[3]}")
assert not bad[3] and bad[2] > 100
print("ok")
sys.exit(0)
