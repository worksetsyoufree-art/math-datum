"""Генератор геодезических примеров «точки → параметры перехода» по субъектам РФ.

Для каждого субъекта (границы — data/geodetic/regions.geojson) создаётся
data/geodetic/regions/<ISO>.json с двумя задачами:

1. helmert_7p — региональный переход СК-42 → ПЗ-90.11 по 7 параметрам
   (ГОСТ 32453-2017, прил. А.1). Даны геоцентрические XYZ в обеих системах,
   найти ΔX, ΔY, ΔZ, ωx, ωy, ωz, m. Два варианта: без шума (ответ — параметры
   ГОСТ) и с шумом, построенным ортогонально якобиану (ответ — те же параметры,
   они остаются точным решением МНК).

2. site_localization — «локализация» GNSS на участке ~5 км: ГНСС-координаты
   (ПЗ-90.11, B L h) → синтетическая местная система (псевдо-МСК, x y H).
   Ответ — МНК-параметры плоского преобразования подобия (4 параметра) в
   заданной рабочей проекции и наклонной плоскости высот (3 параметра),
   остаточные невязки и прогноз в контрольных точках.

Параметры псевдо-МСК СИНТЕТИЧЕСКИЕ и не являются ключами реальных МСК.

Пересчёты (BLH ↔ XYZ, 7 параметров ГОСТ, поперечный Меркатор) — функции mathdatum.datums;
переход на них с pyproj не изменил ни одного байта в data/geodetic (проверено).

Запуск:  python tools/generate_geodetic.py
"""

import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
from shapely.geometry import Point, shape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from mathdatum import datums  # noqa: E402

GEO = ROOT / "data" / "geodetic"
SEED = 32453

ARCSEC = np.pi / (180 * 3600)
KRASS = datums.ELLIPSOIDS["krass"].proj
PZ90 = datums.ELLIPSOIDS["pz90"].proj

# ГОСТ 32453-2017, приложение А.1: СК-42 → ПЗ-90.11 (параметры и формула — из mathdatum.datums).
SK42_TO_PZ9011 = next(t for t in datums.TRANSFORMATIONS if (t.src, t.dst) == ("SK-42", "PZ-90.11"))
GOST_SK42_TO_PZ9011 = {k: getattr(SK42_TO_PZ9011, k) for k in ("dX", "dY", "dZ", "wx", "wy", "wz", "m")}


def helmert(xyz, p):
    """Формула ГОСТ 32453 (малые углы, поворот системы координат):
    X2 = (1 + m) * R * X1 + ΔX,  R = [[1, ωz, -ωy], [-ωz, 1, ωx], [ωy, -ωx, 1]]."""
    return datums.helmert_forward(xyz, replace(SK42_TO_PZ9011, **p))


def helmert_jacobian(xyz, p):
    """Якобиан по (dX, dY, dZ, wx["], wy["], wz["], m[ppm]), размер (3n, 7)."""
    n = len(xyz)
    s = 1 + p["m"] * 1e-6
    X, Y, Z = xyz.T
    J = np.zeros((n, 3, 7))
    J[:, :, 0:3] = np.eye(3)
    J[:, :, 3] = s * ARCSEC * np.column_stack([np.zeros(n), Z, -Y])
    J[:, :, 4] = s * ARCSEC * np.column_stack([-Z, np.zeros(n), X])
    J[:, :, 5] = s * ARCSEC * np.column_stack([Y, -X, np.zeros(n)])
    J[:, :, 6] = 1e-6 * (helmert(xyz, {**p, "m": 0.0}) - np.array([p["dX"], p["dY"], p["dZ"]]))
    return J.reshape(3 * n, 7)


def sample_in(geom, n, rng):
    minx, miny, maxx, maxy = geom.bounds
    pts = []
    while len(pts) < n:
        lon, lat = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        if geom.contains(Point(lon, lat)):
            pts.append((lat, lon))
    return np.array(pts)


def r3(a, nd=4):
    return np.round(np.asarray(a, float), nd).tolist()


