"""Независимая проверка геодезических датасетов data/geodetic/regions/*.json.

- helmert_7p (exact): сравнение с реализацией PROJ (+proj=helmert convention=coordinate_frame);
- helmert_7p (noisy): решение МНК итерациями Гаусса–Ньютона с нуля, сравнение прогноза;
- site_localization: пересчёт рабочей проекции через PROJ, подобие — в комплексной
  форме (z' = t + w·z), высоты — отдельный МНК.

Запуск:  python tools/verify_geodetic.py
"""

import json
import sys
from pathlib import Path

import numpy as np
from pyproj import Transformer

GEO = Path(__file__).resolve().parent.parent / "data" / "geodetic"
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
    rms_given = float(np.sqrt(np.mean(np.sum((x2 - pred) ** 2, axis=1) / 3)))
    fit, q = solve_helmert(x1, x2)
    # Решение МНК должно давать те же координаты, что и параметры ГОСТ.
    dpred = float(np.abs(fit - pred).max())
    dm = abs(q[6] * 1e6 - p["m"])
    if task["variant"] == "exact":
        ok = rms_given < 1e-4 and dpred < 1e-4 and dm < 1e-3
    else:
        ok = abs(rms_given - task["expected"]["rms_residual_m"]) < 2e-4 and dpred < 1e-3 and dm < 1e-2
    return ok, f"{task['variant']}: rms={rms_given:.4f} |LSQ-ГОСТ|={dpred:.1e} dm={dm:.1e}ppm"


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
    tol = task["tolerance"]["coordinates_m"]
    ok = d_proj < tol and d_par < 1e-9 and d_t < 1e-6 and d_v < 1e-9 and d_pred < tol
    return ok, f"site: proj={d_proj:.1e} par={d_par:.1e} t={d_t:.1e} vert={d_v:.1e} pred={d_pred:.1e}"


def check_gost_example():
    ex = json.loads((GEO / "gost_32453_control_example.json").read_text(encoding="utf-8"))
    s = ex["steps"]
    x0 = np.array(s["input_itrf2008_epoch_2005"]["xyz"])
    v = np.array(s["input_itrf2008_epoch_2005"]["velocity"])
    x1 = x0 + v * (2010.0 - 2005.0)
    d1 = float(np.abs(x1 - s["itrf2008_epoch_2010"]["xyz"]).max())
    return d1 < 1e-3, f"шаг 1 (перенос эпохи 2005→2010): max|Δ|={d1:.1e} м"


def main():
    ok_all = True
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
