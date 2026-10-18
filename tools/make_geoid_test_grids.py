"""Маленькие синтетические сетки высот геоида для тестов (Python и Kotlin).

  python tools/make_geoid_test_grids.py

Пишет tests/data/geoid/ (GGF — основной формат, Trimble; GTX и ISG — те же значения):
  RU-MOW_truth.ggf, .gtx, .isg — аномалия высоты ζ участка RU-MOW из блока truth генератора
      data/geodetic (ζ = ζ0 + gN·dN + gE·dE + 1e-10·(dN² − dE²), dN, dE — от центра в СК-42) в узлах
      по координатам ПЗ-90.11 (система ГНСС участка), шаг 1′; ISG — те же значения (6 знаков);
  RU-MOW_bump.ggf, .gtx — та же ζ плюс «бугор» геоида BUMP_A·exp(−r²/(2·BUMP_S²)) (неплоская часть), шаг 15″;
  nodata.ggf, .gtx, .isg — сетка 5×6 с одним узлом NODATA (края, NODATA, вне сетки).

Сами большие модели (EGM2008 и т. п.) в репозиторий не кладутся.
"""

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from mathdatum import datums  # noqa: E402
from mathdatum.geoid import GeoidGrid  # noqa: E402

OUT = ROOT / "tests" / "data" / "geoid"
BUMP_A, BUMP_S = 0.50, 2000.0       # м: амплитуда и радиус «бугра»
BUMP_SHIFT = (1200.0, -800.0)        # м: центр бугра относительно центра участка (север, восток)


def site_task(iso: str) -> dict:
    case = json.loads((ROOT / f"data/geodetic/regions/{iso}.json").read_text(encoding="utf-8"))
    return next(t for t in case["tasks"] if t["type"] == "site_localization")


def site_points(task):
    return np.array([p["gnss_B_L_h"] for p in task["control_points"] + task["check_points"]])


def truth_zeta(task, B, L, h=150.0):
    """ζ(B, L) по блоку truth; B, L — ПЗ-90.11 (переводятся в СК-42 по ГОСТ, как в генераторе)."""
    ha = task["truth"]["height_anomaly"]
    b0, l0 = ha["center_B_L_sk42"]
    Bs, Ls, _ = datums.transform_blh(np.asarray(B, float), np.asarray(L, float), np.full(np.shape(B), h),
                                     "PZ-90.11", "SK-42")
    dn = (Bs - b0) * 111_000
    de = (Ls - l0) * 111_000 * np.cos(np.radians(b0))
    return ha["zeta0"] + ha["gN"] * dn + ha["gE"] * de + ha["curvature"] * (dn ** 2 - de ** 2)


def bump(task, B, L):
    """Неплоская добавка к ζ, м (гауссов «бугор» у центра участка)."""
    pts = site_points(task)
    b0, l0 = pts[:, 0].mean(), pts[:, 1].mean()
    dn = (np.asarray(B, float) - b0) * 111_000 - BUMP_SHIFT[0]
    de = (np.asarray(L, float) - l0) * 111_000 * np.cos(np.radians(b0)) - BUMP_SHIFT[1]
    return BUMP_A * np.exp(-(dn ** 2 + de ** 2) / (2 * BUMP_S ** 2))


def site_grid(task, step_deg, field="truth", margin_deg=0.03, name="grid"):
    """Сетка, покрывающая пункты участка с запасом margin_deg; узлы кратны шагу."""
    pts = site_points(task)
    b0 = np.floor((pts[:, 0].min() - margin_deg) / step_deg) * step_deg
    b1 = np.ceil((pts[:, 0].max() + margin_deg) / step_deg) * step_deg
    k = 1 / np.cos(np.radians(pts[:, 0].mean()))
    l0 = np.floor((pts[:, 1].min() - margin_deg * k) / step_deg) * step_deg
    l1 = np.ceil((pts[:, 1].max() + margin_deg * k) / step_deg) * step_deg
    rows, cols = int(round((b1 - b0) / step_deg)) + 1, int(round((l1 - l0) / step_deg)) + 1
    B, L = np.meshgrid(b0 + step_deg * np.arange(rows), l0 + step_deg * np.arange(cols), indexing="ij")
    v = truth_zeta(task, B, L)
    if field == "bump":
        v = v + bump(task, B, L)
    # Значения — как их хранит GTX (float32), чтобы сетка в памяти и в файле совпадали.
    return GeoidGrid(b0, l0, step_deg, step_deg, v.astype(np.float32).astype(float), name=name)


def nodata_grid():
    lat = 55.0 + 0.25 * np.arange(5)
    lon = 37.0 + 0.5 * np.arange(6)
    v = 14.0 + 0.8 * (lat[:, None] - 55) - 0.3 * (lon[None, :] - 37) + 0.05 * np.sin(3 * lat[:, None]) * np.cos(2 * lon[None, :])
    v = v.astype(np.float32).astype(float)
    v[3, 4] = np.nan                      # B = 55.75, L = 39.0
    return GeoidGrid(55.0, 37.0, 0.25, 0.5, v, name="nodata")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    task = site_task("RU-MOW")
    g = site_grid(task, 1 / 60)
    (OUT / "RU-MOW_truth.ggf").write_bytes(g.to_ggf("RU-MOW synthetic truth"))
    (OUT / "RU-MOW_truth.gtx").write_bytes(g.to_gtx())
    (OUT / "RU-MOW_truth.isg").write_text(g.to_isg("RU-MOW synthetic truth"), encoding="utf-8")
    gb = site_grid(task, 1 / 240, "bump")
    (OUT / "RU-MOW_bump.ggf").write_bytes(gb.to_ggf("RU-MOW synthetic bump"))
    (OUT / "RU-MOW_bump.gtx").write_bytes(gb.to_gtx())
    n = nodata_grid()
    (OUT / "nodata.ggf").write_bytes(n.to_ggf("nodata test"))
    (OUT / "nodata.gtx").write_bytes(n.to_gtx())
    (OUT / "nodata.isg").write_text(n.to_isg("nodata test"), encoding="utf-8")
    for f in sorted(OUT.iterdir()):
        print(f"{f.relative_to(ROOT)}: {f.stat().st_size} байт")


if __name__ == "__main__":
    main()
