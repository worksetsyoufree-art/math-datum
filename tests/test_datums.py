"""Пересчёты между государственными системами (mathdatum.datums) и датум ГНСС в локализации."""

import itertools
import json
import math
from pathlib import Path

import numpy as np
import pytest
from pyproj import Transformer

from mathdatum import LocalizationDatum, Pair, datums, localize
from mathdatum.__main__ import main as cli
from mathdatum.datums import (ELLIPSOIDS, SYSTEMS, TRANSFORMATIONS, TransverseMercator, blh_to_xyz, find_path,
                              gk_forward, gk_inverse, gk_zone, helmert_forward, helmert_inverse, transform_blh,
                              transform_xyz, xyz_to_blh)

ROOT = Path(__file__).resolve().parents[1]
GEO = ROOT / "data/geodetic"
REGIONS = sorted((GEO / "regions").glob("*.json"))
RNG = np.random.default_rng(32453)
# Точки по территории РФ: B 41…78°, L 19…190°, h −100…3000 м.
PTS_BLH = np.column_stack([RNG.uniform(41, 78, 40), RNG.uniform(19, 190, 40), RNG.uniform(-100, 3000, 40)])


def proj_helmert(p):
    return Transformer.from_pipeline(
        f"+proj=helmert +x={p.dX} +y={p.dY} +z={p.dZ} +rx={p.wx} +ry={p.wy} +rz={p.wz} +s={p.m} "
        "+convention=coordinate_frame")


def test_parameters_match_data_file():
    """Константы модуля = data/geodetic/gost_32453_parameters.json (текст ГОСТ)."""
    data = json.loads((GEO / "gost_32453_parameters.json").read_text(encoding="utf-8"))
    names = {s.name.split(" (")[0]: s.id for s in SYSTEMS.values()}
    names["WGS-84"] = "WGS-84"
    assert len(data["transformations"]) == len(TRANSFORMATIONS)
    for t, p in zip(data["transformations"], TRANSFORMATIONS):
        assert names[t["from"].split(" (")[0]] == p.src and names[t["to"]] == p.dst
        assert t["appendix"] == p.source and t.get("epoch") == p.epoch
        assert [t[k] for k in ("dX", "dY", "dZ", "wx", "wy", "wz", "m")] == [p.dX, p.dY, p.dZ, p.wx, p.wy, p.wz, p.m]
    el = data["ellipsoids"]
    assert (el["Красовского (СК-42, СК-95)"]["a"], el["Красовского (СК-42, СК-95)"]["rf"]) == (6378245, 298.3)
    for key, e in (("ПЗ-90 / ПЗ-90.11", ELLIPSOIDS["pz90"]), ("ГСК-2011", ELLIPSOIDS["gsk2011"]),
                   ("WGS-84", ELLIPSOIDS["wgs84"]), ("Красовского (СК-42, СК-95)", ELLIPSOIDS["krass"])):
        assert (el[key]["a"], el[key]["rf"]) == (e.a, e.rf)


def test_parameters_are_composition_with_b1():
    """Наборы А.1, А.3, В.1, Г.1 = ГОСТ Р 51794-2008 (→ ПЗ-90.02) + Б.1 (малые параметры складываются).
    Отсюда знак ωy = +0.00354″ у СК-95 (в исходном файле данных был ошибочно −0.00354″)."""
    b1 = next(t for t in TRANSFORMATIONS if t.source == "Б.1")
    r51794 = {"SK-42": (23.93, -141.03, -79.98, 0, -0.35, -0.79, -0.22),
              "SK-95": (24.83, -130.97, -81.74, 0, 0, -0.13, -0.22),
              "PZ-90": (-1.07, -0.03, 0.02, 0, 0, -0.13, -0.22),
              "WGS-84": (0.36, -0.08, -0.18, 0, 0, 0, 0)}
    keys = ("dX", "dY", "dZ", "wx", "wy", "wz", "m")
    for src, v in r51794.items():
        t = next(t for t in TRANSFORMATIONS if t.src == src)
        assert [getattr(t, k) for k in keys] == pytest.approx([a + getattr(b1, k) for a, k in zip(v, keys)], abs=1e-9)


