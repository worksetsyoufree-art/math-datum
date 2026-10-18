"""Малоискажающая проекция (mathdatum.ldp): искажение в точке, сверка с PROJ, подбор, зоны, карта, localize."""

import json
import math

import numpy as np
import pytest
from pyproj import Proj, Transformer

from mathdatum import Pair, datums, ldp, localize
from mathdatum.__main__ import main
from mathdatum.geoid import GeoidGrid
from mathdatum.localization import LocalizationDatum

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
RNG = np.random.default_rng(20261018)


def square(center_B=55.5, center_L=38.0, half=10e3, el="gsk2011"):
    aux = datums.TransverseMercator(el, center_L, center_B)
    B, L = aux.inverse(np.array([-half, -half, half, half]), np.array([-half, half, half, -half]))
    return ldp.Contour("polygon", B, L)


def route_ew(length_km=150.0, B=55.0, L0=37.0, n=6):
    L = np.linspace(L0, L0 + length_km / (111.3 * math.cos(math.radians(B))), n)
    return ldp.Contour("polyline", np.full(n, B), L)


# --- искажение в точке ---

@pytest.mark.parametrize("el", ["gsk2011", "wgs84", "krass"])
def test_tm_scale_and_convergence_vs_proj(el):
    tm = datums.TransverseMercator(el, 39.5, 55.0, 0.99987, 1000, 2000)
    p = Proj(tm.proj)
    B, L = RNG.uniform(40, 75, 60), 39.5 + RNG.uniform(-4.5, 4.5, 60)
    f = p.get_factors(L, B)
    assert np.abs(tm.scale(B, L) - np.asarray(f.meridional_scale)).max() < 1e-9
    assert np.abs(tm.scale(B, L) - np.asarray(f.parallel_scale)).max() < 1e-9
    assert np.abs(tm.convergence(B, L) - np.asarray(f.meridian_convergence)).max() < 1e-8


def test_tm_scale_on_central_meridian_is_k0_and_grows_as_y2():
    tm = datums.TransverseMercator("gsk2011", 38.0, 0.0, 1.0000784)
    B = np.linspace(-80, 80, 33)
    assert np.abs(tm.scale(B, np.full_like(B, 38.0)) - 1.0000784).max() < 1e-13
    tm1 = datums.TransverseMercator("gsk2011", 38.0)
    for Bd in (45.0, 55.0, 65.0):
        R = float(ldp.gauss_radius("gsk2011", Bd))
        for y_km in (10, 30, 75, 150):
            L = 38.0 + math.degrees(y_km * 1e3 / (R * math.cos(math.radians(Bd))))
            _, y = tm1.forward(Bd, L)
            excess = float(tm1.scale(Bd, L)) - 1
            assert excess == pytest.approx(y * y / (2 * R * R), rel=2e-3 + (y / R) ** 2)


def test_height_factor():
    el = datums.ELLIPSOIDS["gsk2011"]
    for Bd in (0.0, 45.0, 55.5, 70.0):
        s = math.sin(math.radians(Bd))
        W = math.sqrt(1 - el.e2 * s * s)
        M, N = el.a * (1 - el.e2) / W ** 3, el.a / W
        R = float(ldp.gauss_radius(el, Bd))
        assert R == pytest.approx(math.sqrt(M * N), rel=1e-14)
        assert float(ldp.height_factor(el, Bd, 0.0)) == 1.0
        hf = float(ldp.height_factor(el, Bd, 500.0))
        assert (hf - 1) * 1e6 == pytest.approx(-500 / R * 1e6, rel=1e-4)        # ≈ −78.4 ppm
        # Хорды на высоте h и на эллипсоиде: по меридиану (M + h)/M, по параллели (N + h)/N; R — между ними.
        assert M / (M + 500) <= hf <= N / (N + 500)
        for dB, dL in ((0.01, 0.0), (0.0, 0.01)):
            a0 = np.array(datums.blh_to_xyz([Bd, Bd + dB], [37, 37 + dL], [0, 0], el))
            a1 = np.array(datums.blh_to_xyz([Bd, Bd + dB], [37, 37 + dL], [500, 500], el))
            ratio = np.linalg.norm(a0[:, 1] - a0[:, 0]) / np.linalg.norm(a1[:, 1] - a1[:, 0])
            assert ratio == pytest.approx(M / (M + 500) if dB else N / (N + 500), abs=2e-9)
    assert float(ldp.distortion_ppm(1.0000784, ldp.height_factor(el, 55.0, 500.0))) == pytest.approx(0.0, abs=0.5)


