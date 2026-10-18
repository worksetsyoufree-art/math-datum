"""Генератор синтетических примеров для локализации и построения датумов.

Каждый пример содержит измеренные точки и ожидаемый ("эталонный") результат.
Эталон известен точно по построению (метод нуль-пространства): сначала
задаётся ответ, затем к точкам на идеальной геометрии добавляются отклонения,
ортогональные условиям оптимальности соответствующего метода подгонки.
Поэтому даже при шуме ожидаемый результат совпадает с ответом до округления.

Запуск:  python tools/generate_cases.py  [--out data/synthetic]
"""

import argparse
import json
from pathlib import Path

import numpy as np

SEED = 20261018


def random_rotation(rng):
    q = rng.normal(size=4)
    q /= np.linalg.norm(q)
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def project_out(residuals, basis):
    """Убирает из residuals компоненты, лежащие в span(столбцов basis)."""
    q, _ = np.linalg.qr(basis)
    return residuals - q @ (q.T @ residuals)


def scale_to_rms(r, sigma):
    rms = np.sqrt(np.mean(r * r))
    return r if rms == 0 else r * (sigma / rms)


def plane_lsq_case(rng, name, n_points, size, sigma, partial=False):
    """Плоскость МНК (ортогональная регрессия): точка + нормаль."""
    R = random_rotation(rng)
    origin = rng.uniform(-500, 500, size=3)
    u_lim = (0, size) if partial else (-size / 2, size / 2)
    u = rng.uniform(*u_lim, n_points)
    v = rng.uniform(-size / 2, size / 2 * (0.1 if partial else 1), n_points)
    # Условия оптимальности МНК-плоскости: sum r = 0, sum r*u = 0, sum r*v = 0.
    r = project_out(rng.normal(size=n_points), np.column_stack([np.ones(n_points), u, v]))
    r = scale_to_rms(r, sigma)
    e1, e2, n = R[:, 0], R[:, 1], R[:, 2]
    pts = origin + np.outer(u, e1) + np.outer(v, e2) + np.outer(r, n)
    centroid = pts.mean(axis=0)
    return {
        "name": name,
        "type": "plane_lsq",
        "description": "МНК-плоскость по точкам (минимум суммы квадратов ортогональных расстояний).",
        "points": pts.tolist(),
        "expected": {
            "point": centroid.tolist(),
            "normal": n.tolist(),
            "rms_residual": float(np.sqrt(np.mean(r * r))),
            "flatness_lsq": float(r.max() - r.min()),
        },
        "tolerance": {"normal_angle_rad": 1e-9, "distance": 1e-7},
        "notes": "Нормаль определена с точностью до знака; точка — любая точка плоскости (здесь центроид).",
    }


def flatness_mz_case(rng, name, n_points, size, flatness):
    """Минимальная зона (Чебышёв) для плоскостности + касательная плоскость датума.

    Конфигурация 3-1: три точки на верхней границе зоны образуют треугольник,
    проекция нижней контактной точки лежит внутри него. Это достаточное
    условие оптимальности минимальной зоны, поэтому её ширина = flatness.
    """
    R = random_rotation(rng)
    origin = rng.uniform(-500, 500, size=3)
    h = flatness / 2
    tri = np.array([[-0.45, -0.4], [0.45, -0.35], [0.0, 0.48]]) * size
    w = rng.dirichlet([3, 3, 3])
    inner = w @ tri
    uv = rng.uniform(-size / 2, size / 2, size=(n_points - 4, 2))
    r = rng.uniform(-0.9 * h, 0.9 * h, n_points - 4)
    uv = np.vstack([tri, inner, uv])
    r = np.concatenate([[h, h, h, -h], r])
    perm = rng.permutation(n_points)
    uv, r = uv[perm], r[perm]
    e1, e2, n = R[:, 0], R[:, 1], R[:, 2]
    pts = origin + np.outer(uv[:, 0], e1) + np.outer(uv[:, 1], e2) + np.outer(r, n)
    return {
        "name": name,
        "type": "flatness_minimum_zone",
        "description": "Плоскостность по минимальной зоне и датум-плоскость, касательная снаружи материала (ISO 5459).",
        "points": pts.tolist(),
        "material_side": (-n).tolist(),
        "expected": {
            "flatness": flatness,
            "zone_normal": n.tolist(),
            "zone_mid_point": origin.tolist(),
            "datum_plane_point": (origin + h * n).tolist(),
            "datum_plane_normal": n.tolist(),
            "contact_point_indices_upper": [int(np.where(perm == i)[0][0]) for i in range(3)],
            "contact_point_index_lower": int(np.where(perm == 3)[0][0]),
        },
        "tolerance": {"flatness": 1e-7, "normal_angle_rad": 1e-6},
        "notes": "material_side — направление в материал. Датум-плоскость касается точек снаружи материала "
                 "и минимизирует максимальное расстояние до них (constrained minimax).",
    }