def test_system_lookup():
    assert datums.get_system("СК-42").id == "SK-42"
    assert datums.get_system("ск42").id == "SK-42"
    assert datums.get_system("ПЗ-90.11").id == "PZ-90.11"
    assert datums.get_system("WGS-84 (G1150)").id == "WGS-84"
    assert datums.get_system("ITRF2008").id == "ITRF-2008"
    assert datums.get_system("гск-2011").ellipsoid is ELLIPSOIDS["gsk2011"]
    with pytest.raises(ValueError):
        datums.get_system("SK-63")


def test_gost_control_example():
    """ГОСТ 32453-2017, прил. Е (пункт Менделеево): все три шага."""
    s = json.loads((GEO / "gost_32453_control_example.json").read_text(encoding="utf-8"))["steps"]
    x0, v = s["input_itrf2008_epoch_2005"]["xyz"], s["input_itrf2008_epoch_2005"]["velocity"]
    # Шаг 1: перенос эпохи 2005 → 2010 (эпоха параметров Д.1).
    assert np.abs(datums.propagate_epoch(x0, v, 2005.0, 2010.0) - s["itrf2008_epoch_2010"]["xyz"]).max() < 1e-6
    # Шаг 2: ITRF-2008 → ПЗ-90.11 по обратным параметрам Д.1 (значения ГОСТ — до 0.1 мм).
    x2 = transform_xyz(x0, "ITRF-2008", "PZ-90.11", epoch=2005.0, velocity=v)
    assert np.abs(x2 - s["pz9011_epoch_2010"]["xyz"]).max() < 5e-5
    # То же напрямую от эпохи 2010.
    x2b = transform_xyz(s["itrf2008_epoch_2010"]["xyz"], "ITRF-2008", "PZ-90.11")
    assert np.abs(x2b - s["pz9011_epoch_2010"]["xyz"]).max() < 5e-5
    # Шаг 3: перенос эпохи 2010 → 2013.9 той же скоростью (значения ГОСТ — до 1 мм).
    x3 = transform_xyz(x0, "ITRF-2008", "PZ-90.11", epoch=2005.0, velocity=v, target_epoch=2013.9)
    assert np.abs(x3 - s["pz9011_epoch_2013_9"]["xyz"]).max() < 5e-4
    # В обратную сторону: ПЗ-90.11 эпохи 2013.9 → ITRF-2008 эпохи 2005.
    back = transform_xyz(x3, "PZ-90.11", "ITRF-2008", epoch=2013.9, velocity=v, target_epoch=2005.0)
    assert np.abs(back - x0).max() < 1e-8
    with pytest.raises(ValueError):
        transform_xyz(x0, "ITRF-2008", "PZ-90.11", velocity=v)


def test_epoch_ignored_without_velocity():
    x = np.array([2845456.0, 2160954.0, 5265993.0])
    assert np.array_equal(transform_xyz(x, "ITRF-2008", "PZ-90.11", epoch=2005.0),
                          transform_xyz(x, "ITRF-2008", "PZ-90.11"))


def test_paths():
    assert [(s.src, s.dst) for s in find_path("SK-42", "WGS-84")] == [("SK-42", "PZ-90.11"), ("PZ-90.11", "WGS-84")]
    assert [s.forward for s in find_path("SK-42", "WGS-84")] == [True, False]
    assert len(find_path("ITRF-2008", "SK-95")) == 2
    assert find_path("PZ-90.11", "ПЗ-90.11") == []
    assert datums.describe_path(find_path("СК-42", "WGS-84")) == \
        "СК-42 → ПЗ-90.11 → WGS-84 (G1150) (прил. А.1; Г.1, обратный)"
    for a, b in itertools.permutations(SYSTEMS, 2):
        p = find_path(a, b)
        assert p[0].src == a and p[-1].dst == b and len(p) <= 2


@pytest.mark.parametrize("ell", list(ELLIPSOIDS))
def test_blh_xyz_matches_proj(ell):
    e = ELLIPSOIDS[ell]
    B = np.concatenate([PTS_BLH[:, 0], [0.0, 89.9999, -45.0, 89.0]])
    L = np.concatenate([PTS_BLH[:, 1], [0.0, 10.0, -170.0, 180.0]])
    h = np.concatenate([PTS_BLH[:, 2], [0.0, 5000.0, -400.0, 20000.0]])
    X, Y, Z = blh_to_xyz(B, L, h, e)
    ref = Transformer.from_pipeline(f"+proj=cart {e.proj}")
    Xr, Yr, Zr = ref.transform(L, B, h)
    assert max(np.abs(X - Xr).max(), np.abs(Y - Yr).max(), np.abs(Z - Zr).max()) < 1e-6
    B2, L2, h2 = xyz_to_blh(X, Y, Z, e)
    assert np.abs(B2 - B).max() < 1e-11 and np.abs(h2 - h).max() < 1e-6
    dl = np.abs((L2 - L + 180) % 360 - 180)
    assert dl[np.abs(B) < 89.99].max() < 1e-11