@pytest.mark.parametrize("alpha", [-89.983333, -60.0, -15.5, 0.0, 30.0, 72.25])
def test_omerc_vs_proj(alpha):
    om = ldp.ObliqueMercator("gsk2011", 55.3, 38.2, alpha, 1.00003, 10000, 200000)
    p = Proj(om.proj)
    B, L = 55.3 + RNG.uniform(-1, 1, 40), 38.2 + RNG.uniform(-1.5, 1.5, 40)
    x, y = om.forward(B, L)
    E, N = p(L, B)
    assert np.abs(x - N).max() < 1e-6 and np.abs(y - E).max() < 1e-6
    Bi, Li = om.inverse(x, y)
    assert np.abs(Bi - B).max() < 1e-10 and np.abs(Li - L).max() < 1e-10
    f = p.get_factors(L, B)
    assert np.abs(om.scale(B, L) - np.asarray(f.meridional_scale)).max() < 1e-9


# --- подбор ---

def test_site_20x20km_500m():
    c = square()
    r = ldp.design(c, ldp.Heights(constant=500.0))
    p, st = r.projection, r.stats
    assert p.type == "tmerc" and r.fits
    assert st["max_abs_ppm"] < 1.5 and st["share_in_tolerance"] == 1.0 and st["measure"] == "area"
    assert (p.k0 - 1) * 1e6 == pytest.approx(78.3, abs=1.0)       # компенсирует 500 м
    assert abs(p.lon0 - 38.0) < 0.02 and p.lon0 * 60 == pytest.approx(round(p.lon0 * 60), abs=1e-9)
    assert r.object_info["area_m2"] == pytest.approx(400e6, rel=1e-3)
    # Независимо: масштаб по строке PROJ (pyproj) в точках выборки → те же δ.
    S = r._samples
    k = np.asarray(Proj(p.proj).get_factors(S.L, S.B).meridional_scale)
    d = (k * ldp.height_factor(p.ellipsoid, S.B, S.h) - 1) * 1e6
    assert np.abs(d).max() == pytest.approx(st["max_abs_ppm"], abs=1e-4)   # get_factors — численные производные
    x, y = p.forward(S.B, S.L)
    E, N = Transformer.from_pipeline(f"+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step {p.proj}") \
        .transform(S.L, S.B)
    assert np.abs(x - N).max() < 1e-6 and np.abs(y - E).max() < 1e-6
    assert x.min() > 5000 and y.min() > x.max() + 20000                # координаты положительные, x и y не спутать
    assert p.x0 % 10000 == 0 and p.y0 % 100000 == 0
    # ГК и UTM для того же объекта — намного хуже.
    assert r.comparison["gk"]["zones"] == [7] and r.comparison["gk"]["stats"]["max_abs_ppm"] > 20
    assert r.comparison["utm"]["stats"]["mean_ppm"] < -400                 # k0 = 0.9996 и высота
    assert not r.zones


def test_ellipsoid_choice_is_negligible():
    c = square()
    a = ldp.design(c, ldp.Heights(constant=500.0), datum="GSK-2011", options=ldp.FitOptions(round_k0=0, round_angle=0))
    b = ldp.design(c, ldp.Heights(constant=500.0), datum="WGS-84", options=ldp.FitOptions(round_k0=0, round_angle=0))
    assert abs(a.projection.k0 - b.projection.k0) < 1e-8
    assert abs(a.stats["max_abs_ppm"] - b.stats["max_abs_ppm"]) < 0.01


