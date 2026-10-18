import json
import math
from pathlib import Path

import numpy as np
import pytest
from pyproj import Transformer

from mathdatum import LocalizationDatum, LocalizationError, Pair, localize, read_pairs
from mathdatum.__main__ import main as cli

ROOT = Path(__file__).resolve().parents[1]
REGIONS = sorted((ROOT / "data/geodetic/regions").glob("*.json"))


def site(path):
    case = json.loads(path.read_text(encoding="utf-8"))
    return next(t for t in case["tasks"] if t["type"] == "site_localization")


def pairs_of(points, use="both"):
    return [Pair(p["id"], *p["gnss_B_L_h"], *p["local_x_y_H"], use=use) for p in points]


@pytest.mark.parametrize("path", REGIONS, ids=lambda p: p.stem)
def test_regions_exact_with_reference_projection(path):
    """С той же рабочей проекцией, что у эталона, параметры совпадают с точностью до
    округления координат проекции в датасете (0.1 мм на базе ~5 км)."""
    s = site(path)
    e = s["expected"]
    proj = dict(kv.lstrip("+").split("=", 1) for kv in s["working_projection"].split() if "=" in kv)
    d = localize(pairs_of(s["control_points"]), lat0=float(proj["lat_0"]), lon0=float(proj["lon_0"]),
                 ellipsoid=f"+a={proj['a']} +rf={proj['rf']}")
    assert (d.a, d.b) == pytest.approx((e["a"], e["b"]), abs=1e-7)
    assert (d.tx, d.ty) == pytest.approx((e["tx"], e["ty"]), abs=2e-4)
    assert d.c0 == pytest.approx(e["vertical_c0_c1_c2"][0], abs=2e-4)
    assert d.c1 == pytest.approx(e["vertical_c0_c1_c2"][1], abs=1e-7)
    assert d.c2 == pytest.approx(e["vertical_c0_c1_c2"][2], abs=1e-7)
    assert d.rms_plan == pytest.approx(e["rms_horizontal_m"], abs=1e-4)


@pytest.mark.parametrize("path", REGIONS, ids=lambda p: p.stem)
def test_regions_default_projection(path):
    """С проекцией по умолчанию (WGS-84, центр в среднем по точкам) — те же невязки и прогноз
    в контрольных точках с точностью до разницы проекций (< 3 мм)."""
    s = site(path)
    e = s["expected"]
    d = localize(pairs_of(s["control_points"]))
    assert d.plan_model == "similarity" and d.height_model == "plane"
    assert d.rms_plan == pytest.approx(e["rms_horizontal_m"], abs=5e-4)
    assert d.rms_height == pytest.approx(e["rms_vertical_m"], abs=5e-4)
    chk = s["check_points"]
    x, y, H = d.to_local(*np.array([p["gnss_B_L_h"] for p in chk]).T)
    pred = np.array(e["predicted_check_x_y_H"])
    assert np.abs(np.column_stack([x, y, H]) - pred).max() < 3e-3
    # Ошибка на контрольных относительно каталога — в пределах шума данных.
    cat = np.array([p["local_x_y_H"] for p in chk])
    assert np.abs(np.column_stack([x, y]) - cat[:, :2]).max() < 0.1
    assert np.abs(H - cat[:, 2]).max() < 0.05


def synthetic_pairs(n, a=0.99998, b=1.2e-4, t=(512_345.6, 1_310_222.2), c=(-14.2, 3e-5, -2e-5)):
    """Точки, связанные моделью точно: параметры должны восстановиться до округления."""
    rng = np.random.default_rng(1)
    B = 55.75 + rng.uniform(-0.03, 0.03, n)
    L = 37.62 + rng.uniform(-0.05, 0.05, n)
    h = rng.uniform(140, 200, n)
    lat0, lon0 = float(B.mean()), float(L.mean())
    proj = LocalizationDatum(lat0, lon0, 0, 0, 1, 0, 0, 0, 0, 0, 0)._proj()
    E, N = proj.transform(L, B)
    Nc, Ec = N.mean(), E.mean()
    dN, dE = N - Nc, E - Ec
    x = t[0] + a * dN - b * dE
    y = t[1] + b * dN + a * dE
    H = h + c[0] + c[1] * dN + c[2] * dE
    return [Pair(f"P{i}", B[i], L[i], h[i], x[i], y[i], H[i]) for i in range(n)], (a, b, *t, *c)


