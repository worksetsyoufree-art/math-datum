"""Независимая проверка геодезических датасетов data/geodetic/regions/*.json.

- параметры ГОСТ 32453-2017: файл data/geodetic/gost_32453_parameters.json = mathdatum.datums;
- контрольный пример ГОСТ (прил. Е): все три шага библиотечными функциями (mathdatum.datums);
- helmert_7p (exact): mathdatum.datums и независимо PROJ (+proj=helmert convention=coordinate_frame);
- helmert_7p (noisy): решение МНК итерациями Гаусса–Ньютона с нуля, сравнение прогноза;
- site_localization: пересчёт рабочей проекции через PROJ и mathdatum.datums, подобие — в комплексной
  форме (z' = t + w·z), высоты — отдельный МНК; блок truth: H = h − ζ с точностью до шума.

Запуск:  python tools/verify_geodetic.py
"""

import json
import sys
from pathlib import Path

import numpy as np
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent.parent
GEO = ROOT / "data" / "geodetic"
sys.path.insert(0, str(ROOT))
from mathdatum import datums  # noqa: E402

ARCSEC = np.pi / (180 * 3600)


def proj_helmert(xyz, p):
    t = Transformer.from_pipeline(
        f"+proj=helmert +x={p['dX']} +y={p['dY']} +z={p['dZ']} +rx={p['wx']} +ry={p['wy']} +rz={p['wz']} "
        f"+s={p['m']} +convention=coordinate_frame")
    return np.column_stack(t.transform(*xyz.T))


def solve_helmert(x1, x2):
    """Гаусс–Ньютон по 7 параметрам с нулевого приближения (центрирование для устойчивости)."""
    c = x1.mean(axis=0)
    q = np.zeros(7)  # dX dY dZ (относительно центра), wx wy wz [рад], m

    def model(q):
        wx, wy, wz = q[3:6]
        R = np.array([[1, wz, -wy], [-wz, 1, wx], [wy, -wx, 1]])
        return (1 + q[6]) * (x1 - c) @ R.T + c + q[:3]

    for _ in range(10):
        r = (x2 - model(q)).reshape(-1)
        J = np.zeros((len(x1), 3, 7))
        J[:, :, :3] = np.eye(3)
        X, Y, Z = (x1 - c).T
        z = np.zeros(len(x1))
        J[:, :, 3] = np.column_stack([z, Z, -Y])
        J[:, :, 4] = np.column_stack([-Z, z, X])
        J[:, :, 5] = np.column_stack([Y, -X, z])
        J[:, :, 6] = (x1 - c)
        q += np.linalg.lstsq(J.reshape(-1, 7), r, rcond=None)[0]
    return model(q), q


def check_helmert(task):
    x1, x2 = np.array(task["source_xyz"]), np.array(task["target_xyz"])
    p = task["expected"]["parameters"]
    pred = proj_helmert(x1, p)
    # Библиотека: путь СК-42 → ПЗ-90.11 по графу параметров, те же параметры, что в задаче.
    lib = datums.transform_xyz(x1, "SK-42", "PZ-90.11")
    d_lib = float(np.abs(lib - pred).max())
    gost = next(t for t in datums.TRANSFORMATIONS if t.src == "SK-42")
    same = all(getattr(gost, k) == v for k, v in p.items())
    rms_given = float(np.sqrt(np.mean(np.sum((x2 - pred) ** 2, axis=1) / 3)))
    fit, q = solve_helmert(x1, x2)
    # Решение МНК должно давать те же координаты, что и параметры ГОСТ.
    dpred = float(np.abs(fit - pred).max())
    dm = abs(q[6] * 1e6 - p["m"])
    if task["variant"] == "exact":
        ok = rms_given < 1e-4 and dpred < 1e-4 and dm < 1e-3
    else:
        ok = abs(rms_given - task["expected"]["rms_residual_m"]) < 2e-4 and dpred < 1e-3 and dm < 1e-2
    ok = ok and same and d_lib < 1e-6
    return ok, f"{task['variant']}: rms={rms_given:.4f} |LSQ-ГОСТ|={dpred:.1e} dm={dm:.1e}ppm |lib-PROJ|={d_lib:.1e}"