def test_route_150km_east_west_needs_zones():
    c = route_ew()
    r = ldp.design(c, ldp.Heights(constant=200.0), type="tm")
    assert not r.fits and r.stats["max_abs_ppm"] > 30            # одна TM: ±35 ppm
    assert len(r.zones) == 2
    total = r.object_info["length_m"]
    assert r.zones[0].start == 0 and r.zones[-1].end == pytest.approx(total)
    for z1, z2 in zip(r.zones, r.zones[1:]):
        assert z1.end == z2.start and len(z2.boundary) == 1
    for z in r.zones:
        assert z.stats["max_abs_ppm"] <= 20 and z.projection.type == "tmerc"
        # каждая зона проверена на всей своей части трассы
        S = r._samples.subset((r._samples.s >= z.start) & (r._samples.s <= z.end))
        assert np.abs(z.projection.distortion(S.B, S.L, S.h)).max() <= 20
    # Длиннее — больше зон; жадное деление выравнивается до равных зон.
    r3 = ldp.design(route_ew(260.0), ldp.Heights(constant=200.0), type="tm")
    assert len(r3.zones) == 3 and all(z.stats["max_abs_ppm"] <= 20 for z in r3.zones)
    # auto: косая проекция Меркатора вдоль трассы укладывается одной зоной, зоны TM — запасной вариант.
    a = ldp.design(c, ldp.Heights(constant=200.0))
    assert a.projection.type == "omerc" and a.fits and a.stats["max_abs_ppm"] < 2
    assert abs(abs(a.projection.alpha) - 90) < 0.1 and a.alternatives[0][0].type == "tmerc"
    assert len(a.zones) == 2
    S = a._samples
    k = np.asarray(Proj(a.projection.proj).get_factors(S.L, S.B).meridional_scale)
    assert np.abs((k * ldp.height_factor(a.projection.ellipsoid, S.B, S.h) - 1) * 1e6).max() == \
        pytest.approx(a.stats["max_abs_ppm"], abs=1e-4)


def test_oblique_route_omerc():
    aux = datums.TransverseMercator("gsk2011", 40.0, 56.0)
    t = np.linspace(-60e3, 60e3, 5)
    B, L = aux.inverse(t * math.cos(math.radians(40)), t * math.sin(math.radians(40)))   # азимут 40°
    r = ldp.design(ldp.Contour("polyline", B, L), ldp.Heights(constant=150.0), type="omerc")
    assert r.fits and r.stats["max_abs_ppm"] < 2 and abs(r.projection.alpha - 40) < 1


def test_criteria():
    c = square(half=25e3)
    mm = ldp.design(c, ldp.Heights(constant=300.0), options=ldp.FitOptions(round_k0=0, round_angle=0))
    rms = ldp.design(c, ldp.Heights(constant=300.0), criterion="rms", options=ldp.FitOptions(round_k0=0, round_angle=0))
    assert rms.stats["rms_ppm"] < mm.stats["rms_ppm"] and rms.stats["max_abs_ppm"] > mm.stats["max_abs_ppm"]
    # минимакс: экстремумы симметричны
    assert mm.stats["max_ppm"] == pytest.approx(-mm.stats["min_ppm"], abs=1e-6)
    assert abs(rms.stats["mean_ppm"]) < 0.5
    fixed = ldp.design(c, ldp.Heights(constant=300.0), options=ldp.FitOptions(lon0=38.5, k0=1.0))
    assert fixed.projection.lon0 == 38.5 and fixed.projection.k0 == 1.0


def test_central_meridian_compensates_slope():
    """Узкая полоса N–S, рельеф поднимается на восток: L0 уходит на запад, рост масштаба TM гасит высоту."""
    aux = datums.TransverseMercator("gsk2011", 38.0, 55.0)
    B, L = aux.inverse(np.array([-15e3, -15e3, 15e3, 15e3]), np.array([-2e3, 2e3, 2e3, -2e3]))
    c = ldp.Contour("polygon", B, L)
    la, lo = np.arange(54.7, 55.31, 0.02), np.arange(37.8, 38.21, 0.01)
    dem = GeoidGrid(54.7, 37.8, 0.02, 0.01, 1595.0 * (lo[None, :] - 37.8) + 0 * la[:, None], "ramp")  # 100 м на 4 км
    opt = dict(round_k0=0, round_angle=0)
    r = ldp.design(c, ldp.Heights(dem=dem), options=ldp.FitOptions(**opt))
    centered = ldp.design(c, ldp.Heights(dem=dem), options=ldp.FitOptions(lon0=38.0, **opt))
    # По центру — только k0: ±7.8 ppm (100 м = 15.7 ppm). Сдвиг L0 гасит наклон; остаток ±2.1 ppm — от сходимости
    # меридианов (на 30 км по северу y меняется на ~1 км).
    assert centered.stats["max_abs_ppm"] > 7.5 and r.stats["max_abs_ppm"] < 2.5
    # Наклон 100 м на 4 км: y·dy/R² = dh/R → осевой меридиан в y ≈ R·dh/dx ≈ 160 км западнее.
    y = (38.0 - r.projection.lon0) * math.pi / 180 * 6.38e6 * math.cos(math.radians(55))
    assert y == pytest.approx(160e3, rel=0.05)


