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


# --- Надёжность: грубые ошибки, leave-one-out, ковариации, экстраполяция ---

def region_pairs(iso="RU-MOW"):
    return pairs_of(site(ROOT / f"data/geodetic/regions/{iso}.json")["control_points"])


def test_redundancy_and_zero_redundancy_warning():
    d = localize(synthetic_pairs(6)[0])
    assert (d.redundancy_plan, d.redundancy_height) == (8, 3)
    assert not d.warnings
    d = localize(synthetic_pairs(2)[0])        # подобие по 2 точкам, высота — сдвиг
    assert (d.redundancy_plan, d.redundancy_height) == (0, 1)
    assert [w.code for w in d.warnings] == ["plan_no_redundancy"]
    assert d.s0_plan is None and all(r.wx is None and r.loo_dx is None for r in d.residuals)
    d = localize(synthetic_pairs(3)[0])        # плоскость по 3 точкам
    assert d.redundancy_height == 0 and "height_no_redundancy" in [w.code for w in d.warnings]
    assert all(r.loo_dH is None and r.wH is None for r in d.residuals)
    d = localize(synthetic_pairs(1)[0])
    assert (d.redundancy_plan, d.redundancy_height) == (0, 0)
    assert {w.code for w in d.warnings} == {"plan_no_redundancy", "height_no_redundancy"}


def test_blunder_10cm_detected():
    """+10 см по x на одном из 6 пунктов: подсветка 3·СКО сработать не может (max|v| ≤ √n·СКО),
    а нормированная поправка выделяет именно этот пункт."""
    pairs = read_pairs(ROOT / "examples/pairs.csv")[:6]
    pairs[3].x += 0.10
    d = localize(pairs)
    r = d.residuals
    assert max(math.hypot(q.dx, q.dy) for q in r) < 3 * d.rms_plan
    assert [q.name for q in r if q.suspect] == ["R4"]
    assert r[3].w_plan > 3.29 and max(q.w_plan for q in r[:3] + r[4:]) < 3.29
    assert r[3].loo_dx == pytest.approx(0.10, abs=0.03)          # без точки ошибка видна целиком
    w = [x for x in d.warnings if x.code == "suspect_plan"]
    assert len(w) == 1 and w[0].point == "R4"
    from mathdatum import suggest_exclusions
    assert [(n, part) for n, part, _ in suggest_exclusions(pairs)] == [("R4", "plan")]
    # Исходные пары не изменились.
    assert all(p.use == "both" for p in pairs)


def test_blunder_20cm_detected_in_all_regions():
    """20 см (≈ 2 МДО при σ = 2 см) — худший |w| всегда у сбитого пункта, и он помечен."""
    for path in REGIONS:
        pairs = pairs_of(site(path)["control_points"])
        k = len(path.stem) % 6
        pairs[k].y += 0.20
        d = localize(pairs)
        w = [r.w_plan for r in d.residuals]
        assert int(np.argmax(w)) == k and d.residuals[k].suspect, path.stem


def test_height_blunder_and_control_points():
    pairs = read_pairs(ROOT / "examples/pairs.csv")
    pairs[1].H += 0.25
    d = localize(pairs)
    # Соседний R1 (150 м) тоже получает большую поправку — ошибка «размазывается»;
    # худший |w| и итеративное исключение указывают на R2.
    assert int(np.argmax([abs(r.wH) for r in d.residuals[:6]])) == 1 and d.residuals[1].suspect
    assert "suspect_height" in [w.code for w in d.warnings]
    from mathdatum import suggest_exclusions
    assert [(n, part) for n, part, _ in suggest_exclusions(pairs)] == [("R2", "height")]
    # Контрольная точка: q_vv = 1 + aᵀQa, ошибка прогноза — сама невязка.
    k = d.residuals[6]
    assert k.use == "none" and k.qvv_plan > 1 and k.loo_dx == k.dx and k.loo_dH == k.dH
    pairs[7].x += 0.5                           # грубая ошибка на контрольной K2
    d = localize(pairs)
    assert d.residuals[7].suspect and "контроль" in [w for w in d.warnings if w.point == "K2"][0].message