@pytest.mark.parametrize("t", TRANSFORMATIONS, ids=lambda t: t.source)
def test_helmert_matches_proj(t):
    xyz = np.column_stack(blh_to_xyz(*PTS_BLH.T, SYSTEMS[t.src].ellipsoid))
    ref = proj_helmert(t)
    fwd = helmert_forward(xyz, t)
    assert np.abs(fwd - np.column_stack(ref.transform(*xyz.T))).max() < 1e-6
    # Обратный: PROJ обращает приближённо (Rᵀ вместо R⁻¹), расхождение ≤ |ω|²·|X| ≈ 0.1 мм.
    inv = helmert_inverse(fwd, t)
    assert np.abs(inv - xyz).max() < 1e-8
    assert np.abs(inv - np.column_stack(ref.transform(*fwd.T, direction="INVERSE"))).max() < 2e-4


def test_chains_match_proj_pipeline():
    xyz = np.column_stack(blh_to_xyz(*PTS_BLH.T, ELLIPSOIDS["krass"]))
    for dst in SYSTEMS:
        path = find_path("SK-42", dst)
        if not path:
            continue
        steps = "".join(
            f" +step {'' if s.forward else '+inv '}+proj=helmert +x={s.params.dX} +y={s.params.dY} +z={s.params.dZ} "
            f"+rx={s.params.wx} +ry={s.params.wy} +rz={s.params.wz} +s={s.params.m} +convention=coordinate_frame"
            for s in path)
        ref = np.column_stack(Transformer.from_pipeline("+proj=pipeline" + steps).transform(*xyz.T))
        tol = 1e-6 if all(s.forward for s in path) else 2e-4
        assert np.abs(transform_xyz(xyz, "SK-42", dst) - ref).max() < tol, dst


@pytest.mark.parametrize("src,dst", list(itertools.permutations(SYSTEMS, 2)))
def test_round_trip_all_pairs(src, dst):
    """Туда-обратно по всем парам систем: XYZ < 1e-8 м, BLH < 0.1 мм (по факту ~1e-9 м)."""
    xyz = np.column_stack(blh_to_xyz(*PTS_BLH.T, SYSTEMS[src].ellipsoid))
    back = transform_xyz(transform_xyz(xyz, src, dst), dst, src)
    assert np.abs(back - xyz).max() < 1e-8
    B, L, h = transform_blh(*transform_blh(*PTS_BLH.T, src, dst), dst, src)
    d = np.column_stack(blh_to_xyz(B, L, h, SYSTEMS[src].ellipsoid)) - xyz
    assert np.abs(d).max() < 1e-4


def test_scalar_inputs():
    B, L, h = transform_blh(55.7, 37.6, 180.0, "SK-42", "WGS-84")
    assert np.ndim(B) == 0 and 55.70 < B < 55.71
    assert transform_xyz([2.8e6, 2.2e6, 5.2e6], "SK-42", "PZ-90.11").shape == (3,)


@pytest.mark.parametrize("path", REGIONS, ids=lambda p: p.stem)
def test_regions_helmert_7p(path):
    """Задачи helmert_7p из 83 регионов: BLH Красовского → XYZ и СК-42 → ПЗ-90.11 по ГОСТ."""
    case = json.loads(path.read_text(encoding="utf-8"))
    for task in (t for t in case["tasks"] if t["type"] == "helmert_7p"):
        blh = np.array(task["source_geodetic_B_L_H"])
        src, dst = np.array(task["source_xyz"]), np.array(task["target_xyz"])
        # B, L хранятся до 1e-9° (≤ 0.06 мм), XYZ — до 0.1 мм.
        assert np.abs(np.column_stack(blh_to_xyz(*blh.T, "SK-42")) - src).max() < 2e-4
        e = task["expected"]["parameters"]
        p = next(t for t in TRANSFORMATIONS if t.src == "SK-42")
        assert [e[k] for k in ("dX", "dY", "dZ", "wx", "wy", "wz", "m")] == [p.dX, p.dY, p.dZ, p.wx, p.wy, p.wz, p.m]
        v = dst - transform_xyz(src, "SK-42", "PZ-90.11")
        if task["variant"] == "exact":
            assert np.abs(v).max() < 1e-4
        else:
            assert math.sqrt(np.mean(v ** 2)) == pytest.approx(task["expected"]["rms_residual_m"], abs=2e-4)
        # Обратно: ПЗ-90.11 → СК-42 → B, L, H.
        B, L, H = xyz_to_blh(*transform_xyz(dst, "PZ-90.11", "SK-42").T, "SK-42")
        if task["variant"] == "exact":
            assert np.abs(B - blh[:, 0]).max() < 3e-9 and np.abs(H - blh[:, 2]).max() < 2e-4


