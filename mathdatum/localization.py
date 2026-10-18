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

Надёжность (диагностика, точки автоматически не исключаются):
  избыточность  r_plan = 2n − 4 (сдвиг: 2n − 2),  r_height = n − 3 (сдвиг: n − 1);
  кофакторы параметров  Q = (AᵀA)⁻¹;  ковариация  C = σ²·Q,  σ — априорная (sigma_plan,
     sigma_height — СКО одной координаты) или апостериорная  s0 = sqrt(Σv² / r);
  поправка точки  v = каталог − вычисленное,  кофактор  q_vv = 1 − aᵀQa  (для точек вне
     подгонки — ошибка прогноза, q_vv = 1 + aᵀQa), a — строка матрицы плана;
  нормированная поправка (тест Баарда)  w = v / (σ·sqrt(q_vv)),  |w| > w_limit (3.29) → подозрение;
  ошибка с исключением (leave-one-out) — прогноз датумом без этой точки,  v_loo = v / q_vv;
  СКО прогноза в точке  m = σ·sqrt(aᵀQa)  (план: радиальная, по x и y);
  экстраполяция — расстояние от точки до выпуклой оболочки опорных пунктов плана.
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
    """Невязка (каталог − вычисленное) и диагностика точки. None — величина не определена
    (точка не участвует в этой части, нет избыточности или без точки модель вырождается)."""

    name: str
    use: str
    dx: float
    dy: float
    dH: float
    qvv_plan: float | None = None    # кофактор поправки по x (= по y)
    qvv_height: float | None = None
    wx: float | None = None          # нормированные поправки (априорная σ)
    wy: float | None = None
    wH: float | None = None
    loo_dx: float | None = None      # ошибка прогноза без этой точки (для контрольных — сама невязка)
    loo_dy: float | None = None
    loo_dH: float | None = None
    suspect: bool = False            # |w| > w_limit: вероятна грубая ошибка

    @property
    def w_plan(self) -> float | None:
        return None if self.wx is None else max(abs(self.wx), abs(self.wy))

    @property
    def loo_plan(self) -> float | None:
        return None if self.loo_dx is None else math.hypot(self.loo_dx, self.loo_dy)


@dataclass
class DatumWarning:
    """Предупреждение о качестве датума. code — для программ, message — для человека."""

    code: str
    message: str
    point: str | None = None


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
    # Надёжность (в старых JSON отсутствует → None).
    redundancy_plan: int | None = None
    redundancy_height: int | None = None
    sigma0_plan: float | None = None      # априорная СКО одной координаты в плане, м
    sigma0_height: float | None = None    # априорная СКО высоты, м
    s0_plan: float | None = None          # апостериорная СКО (на одну координату), None при r = 0
    s0_height: float | None = None
    w_limit: float | None = None
    q_plan: list[list[float]] | None = None    # кофакторы (tx, ty, a, b), 4×4
    q_height: list[list[float]] | None = None  # кофакторы (c0, c1, c2), 3×3
    plan_hull: list[list[float]] | None = None # выпуклая оболочка опорных пунктов плана, [N, E]
    warnings: list[DatumWarning] = field(default_factory=list)

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

    # --- точность и экстраполяция ---
    def _dne_wgs(self, B, L):
        E, N = self._proj().transform(np.asarray(L, float), np.asarray(B, float))
        return np.asarray(N, float) - self.Nc, np.asarray(E, float) - self.Ec

    def _dne_local(self, x, y):
        k2 = self.a ** 2 + self.b ** 2
        u, v = np.asarray(x, float) - self.tx, np.asarray(y, float) - self.ty
        return (self.a * u + self.b * v) / k2, (-self.b * u + self.a * v) / k2

    def _sigma(self, posterior: bool):
        if posterior:
            return self.s0_plan, self.s0_height
        return self.sigma0_plan, self.sigma0_height

    def covariance_plan(self, posterior: bool = False) -> np.ndarray | None:
        """Ковариация параметров плана (tx, ty, a, b): σ²·Q."""
        s = self._sigma(posterior)[0]
        return None if s is None or self.q_plan is None else s * s * np.array(self.q_plan)

    def covariance_height(self, posterior: bool = False) -> np.ndarray | None:
        """Ковариация параметров высоты (c0, c1, c2): σ²·Q."""
        s = self._sigma(posterior)[1]
        return None if s is None or self.q_height is None else s * s * np.array(self.q_height)

    def _quality(self, dN, dE, posterior):
        dN, dE = np.asarray(dN, float), np.asarray(dE, float)
        sp, sh = self._sigma(posterior)
        nan = np.full(dN.shape, np.nan)
        m_plan = nan if sp is None or self.q_plan is None else sp * np.sqrt(
            _qform(self.q_plan, (1, 0, dN, -dE)) + _qform(self.q_plan, (0, 1, dE, dN)))
        m_h = nan if sh is None or self.q_height is None else sh * np.sqrt(_qform(self.q_height, (1, dN, dE)))
        out = nan if not self.plan_hull else _outside(self.plan_hull, dN + self.Nc, dE + self.Ec)
        return out, m_plan, m_h

    def quality_wgs(self, B, L, posterior: bool = False):
        """Для точек WGS-84 → (вне оболочки, м; СКО прогноза в плане, м; по высоте, м).
        Расстояние 0 — внутри оболочки опорных пунктов; nan — не определено (старый датум)."""
        return self._quality(*self._dne_wgs(B, L), posterior)

    def quality_local(self, x, y, posterior: bool = False):
        """То же для точек в местной системе."""
        return self._quality(*self._dne_local(x, y), posterior)

    def prediction_sigma(self, B, L, posterior: bool = False):
        """СКО прогноза (план — радиальная, высота) в точке B, L: m = σ·sqrt(aᵀQa)."""
        return self.quality_wgs(B, L, posterior)[1:]

    def outside_distance(self, B, L):
        """Расстояние (м) от точки до выпуклой оболочки опорных пунктов плана; 0 внутри."""
        return self.quality_wgs(B, L)[0]

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
        d["warnings"] = [DatumWarning(**w) for w in d.get("warnings", [])]
        return cls(**d)