def helmert_task(geom, rng, noisy):
    n = 15
    bl = sample_in(geom, n, rng)
    h = rng.uniform(0, 800, n)
    x1 = np.column_stack(datums.blh_to_xyz(bl[:, 0], bl[:, 1], h, "SK-42"))
    x2 = helmert(x1, GOST_SK42_TO_PZ9011)
    sigma = 0.0
    if noisy:
        sigma = 0.02
        J = helmert_jacobian(x1, GOST_SK42_TO_PZ9011)
        q, _ = np.linalg.qr(J)
        r = rng.normal(size=3 * n)
        r -= q @ (q.T @ r)
        r *= sigma / np.sqrt(np.mean(r * r))
        x2 = x2 + r.reshape(n, 3)
    # Хранимые значения округляются до 0.1 мм; это часть данных, а не шума.
    x1, x2 = np.round(x1, 4), np.round(x2, 4)
    return {
        "type": "helmert_7p",
        "variant": "noisy" if noisy else "exact",
        "description": "Найти 7 параметров перехода СК-42 → ПЗ-90.11 по геоцентрическим координатам общих точек.",
        "model": "X2 = (1 + m·1e-6) · R(ωx, ωy, ωz) · X1 + [ΔX, ΔY, ΔZ];  "
                 "R = [[1, ωz, -ωy], [-ωz, 1, ωx], [ωy, -ωx, 1]] (углы в радианах; в ответе — в угловых секундах)",
        "source_crs": "СК-42 (эллипсоид Красовского), геоцентрические XYZ, м",
        "target_crs": "ПЗ-90.11, геоцентрические XYZ, м",
        "source_geodetic_B_L_H": [[round(b, 9), round(l, 9), round(hh, 4)] for (b, l), hh in zip(bl, h)],
        "source_xyz": x1.tolist(),
        "target_xyz": x2.tolist(),
        "expected": {
            "parameters": GOST_SK42_TO_PZ9011,
            "units": {"dX": "m", "dY": "m", "dZ": "m", "wx": "arcsec", "wy": "arcsec", "wz": "arcsec", "m": "ppm"},
            "rms_residual_m": sigma,
        },
        "tolerance": {"residual_rms_m": 1e-3 + sigma * 0.01, "parameters_note":
                      "На региональной сети сдвиги и повороты сильно коррелированы, поэтому сравнивать "
                      "лучше невязки и предсказанные координаты, а не сами параметры."},
        "notes": "Источник параметров: ГОСТ 32453-2017, прил. А.1. "
                 + ("Шум 2 см построен ортогонально якобиану: параметры ГОСТ — точное решение МНК."
                    if noisy else "Без шума (только округление до 0.1 мм)."),
    }


def similarity_lsq(src, dst):
    """МНК подобие 2D: dst = t + [[a, -b], [b, a]] · (src - c), c — центроид src."""
    c = src.mean(axis=0)
    s = src - c
    n = len(src)
    A = np.zeros((2 * n, 4))
    A[0::2] = np.column_stack([s[:, 0], -s[:, 1], np.ones(n), np.zeros(n)])
    A[1::2] = np.column_stack([s[:, 1], s[:, 0], np.zeros(n), np.ones(n)])
    sol = np.linalg.lstsq(A, dst.reshape(-1), rcond=None)[0]
    return c, sol, (dst.reshape(-1) - A @ sol).reshape(n, 2)


def apply_similarity(c, sol, src):
    a, b, tx, ty = sol
    s = src - c
    return np.column_stack([tx + a * s[:, 0] - b * s[:, 1], ty + b * s[:, 0] + a * s[:, 1]])


