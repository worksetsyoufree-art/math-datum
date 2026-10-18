"""Локализация ГНСС: пары точек WGS-84 ↔ местная система → датум → пересчёты.

Модель (как в полевом ПО):
  1. Рабочая проекция — поперечный Меркатор на эллипсоиде WGS-84 с осевым
     меридианом в центре точек: (B, L) → (N, E).
  2. План — преобразование подобия (4 параметра) относительно центроида:
        [x, y] = [tx, ty] + [[a, -b], [b, a]] · ([N, E] - [Nc, Ec])
     масштаб = sqrt(a² + b²), разворот = atan2(b, a).
  3. Высота — наклонная плоскость (3 параметра):
        H = h + c0 + c1·(N - Nc) + c2·(E - Ec)

Все подгонки — линейный МНК в замкнутой форме, без итераций.
Если точек мало, модель упрощается автоматически:
  план:   1 точка → только сдвиг (масштаб 1, разворот 0); ≥ 2 → подобие;
  высота: 1–2 точки → только сдвиг c0; ≥ 3 → плоскость.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from pyproj import Transformer

WGS84 = "+ellps=WGS84"
ARCSEC = math.pi / (180 * 3600)

USE_BOTH, USE_PLAN, USE_HEIGHT, USE_NONE = "both", "plan", "height", "none"


@dataclass
class Pair:
    """Пара точек: ГНСС (B, L в градусах, h — эллипсоидальная высота) и местные x (север), y (восток), H."""

    name: str
    B: float
    L: float
    h: float
    x: float
    y: float
    H: float
    use: str = USE_BOTH

    @property
    def in_plan(self) -> bool:
        return self.use in (USE_BOTH, USE_PLAN)

    @property
    def in_height(self) -> bool:
        return self.use in (USE_BOTH, USE_HEIGHT)


@dataclass
class Residual:
    name: str
    use: str
    dx: float
    dy: float
    dH: float


@dataclass
class LocalizationDatum:
    """Результат локализации. Сохраняется в JSON и выполняет пересчёты в обе стороны."""

    # Рабочая проекция.
    lat0: float
    lon0: float
    # План: центроид (N, E) рабочей проекции и параметры подобия.
    Nc: float
    Ec: float
    a: float
    b: float
    tx: float
    ty: float
    # Высота.
    c0: float
    c1: float
    c2: float
    ellipsoid: str = WGS84  # эллипсоид рабочей проекции в синтаксисе PROJ
    plan_model: str = "similarity"
    height_model: str = "plane"
    residuals: list[Residual] = field(default_factory=list)
    rms_plan: float | None = None
    rms_height: float | None = None

    # --- свойства для отчёта ---
    @property
    def scale(self) -> float:
        return math.hypot(self.a, self.b)

    @property
    def scale_ppm(self) -> float:
        return (self.scale - 1) * 1e6

    @property
    def rotation_arcsec(self) -> float:
        return math.atan2(self.b, self.a) / ARCSEC

    @property
    def projection(self) -> str:
        return f"+proj=tmerc +lat_0={self.lat0!r} +lon_0={self.lon0!r} +k=1 +x_0=0 +y_0=0 {self.ellipsoid} +units=m"

    def _proj(self) -> Transformer:
        return Transformer.from_pipeline(
            f"+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step {self.projection}")

    # --- пересчёты ---
    def to_local(self, B, L, h):
        """WGS-84 (B, L градусы, h) → местные (x, y, H). Принимает числа или массивы."""
        B, L, h = np.asarray(B, float), np.asarray(L, float), np.asarray(h, float)
        E, N = self._proj().transform(L, B)
        dN, dE = N - self.Nc, E - self.Ec
        x = self.tx + self.a * dN - self.b * dE
        y = self.ty + self.b * dN + self.a * dE
        H = h + self.c0 + self.c1 * dN + self.c2 * dE
        return x, y, H

    def to_wgs(self, x, y, H):
        """Местные (x, y, H) → WGS-84 (B, L градусы, h)."""
        x, y, H = np.asarray(x, float), np.asarray(y, float), np.asarray(H, float)
        k2 = self.a ** 2 + self.b ** 2
        u, v = x - self.tx, y - self.ty
        dN = (self.a * u + self.b * v) / k2
        dE = (-self.b * u + self.a * v) / k2
        L, B = self._proj().transform(dE + self.Ec, dN + self.Nc, direction="INVERSE")
        h = H - (self.c0 + self.c1 * dN + self.c2 * dE)
        return B, L, h

    def to_proj_pipeline(self) -> str:
        """Строка PROJ для пересчёта WGS-84 (широта, долгота, h) → местные (x, y, H).
        Подходит для pyproj, cs2cs, QGIS. На выходе порядок: x (север), y (восток), H."""
        # После tmerc: X = E, Y = N. Аффинное преобразование (PROJ: x' = xoff + s11·x + s12·y + s13·z, ...).
        # Местные: x = tx + a·(N-Nc) - b·(E-Ec);  y = ty + b·(N-Nc) + a·(E-Ec);  H = h + c0 + c1·(N-Nc) + c2·(E-Ec).
        a, b = self.a, self.b
        xoff = self.tx - a * self.Nc + b * self.Ec
        yoff = self.ty - b * self.Nc - a * self.Ec
        zoff = self.c0 - self.c1 * self.Nc - self.c2 * self.Ec
        return (
            "+proj=pipeline +step +proj=axisswap +order=2,1 "
            "+step +proj=unitconvert +xy_in=deg +xy_out=rad "
            f"+step {self.projection} "
            f"+step +proj=affine +xoff={xoff!r} +s11={-b!r} +s12={a!r} +s13=0 "
            f"+yoff={yoff!r} +s21={a!r} +s22={b!r} +s23=0 "
            f"+zoff={zoff!r} +s31={self.c2!r} +s32={self.c1!r} +s33=1"
        )

    # --- сохранение ---
    def to_dict(self) -> dict:
        d = asdict(self)
        d["summary"] = {
            "scale": self.scale, "scale_ppm": self.scale_ppm, "rotation_arcsec": self.rotation_arcsec,
            "projection": self.projection, "proj_pipeline_wgs_to_local": self.to_proj_pipeline(),
        }
        return d

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "LocalizationDatum":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        d.pop("summary", None)
        d["residuals"] = [Residual(**r) for r in d.get("residuals", [])]
        return cls(**d)


class LocalizationError(ValueError):
    pass


def localize(pairs: list[Pair], lat0: float | None = None, lon0: float | None = None,
             ellipsoid: str = WGS84) -> LocalizationDatum:
    """Вычисляет датум локализации по парам точек.

    lat0, lon0 — центр рабочей проекции; по умолчанию — среднее по всем используемым точкам.
    ellipsoid — эллипсоид рабочей проекции (PROJ), по умолчанию WGS-84.
    """
    plan = [p for p in pairs if p.in_plan]
    height = [p for p in pairs if p.in_height]
    if not plan:
        raise LocalizationError("Нет ни одной точки для плана (use = both/plan).")
    used = [p for p in pairs if p.use != USE_NONE]
    if lat0 is None:
        lat0 = float(np.mean([p.B for p in used]))
    if lon0 is None:
        lon0 = float(np.mean([p.L for p in used]))

    datum = LocalizationDatum(lat0=lat0, lon0=lon0, Nc=0, Ec=0, a=1, b=0, tx=0, ty=0, c0=0, c1=0, c2=0,
                              ellipsoid=ellipsoid)
    proj = datum._proj()

    def ne(points):
        E, N = proj.transform([p.L for p in points], [p.B for p in points])
        return np.asarray(N, float), np.asarray(E, float)

    # План: подобие в комплексной форме w = t + k·(z - zc), z = N + iE, w = x + iy.
    N, E = ne(plan)
    z = N + 1j * E
    w = np.array([p.x + 1j * p.y for p in plan])
    zc, wc = z.mean(), w.mean()
    if len(plan) >= 2:
        denom = np.sum(np.abs(z - zc) ** 2)
        if denom < 1e-6:
            raise LocalizationError("Точки для плана совпадают: нельзя определить разворот и масштаб.")
        k = np.sum(np.conj(z - zc) * (w - wc)) / denom
        datum.plan_model = "similarity"
    else:
        k = 1.0 + 0j
        datum.plan_model = "shift"
    datum.Nc, datum.Ec = float(zc.real), float(zc.imag)
    datum.a, datum.b = float(k.real), float(k.imag)
    datum.tx, datum.ty = float(wc.real), float(wc.imag)

    # Высота: плоскость относительно того же центроида.
    if height:
        Nh, Eh = ne(height)
        dN, dE = Nh - datum.Nc, Eh - datum.Ec
        dh = np.array([p.H - p.h for p in height])
        A = np.column_stack([np.ones(len(height)), dN, dE])
        if len(height) >= 3 and np.linalg.matrix_rank(A, tol=1e-3) == 3:
            datum.c0, datum.c1, datum.c2 = (float(v) for v in np.linalg.lstsq(A, dh, rcond=None)[0])
            datum.height_model = "plane"
        else:
            datum.c0, datum.c1, datum.c2 = float(dh.mean()), 0.0, 0.0
            datum.height_model = "shift"
    else:
        datum.height_model = "none"

    # Невязки (каталог минус вычисленное) по всем точкам. Для точек, не участвовавших
    # в подгонке, это ошибка контроля; в СКО они не входят.
    sp, sh = [], []
    for p in pairs:
        x, y, H = datum.to_local(p.B, p.L, p.h)
        r = Residual(p.name, p.use, float(p.x - x), float(p.y - y), float(p.H - H))
        datum.residuals.append(r)
        if p.in_plan:
            sp.append(r.dx ** 2 + r.dy ** 2)
        if p.in_height:
            sh.append(r.dH ** 2)
    datum.rms_plan = float(math.sqrt(np.mean(sp))) if sp else None
    datum.rms_height = float(math.sqrt(np.mean(sh))) if sh else None
    return datum