# --- Гаусс–Крюгер и поперечный Меркатор ---

def test_gk_zone():
    assert list(gk_zone([0.0, 5.999, 6.0, 37.6, 39.0, 179.9, 180.0, 190.0, -10.0])) == [1, 1, 2, 7, 7, 30, 31, 32, 59]
    assert datums.gk_projection(7).lon0 == 39.0 and datums.gk_projection(7).y0 == 7_500_000.0
    with pytest.raises(ValueError):
        datums.gk_projection(61)


@pytest.mark.parametrize("ell", ["krass", "gsk2011"])
def test_gk_matches_proj(ell):
    e = ELLIPSOIDS[ell]
    B, L = PTS_BLH[:, 0], PTS_BLH[:, 1] % 360
    x, y = gk_forward(B, L, e)
    for z in np.unique(gk_zone(L)):
        m = gk_zone(L) == z
        ref = Transformer.from_pipeline(
            f"+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step +proj=tmerc +lat_0=0 "
            f"+lon_0={6 * z - 3} +k=1 +x_0={z * 1e6 + 5e5} +y_0=0 {e.proj} +units=m")
        E, N = ref.transform(L[m], B[m])
        assert np.abs(x[m] - N).max() < 1e-6 and np.abs(y[m] - E).max() < 1e-6
        assert np.all(np.floor(y[m] / 1e6) == z)
    B2, L2 = gk_inverse(x, y, e)
    assert np.abs(B2 - B).max() < 1e-10 and np.abs(L2 - L).max() < 1e-10
    # Принудительная соседняя зона (перекрытие зон) и EPSG:28407 (Pulkovo 1942 / Gauss-Kruger zone 7).
    xa, ya = gk_forward(55.7, 42.5, e, zone=7)
    assert gk_inverse(xa, ya, e, zone=7) == pytest.approx((55.7, 42.5), abs=1e-10)
    with pytest.raises(ValueError):
        gk_inverse(xa, ya, e, zone=8)
    if ell == "krass":
        E, N = Transformer.from_crs("EPSG:4284", "EPSG:28407", always_xy=True).transform(37.6, 55.7)
        assert gk_forward(55.7, 37.6) == pytest.approx((N, E), abs=1e-6)


def test_custom_tm_matches_proj():
    """«МСК-подобная» система: свой осевой меридиан, масштаб, широта начала и ложные смещения."""
    for ell, lon0, lat0, k0, x0, y0 in (("krass", 38.48333, 0.0, 1.0, -5_712_900.566, 1_250_000.0),
                                        ("krass", 44.55, 0.0, 1.0, -4_511_143.71, 2_300_000.0),
                                        ("pz90", 131.9, 43.1, 0.9996, 100.0, 500_000.0),
                                        ("wgs84", 39.0, 55.0, 1.0002, 0.0, 0.0)):
        tm = TransverseMercator(ell, lon0, lat0, k0, x0, y0)
        B, L = lat0 + RNG.uniform(-2, 2, 30) + (55 if lat0 == 0 else 0), lon0 + RNG.uniform(-3, 3, 30)
        x, y = tm.forward(B, L)
        ref = Transformer.from_pipeline(f"+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step {tm.proj}")
        E, N = ref.transform(L, B)
        assert np.abs(x - N).max() < 1e-6 and np.abs(y - E).max() < 1e-6
        B2, L2 = tm.inverse(x, y)
        assert np.abs(B2 - B).max() < 1e-10 and np.abs(L2 - L).max() < 1e-10