def test_heights_dem_geoid_and_vertex(tmp_path):
    c = square(half=5e3)
    lat, lon = c.B, c.L
    # DEM: наклонная плоскость нормальных высот; геоид: N = 15 м.
    la, lo = np.arange(55.3, 55.71, 0.01), np.arange(37.8, 38.21, 0.01)
    H = 300 + 200 * (lo[None, :] - 38.0) + 0 * la[:, None]
    GeoidGrid(55.3, 37.8, 0.01, 0.01, H, "dem").save(tmp_path / "dem.gtx")
    GeoidGrid(55.3, 37.8, 0.01, 0.01, np.full_like(H, 15.0), "n").save(tmp_path / "n.gtx")
    r = ldp.design(c, ldp.Heights(dem=tmp_path / "dem.gtx", geoid=tmp_path / "n.gtx", height_type="normal"))
    S = r._samples
    assert np.allclose(S.h, 300 + 200 * (S.L - 38.0) + 15, atol=1e-6)
    assert r.object_info["height_source"] == "сетка рельефа" and not r.warnings
    r0 = ldp.design(c, ldp.Heights(dem=tmp_path / "dem.gtx", height_type="normal"))
    assert any("N = 0" in w for w in r0.warnings)
    # Высоты вершин: в вершине — она сама, внутри — между мин и макс.
    cz = ldp.Contour("polygon", lat, lon, z=np.array([100.0, 200.0, 300.0, 400.0]), z_type="ellipsoidal")
    rz = ldp.design(cz, ldp.Heights(constant=0.0))
    assert 100 <= rz._samples.h.min() and rz._samples.h.max() <= 400
    assert rz.object_info["h_min"] == pytest.approx(100.0) and rz.object_info["h_max"] == pytest.approx(400.0)
    with pytest.raises(ldp.LdpError):
        ldp.design(c, ldp.Heights())


def test_unreachable_height_range():
    aux = datums.TransverseMercator("gsk2011", 38.0, 55.0)
    B, L = aux.inverse(np.array([-3e3, -3e3, 3e3, 3e3]), np.array([-3e3, 3e3, 3e3, -3e3]))
    c = ldp.Contour("polygon", B, L, z=np.array([0.0, 0.0, 600.0, 600.0]), z_type="ellipsoidal")   # перепад N–S
    r = ldp.design(c, ldp.Heights(), tolerance=20)
    assert not r.fits and any("Перепад высот" in w for w in r.warnings)
    assert not r.zones and any("недостижим" in w for w in r.warnings)


