"""Независимая проверка эталонов: NIST (плоскость, прямая) и синтетических примеров.

Запуск:  python tools/verify_cases.py
"""

import json
import sys
from pathlib import Path

import numpy as np

DATA = Path(__file__).resolve().parent.parent / "data"


def read_ds(path):
    lines = path.read_text().split()
    n = int(lines[0])
    return np.array(lines[1:1 + 3 * n], float).reshape(n, 3)


def read_fit(path):
    return np.array(path.read_text().split(), float)


def fit_plane(p):
    c = p.mean(axis=0)
    return c, np.linalg.svd(p - c)[2][-1]


def fit_line(p):
    c = p.mean(axis=0)
    return c, np.linalg.svd(p - c)[2][0]


def angle(a, b):
    """Угол между направлениями без учёта знака."""
    return float(np.arctan2(np.linalg.norm(np.cross(a, b)), abs(np.dot(a, b))))


def check_nist():
    worst = {}
    for kind, fit, folder in [("plane", fit_plane, "Plane"), ("line3d", fit_line, "Line3d"), ("line2d", fit_line, "Line2d")]:
        w = 0.0
        for ds in sorted((DATA / "nist_l2" / folder).glob("*.ds")):
            p = read_ds(ds)
            ref = read_fit(ds.with_suffix(".fit"))
            c, d = fit(p)
            w = max(w, angle(d, ref[3:6]))
            # Точка эталона должна лежать на нашей плоскости / прямой.
            off = ref[:3] - c
            dist = abs(off @ d) if kind == "plane" else np.linalg.norm(off - (off @ d) * d)
            w = max(w, dist)
        worst[kind] = w
    return worst


def frame_321(case):
    a = np.array(case["datums"]["A"]["points"])
    b = np.array(case["datums"]["B"]["points"])
    c = np.array(case["datums"]["C"]["points"])
    hint = case["material_direction_hint"]
    ca, z = fit_plane(a)
    z *= np.sign(z @ hint["A"])
    # B ⟂ A: прямая МНК в проекции на плоскость A.
    bp = b - np.outer(b @ z, z)
    cb, dir_b = fit_line(bp)
    y = np.cross(z, dir_b)
    y *= np.sign(y @ hint["B"])
    x = np.cross(y, z)
    cc = c.mean(axis=0)
    # Начало: z·o = z·ca, y·o = y·cb, x·o = x·cc.
    M = np.vstack([x, y, z])
    o = np.linalg.solve(M, [x @ cc, y @ cb, z @ ca])
    return o, x, y, z


def box_distance(p, size):
    """Расстояние от точек до поверхности бруса [0,size]."""
    s = np.array(size, float)
    q = np.abs(p - s / 2) - s / 2
    outside = np.linalg.norm(np.maximum(q, 0), axis=1)
    inside = np.minimum(q.max(axis=1), 0)
    return np.abs(outside + inside)


def check_case(case):
    e, tol = case["expected"], case["tolerance"]
    t = case["type"]
    if t == "plane_lsq":
        p = np.array(case["points"])
        c, n = fit_plane(p)
        err_a = angle(n, e["normal"])
        err_d = abs((np.array(e["point"]) - c) @ n)
        return err_a <= tol["normal_angle_rad"] and err_d <= tol["distance"], f"angle={err_a:.2e} dist={err_d:.2e}"
    if t == "flatness_minimum_zone":
        p = np.array(case["points"])
        n = np.array(e["zone_normal"])
        r = (p - e["zone_mid_point"]) @ n
        h = e["flatness"] / 2
        up, lo = e["contact_point_indices_upper"], e["contact_point_index_lower"]
        inside_zone = np.all(np.abs(r) <= h + 1e-9)
        contacts = np.allclose(r[up], h) and np.isclose(r[lo], -h)
        # Проекция нижней точки внутри треугольника верхних (условие оптимальности 3-1).
        e1 = np.linalg.svd(np.outer(n, n) - np.eye(3))[0][:, 0]
        e2 = np.cross(n, e1)
        uv = np.column_stack([p @ e1, p @ e2])
        A = np.column_stack([uv[up[1]] - uv[up[0]], uv[up[2]] - uv[up[0]]])
        s, q = np.linalg.solve(A, uv[lo] - uv[up[0]])
        in_tri = s > 0 and q > 0 and s + q < 1
        dp = (np.array(e["datum_plane_point"]) - e["zone_mid_point"]) @ n
        ok = inside_zone and contacts and in_tri and np.isclose(dp, h)
        return ok, f"zone={inside_zone} contacts={contacts} 3-1={in_tri}"
    if t == "datum_system_321":
        o, x, y, z = frame_321(case)
        err_a = max(angle(x, e["x_axis"]), angle(y, e["y_axis"]), angle(z, e["z_axis"]))
        signs = all(np.dot(u, e[k]) > 0 for u, k in [(x, "x_axis"), (y, "y_axis"), (z, "z_axis")])
        err_d = float(np.linalg.norm(o - e["origin"]))
        if "outlier_indices_A" in case:
            # Наивный МНК должен провалиться — убеждаемся, что пример действительно на робастность.
            return err_d > tol["distance"] or err_a > tol["angle_rad"], f"(LSQ без отбраковки) angle={err_a:.2e} dist={err_d:.2e} — ожидаемо не проходит"
        return err_a <= tol["angle_rad"] and err_d <= tol["distance"] and signs, f"angle={err_a:.2e} dist={err_d:.2e}"
    if t == "best_fit_to_nominal":
        R = np.array(e["rotation_measured_from_nominal"])
        tr = np.array(e["translation_measured_from_nominal"])
        p = (np.array(case["points"]) - tr) @ R
        d = box_distance(p, case["nominal"]["size"])
        rms = float(np.sqrt(np.mean(d * d)))
        ok = rms <= (1e-7 if tol["distance"] <= 1e-7 else tol["distance"])
        return ok, f"rms distance to nominal={rms:.2e}"
    return False, "unknown type"


def main():
    ok_all = True
    for kind, w in check_nist().items():
        ok = w < 1e-6
        ok_all &= ok
        print(f"[{'OK' if ok else 'FAIL'}] NIST {kind}: max deviation {w:.2e}")
    for f in sorted((DATA / "synthetic").glob("*.json")):
        ok, msg = check_case(json.loads(f.read_text(encoding="utf-8")))
        ok_all &= ok
        print(f"[{'OK' if ok else 'FAIL'}] {f.stem}: {msg}")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