def test_leave_one_out_matches_manual():
    pairs = region_pairs()
    pairs[2].use = "plan"
    d = localize(pairs)
    for i, r in enumerate(d.residuals):
        rest = [p for j, p in enumerate(pairs) if j != i]
        m = localize(rest, lat0=d.lat0, lon0=d.lon0)
        x, y, H = m.to_local(pairs[i].B, pairs[i].L, pairs[i].h)
        assert r.loo_dx == pytest.approx(pairs[i].x - x, abs=1e-9)
        assert r.loo_dy == pytest.approx(pairs[i].y - y, abs=1e-9)
        assert r.loo_dx == pytest.approx(r.dx / r.qvv_plan, abs=1e-9)   # v_loo = v / q_vv
        if pairs[i].in_height:
            assert r.loo_dH == pytest.approx(pairs[i].H - H, abs=1e-9)
            assert r.loo_dH == pytest.approx(r.dH / r.qvv_height, abs=1e-9)
        else:
            assert r.loo_dH == r.dH                                        # высота — контроль
    # Сумма q_vv = избыточность.
    assert sum(2 * r.qvv_plan for r in d.residuals) == pytest.approx(d.redundancy_plan)
    assert sum(r.qvv_height for r, p in zip(d.residuals, pairs) if p.in_height) == pytest.approx(d.redundancy_height)


def test_leave_one_out_not_checkable():
    # 4 точки по высоте, 3 из них на одном меридиане: без 4-й плоскость не определена.
    pairs, _ = synthetic_pairs(4)
    for p in pairs[:3]:
        p.L = pairs[0].L
    d = localize(pairs)
    assert d.height_model == "plane" and d.residuals[3].loo_dH is None and d.residuals[3].wH is None
    assert all(r.loo_dH is not None for r in d.residuals[:3])


def test_normalized_residuals_and_covariance():
    pairs = region_pairs("RU-SPE")
    d = localize(pairs, sigma_plan=0.015, sigma_height=0.025)
    proj = d._proj()
    E, N = proj.transform([p.L for p in pairs], [p.B for p in pairs])
    dN, dE = np.array(N) - d.Nc, np.array(E) - d.Ec
    n = len(pairs)
    # План: A — строки x и y по каждой точке, параметры (tx, ty, a, b).
    A = np.zeros((2 * n, 4))
    A[0::2] = np.column_stack([np.ones(n), np.zeros(n), dN, -dE])
    A[1::2] = np.column_stack([np.zeros(n), np.ones(n), dE, dN])
    Q = np.linalg.inv(A.T @ A)
    assert np.allclose(d.q_plan, Q, rtol=1e-9, atol=1e-18)
    qvv = 1 - np.diag(A @ Q @ A.T)
    v = np.array([[r.dx, r.dy] for r in d.residuals]).ravel()
    w = v / (0.015 * np.sqrt(qvv))
    assert np.allclose(w, [x for r in d.residuals for x in (r.wx, r.wy)], atol=1e-9)
    assert d.s0_plan == pytest.approx(math.sqrt(v @ v / (2 * n - 4)))
    Ah = np.column_stack([np.ones(n), dN, dE])
    Qh = np.linalg.inv(Ah.T @ Ah)
    assert np.allclose(d.q_height, Qh, rtol=1e-8, atol=1e-18)
    assert np.allclose(d.covariance_height(), 0.025 ** 2 * Qh, rtol=1e-8, atol=1e-20)
    assert np.allclose(d.covariance_plan(posterior=True), d.s0_plan ** 2 * Q, rtol=1e-9, atol=1e-20)
    # СКО прогноза: m² = σ²·aᵀQa; в опорной точке — σ²·(1 − q_vv).
    B, L = pairs[0].B + 0.01, pairs[0].L - 0.02
    e, nn = proj.transform(L, B)
    a = np.array([1, nn - d.Nc, e - d.Ec])
    m_plan, m_h = d.prediction_sigma(B, L)
    assert m_h == pytest.approx(0.025 * math.sqrt(a @ Qh @ a))
    assert m_plan == pytest.approx(0.015 * math.sqrt(2 * (1 / n + (a[1] ** 2 + a[2] ** 2) / np.sum(dN ** 2 + dE ** 2))))
    mp0, _ = d.prediction_sigma(pairs[0].B, pairs[0].L)
    assert mp0 == pytest.approx(0.015 * math.sqrt(2 * (1 - d.residuals[0].qvv_plan)))