def datum_321_case(rng, name, size, n_a, n_b, n_c, sigma, outliers=0):
    """Система датумов A|B|C на призматической детали (3-2-1).

    A — МНК-плоскость (нормаль задаёт Z), B — МНК-плоскость, перпендикулярная A
    (нормаль задаёт Y), C — МНК-плоскость, перпендикулярная A и B (нормаль задаёт X).
    Начало координат — пересечение трёх плоскостей.
    """
    L, W, H = size
    R = random_rotation(rng)
    t = rng.uniform(-500, 500, size=3)

    # Локальная СК детали: A: z=0 (нормаль -z, наружу), B: y=0 (наружу -y), C: x=0 (наружу -x).
    # Ориентация датумной СК: Z = +z, X = +x, Y = +y (внутрь материала, как принято в 3-2-1).
    a_uv = rng.uniform([0.05 * L, 0.05 * W], [0.95 * L, 0.95 * W], size=(n_a, 2))
    r_a = scale_to_rms(project_out(rng.normal(size=n_a), np.column_stack([np.ones(n_a), a_uv])), sigma)
    a_loc = np.column_stack([a_uv, r_a])

    # B ⟂ A: свободны поворот вокруг Z и смещение -> условия sum r = 0, sum r*x = 0.
    b_xz = rng.uniform([0.05 * L, 0.1 * H], [0.95 * L, 0.9 * H], size=(n_b, 2))
    r_b = scale_to_rms(project_out(rng.normal(size=n_b), np.column_stack([np.ones(n_b), b_xz[:, 0]])), sigma)
    b_loc = np.column_stack([b_xz[:, 0], r_b, b_xz[:, 1]])

    # C ⟂ A и B: свободно только смещение -> sum r = 0.
    c_yz = rng.uniform([0.1 * W, 0.1 * H], [0.9 * W, 0.9 * H], size=(n_c, 2))
    r_c = rng.normal(size=n_c)
    r_c = scale_to_rms(r_c - r_c.mean(), sigma) if n_c > 1 else np.zeros(1)
    c_loc = np.column_stack([r_c, c_yz])

    def to_world(p):
        return (R @ p.T).T + t

    groups = {"A": to_world(a_loc), "B": to_world(b_loc), "C": to_world(c_loc)}
    outlier_idx = []
    if outliers:
        idx = rng.choice(n_a, outliers, replace=False)
        a = groups["A"].copy()
        a[idx] += np.outer(rng.choice([-1, 1], outliers) * rng.uniform(20, 50, outliers) * sigma, R[:, 2])
        groups["A"] = a
        outlier_idx = sorted(int(i) for i in idx)

    case = {
        "name": name,
        "type": "datum_system_321",
        "description": "Система датумов A|B|C по точкам на трёх гранях призматической детали.",
        "datums": {
            "A": {"feature": "plane", "constraint": "none", "points": groups["A"].tolist()},
            "B": {"feature": "plane", "constraint": "perpendicular to A", "points": groups["B"].tolist()},
            "C": {"feature": "plane", "constraint": "perpendicular to A and B", "points": groups["C"].tolist()},
        },
        "material_direction_hint": {"A": R[:, 2].tolist(), "B": R[:, 1].tolist(), "C": R[:, 0].tolist()},
        "expected": {
            "origin": t.tolist(),
            "x_axis": R[:, 0].tolist(),
            "y_axis": R[:, 1].tolist(),
            "z_axis": R[:, 2].tolist(),
            "rotation_world_from_datum": R.tolist(),
            "translation_world_from_datum": t.tolist(),
        },
        "tolerance": {"angle_rad": 1e-9, "distance": 1e-7},
        "notes": "Оси датумной СК направлены в материал (material_direction_hint). "
                 "Все датумы — МНК с ограничениями ориентации; ожидаемый ответ точен при данном шуме.",
    }
    if outliers:
        case["outlier_indices_A"] = outlier_idx
        case["tolerance"] = {"angle_rad": 1e-3, "distance": 5 * sigma}
        case["notes"] += (" В A добавлены выбросы: ожидаемый результат — истинная поза; "
                          "без робастного метода (RANSAC/Huber) тест не пройдёт.")
    return case