def test_contour_readers(tmp_path):
    (tmp_path / "a.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "LineString", "coordinates": [[37, 55, 150], [38, 55.1, 160]]}}]}))
    c = ldp.read_contour(tmp_path / "a.geojson")
    assert c.kind == "polyline" and list(c.z) == [150, 160] and c.B[1] == 55.1
    c = ldp.read_contour(ROOT / "examples/ldp_site.csv")
    assert c.kind == "polygon" and len(c.B) == 6 and c.z_type == "ellipsoidal"
    c = ldp.read_contour(ROOT / "examples/ldp_route.csv")
    assert c.kind == "polyline" and c.z_type == "normal"
    assert ldp.read_contour(ROOT / "examples/ldp_route.csv", kind="polygon").kind == "polygon"


def test_json_and_load_projection(tmp_path):
    r = ldp.design(route_ew(), ldp.Heights(constant=200.0), type="tm")
    r.save(tmp_path / "r.json")
    d = json.loads((tmp_path / "r.json").read_text())
    assert d["format"] == "mathdatum-ldp" and d["version"] == 1 and len(d["zones"]) == 2
    with pytest.raises(ldp.LdpError, match="зону"):
        ldp.load_projection(tmp_path / "r.json")
    z2 = ldp.load_projection(tmp_path / "r.json", zone=2)
    assert z2 == r.zones[1].projection
    # Без необязательных полей и с лишними — читается.
    bare = {"type": "tmerc", "lat0": 55.0, "lon0": 38.0, "k0": 1.00002, "future_field": 1}
    p = ldp.load_projection(bare)
    assert p.x0 == 0 and p.datum == "GSK-2011"
    s = ldp.design(square(), ldp.Heights(constant=500.0))
    assert ldp.load_projection(s.to_dict()) == s.projection


def test_distortion_map(tmp_path):
    r = ldp.design(route_ew(), ldp.Heights(constant=200.0), type="tm")
    m = r.distortion_map(40)
    assert m.ppm.shape[1] == 40 and set(np.unique(m.zone)) == {1, 2}
    j, i = 2, 7
    z = r.zones[m.zone[j, i] - 1].projection
    assert m.ppm[j, i] == pytest.approx(float(z.distortion(m.B[j, i], m.L[j, i], m.h[j, i])), abs=1e-9)
    near = m.dist < 5000
    assert near.any() and np.abs(m.ppm[near]).max() <= 21
    m.to_csv(tmp_path / "m.csv")
    m.to_geojson(tmp_path / "m.geojson")
    g = json.loads((tmp_path / "m.geojson").read_text())
    roles = [f["properties"]["role"] for f in g["features"]]
    assert roles[0] == "object" and "zone_boundary" in roles and "isoline" in roles
    # Вершины изолинии 0 ppm одной зоны: δ ≈ 0 (линейная интерполяция по ребру сетки).
    site = ldp.design(square(), ldp.Heights(constant=500.0), options=ldp.FitOptions(round_k0=0))
    sm = site.distortion_map(50)
    lines = sm.isolines(0.0)
    assert lines and all(len(ln) >= 2 for ln in lines)
    pts = np.array([p for ln in lines for p in ln])
    d0 = site.projection.distortion(pts[:, 1], pts[:, 0], 500.0)
    assert np.abs(d0).max() < 0.05
    rows = (tmp_path / "m.csv").read_text().splitlines()
    assert rows[0] == "row;col;B;L;h;zone;k;height_factor;ppm;dist_m" and len(rows) == m.ppm.size + 1


# --- интеграция с localize ---

def ground_pairs(site_B=55.5, site_L=38.0, h0=500.0, n=8, el="gsk2011"):
    """Опорные пункты и местные координаты «плоскость = местность»: топоцентрические E, N на высоте участка,
    развёрнутые на 0.3° и сдвинутые; H — по нормали (u) + 480 м."""
    aux = datums.TransverseMercator(el, site_L, site_B)
    rng = np.random.default_rng(7)
    B, L = aux.inverse(rng.uniform(-9e3, 9e3, n), rng.uniform(-9e3, 9e3, n))
    h = h0 + rng.uniform(-5, 5, n)
    X, Y, Z = datums.blh_to_xyz(B, L, h, el)
    X0, Y0, Z0 = datums.blh_to_xyz(site_B, site_L, h0, el)
    b, l = math.radians(site_B), math.radians(site_L)
    dx, dy, dz = X - X0, Y - Y0, Z - Z0
    e = -math.sin(l) * dx + math.cos(l) * dy
    nn = -math.sin(b) * math.cos(l) * dx - math.sin(b) * math.sin(l) * dy + math.cos(b) * dz
    u = math.cos(b) * math.cos(l) * dx + math.cos(b) * math.sin(l) * dy + math.sin(b) * dz
    t = math.radians(0.3)
    x, y = 5000 + nn * math.cos(t) - e * math.sin(t), 7000 + nn * math.sin(t) + e * math.cos(t)
    return [Pair(f"P{i}", B[i], L[i], h[i], x[i], y[i], u[i] + 480) for i in range(n)]


def test_localize_with_ldp_keeps_scale_one(tmp_path):
    pairs = ground_pairs()
    r = ldp.design(square(), ldp.Heights(constant=500.0))
    d0 = localize(pairs, gnss_datum="GSK-2011")
    d1 = localize(pairs, gnss_datum="GSK-2011", projection=r.projection)
    assert d0.scale_ppm == pytest.approx(78, abs=2)           # рабочая TM k = 1 на высоте 500 м
    assert abs(d1.scale_ppm) < 1.0                            # LDP: план = местность
    assert d1.rms_plan == pytest.approx(d0.rms_plan, abs=2e-4)
    assert (d1.k0, d1.x0, d1.y0) == (r.projection.k0, r.projection.x0, r.projection.y0)
    p = pairs[3]
    x, y, H = d1.to_local(p.B, p.L, p.h)
    B, L, h = d1.to_wgs(x, y, H)
    assert abs(B - p.B) < 1e-10 and abs(L - p.L) < 1e-10 and abs(h - p.h) < 1e-6
    # JSON туда-обратно, строка PROJ = to_local.
    d1.save(tmp_path / "d.json")
    d2 = LocalizationDatum.load(tmp_path / "d.json")
    assert d2.k0 == d1.k0 and d2.to_local(p.B, p.L, p.h) == pytest.approx((x, y, H), abs=1e-9)
    t = Transformer.from_pipeline(d1.to_proj_pipeline())
    assert t.transform(p.B, p.L, p.h) == pytest.approx((x, y, H), abs=1e-6)
    assert "+k=1.000078" in d1.projection and "+x_0=100000" in d1.projection
    # Без projection — прежняя строка (обратная совместимость), старый JSON без k0 читается как k0 = 1.
    assert "+k=1 +x_0=0 +y_0=0" in d0.projection
    old = LocalizationDatum.load(ROOT / "tests/data/datum_old_format.json")
    assert (old.k0, old.x0, old.y0) == (1.0, 0.0, 0.0)
    with pytest.raises(ldp.LdpError):
        localize(pairs, projection=ldp.LdpProjection("omerc", "GSK-2011", 55.5, 38.0, 1.0, alpha=10.0))


def test_cli_ldp_and_localize(tmp_path, capsys):
    out, mcsv, mgj = tmp_path / "ldp.json", tmp_path / "m.csv", tmp_path / "m.geojson"
    assert main(["ldp", str(ROOT / "examples/ldp_site.csv"), "-o", str(out), "--map", str(mcsv),
                 "--map", str(mgj), "--map-size", "30"]) == 0
    text = capsys.readouterr().out
    assert "укладывается в допуск" in text and "ГК 6°" in text and "UTM" in text
    assert json.loads(out.read_text())["fits_tolerance"] and mcsv.exists() and mgj.exists()
    assert main(["ldp", str(ROOT / "examples/ldp_route.csv"), "-o", str(tmp_path / "route.json"), "--type", "tm"]) == 0
    text = capsys.readouterr().out
    assert "Предлагается 2 зон" in text and "N = 0" in text
    pairs_csv = tmp_path / "pairs.csv"
    pairs_csv.write_text("name;B;L;h;x;y;H\n" + "".join(
        f"{p.name};{p.B:.10f};{p.L:.10f};{p.h:.4f};{p.x:.4f};{p.y:.4f};{p.H:.4f}\n"
        for p in ground_pairs(55.08, 39.27, 220.0)))
    assert main(["localize", str(pairs_csv), "-o", str(tmp_path / "d.json"), "--gnss-datum", "GSK-2011",
                 "--projection", str(out)]) == 0
    text = capsys.readouterr().out
    assert "Рабочая проекция задана" in text
    d = LocalizationDatum.load(tmp_path / "d.json")
    assert abs(d.scale_ppm) < 2 and d.k0 != 1.0
    assert main(["localize", str(pairs_csv), "-o", str(tmp_path / "d2.json"), "--projection",
                 str(tmp_path / "route.json")]) == 1
    assert "укажите зону" in capsys.readouterr().err
    assert main(["localize", str(pairs_csv), "-o", str(tmp_path / "d3.json"), "--projection",
                 "tm:lon0=39.27,lat0=55.08,k0=1.0000345,x0=20000,y0=100000"]) == 0
    assert LocalizationDatum.load(tmp_path / "d3.json").k0 == 1.0000345