def site_task(geom, rng):
    n_ctrl, n_chk = 6, 4
    lat0, lon0 = sample_in(geom.buffer(-0.05) if geom.buffer(-0.05).area > 0 else geom, 1, rng)[0]
    # Точки на участке радиусом ~5 км.
    r = 5000 * np.sqrt(rng.uniform(0, 1, n_ctrl + n_chk))
    az = rng.uniform(0, 2 * np.pi, n_ctrl + n_chk)
    lat = lat0 + r * np.cos(az) / 111_000
    lon = lon0 + r * np.sin(az) / (111_000 * np.cos(np.radians(lat0)))
    H_sk = rng.uniform(50, 300) + rng.normal(0, 20, n_ctrl + n_chk)

    # СК-42 (B, L, H) → ПЗ-90.11 (B, L, h) по ГОСТ.
    xyz = helmert(np.column_stack(datums.blh_to_xyz(lat, lon, H_sk, "SK-42")), GOST_SK42_TO_PZ9011)
    lat_g, lon_g, h_g = datums.xyz_to_blh(*xyz.T, "PZ-90.11")
    # Шум ГНСС: 1 см в плане, 2 см по высоте.
    lat_g = lat_g + rng.normal(0, 0.01, len(lat)) / 111_000
    lon_g = lon_g + rng.normal(0, 0.01, len(lat)) / (111_000 * np.cos(np.radians(lat0)))
    h_g = h_g + rng.normal(0, 0.02, len(lat))
    lat_g, lon_g, h_g = np.round(lat_g, 10), np.round(lon_g, 10), np.round(h_g, 4)

    # Синтетическая МСК: Гаусс–Крюгер на Красовском со «сдвинутым» осевым меридианом.
    msk_lon0 = round(np.floor(lon0) + rng.choice([0.0, 0.5]) + rng.integers(-30, 31) / 60, 6)
    msk_x0 = -float(rng.integers(4_000_000, 6_500_000)) - round(rng.uniform(0, 1000), 2)
    msk_y0 = float(rng.choice([1, 2, 3])) * 1_000_000 + 250_000 + round(rng.uniform(0, 1000), 2)
    # В PROJ x_0 — ложное смещение на восток, y_0 — на север.
    msk = f"+proj=tmerc +lat_0=0 +lon_0={msk_lon0} +k=1 +x_0={msk_y0} +y_0={msk_x0} {KRASS} +units=m"
    n_m, e_m = datums.TransverseMercator("krass", msk_lon0, 0.0, 1.0, msk_x0, msk_y0).forward(lat, lon)
    # Аномалия высоты (синтетическая гладкая поверхность) и ошибки каталога 5 мм.
    zeta0, gx, gy = rng.uniform(5, 30), rng.normal(0, 2e-5), rng.normal(0, 2e-5)
    dn, de = (lat - lat0) * 111_000, (lon - lon0) * 111_000 * np.cos(np.radians(lat0))
    zeta = zeta0 + gx * dn + gy * de + 1e-10 * (dn ** 2 - de ** 2)
    H_msk = h_g - zeta + rng.normal(0, 0.005, len(lat))
    msk_xy = np.round(np.column_stack([n_m, e_m]) + rng.normal(0, 0.005, (len(lat), 2)), 4)
    H_msk = np.round(H_msk, 4)

    # Рабочая проекция для локализации (как в полевом ПО): ТМ на эллипсоиде ПЗ-90.11.
    work_lon0 = round(float(lon0), 2)
    work = f"+proj=tmerc +lat_0=0 +lon_0={work_lon0} +k=1 +x_0=0 +y_0=0 {PZ90} +units=m"
    n_w, e_w = datums.TransverseMercator("pz90", work_lon0).forward(lat_g, lon_g)
    work_ne = np.round(np.column_stack([n_w, e_w]), 4)

    ctrl, chk = slice(0, n_ctrl), slice(n_ctrl, None)
    c, sol, res = similarity_lsq(work_ne[ctrl], msk_xy[ctrl])
    a, b, tx, ty = sol
    pred_chk = apply_similarity(c, sol, work_ne[chk])
    # Высоты: H = h + c0 + c1·(N - Nc) + c2·(E - Ec).
    d = work_ne[ctrl] - c
    Av = np.column_stack([np.ones(n_ctrl), d[:, 0], d[:, 1]])
    cv = np.linalg.lstsq(Av, H_msk[ctrl] - h_g[ctrl], rcond=None)[0]
    res_v = H_msk[ctrl] - h_g[ctrl] - Av @ cv
    dchk = work_ne[chk] - c
    pred_H = h_g[chk] + np.column_stack([np.ones(n_chk), dchk[:, 0], dchk[:, 1]]) @ cv

    def pts(sl, ids):
        return [{"id": f"{ids}{i + 1}", "gnss_B_L_h": [float(lat_g[k]), float(lon_g[k]), float(h_g[k])],
                 "work_N_E": work_ne[k].tolist(), "local_x_y_H": [*msk_xy[k].tolist(), float(H_msk[k])]}
                for i, k in enumerate(range(len(lat))[sl])]

    return {
        "type": "site_localization",
        "description": "Локализация ГНСС на участке: плоское подобие (4 параметра) + наклонная плоскость высот (3 параметра).",
        "gnss_crs": "ПЗ-90.11, B L (градусы), h — эллипсоидальная высота (м)",
        "local_crs": "Синтетическая МСК: x (север), y (восток), H — нормальная высота (м)",
        "working_projection": work,
        "control_points": pts(ctrl, "R"),
        "check_points": pts(chk, "K"),
        "model": {
            "horizontal": "[x, y] = [tx, ty] + [[a, -b], [b, a]] · ([N, E] - [Nc, Ec]),  (N, E) — рабочая проекция, "
                          "(Nc, Ec) — центроид контрольных точек",
            "vertical": "H = h + c0 + c1·(N - Nc) + c2·(E - Ec)",
        },
        "expected": {
            "centroid_N_E": r3(c, 6),
            "a": float(a), "b": float(b), "tx": float(tx), "ty": float(ty),
            "scale": float(np.hypot(a, b)),
            "scale_ppm": float((np.hypot(a, b) - 1) * 1e6),
            "rotation_arcsec": float(np.arctan2(b, a) / ARCSEC),
            "vertical_c0_c1_c2": cv.tolist(),
            "residuals_control_dx_dy_dH": np.column_stack([res, res_v]).round(6).tolist(),
            "rms_horizontal_m": float(np.sqrt(np.mean(np.sum(res ** 2, axis=1)))),
            "rms_vertical_m": float(np.sqrt(np.mean(res_v ** 2))),
            "predicted_check_x_y_H": np.column_stack([pred_chk, pred_H]).round(4).tolist(),
            "check_errors_dx_dy_dH": np.column_stack([msk_xy[chk] - pred_chk, H_msk[chk] - pred_H]).round(4).tolist(),
        },
        "tolerance": {"parameters_relative": 1e-9, "coordinates_m": 1e-3},
        "truth": {
            "note": "Как на самом деле получены данные (для проверки точности, а не для подгонки).",
            "local_projection": msk,
            "gnss_to_sk42": "ГОСТ 32453-2017 прил. А.1 (обратный переход)",
            "height_anomaly": {"zeta0": zeta0, "gN": gx, "gE": gy, "curvature": 1e-10,
                               "formula": "ζ = ζ0 + gN·dN + gE·dE + 1e-10·(dN² - dE²), H = h - ζ"},
            "noise_sigma_m": {"gnss_plan": 0.01, "gnss_h": 0.02, "catalog_plan": 0.005, "catalog_H": 0.005},
        },
    }