def test_working_projection_same_as_pyproj():
    """Своя проекция совпадает с рабочей проекцией локализации (pyproj) до 1e-6 м."""
    d = localize([Pair("A", 55.0, 37.0, 100, 0, 0, 0), Pair("B", 55.05, 37.1, 100, 5560, 6370, 0)])
    E, N = d._proj().transform(37.07, 55.03)
    x, y = TransverseMercator("wgs84", d.lon0, d.lat0).forward(55.03, 37.07)
    assert (x, y) == pytest.approx((N, E), abs=1e-6)


# --- датум ГНСС в локализации ---

def site(path):
    case = json.loads(path.read_text(encoding="utf-8"))
    return next(t for t in case["tasks"] if t["type"] == "site_localization")


def test_default_gnss_datum_unchanged():
    from mathdatum import read_pairs
    pairs = read_pairs(ROOT / "examples/pairs.csv")
    d = localize(pairs)
    assert d.gnss_datum == "WGS-84" and d.ellipsoid == "+ellps=WGS84"
    old = LocalizationDatum.load(ROOT / "examples/datum.json")
    for k in ("lat0", "lon0", "Nc", "Ec", "a", "b", "tx", "ty", "c0", "c1", "c2", "rms_plan", "rms_height"):
        assert getattr(d, k) == getattr(old, k), k
    assert localize(pairs, ellipsoid="+ellps=WGS84", gnss_datum="WGS 84") == d


@pytest.mark.parametrize("path", REGIONS[::8], ids=lambda p: p.stem)
def test_regions_with_pz9011_datum(path):
    """ГНСС-координаты датасетов — в ПЗ-90.11: gnss_datum даёт рабочую проекцию эталона без ellipsoid."""
    s = site(path)
    e = s["expected"]
    proj = dict(kv.lstrip("+").split("=", 1) for kv in s["working_projection"].split() if "=" in kv)
    pairs = [Pair(p["id"], *p["gnss_B_L_h"], *p["local_x_y_H"]) for p in s["control_points"]]
    d = localize(pairs, lat0=0.0, lon0=float(proj["lon_0"]), gnss_datum="ПЗ-90.11")
    assert d.gnss_datum == "PZ-90.11" and d.ellipsoid == "+a=6378136 +rf=298.25784"
    assert (d.a, d.b) == pytest.approx((e["a"], e["b"]), abs=1e-7)
    assert (d.tx, d.ty) == pytest.approx((e["tx"], e["ty"]), abs=2e-4)


@pytest.mark.parametrize("path", REGIONS[::8], ids=lambda p: p.stem)
def test_datum_choice_does_not_matter_on_site(path):
    """Обоснование выбора: локализация на эллипсоиде системы измерений и в другой системе
    (после пересчёта по ГОСТ) дают на участке 5 км одно и то же: СК-42 — ≤ 2 мм, WGS-84 и ГСК-2011 — ≤ 0.01 мм."""
    s = site(path)
    c = np.array([p["gnss_B_L_h"] for p in s["control_points"]])
    loc = [p["local_x_y_H"] for p in s["control_points"]]
    k = np.array([p["gnss_B_L_h"] for p in s["check_points"]])
    d0 = localize([Pair(f"R{i}", *b, *l) for i, (b, l) in enumerate(zip(c, loc))], gnss_datum="PZ-90.11")
    p0 = np.column_stack(d0.to_local(*k.T))
    for system, tol in (("SK-42", 2e-3), ("WGS-84", 1e-5), ("GSK-2011", 1e-5)):
        cc = np.column_stack(transform_blh(*c.T, "PZ-90.11", system))
        d = localize([Pair(f"R{i}", *b, *l) for i, (b, l) in enumerate(zip(cc, loc))], gnss_datum=system)
        assert d.gnss_datum == system
        # Точки в ПЗ-90.11 подаются в датум другой системы: пересчёт внутри to_local.
        assert np.abs(np.column_stack(d.to_local(*k.T, datum="PZ-90.11")) - p0).max() < tol
        B, L, h = d.to_wgs(*p0.T, datum="PZ-90.11")
        assert np.abs(np.column_stack(d0.to_local(B, L, h)) - p0).max() < tol