def test_exact_model_is_recovered():
    pairs, (a, b, tx, ty, c0, c1, c2) = synthetic_pairs(7)
    d = localize(pairs)
    assert (d.a, d.b, d.tx, d.ty) == pytest.approx((a, b, tx, ty), rel=1e-12, abs=1e-7)
    assert (d.c0, d.c1, d.c2) == pytest.approx((c0, c1, c2), rel=1e-9, abs=1e-9)
    assert d.rms_plan < 1e-7 and d.rms_height < 1e-7


def test_round_trip():
    pairs, _ = synthetic_pairs(5)
    d = localize(pairs)
    B = np.array([p.B for p in pairs]) + 0.01
    L = np.array([p.L for p in pairs]) - 0.02
    h = np.array([p.h for p in pairs])
    B2, L2, h2 = d.to_wgs(*d.to_local(B, L, h))
    assert np.abs(B2 - B).max() < 1e-11 and np.abs(L2 - L).max() < 1e-11
    assert np.abs(h2 - h).max() < 1e-8


def test_proj_pipeline_matches():
    pairs, _ = synthetic_pairs(6)
    d = localize(pairs)
    t = Transformer.from_pipeline(d.to_proj_pipeline())
    B, L, h = (np.array([getattr(p, k) for p in pairs]) for k in "BLh")
    px, py, pH = t.transform(B, L, h)
    x, y, H = d.to_local(B, L, h)
    assert np.abs(np.column_stack([px - x, py - y, pH - H])).max() < 1e-6


def test_save_load(tmp_path):
    d = localize(synthetic_pairs(4)[0])
    d.save(tmp_path / "datum.json")
    d2 = LocalizationDatum.load(tmp_path / "datum.json")
    assert d2 == d


def test_one_point_is_shift_only():
    pairs, _ = synthetic_pairs(1)
    d = localize(pairs)
    assert d.plan_model == "shift" and d.height_model == "shift"
    assert (d.a, d.b, d.c1, d.c2) == (1.0, 0.0, 0.0, 0.0)
    assert d.rms_plan < 1e-9 and d.rms_height < 1e-9


def test_two_points_height_is_shift_only():
    pairs, _ = synthetic_pairs(2)
    d = localize(pairs)
    assert d.plan_model == "similarity" and d.height_model == "shift"


def test_collinear_points_height_falls_back_to_shift():
    pairs, _ = synthetic_pairs(3)
    # Ставим все три точки на один меридиан: плоскость по высоте не определена.
    for p in pairs:
        p.L = pairs[0].L
    assert localize(pairs).height_model == "shift"


def test_use_flags():
    pairs, _ = synthetic_pairs(6)
    pairs[0].use = "none"
    pairs[1].use = "plan"
    pairs[2].use = "height"
    pairs[0].x += 10  # испорченная точка исключена и не влияет на результат
    d = localize(pairs, lat0=float(np.mean([p.B for p in pairs])), lon0=float(np.mean([p.L for p in pairs])))
    assert d.rms_plan < 1e-7
    assert d.residuals[0].dx == pytest.approx(10, abs=1e-6)


def test_errors():
    pairs, _ = synthetic_pairs(3)
    for p in pairs:
        p.use = "height"
    with pytest.raises(LocalizationError):
        localize(pairs)
    same = [Pair("A", 55.0, 37.0, 150, 1, 2, 3), Pair("B", 55.0, 37.0, 150, 1, 2, 3)]
    with pytest.raises(LocalizationError):
        localize(same)


def test_cli(tmp_path, capsys):
    example = ROOT / "examples/pairs.csv"
    assert len(read_pairs(example)) == 10
    datum = tmp_path / "datum.json"
    assert cli(["localize", str(example), "-o", str(datum)]) == 0
    assert "СКО" in capsys.readouterr().out
    assert cli(["to-local", str(datum), str(ROOT / "examples/wgs_points.csv"), "-o", str(tmp_path / "l.csv")]) == 0
    assert cli(["to-wgs", str(datum), str(tmp_path / "l.csv"), "-o", str(tmp_path / "w.csv")]) == 0
    src = (ROOT / "examples/wgs_points.csv").read_text().splitlines()[1].split(";")
    back = (tmp_path / "w.csv").read_text().splitlines()[1].split(";")
    assert math.isclose(float(src[1]), float(back[1]), abs_tol=1e-9)
    assert math.isclose(float(src[3]), float(back[3]), abs_tol=1e-3)