def box_surface_samples(rng, size, n):
    L, W, H = size
    areas = np.array([L * W, L * W, L * H, L * H, W * H, W * H])
    faces = rng.choice(6, n, p=areas / areas.sum())
    a, b = rng.uniform(0, 1, n), rng.uniform(0, 1, n)
    p = np.zeros((n, 3))
    for f in range(6):
        m = faces == f
        if f in (0, 1):
            p[m] = np.column_stack([a[m] * L, b[m] * W, np.full(m.sum(), 0 if f == 0 else H)])
        elif f in (2, 3):
            p[m] = np.column_stack([a[m] * L, np.full(m.sum(), 0 if f == 2 else W), b[m] * H])
        else:
            p[m] = np.column_stack([np.full(m.sum(), 0 if f == 4 else L), a[m] * W, b[m] * H])
    normals = np.array([[0, 0, -1], [0, 0, 1], [0, -1, 0], [0, 1, 0], [-1, 0, 0], [1, 0, 0]], float)
    return p, normals[faces]


def best_fit_to_cad_case(rng, name, size, n, sigma, max_angle_deg, max_shift):
    """Локализация по номинальной модели (best-fit / ICP): поиск R, t."""
    angle = np.deg2rad(rng.uniform(0.3, 1.0) * max_angle_deg)
    axis = rng.normal(size=3)
    axis /= np.linalg.norm(axis)
    K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    R = np.eye(3) + np.sin(angle) * K + (1 - np.cos(angle)) * K @ K
    t = rng.uniform(-max_shift, max_shift, size=3)
    p, nrm = box_surface_samples(rng, size, n)
    p = p + nrm * rng.normal(scale=sigma, size=(n, 1))
    measured = (R @ p.T).T + t
    return {
        "name": name,
        "type": "best_fit_to_nominal",
        "description": "Совмещение измеренных точек с номинальной моделью (прямоугольный брус) по МНК расстояний до поверхности.",
        "nominal": {"kind": "box", "min_corner": [0, 0, 0], "size": list(size)},
        "points": measured.tolist(),
        "expected": {
            "rotation_measured_from_nominal": R.tolist(),
            "translation_measured_from_nominal": t.tolist(),
            "rotation_angle_deg": float(np.rad2deg(angle)),
        },
        "tolerance": {"angle_rad": 1e-9 if sigma == 0 else 20 * sigma / min(size),
                      "distance": 1e-7 if sigma == 0 else 10 * sigma},
        "notes": "Начальное приближение — тождественное преобразование. "
                 + ("Без шума: ответ точен." if sigma == 0 else
                    "Шум нормальный по нормали к поверхности; ответ — истинная поза, допуск статистический."),
    }


def build_cases():
    rng = np.random.default_rng(SEED)
    cases = []
    for i, (n, size, sigma, partial) in enumerate([
        (3, 50, 0.0, False), (4, 50, 0.0, False), (25, 100, 0.005, False),
        (200, 300, 0.01, False), (500, 10, 0.001, False), (60, 200, 0.02, True),
    ], 1):
        cases.append(plane_lsq_case(rng, f"plane_lsq_{i:02d}", n, size, sigma, partial))
    for i, (n, size, f) in enumerate([(10, 100, 0.02), (50, 200, 0.05), (300, 400, 0.1)], 1):
        cases.append(flatness_mz_case(rng, f"flatness_mz_{i:02d}", n, size, f))
    for i, (size, na, nb, nc, sigma, out) in enumerate([
        ((200, 100, 50), 3, 2, 1, 0.0, 0),
        ((200, 100, 50), 9, 6, 3, 0.005, 0),
        ((500, 300, 80), 40, 20, 8, 0.01, 0),
        ((120, 80, 30), 30, 15, 5, 0.01, 3),
    ], 1):
        cases.append(datum_321_case(rng, f"datum_321_{i:02d}", size, na, nb, nc, sigma, out))
    for i, (size, n, sigma, ang, sh) in enumerate([
        ((200, 100, 50), 300, 0.0, 5, 5),
        ((200, 100, 50), 500, 0.005, 3, 2),
        ((300, 200, 100), 1000, 0.01, 10, 10),
    ], 1):
        cases.append(best_fit_to_cad_case(rng, f"best_fit_{i:02d}", size, n, sigma, ang, sh))
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "data" / "synthetic"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for case in build_cases():
        (out / f"{case['name']}.json").write_text(json.dumps(case, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(case["name"])


if __name__ == "__main__":
    main()