def test_to_local_with_other_datum_and_json(tmp_path):
    from mathdatum import read_pairs
    d = localize(read_pairs(ROOT / "examples/pairs.csv"))
    B, L, h = 55.07, 39.3, 200.0
    Bp, Lp, hp = transform_blh(B, L, h, "WGS-84", "PZ-90.11")
    assert d.to_local(Bp, Lp, hp, datum="PZ-90.11") == pytest.approx(d.to_local(B, L, h), abs=1e-6)
    assert d.to_wgs(*d.to_local(B, L, h), datum="PZ-90.11") == pytest.approx((Bp, Lp, hp), abs=1e-9)
    assert d.to_local(B, L, h, datum="WGS-84") == d.to_local(B, L, h)
    d.save(tmp_path / "d.json")
    assert json.loads((tmp_path / "d.json").read_text())["gnss_datum"] == "WGS-84"
    assert LocalizationDatum.load(tmp_path / "d.json") == d
    # Старый JSON: поля нет → None; на WGS-84 считается WGS-84, пересчёт из других систем работает.
    old = LocalizationDatum.load(ROOT / "tests/data/datum_old_format.json")
    assert old.gnss_datum is None and old.gnss_system == "WGS-84"
    assert old.to_local(Bp, Lp, hp, datum="PZ-90.11") == pytest.approx(old.to_local(B, L, h), abs=1e-6)
    # Старый JSON с другим эллипсоидом: система неизвестна — пересчёт из другой системы невозможен.
    raw = json.loads((ROOT / "tests/data/datum_old_format.json").read_text())
    raw["ellipsoid"] = "+ellps=krass"
    (tmp_path / "k.json").write_text(json.dumps(raw))
    k = LocalizationDatum.load(tmp_path / "k.json")
    assert k.gnss_system is None
    k.to_local(B, L, h)
    with pytest.raises(ValueError):
        k.to_local(B, L, h, datum="WGS-84")


# --- командная строка ---

def test_cli_transform(tmp_path, capsys):
    src = tmp_path / "sk42.csv"
    blh = PTS_BLH[:8]
    src.write_text("name;B;L;h\n" + "".join(f"P{i};{b};{l};{h}\n" for i, (b, l, h) in enumerate(blh.tolist())))
    assert cli(["transform", str(src), "-o", str(tmp_path / "w.csv"), "--from", "СК-42", "--to", "WGS-84"]) == 0
    assert "СК-42 → ПЗ-90.11 → WGS-84 (G1150)" in capsys.readouterr().err
    rows = [r.split(";") for r in (tmp_path / "w.csv").read_text().splitlines()]
    assert rows[0] == ["name", "B", "L", "h"]
    ref = np.column_stack(transform_blh(*blh.T, "SK-42", "WGS-84"))
    assert np.abs(np.array(rows[1:])[:, 1:].astype(float) - ref).max() < 1e-4
    # WGS-84 → ГК (зоны 6°) СК-42 → обратно в BLH СК-42 → XYZ.
    assert cli(["transform", str(tmp_path / "w.csv"), "-o", str(tmp_path / "gk.csv"), "--from", "WGS-84",
                "--to", "SK-42", "--out-format", "gk"]) == 0
    assert cli(["transform", str(tmp_path / "gk.csv"), "-o", str(tmp_path / "b.csv"), "--from", "SK-42",
                "--to", "SK-42", "--in", "gk"]) == 0
    back = np.array([r.split(";")[1:] for r in (tmp_path / "b.csv").read_text().splitlines()[1:]], float)
    assert np.abs(back[:, :2] - blh[:, :2]).max() < 2e-8 and np.abs(back[:, 2] - blh[:, 2]).max() < 2e-4
    gk = np.array([r.split(";")[1:] for r in (tmp_path / "gk.csv").read_text().splitlines()[1:]], float)
    assert np.abs(gk[:, :2] - np.column_stack(gk_forward(blh[:, 0], blh[:, 1]))).max() < 2e-4
    assert cli(["transform", str(src), "-o", str(tmp_path / "x.csv"), "--from", "SK-42", "--to", "PZ-90.11",
                "--out-format", "xyz"]) == 0
    assert (tmp_path / "x.csv").read_text().splitlines()[0] == "name;X;Y;Z"
    # Свой поперечный Меркатор (МСК-подобная система).
    assert cli(["transform", str(src), "-o", str(tmp_path / "m.csv"), "--from", "SK-42", "--to", "SK-42",
                "--out-format", "tm:lon0=38.48333,x0=-5712900.566,y0=1250000"]) == 0
    m = np.array([r.split(";")[1:] for r in (tmp_path / "m.csv").read_text().splitlines()[1:]], float)
    x, y = TransverseMercator("krass", 38.48333, x0=-5712900.566, y0=1250000).forward(blh[:, 0], blh[:, 1])
    assert np.abs(m[:, 0] - x).max() < 1e-4 and np.abs(m[:, 1] - y).max() < 1e-4
    assert cli(["transform", str(src), "-o", str(tmp_path / "e.csv"), "--from", "SK-42", "--to", "XX"]) == 1
    assert cli(["transform", str(src), "-o", str(tmp_path / "e.csv"), "--from", "SK-42", "--to", "SK-95",
                "--in", "tm:k0=1"]) == 1
    assert cli(["systems"]) == 0
    assert "СК-95" in capsys.readouterr().out