class LocalizationError(ValueError):
    pass


def localize(pairs: list[Pair], lat0: float | None = None, lon0: float | None = None,
             ellipsoid: str = WGS84, sigma_plan: float = 0.02, sigma_height: float = 0.03,
             w_limit: float = 3.29, max_scale_ppm: float = 200.0,
             max_rotation_deg: float = 1.0) -> LocalizationDatum:
    """Вычисляет датум локализации по парам точек.

    lat0, lon0 — центр рабочей проекции; по умолчанию — среднее по всем используемым точкам.
    ellipsoid — эллипсоид рабочей проекции (PROJ), по умолчанию WGS-84.
    sigma_plan, sigma_height — априорные СКО (м) одной координаты плана и высоты для теста Баарда
    и ковариаций; w_limit — порог |w| (3.29 ≈ α = 0.001, двусторонний).
    max_scale_ppm, max_rotation_deg — пределы правдоподобия масштаба и разворота.
    """
    datum = _fit(pairs, lat0, lon0, ellipsoid)
    _diagnose(datum, pairs, sigma_plan, sigma_height, w_limit, max_scale_ppm, max_rotation_deg)
    return datum


def _fit(pairs, lat0, lon0, ellipsoid) -> LocalizationDatum:
    """Подгонка параметров и невязки, без диагностики."""
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
        # Плоскость определена, если точки не лежат на одной линии: det ковариации (dN, dE)
        # не мал относительно её следа (тот же критерий, что в Kotlin-модуле).
        u, v = dN - dN.mean(), dE - dE.mean()
        snn, see, sne = u @ u, v @ v, u @ v
        trace, det = snn + see, snn * see - sne * sne
        if len(height) >= 3 and trace > 0 and det > 1e-12 * trace * trace:
            A = np.column_stack([np.ones(len(height)), dN, dE])
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


Q_EPS = 1e-8  # q_vv меньше — у точки нет контроля (без неё модель вырождается)


def _qform(Q, a):
    """aᵀ·Q·a; элементы a — числа или массивы."""
    return sum(Q[i][j] * a[i] * a[j] for i in range(len(a)) for j in range(len(a)))