def test_extrapolation():
    from mathdatum.localization import convex_hull, _outside
    assert convex_hull([(0, 0), (2, 0), (1, 1), (2, 2), (0, 2), (1, 0)]) == [[0, 0], [2, 0], [2, 2], [0, 2]]
    hull = convex_hull([(0, 0), (2, 0), (2, 2), (0, 2)])
    out = _outside(hull, [1, 0, 3, 3, -1, 1], [1, 2, 1, 3, -1, 2.5])
    assert np.allclose(out, [0, 0, 1, math.sqrt(2), math.sqrt(2), 0.5])
    assert np.allclose(_outside([[0, 0], [4, 0]], [2, 5], [3, 0]), [3, 1])   # оболочка-отрезок
    assert np.allclose(_outside([[1, 1]], [4], [5]), [5])                      # одна точка
    pairs = read_pairs(ROOT / "examples/pairs.csv")
    d = localize(pairs)
    B = np.array([p.B for p in pairs])
    L = np.array([p.L for p in pairs])
    out = d.outside_distance(B, L)
    assert np.all(out[:6] < 1e-6)                    # опорные — внутри или на границе
    assert out[7] > 1000 and out[8] == 0             # K2 далеко снаружи, K3 внутри
    # Из местной системы — то же расстояние.
    x, y, _ = d.to_local(B, L, np.zeros_like(B))
    assert np.allclose(d.quality_local(x, y)[0], out, atol=1e-6)


def test_plausibility_warnings():
    pairs, _ = synthetic_pairs(5, a=1.0005, b=0.0)
    assert [w.code for w in localize(pairs).warnings] == ["scale_implausible"]
    assert not localize(pairs, max_scale_ppm=600).warnings
    # Перепутаны x и y: подобие не может это описать, разворот получается огромным.
    pairs, _ = synthetic_pairs(5)
    swapped = [Pair(p.name, p.B, p.L, p.h, p.y, p.x, p.H) for p in pairs]
    codes = [w.code for w in localize(swapped).warnings]
    assert "rotation_implausible" in codes
    pairs, _ = synthetic_pairs(5, a=math.cos(math.radians(2)), b=math.sin(math.radians(2)))
    assert [w.code for w in localize(pairs).warnings] == ["rotation_implausible"]
    assert not localize(pairs, max_rotation_deg=3).warnings


def test_save_load_diagnostics_and_old_format(tmp_path):
    pairs = read_pairs(ROOT / "examples/pairs.csv")
    pairs[0].x += 0.3
    d = localize(pairs)
    assert d.warnings and d.plan_hull and d.q_height
    d.save(tmp_path / "d.json")
    assert LocalizationDatum.load(tmp_path / "d.json") == d
    old = LocalizationDatum.load(ROOT / "tests/data/datum_old_format.json")
    assert old.warnings == [] and old.redundancy_plan is None and old.residuals[0].wx is None
    out, mp, mh = old.quality_wgs(55.07, 39.3)
    assert np.isnan(out) and np.isnan(mp) and np.isnan(mh)
    x, y, H = old.to_local(55.07, 39.3, 200)        # пересчёты работают как раньше
    assert math.isfinite(float(x))


def test_cli_quality_and_report(tmp_path, capsys):
    pairs = tmp_path / "pairs.csv"
    lines = (ROOT / "examples/pairs.csv").read_text().splitlines()
    f = lines[4].split(";")
    f[4] = f"{float(f[4]) + 0.15:.4f}"               # R4: +15 см по x
    lines[4] = ";".join(f)
    pairs.write_text("\n".join(lines) + "\n")
    datum = tmp_path / "datum.json"
    assert cli(["localize", str(pairs), "-o", str(datum), "--suggest"]) == 0
    out = capsys.readouterr().out
    assert "Предупреждения" in out and "R4 (план)" in out and "Избыточность: план 8, высота 3" in out
    assert "Предлагается исключить (по порядку): R4" in out
    src = ROOT / "examples/wgs_points.csv"
    assert cli(["to-local", str(datum), str(src), "-o", str(tmp_path / "a.csv")]) == 0
    err = capsys.readouterr().err
    assert "вне выпуклой оболочки" in err and "T2" in err and "T3" not in err
    assert (tmp_path / "a.csv").read_text().splitlines()[0] == "name;x;y;H"      # формат по умолчанию прежний
    assert cli(["to-local", str(datum), str(src), "-o", str(tmp_path / "b.csv"), "--quality"]) == 0
    rows = [r.split(";") for r in (tmp_path / "b.csv").read_text().splitlines()]
    assert rows[0] == ["name", "x", "y", "H", "outside_m", "m_plan", "m_H"]
    assert rows[3][:4] == (tmp_path / "a.csv").read_text().splitlines()[3].split(";")
    assert float(rows[3][4]) == 0 and float(rows[2][4]) > 1000
    # Результат с доп. столбцами читается обратно.
    assert cli(["to-wgs", str(datum), str(tmp_path / "b.csv"), "-o", str(tmp_path / "c.csv")]) == 0