def test_cli_transform_epoch(tmp_path):
    """Контрольный пример ГОСТ через командную строку: эпоха и скорости пункта."""
    s = json.loads((GEO / "gost_32453_control_example.json").read_text(encoding="utf-8"))["steps"]
    x, v = s["input_itrf2008_epoch_2005"]["xyz"], s["input_itrf2008_epoch_2005"]["velocity"]
    f = tmp_path / "mdvj.csv"
    f.write_text("name;X;Y;Z;VX;VY;VZ\nMDVJ;" + ";".join(map(str, x + v)) + "\n")
    assert cli(["transform", str(f), "-o", str(tmp_path / "o.csv"), "--from", "ITRF-2008", "--to", "PZ-90.11",
                "--in", "xyz", "--out-format", "xyz", "--epoch", "2005", "--target-epoch", "2013.9"]) == 0
    out = np.array((tmp_path / "o.csv").read_text().splitlines()[1].split(";")[1:], float)
    assert np.abs(out - s["pz9011_epoch_2013_9"]["xyz"]).max() < 5e-4
    f.write_text("name;X;Y;Z\nMDVJ;" + ";".join(map(str, x)) + "\n")
    assert cli(["transform", str(f), "-o", str(tmp_path / "o.csv"), "--from", "ITRF-2008", "--to", "PZ-90.11",
                "--in", "xyz", "--epoch", "2005"]) == 1


def test_cli_gnss_datum(tmp_path, capsys):
    s = site(REGIONS[0])
    pairs = tmp_path / "pz.csv"
    pairs.write_text("name;B;L;h;x;y;H\n" + "".join(
        f"{p['id']};{';'.join(map(repr, p['gnss_B_L_h'] + p['local_x_y_H']))}\n" for p in s["control_points"]))
    datum = tmp_path / "d.json"
    assert cli(["localize", str(pairs), "-o", str(datum), "--gnss-datum", "PZ-90.11"]) == 0
    assert "ГНСС:   ПЗ-90.11" in capsys.readouterr().out
    d = LocalizationDatum.load(datum)
    assert d.gnss_datum == "PZ-90.11" and d.ellipsoid == "+a=6378136 +rf=298.25784"
    # Контрольные точки в WGS-84: to-local пересчитывает их в ПЗ-90.11.
    k = np.array([p["gnss_B_L_h"] for p in s["check_points"]])
    kw = np.column_stack(transform_blh(*k.T, "PZ-90.11", "WGS-84"))
    pts = tmp_path / "wgs.csv"
    pts.write_text("name;B;L;h\n" + "".join(f"K{i};{a};{b};{c}\n" for i, (a, b, c) in enumerate(kw.tolist())))
    assert cli(["to-local", str(datum), str(pts), "-o", str(tmp_path / "l.csv"), "--gnss-datum", "WGS-84"]) == 0
    assert "WGS-84 (G1150) → ПЗ-90.11" in capsys.readouterr().err
    loc = np.array([r.split(";")[1:] for r in (tmp_path / "l.csv").read_text().splitlines()[1:]], float)
    assert np.abs(loc - np.column_stack(d.to_local(*k.T))).max() < 1e-4
    assert cli(["to-wgs", str(datum), str(tmp_path / "l.csv"), "-o", str(tmp_path / "w.csv"), "--gnss-datum", "WGS-84"]) == 0
    w = np.array([r.split(";")[1:] for r in (tmp_path / "w.csv").read_text().splitlines()[1:]], float)
    assert np.abs(w[:, :2] - kw[:, :2]).max() < 1e-8 and np.abs(w[:, 2] - kw[:, 2]).max() < 2e-4