def _cofactors(datum: LocalizationDatum, pairs: list[Pair]):
    """Q = (AᵀA)⁻¹ для плана (tx, ty, a, b) и высоты (c0, c1, c2) в замкнутой форме.

    План (координаты относительно центроида, Σ dN = Σ dE = 0): AᵀA = diag(n, n, S, S),
    S = Σ (dN² + dE²); для модели «сдвиг» — diag(1/n, 1/n, 0, 0).
    Высота: m = средние (dN, dE) по точкам высоты, K = ковариация (u, v) = (dN − mN, dE − mE):
        Q[c1,c2] = K⁻¹,  Q[c0,c·] = −K⁻¹m,  Q[c0,c0] = 1/n + mᵀK⁻¹m;  «сдвиг» — Q[c0,c0] = 1/n.
    """
    plan = [p for p in pairs if p.in_plan]
    proj = datum._proj()
    E, N = proj.transform([p.L for p in plan], [p.B for p in plan])
    dN, dE = np.asarray(N, float) - datum.Nc, np.asarray(E, float) - datum.Ec
    n = len(plan)
    if datum.plan_model == "similarity":
        S = float(np.sum(dN ** 2 + dE ** 2))
        qp = [[1 / n, 0, 0, 0], [0, 1 / n, 0, 0], [0, 0, 1 / S, 0], [0, 0, 0, 1 / S]]
    else:
        qp = [[1 / n, 0, 0, 0], [0, 1 / n, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
    qp = [[float(v) for v in row] for row in qp]
    height = [p for p in pairs if p.in_height]
    qh = None
    if height:
        E, N = proj.transform([p.L for p in height], [p.B for p in height])
        hn, he = np.asarray(N, float) - datum.Nc, np.asarray(E, float) - datum.Ec
        nh = len(height)
        if datum.height_model == "plane":
            mn, me = float(hn.mean()), float(he.mean())
            u, v = hn - mn, he - me
            snn, see, sne = float(u @ u), float(v @ v), float(u @ v)
            det = snn * see - sne * sne
            k11, k22, k12 = see / det, snn / det, -sne / det
            g1, g2 = k11 * mn + k12 * me, k12 * mn + k22 * me   # K⁻¹m
            qh = [[1 / nh + mn * g1 + me * g2, -g1, -g2], [-g1, k11, k12], [-g2, k12, k22]]
        else:
            qh = [[1 / nh, 0.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]
    return qp, qh


def _without(pairs: list[Pair], i: int, part: str) -> list[Pair]:
    """Копия пар, где точка i исключена из плана (part = "plan") или из высоты."""
    p = pairs[i]
    if part == "plan":
        use = USE_HEIGHT if p.in_height else USE_NONE
    else:
        use = USE_PLAN if p.in_plan else USE_NONE
    return [Pair(**{**asdict(q), "use": use}) if j == i else q for j, q in enumerate(pairs)]


def _loo(datum: LocalizationDatum, pairs: list[Pair], i: int, part: str):
    """Ошибка прогноза в точке i датумом без неё (та же рабочая проекция). None — без точки
    модель этой части вырождается или меняется (например, плоскость → сдвиг)."""
    try:
        d = _fit(_without(pairs, i, part), datum.lat0, datum.lon0, datum.ellipsoid)
    except LocalizationError:
        return None
    r = d.residuals[i]
    if part == "plan":
        return (r.dx, r.dy) if d.plan_model == datum.plan_model else None
    return r.dH if d.height_model == datum.height_model else None


def _diagnose(datum: LocalizationDatum, pairs: list[Pair], sigma_plan, sigma_height, w_limit,
              max_scale_ppm, max_rotation_deg) -> None:
    datum.sigma0_plan, datum.sigma0_height, datum.w_limit = float(sigma_plan), float(sigma_height), float(w_limit)
    plan = [p for p in pairs if p.in_plan]
    n_h = sum(p.in_height for p in pairs)
    datum.redundancy_plan = 2 * len(plan) - (4 if datum.plan_model == "similarity" else 2)
    datum.redundancy_height = None if not n_h else n_h - (3 if datum.height_model == "plane" else 1)
    datum.q_plan, datum.q_height = _cofactors(datum, pairs)

    proj = datum._proj()
    E, N = proj.transform([p.L for p in plan], [p.B for p in plan])
    datum.plan_hull = convex_hull(list(zip((float(v) for v in N), (float(v) for v in E))))

    vp = [r.dx ** 2 + r.dy ** 2 for r, p in zip(datum.residuals, pairs) if p.in_plan]
    vh = [r.dH ** 2 for r, p in zip(datum.residuals, pairs) if p.in_height]
    rp, rh = datum.redundancy_plan, datum.redundancy_height
    datum.s0_plan = float(math.sqrt(sum(vp) / rp)) if rp > 0 else None
    datum.s0_height = float(math.sqrt(sum(vh) / rh)) if rh else None

    warns = datum.warnings
    if rp == 0:
        warns.append(DatumWarning("plan_no_redundancy",
                                  "План: избыточность 0 — невязки нулевые, контроля нет."))
    if rh == 0:
        warns.append(DatumWarning("height_no_redundancy",
                                  "Высота: избыточность 0 — невязки нулевые, контроля нет."))
    if datum.plan_model == "similarity":
        rot_deg = datum.rotation_arcsec / 3600
        if abs(datum.scale_ppm) > max_scale_ppm:
            warns.append(DatumWarning("scale_implausible",
                                      f"Масштаб {datum.scale_ppm:+.1f} ppm (предел {max_scale_ppm:g}): вероятно, "
                                      "перепутаны оси x/y, системы координат или единицы."))
        if abs(rot_deg) > max_rotation_deg:
            warns.append(DatumWarning("rotation_implausible",
                                      f"Разворот {rot_deg:+.3f}° (предел {max_rotation_deg:g}°): проверьте оси x/y "
                                      "и системы координат; до ~1.5° бывает при удалённом осевом меридиане "
                                      "местной системы (сближение меридианов)."))

    dN_all, dE_all = datum._dne_wgs([p.B for p in pairs], [p.L for p in pairs])
    for i, (p, r) in enumerate(zip(pairs, datum.residuals)):
        dN, dE = float(dN_all[i]), float(dE_all[i])
        # План: кофактор поправки по x и по y одинаков, q_vv = 1 ∓ aᵀQa.
        hp = float(_qform(datum.q_plan, (1, 0, dN, -dE)))
        r.qvv_plan = 1 - hp if p.in_plan else 1 + hp
        if r.qvv_plan > Q_EPS:
            s = sigma_plan * math.sqrt(r.qvv_plan)
            r.wx, r.wy = r.dx / s, r.dy / s
        if p.in_plan:
            loo = _loo(datum, pairs, i, "plan") if r.qvv_plan > Q_EPS else None
            if loo is not None:
                r.loo_dx, r.loo_dy = (float(v) for v in loo)
        else:
            r.loo_dx, r.loo_dy = r.dx, r.dy
        if datum.q_height is not None:
            hh = float(_qform(datum.q_height, (1, dN, dE)))
            r.qvv_height = 1 - hh if p.in_height else 1 + hh
            if r.qvv_height > Q_EPS:
                r.wH = r.dH / (sigma_height * math.sqrt(r.qvv_height))
            if p.in_height:
                r.loo_dH = _loo(datum, pairs, i, "height") if r.qvv_height > Q_EPS else None
            else:
                r.loo_dH = r.dH
        for part, w, loo, inside in (("plan", r.w_plan, r.loo_plan, p.in_plan),
                                     ("height", None if r.wH is None else abs(r.wH),
                                      None if r.loo_dH is None else abs(r.loo_dH), p.in_height)):
            if w is None or w <= w_limit:
                continue
            r.suspect = True
            what = "план" if part == "plan" else "высота"
            kind = "нормированная поправка" if inside else "контроль: нормированная ошибка"
            loo_txt = "" if loo is None else f", ошибка без точки {loo:.3f} м"
            warns.append(DatumWarning(f"suspect_{part}",
                                      f"{p.name} ({what}): {kind} |w| = {w:.2f} > {w_limit:g}{loo_txt} — "
                                      "вероятна грубая ошибка.", p.name))


def convex_hull(points: list[tuple[float, float]]) -> list[list[float]]:
    """Выпуклая оболочка (монотонная цепь Эндрю), против часовой стрелки в осях (N, E).
    Для 1–2 различных точек — точка или отрезок."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return [list(p) for p in pts]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return [list(p) for p in lower[:-1] + upper[:-1]]


def _outside(hull, N, E):
    """Расстояние от точек (N, E) до выпуклой оболочки; 0 внутри и на границе."""
    N, E = np.asarray(N, float), np.asarray(E, float)
    h = np.asarray(hull, float)
    m = len(h)
    if m == 1:
        return np.hypot(N - h[0, 0], E - h[0, 1])
    edges = [(h[k], h[(k + 1) % m]) for k in range(m if m > 2 else 1)]
    dist = np.full(N.shape, np.inf)
    inside = np.full(N.shape, m > 2)
    for p0, p1 in edges:
        ex, ey = p1[0] - p0[0], p1[1] - p0[1]
        px, py = N - p0[0], E - p0[1]
        t = np.clip((px * ex + py * ey) / (ex * ex + ey * ey), 0, 1)
        dist = np.minimum(dist, np.hypot(px - t * ex, py - t * ey))
        inside &= ex * py - ey * px >= 0
    return np.where(inside, 0.0, dist)


def suggest_exclusions(pairs: list[Pair], **kwargs) -> list[tuple[str, str, float]]:
    """Итеративно предлагает исключить худшую точку: на каждом шаге — компонент (план или высота)
    с наибольшим |w| > w_limit среди участвующих точек; он исключается, датум пересчитывается.
    Возвращает [(имя, "plan" | "height", |w|), ...]; исходные пары не меняются.
    kwargs — параметры localize (центр проекции фиксируется по исходному датуму)."""
    d = localize(pairs, **kwargs)
    kwargs = {**kwargs, "lat0": d.lat0, "lon0": d.lon0}
    cur, out = list(pairs), []
    while True:
        worst = None
        for i, (p, r) in enumerate(zip(cur, d.residuals)):
            for part, w, inside in (("plan", r.w_plan, p.in_plan),
                                    ("height", None if r.wH is None else abs(r.wH), p.in_height)):
                if inside and w is not None and w > d.w_limit and (worst is None or w > worst[2]):
                    worst = (i, part, w)
        if worst is None:
            return out
        i, part, w = worst
        out.append((cur[i].name, part, w))
        cur = _without(cur, i, part)
        try:
            d = localize(cur, **kwargs)
        except LocalizationError:
            return out
