"""Сравнение результатов gsimath (вывод LocalizationCheck) с эталоном data/geodetic.

Запуск:  python tools/kotlin_check/compare.py <kt_out.txt> [report.csv]
"""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]


def reference_subset(ctrl, check):
    """Эталонный МНК (подобие + плоскость высот) по первым опорным точкам.
    При 1 точке — только сдвиг в плане; при < 3 точках по высоте — только сдвиг."""
    ne = np.array([p["work_N_E"] for p in ctrl])
    xyH = np.array([p["local_x_y_H"] for p in ctrl])
    h = np.array([p["gnss_B_L_h"][2] for p in ctrl])
    ne_k = np.array([p["work_N_E"] for p in check])
    h_k = np.array([p["gnss_B_L_h"][2] for p in check])
    z, w = ne[:, 0] + 1j * ne[:, 1], xyH[:, 0] + 1j * xyH[:, 1]
    zc = z.mean()
    k = 1.0 if len(z) < 2 else np.sum(np.conj(z - zc) * (w - w.mean())) / np.sum(np.abs(z - zc) ** 2)
    t = w.mean()
    zk = ne_k[:, 0] + 1j * ne_k[:, 1]
    wk = t + k * (zk - zc)
    dz = z - zc
    if len(z) >= 3:
        A = np.column_stack([np.ones(len(z)), dz.real, dz.imag])
        cv = np.linalg.lstsq(A, xyH[:, 2] - h, rcond=None)[0]
    else:
        cv = np.array([np.mean(xyH[:, 2] - h), 0.0, 0.0])
    A = np.column_stack([np.ones(len(z)), dz.real, dz.imag])
    res_p = w - (t + k * dz)
    res_h = xyH[:, 2] - h - A @ cv
    Hk = h_k + np.column_stack([np.ones(len(zk)), (zk - zc).real, (zk - zc).imag]) @ cv
    return (np.column_stack([wk.real, wk.imag, Hk]),
            float(np.sqrt(np.mean(np.abs(res_p) ** 2))), float(np.sqrt(np.mean(res_h ** 2))))


def main():
    out = defaultdict(lambda: {"C": [], "K": [], "status": None})
    for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
        s = line.split()
        if len(s) < 2:
            continue
        iso, st = s[0], s[1]
        if st == "OK":
            out[iso][s[2]].append([float(v) for v in s[3:]])
        elif st != "INFO":
            out[iso]["status"] = " ".join(s[1:])

    rows = []
    for f in sorted((ROOT / "data/geodetic/regions").glob("*.json")):
        case = json.loads(f.read_text(encoding="utf-8"))
        iso = case["region"]["iso_3166_2"]
        site = next(t for t in case["tasks"] if t["type"] == "site_localization")
        e = site["expected"]
        r = out.get(iso)
        if r is None or r["status"] or not r["C"]:
            rows.append({"iso": iso, "status": (r or {}).get("status") or "нет результата"})
            continue
        C, K = np.array(r["C"]), np.array(r["K"])
        m = len(C)  # сколько опорных точек отдали библиотеке
        ctrl = site["control_points"][:m]
        cat_c = np.array([p["local_x_y_H"] for p in ctrl])
        cat_k = np.array([p["local_x_y_H"] for p in site["check_points"]])
        if m == len(site["control_points"]):
            ref_k = np.array(e["predicted_check_x_y_H"])
            ref_rms_plan, ref_rms_h = e["rms_horizontal_m"], e["rms_vertical_m"]
        else:
            ref_k, ref_rms_plan, ref_rms_h = reference_subset(ctrl, site["check_points"])
        # C/K: resLat resLon resH | act x y H | two x y H
        act_c, two_c = C[:, 3:6], C[:, 6:9]
        act_k, two_k = K[:, 3:6], K[:, 6:9]

        def plan(a, b):
            return float(np.sqrt(np.mean(np.sum((a[:, :2] - b[:, :2]) ** 2, axis=1))))

        def hgt(a, b):
            return float(np.sqrt(np.mean((a[:, 2] - b[:, 2]) ** 2)))

        rows.append({
            "iso": iso, "status": "OK",
            # Невязки на опорных: что вернула библиотека и что получается пересчётом.
            "lib_res_plan": float(np.sqrt(np.mean(C[:, 0] ** 2 + C[:, 1] ** 2))),
            "lib_res_H": float(np.sqrt(np.mean(C[:, 2] ** 2))),
            "ref_res_plan": ref_rms_plan, "ref_res_H": ref_rms_h,
            "ctrl_plan": plan(act_c, cat_c),
            # Контрольные точки: ошибка относительно каталога и отличие от эталонного МНК.
            "chk_plan": plan(act_k, cat_k), "ref_chk_plan": plan(ref_k, cat_k),
            "chk_vs_ref_plan": plan(act_k, ref_k),
            "chk_H_app": hgt(act_k, cat_k), "chk_H_two": hgt(two_k, cat_k), "ref_chk_H": hgt(ref_k, cat_k),
            "chk_vs_ref_H_two": hgt(two_k, ref_k),
        })

    ok = [r for r in rows if r["status"] == "OK"]
    keys = [k for k in ok[0] if k not in ("iso", "status")] if ok else []
    print(f"регионов: {len(rows)}, успешно: {len(ok)}, ошибок: {len(rows) - len(ok)}")
    for r in rows:
        if r["status"] != "OK":
            print(f"  {r['iso']}: {r['status']}")
    print(f"{'метрика (м)':<20}{'медиана':>12}{'максимум':>12}")
    for k in keys:
        v = np.array([r[k] for r in ok])
        print(f"{k:<20}{np.median(v):>12.4f}{v.max():>12.4f}")
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["iso", "status"] + keys, delimiter=";")
            w.writeheader()
            for r in rows:
                w.writerow({k: (f"{v:.5f}" if isinstance(v, float) else v) for k, v in r.items()})


if __name__ == "__main__":
    main()