def check_site(task):
    e = task["expected"]
    ctrl, chk = task["control_points"], task["check_points"]
    work = Transformer.from_pipeline(
        f"+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step {task['working_projection']}")

    def ne(points):
        b = np.array([p["gnss_B_L_h"] for p in points])
        E, N = work.transform(b[:, 1], b[:, 0])
        return np.column_stack([N, E]), b[:, 2]

    src, h = ne(ctrl)
    stored = np.array([p["work_N_E"] for p in ctrl])
    d_proj = float(np.abs(src - stored).max())
    kv = dict(x.lstrip("+").split("=", 1) for x in task["working_projection"].split() if "=" in x)
    b = np.array([p["gnss_B_L_h"] for p in ctrl])
    lib = np.column_stack(datums.TransverseMercator("pz90", float(kv["lon_0"])).forward(b[:, 0], b[:, 1]))
    d_proj = max(d_proj, float(np.abs(lib - stored).max()))
    dst = np.array([p["local_x_y_H"] for p in ctrl])
    # Подобие в комплексной форме: z = N + iE, w = x + iy; w = t + k·(z - zc).
    z = stored[:, 0] + 1j * stored[:, 1]
    w = dst[:, 0] + 1j * dst[:, 1]
    zc = z.mean()
    k = np.sum(np.conj(z - zc) * (w - w.mean())) / np.sum(np.abs(z - zc) ** 2)
    t = w.mean()
    d_par = max(abs(k.real - e["a"]), abs(k.imag - e["b"]))
    d_t = max(abs(t.real - e["tx"]), abs(t.imag - e["ty"]))
    # Высоты.
    A = np.column_stack([np.ones(len(z)), (z - zc).real, (z - zc).imag])
    cv = np.linalg.lstsq(A, dst[:, 2] - h, rcond=None)[0]
    d_v = float(np.abs(cv - e["vertical_c0_c1_c2"]).max())
    # Прогноз в контрольных точках.
    zk = np.array([p["work_N_E"] for p in chk])
    zk = zk[:, 0] + 1j * zk[:, 1]
    hk = np.array([p["gnss_B_L_h"][2] for p in chk])
    wk = t + k * (zk - zc)
    Hk = hk + np.column_stack([np.ones(len(zk)), (zk - zc).real, (zk - zc).imag]) @ cv
    d_pred = float(np.abs(np.column_stack([wk.real, wk.imag, Hk]) - e["predicted_check_x_y_H"]).max())
    # Блок truth: H = h − ζ(B, L) с точностью до шума (ζ по формуле, B, L — СК-42 от центра участка);
    # на этом основаны тестовые сетки геоида (tools/make_geoid_test_grids.py).
    ha = task["truth"]["height_anomaly"]
    pts = ctrl + chk
    g = np.array([p["gnss_B_L_h"] for p in pts])
    Bs, Ls, _ = datums.transform_blh(g[:, 0], g[:, 1], g[:, 2], "PZ-90.11", "SK-42")
    b0, l0 = ha["center_B_L_sk42"]
    dn, de = (Bs - b0) * 111_000, (Ls - l0) * 111_000 * np.cos(np.radians(b0))
    zeta = ha["zeta0"] + ha["gN"] * dn + ha["gE"] * de + ha["curvature"] * (dn ** 2 - de ** 2)
    d_zeta = float(np.abs(np.array([p["local_x_y_H"][2] for p in pts]) - (g[:, 2] - zeta)).max())
    tol = task["tolerance"]["coordinates_m"]
    ok = d_proj < tol and d_par < 1e-9 and d_t < 1e-6 and d_v < 1e-9 and d_pred < tol and d_zeta < 0.1
    return ok, (f"site: proj={d_proj:.1e} par={d_par:.1e} t={d_t:.1e} vert={d_v:.1e} pred={d_pred:.1e} "
                f"|H-(h-ζ)|={d_zeta:.3f}")


def check_parameters():
    data = json.loads((GEO / "gost_32453_parameters.json").read_text(encoding="utf-8"))
    keys = ("dX", "dY", "dZ", "wx", "wy", "wz", "m")
    bad = [t["appendix"] for t, p in zip(data["transformations"], datums.TRANSFORMATIONS)
           if [t[k] for k in keys] != [getattr(p, k) for k in keys] or t.get("epoch") != p.epoch]
    ok = not bad and len(data["transformations"]) == len(datums.TRANSFORMATIONS)
    return ok, f"{len(data['transformations'])} наборов = mathdatum.datums" + (f"; расходятся: {bad}" if bad else "")


def check_gost_example():
    ex = json.loads((GEO / "gost_32453_control_example.json").read_text(encoding="utf-8"))
    s = ex["steps"]
    x0 = np.array(s["input_itrf2008_epoch_2005"]["xyz"])
    v = np.array(s["input_itrf2008_epoch_2005"]["velocity"])
    x1 = datums.propagate_epoch(x0, v, 2005.0, 2010.0)
    d1 = float(np.abs(x1 - s["itrf2008_epoch_2010"]["xyz"]).max())
    # Шаг 2: ITRF-2008 → ПЗ-90.11 (обратный Д.1, эпоха 2010); шаг 3: перенос на 2013.9 той же скоростью.
    x2 = datums.transform_xyz(x0, "ITRF-2008", "PZ-90.11", epoch=2005.0, velocity=v)
    d2 = float(np.abs(x2 - s["pz9011_epoch_2010"]["xyz"]).max())
    x3 = datums.transform_xyz(x0, "ITRF-2008", "PZ-90.11", epoch=2005.0, velocity=v, target_epoch=2013.9)
    d3 = float(np.abs(x3 - s["pz9011_epoch_2013_9"]["xyz"]).max())
    # Допуски — по разрядам значений в ГОСТ: 1 мм (шаги 1, 3), 0.1 мм (шаг 2).
    ok = d1 < 1e-3 and d2 < 1e-4 and d3 < 1e-3
    return ok, (f"шаг 1 (эпоха 2005→2010) max|Δ|={d1:.1e} м; шаг 2 (ITRF-2008→ПЗ-90.11) {d2:.1e} м; "
                f"шаг 3 (эпоха 2010→2013.9) {d3:.1e} м")


def main():
    ok_all = True
    ok, msg = check_parameters()
    ok_all &= ok
    print(f"[{'OK' if ok else 'FAIL'}] ГОСТ 32453 параметры: {msg}")
    ok, msg = check_gost_example()
    ok_all &= ok
    print(f"[{'OK' if ok else 'FAIL'}] ГОСТ 32453 контрольный пример: {msg}")
    files = sorted((GEO / "regions").glob("*.json"))
    n_fail = 0
    for f in files:
        case = json.loads(f.read_text(encoding="utf-8"))
        msgs = []
        for task in case["tasks"]:
            ok, msg = (check_helmert if task["type"] == "helmert_7p" else check_site)(task)
            msgs.append(msg)
            if not ok:
                n_fail += 1
                print(f"[FAIL] {f.stem}: {msg}")
        if f is files[0]:
            print(f"[пример] {f.stem}: " + " | ".join(msgs))
    ok_all &= n_fail == 0
    print(f"[{'OK' if n_fail == 0 else 'FAIL'}] регионов: {len(files)}, задач с ошибкой: {n_fail}")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