def main():
    rng = np.random.default_rng(SEED)
    regions = json.loads((GEO / "regions.geojson").read_text(encoding="utf-8"))["features"]
    out_dir = GEO / "regions"
    out_dir.mkdir(parents=True, exist_ok=True)
    index = ["iso_3166_2;name_ru;site_rms_plan_m;site_rms_H_m;site_scale_ppm;site_rotation_arcsec"]
    for f in regions:
        p = f["properties"]
        geom = shape(f["geometry"])
        site = site_task(geom, rng)
        case = {
            "region": {"iso_3166_2": p["iso_3166_2"], "name_ru": p["name_ru"], "name_en": p["name_en"],
                       "bbox_lon_lat": r3(geom.bounds, 4), "centroid_lat_lon": r3([geom.centroid.y, geom.centroid.x], 4)},
            "tasks": [helmert_task(geom, rng, False), helmert_task(geom, rng, True), site],
        }
        (out_dir / f"{p['iso_3166_2']}.json").write_text(json.dumps(case, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        e = site["expected"]
        index.append(f"{p['iso_3166_2']};{p['name_ru']};{e['rms_horizontal_m']:.4f};{e['rms_vertical_m']:.4f};"
                     f"{e['scale_ppm']:.3f};{e['rotation_arcsec']:.2f}")
    (GEO / "index.csv").write_text("\n".join(index) + "\n", encoding="utf-8")
    print(f"{len(regions)} regions -> {out_dir}")


if __name__ == "__main__":
    main()
