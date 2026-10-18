"""Проектирование малоискажающей проекции (Low Distortion Projection, LDP) под объект строительства.

Строителю нужно, чтобы расстояние на плане равнялось расстоянию на местности. Суммарное искажение длины
(комбинированный масштаб) в точке:
    δ = k(B, L) · R / (R + h) − 1,     R = √(M·N) = a·√(1 − e²) / (1 − e²·sin²B),
k — масштаб проекции, R/(R + h) — высотный множитель (редукция на эллипсоид), h — эллипсоидальная высота,
R — средний (гауссов) радиус кривизны. δ > 0 — на плане длиннее, чем на местности. 1 ppm = 1 мм/км.

Проекции:
  tmerc — поперечный Меркатор (datums.TransverseMercator, масштаб — TransverseMercator.scale):
          k ≈ k0·(1 + y²/(2R²)), искажение растёт с удалением от осевого меридиана L0;
  omerc — косая проекция Меркатора (Хотин, вариант B, как +proj=omerc PROJ: центр lat0/lon0, азимут
          центральной линии alpha, сетка развёрнута на тот же угол — x на север в центре): искажение растёт
          с удалением от центральной линии — для трасс под углом и с востока на запад.

Подбор по выборке точек объекта (полигон — центры ячеек сетки с шагом step и точки контура, полилиния —
точки трассы с шагом step; вес — площадь ячейки / длина участка):
    c_i = k_i(k0 = 1) · R_i/(R_i + h_i),   δ_i = k0·c_i − 1;
    минимакс (по умолчанию):  k0 = 2 / (c_min + c_max),  max|δ| = (c_max − c_min) / (c_max + c_min);
    СКО (rms):                k0 = Σw·c / Σw·c²  (минимум Σw·δ²).
  tmerc: L0 — перебор 121 значения в пределах объекта ± 300 км и золотое сечение (60 шагов) вокруг лучшего;
         L0 может уйти за объект — так масштаб проекции компенсирует наклон рельефа.
  omerc: азимут — по главной оси точек, затем Нелдер–Мид по (азимут, сдвиг линии поперёк).
Затем L0, широта начала (центр объекта), азимут округляются (round_angle, 1′), k0 — до round_k0 (1e-6),
статистика считается с округлёнными значениями. Ложные смещения (если не заданы): x0 — кратно 10 км, чтобы
x ≥ 5 км; y0 — кратно 100 км, чтобы y ≥ 5 км и y > max x + 20 км: координаты пяти-шестизначные, не похожи на
ГК (7 знаков с номером зоны), UTM (x ~ 6·10⁶) и МСК, и x с y не перепутать.

Если одна проекция не укладывается в допуск — зоны: полилиния делится по пикетажу, полигон — полосами по
восточной координате (tmerc) или поперёк центральной линии (omerc). Жадно: каждая зона — наибольший отрезок,
для которого минимаксная проекция даёт max|δ| ≤ допуска (бинарный поиск по точкам выборки; соседние зоны
делят граничную точку); если зон n — пробуются n равных по длине зон (ровнее), иначе остаются жадные.

Те же формулы и тот же порядок операций для tmerc — в Kotlin (Ldp.kt); omerc, GeoJSON, изолинии — только Python.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import datums
from .geoid import GeoidGrid, read_grid

FORMAT = "mathdatum-ldp"
VERSION = 1
DEFAULT_DATUM = "GSK-2011"
KINDS = ("polygon", "polyline")
CRITERIA = ("minimax", "rms")
TYPES = ("tm", "omerc", "auto")
HEIGHT_TYPES = ("ellipsoidal", "normal")
SEARCH_KM = 300.0       # осевой меридиан ищется в пределах объекта ± SEARCH_KM
SCAN, GOLDEN = 121, 60  # перебор L0 и шаги золотого сечения
MARGIN, GAP = 5000.0, 20000.0
MAX_ZONES = 50


class LdpError(ValueError):
    pass


# --- искажение в точке ---

def gauss_radius(ellipsoid, B):
    """Средний радиус кривизны R = √(M·N) = a·√(1 − e²) / (1 − e²·sin²B), м."""
    el = datums.get_ellipsoid(ellipsoid)
    s = np.sin(np.radians(np.asarray(B, float)))
    return el.a * math.sqrt(1 - el.e2) / (1 - el.e2 * s * s)


def height_factor(ellipsoid, B, h):
    """Высотный множитель R / (R + h): длина на эллипсоиде / длина на высоте h."""
    R = gauss_radius(ellipsoid, B)
    return R / (R + np.asarray(h, float))


def distortion_ppm(scale, hf):
    """δ = k·R/(R + h) − 1, ppm (= мм/км)."""
    return (np.asarray(scale, float) * np.asarray(hf, float) - 1) * 1e6


class ObliqueMercator:
    """Косая проекция Меркатора (Хотин, вариант B — начало в центре), как +proj=omerc в PROJ с
    +lat_0 +lonc +alpha (+gamma = alpha) +k_0; x0 — на север, y0 — на восток.
      B = √(1 + e²cos⁴φc/(1 − e²)),  A = B·k0·√(1 − e²)/(1 − e²sin²φc),  D = B·√(1 − e²)/(cos φc·√(1 − e²sin²φc)),
      F = D + √(D² − 1)·sign φc,  E = F·t(φc)^B,  γ0 = asin(sin αc / D),  λ0 = λc − asin((F − 1/F)/2·tg γ0)/B,
      t(φ) = tg(π/4 − φ/2) / ((1 − e sin φ)/(1 + e sin φ))^(e/2);
      Q = E/t^B, S = (Q − 1/Q)/2, T = (Q + 1/Q)/2, V = sin B(λ − λ0), U = (S sin γ0 − V cos γ0)/T,
      v = A/(2B)·ln((1 − U)/(1 + U)),  u = A/B·atan2(S cos γ0 + V sin γ0, cos B(λ − λ0)) − uc,
      восток = a(v cos αc + u sin αc), север = a(u cos αc − v sin αc);
      масштаб (Snyder, 9-32): k = A·cos(B·u/A)·√(1 − e² sin²φ) / (cos φ·cos B(λ − λ0)), u — без uc.
    При |αc| = 90° PROJ считает иначе (до 5 см) — LDP такой азимут не выдаёт."""

    def __init__(self, ellipsoid, lat0: float, lonc: float, alpha: float, k0: float = 1.0, x0: float = 0.0,
                 y0: float = 0.0):
        el = datums.get_ellipsoid(ellipsoid)
        self.ellipsoid, self.lat0, self.lonc, self.alpha, self.k0, self.x0, self.y0 = el, lat0, lonc, alpha, k0, x0, y0
        e2 = el.e2
        self.e = e = math.sqrt(e2)
        phi0 = math.radians(lat0)
        s0, c0 = math.sin(phi0), math.cos(phi0)
        con, com = 1 - e2 * s0 * s0, math.sqrt(1 - e2)
        Bc = math.sqrt(1 + e2 * c0 ** 4 / (1 - e2))
        A = Bc * k0 * com / con
        D = Bc * com / (c0 * math.sqrt(con))
        F = math.sqrt(D * D - 1) if D * D > 1 else 0.0
        F = (-F if phi0 < 0 else F) + D
        self.E = F * self._ts(phi0) ** Bc
        ac = math.radians(alpha)
        g0 = math.asin(math.sin(ac) / D)
        self.lam0 = math.radians(lonc) - math.asin(0.5 * (F - 1 / F) * math.tan(g0)) / Bc
        self.B, self.A = Bc, A
        self.sg, self.cg, self.sr, self.cr = math.sin(g0), math.cos(g0), math.sin(ac), math.cos(ac)
        u0 = abs(A / Bc * math.atan2(math.sqrt(max(D * D - 1, 0.0)), math.cos(ac)))
        self.u0 = -u0 if phi0 < 0 else u0

    def _ts(self, phi):
        e, s = self.e, np.sin(phi)
        return np.tan(np.pi / 4 - phi / 2) / ((1 - e * s) / (1 + e * s)) ** (e / 2)

    def _uv(self, B, L):
        phi = np.radians(np.asarray(B, float))
        lam = np.radians(np.asarray(L, float)) - self.lam0
        lam = (lam + np.pi) % (2 * np.pi) - np.pi
        W = self.E / self._ts(phi) ** self.B
        S, T = 0.5 * (W - 1 / W), 0.5 * (W + 1 / W)
        V = np.sin(self.B * lam)
        U = (S * self.sg - V * self.cg) / T
        v = 0.5 * self.A / self.B * np.log((1 - U) / (1 + U))
        u = self.A / self.B * np.arctan2(S * self.cg + V * self.sg, np.cos(self.B * lam))
        return u, v, phi, lam

    def forward(self, B, L):
        """B, L (градусы) → x (север), y (восток), м."""
        u, v, _, _ = self._uv(B, L)
        u = u - self.u0
        a = self.ellipsoid.a
        return self.x0 + a * (u * self.cr - v * self.sr), self.y0 + a * (v * self.cr + u * self.sr)

    def inverse(self, x, y):
        """x (север), y (восток) → B, L (градусы)."""
        a = self.ellipsoid.a
        N, E = (np.asarray(x, float) - self.x0) / a, (np.asarray(y, float) - self.y0) / a
        v = E * self.cr - N * self.sr
        u = N * self.cr + E * self.sr + self.u0
        BrA = self.B / self.A
        Q = np.exp(-BrA * v)
        S, T = 0.5 * (Q - 1 / Q), 0.5 * (Q + 1 / Q)
        V = np.sin(BrA * u)
        U = (V * self.cg + S * self.sg) / T
        ts = (self.E / np.sqrt((1 + U) / (1 - U))) ** (1 / self.B)
        e = self.e
        phi = np.pi / 2 - 2 * np.arctan(ts)
        for _ in range(15):
            s = e * np.sin(phi)
            phi = np.pi / 2 - 2 * np.arctan(ts * ((1 - s) / (1 + s)) ** (e / 2))
        lam = -np.arctan2(S * self.cg - V * self.sg, np.cos(BrA * u)) / self.B
        return np.degrees(phi), np.degrees(lam + self.lam0)

    def scale(self, B, L):
        u, _, phi, lam = self._uv(B, L)
        return self.A * np.cos(self.B * u / self.A) * np.sqrt(1 - self.ellipsoid.e2 * np.sin(phi) ** 2) \
            / (np.cos(phi) * np.cos(self.B * lam))

    @property
    def proj(self) -> str:
        return (f"+proj=omerc +lat_0={_num(self.lat0)} +lonc={_num(self.lonc)} +alpha={_num(self.alpha)} "
                f"+gamma={_num(self.alpha)} +k_0={_num(self.k0)} +x_0={_num(self.y0)} +y_0={_num(self.x0)} "
                f"{self.ellipsoid.proj} +units=m")


def _num(v: float) -> str:
    """Число для строки PROJ / отчёта: целое — без дробной части, иначе кратчайшая запись."""
    v = float(v)
    return str(int(v)) if v == math.floor(v) and abs(v) < 1e15 else repr(v)


# --- проекция ---

@dataclass
class LdpProjection:
    """Спроектированная проекция. type: tmerc | omerc; lat0, lon0 — широта начала и осевой меридиан
    (omerc — центр); alpha — азимут центральной линии omerc, градусы; x0 — на север, y0 — на восток."""

    type: str
    datum: str
    lat0: float
    lon0: float
    k0: float
    x0: float = 0.0
    y0: float = 0.0
    alpha: float | None = None

    @property
    def system(self) -> datums.System:
        return datums.get_system(self.datum)

    @property
    def ellipsoid(self) -> datums.Ellipsoid:
        return self.system.ellipsoid

    def impl(self):
        if self.type == "tmerc":
            return datums.TransverseMercator(self.ellipsoid, self.lon0, self.lat0, self.k0, self.x0, self.y0)
        if self.type == "omerc":
            return ObliqueMercator(self.ellipsoid, self.lat0, self.lon0, self.alpha, self.k0, self.x0, self.y0)
        raise LdpError(f"Тип проекции «{self.type}»: ожидается tmerc или omerc.")

    def tm(self) -> datums.TransverseMercator:
        """Поперечный Меркатор (для рабочей проекции локализации); omerc — ошибка."""
        if self.type != "tmerc":
            raise LdpError("Рабочей проекцией локализации может быть только поперечный Меркатор (tmerc): "
                           "Kotlin-порт и JSON датума omerc не поддерживают — возьмите зону TM.")
        return self.impl()

    def forward(self, B, L):
        return self.impl().forward(B, L)

    def inverse(self, x, y):
        return self.impl().inverse(x, y)

    def scale(self, B, L):
        return self.impl().scale(B, L)

    def distortion(self, B, L, h):
        """δ, ppm, в точках (B, L, h эллипсоидальная)."""
        return distortion_ppm(self.scale(B, L), height_factor(self.ellipsoid, B, h))

    @property
    def proj(self) -> str:
        """Строка PROJ (x_0 в PROJ — восток, y_0 — север)."""
        if self.type == "tmerc":
            return (f"+proj=tmerc +lat_0={_num(self.lat0)} +lon_0={_num(self.lon0)} +k={_num(self.k0)} "
                    f"+x_0={_num(self.y0)} +y_0={_num(self.x0)} {self.ellipsoid.proj} +units=m")
        return self.impl().proj

    def to_dict(self) -> dict:
        d = {"type": self.type, "datum": self.datum, "ellipsoid": self.ellipsoid.proj, "lat0": self.lat0,
             "lon0": self.lon0, "k0": self.k0, "x0": self.x0, "y0": self.y0, "proj": self.proj}
        if self.alpha is not None:
            d["alpha"] = self.alpha
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "LdpProjection":
        """Из JSON; недостающие необязательные поля — по умолчанию, лишние (stats, proj…) — игнорируются."""
        try:
            return cls(type=d.get("type", "tmerc"), datum=d.get("datum", DEFAULT_DATUM), lat0=float(d["lat0"]),
                       lon0=float(d["lon0"]), k0=float(d.get("k0", 1.0)), x0=float(d.get("x0", 0.0)),
                       y0=float(d.get("y0", 0.0)), alpha=None if d.get("alpha") is None else float(d["alpha"]))
        except KeyError as e:
            raise LdpError(f"Проекция LDP: нет поля {e}") from None


# --- объект и высоты ---

@dataclass
class Contour:
    """Контур объекта: kind — polygon | polyline; вершины B, L (градусы); z — высоты вершин (или None),
    z_type — ellipsoidal | normal (None — по параметру height_type)."""

    kind: str
    B: np.ndarray
    L: np.ndarray
    z: np.ndarray | None = None
    z_type: str | None = None
    names: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.B, self.L = np.asarray(self.B, float), np.asarray(self.L, float)
        if self.z is not None:
            self.z = np.asarray(self.z, float)
        if self.kind not in KINDS:
            raise LdpError(f"Вид объекта «{self.kind}»: ожидается polygon или polyline.")
        if self.kind == "polygon" and len(self.B) > 3 and self.B[0] == self.B[-1] and self.L[0] == self.L[-1]:
            self.B, self.L = self.B[:-1], self.L[:-1]
            self.z = None if self.z is None else self.z[:-1]
            self.names = self.names[:-1]
        need = 3 if self.kind == "polygon" else 2
        if len(self.B) < need:
            raise LdpError(f"{'Полигону' if self.kind == 'polygon' else 'Полилинии'} нужно не меньше {need} вершин.")


def read_contour(path, kind: str | None = None) -> Contour:
    """Контур из CSV (name;B;L[;h | ;H], порядок строк — порядок вершин) или GeoJSON (Polygon — внешнее
    кольцо, LineString; Feature / FeatureCollection с одной геометрией; координаты [L, B(, z)]).
    kind — polygon | polyline; по умолчанию: GeoJSON — по типу геометрии, CSV — polygon, если кольцо
    замкнуто (первая вершина = последней), иначе polyline. Столбец h — эллипсоидальная высота, H — нормальная."""
    path = Path(path)
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in (".geojson", ".json") or text.lstrip().startswith("{"):
        return _contour_geojson(json.loads(text), kind)
    from .io import _num as num, _rows
    rows, d = _rows(path)
    names, B, L, z = [], [], [], []
    col = None
    for i, r in enumerate(rows, 1):
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        if col is None:
            col = "h" if "h" in r else "H" if "H" in r else ""
        try:
            names.append(r.get("name") or f"V{i}")
            B.append(num(r["B"], d))
            L.append(num(r["L"], d))
            if col:
                z.append(num(r[col], d) if r[col] else float("nan"))
        except (KeyError, ValueError) as e:
            raise LdpError(f"{path}: строка {i + 1}: {e}") from None
    zz = np.array(z, float) if col else None
    if zz is not None and np.isnan(zz).any():
        if not np.isnan(zz).all():
            raise LdpError(f"{path}: столбец {col} заполнен не во всех строках")
        zz = None
    closed = len(B) > 3 and B[0] == B[-1] and L[0] == L[-1]
    return Contour(kind or ("polygon" if closed else "polyline"), B, L, zz,
                   None if zz is None else ("ellipsoidal" if col == "h" else "normal"), names)


def _contour_geojson(g: dict, kind: str | None) -> Contour:
    if g.get("type") == "FeatureCollection":
        feats = [f for f in g.get("features", []) if f.get("geometry")]
        if len(feats) != 1:
            raise LdpError(f"GeoJSON: нужна одна геометрия объекта, найдено {len(feats)}.")
        g = feats[0]
    if g.get("type") == "Feature":
        g = g["geometry"]
    t = g.get("type")
    if t == "Polygon":
        coords, auto = g["coordinates"][0], "polygon"
    elif t == "LineString":
        coords, auto = g["coordinates"], "polyline"
    elif t in ("MultiPolygon", "MultiLineString") and len(g["coordinates"]) == 1:
        coords = g["coordinates"][0][0] if t == "MultiPolygon" else g["coordinates"][0]
        auto = "polygon" if t == "MultiPolygon" else "polyline"
    else:
        raise LdpError(f"GeoJSON: геометрия {t} не поддерживается (Polygon или LineString).")
    c = np.array([list(p[:3]) + [np.nan] * (3 - len(p[:3])) for p in coords], float)
    z = None if np.isnan(c[:, 2]).any() else c[:, 2]
    return Contour(kind or auto, c[:, 1], c[:, 0], z, None)


@dataclass
class Heights:
    """Источник высот. Приоритет: сетка рельефа dem (значения — по height_type) → высоты вершин контура
    (вдоль полилинии и по контуру — линейно, внутри полигона — обратные расстояния, p = 2) → constant.
    height_type: ellipsoidal (h) | normal (нормальная / ортометрическая H; h = H + N(B, L) по сетке geoid)."""

    constant: float | None = None
    dem: GeoidGrid | None = None
    geoid: GeoidGrid | None = None
    height_type: str = "ellipsoidal"

    def __post_init__(self):
        if isinstance(self.dem, (str, Path)):
            self.dem = read_grid(self.dem)
        if isinstance(self.geoid, (str, Path)):
            self.geoid = read_grid(self.geoid)
        if self.height_type not in HEIGHT_TYPES:
            raise LdpError(f"Тип высот «{self.height_type}»: ожидается ellipsoidal или normal.")


# --- выборка точек объекта ---

@dataclass
class Samples:
    """Точки выборки: B, L, h (эллипсоидальная), вес w (площадь, м², или длина, м; 0 — точка контура
    полигона: только для экстремумов), n, e — вспомогательный поперечный Меркатор, s — пикетаж (полилиния)."""

    B: np.ndarray
    L: np.ndarray
    h: np.ndarray
    w: np.ndarray
    n: np.ndarray
    e: np.ndarray
    s: np.ndarray | None = None

    def subset(self, m) -> "Samples":
        return Samples(self.B[m], self.L[m], self.h[m], self.w[m], self.n[m], self.e[m],
                       None if self.s is None else self.s[m])


class _Site:
    """Объект во вспомогательной проекции (TM в центре вершин): выборка, высоты, расстояния."""

    def __init__(self, contour: Contour, heights: Heights, ellipsoid, step: float | None):
        self.c, self.hs, self.el = contour, heights, datums.get_ellipsoid(ellipsoid)
        self.aux = datums.TransverseMercator(self.el, _mean(contour.L), _mean(contour.B))
        self.vn, self.ve = (np.asarray(v, float) for v in self.aux.forward(contour.B, contour.L))
        self.notes: list[str] = []
        vz = None
        if contour.z is not None:
            vz = self._ellipsoidal(contour.z, contour.B, contour.L, contour.z_type or heights.height_type, "вершин")
        self.vz = vz
        if heights.dem is None and vz is None and heights.constant is None:
            raise LdpError("Нет высот: задайте среднюю высоту, высоты вершин (столбец h или H) или сетку рельефа.")
        if self.polygon:
            ring = np.append(np.arange(len(self.vn)), 0)
            seg = np.hypot(np.diff(self.vn[ring]), np.diff(self.ve[ring]))
            self.perimeter = float(seg.sum())
            self.area = float(abs(np.dot(self.ve, np.roll(self.vn, -1)) - np.dot(self.vn, np.roll(self.ve, -1))) / 2)
            ext = max(self.vn.max() - self.vn.min(), self.ve.max() - self.ve.min())
            self.step = float(step) if step else max(ext / 50, 1.0)
        else:
            seg = np.hypot(np.diff(self.vn), np.diff(self.ve))
            self.chain = np.concatenate([[0.0], np.cumsum(seg)])
            self.length = float(self.chain[-1])
            if self.length <= 0:
                raise LdpError("Полилиния нулевой длины.")
            self.step = float(step) if step else max(self.length / 200, 1.0)
        if not self.step > 0:
            raise LdpError("Шаг выборки должен быть > 0.")

    @property
    def polygon(self) -> bool:
        return self.c.kind == "polygon"

    def _ellipsoidal(self, H, B, L, kind, what):
        """Высоты → эллипсоидальные: normal — h = H + N(B, L) по сетке геоида (без неё N = 0, предупреждение)."""
        H = np.asarray(H, float)
        if kind == "ellipsoidal":
            return H
        if self.hs.geoid is None:
            note = (f"Высоты {what} нормальные, сетки геоида нет — приняты за эллипсоидальные (N = 0): "
                    "ошибка 0.157 ppm на каждый метр N.")
            if note not in self.notes:
                self.notes.append(note)
            return H
        return H + self.hs.geoid.value(B, L)

    def heights(self, B, L, base):
        """Эллипсоидальные высоты в точках: сетка рельефа, иначе base (по вершинам), иначе constant."""
        if self.hs.dem is not None:
            return self._ellipsoidal(self.hs.dem.value(B, L), B, L, self.hs.height_type, "сетки рельефа")
        if base is not None:
            return base
        return self._ellipsoidal(np.full(np.shape(B), float(self.hs.constant)), B, L, self.hs.height_type,
                                 "(средняя)")

    def idw(self, n, e):
        """Обратные расстояния (p = 2) по высотам вершин; в вершине — её высота."""
        dn, de = n[:, None] - self.vn[None, :], e[:, None] - self.ve[None, :]
        d2 = dn * dn + de * de
        w = 1.0 / np.maximum(d2, 1e-12)
        return (w @ self.vz) / w.sum(axis=1)

    def samples(self) -> Samples:
        st = self.step
        if self.polygon:
            n0, n1, e0, e1 = self.vn.min(), self.vn.max(), self.ve.min(), self.ve.max()
            nx, ny = max(1, math.ceil((e1 - e0) / st - 1e-9)), max(1, math.ceil((n1 - n0) / st - 1e-9))
            sx, sy = (e1 - e0) / nx, (n1 - n0) / ny
            ee = e0 + (np.arange(nx) + 0.5) * sx
            nn = n0 + (np.arange(ny) + 0.5) * sy
            gn, ge = (a.ravel() for a in np.meshgrid(nn, ee, indexing="ij"))
            inside = point_in_polygon(self.vn, self.ve, gn, ge)
            gn, ge = gn[inside], ge[inside]
            bn, be, bz = self._densify(closed=True)
            n = np.concatenate([gn, bn])
            e = np.concatenate([ge, be])
            w = np.concatenate([np.full(len(gn), sx * sy), np.zeros(len(bn))])
            if len(gn) == 0:  # объект меньше ячейки — по контуру с весом длины
                w = self._seg_weights(bn, be, closed=True)
            base = None if self.vz is None else np.concatenate([self.idw(gn, ge), bz])
            s = None
        else:
            n, e, base, s = self._densify(closed=False, chain=True)
            w = np.zeros(len(n))
            ds = np.diff(s)
            w[:-1] += ds / 2
            w[1:] += ds / 2
        B, L = (np.asarray(v, float) for v in self.aux.inverse(n, e))
        return Samples(B, L, np.asarray(self.heights(B, L, base), float), w, n, e, s)

    def _densify(self, closed: bool, chain: bool = False):
        """Точки по сторонам с шагом ≤ step: вершины и равномерно между ними; высоты — линейно."""
        m = len(self.vn)
        idx = list(range(m)) + ([0] if closed else [])
        ns, es, zs, ss = [], [], [], []
        acc = 0.0
        for a, b in zip(idx[:-1], idx[1:]):
            dn, de = self.vn[b] - self.vn[a], self.ve[b] - self.ve[a]
            ln = math.hypot(dn, de)
            k = max(1, math.ceil(ln / self.step - 1e-9))
            for j in range(k):
                t = j / k
                ns.append(self.vn[a] + t * dn)
                es.append(self.ve[a] + t * de)
                ss.append(acc + t * ln)
                if self.vz is not None:
                    zs.append(self.vz[a] + t * (self.vz[b] - self.vz[a]))
            acc += ln
        if not closed:
            ns.append(self.vn[-1])
            es.append(self.ve[-1])
            ss.append(acc)
            if self.vz is not None:
                zs.append(self.vz[-1])
        z = np.array(zs) if self.vz is not None else None
        if chain:
            return np.array(ns), np.array(es), z, np.array(ss)
        return np.array(ns), np.array(es), z

    @staticmethod
    def _seg_weights(n, e, closed: bool):
        d = np.hypot(np.diff(np.append(n, n[0])), np.diff(np.append(e, e[0])))
        return (d + np.roll(d, 1)) / 2

    def nearest_on_line(self, n, e):
        """Для точек (n, e): пикетаж ближайшей точки полилинии, расстояние до неё, м."""
        best_d = np.full(len(n), np.inf)
        best_s = np.zeros(len(n))
        for i in range(len(self.vn) - 1):
            an, ae = self.vn[i], self.ve[i]
            dn, de = self.vn[i + 1] - an, self.ve[i + 1] - ae
            ln2 = dn * dn + de * de
            t = np.clip(((n - an) * dn + (e - ae) * de) / ln2, 0, 1)
            d = np.hypot(n - an - t * dn, e - ae - t * de)
            better = d < best_d
            best_d = np.where(better, d, best_d)
            best_s = np.where(better, self.chain[i] + t * math.sqrt(ln2), best_s)
        return best_s, best_d

    def line_height(self, s):
        """Высота вершин, линейно по пикетажу."""
        return np.interp(s, self.chain, self.vz)

    def boundary_distance(self, n, e):
        d = np.full(len(n), np.inf)
        m = len(self.vn)
        for i in range(m):
            j = (i + 1) % m
            an, ae = self.vn[i], self.ve[i]
            dn, de = self.vn[j] - an, self.ve[j] - ae
            t = np.clip(((n - an) * dn + (e - ae) * de) / (dn * dn + de * de), 0, 1)
            d = np.minimum(d, np.hypot(n - an - t * dn, e - ae - t * de))
        return d


def _mean(v) -> float:
    """Среднее последовательной суммой (как в Kotlin; np.mean и sum() суммируют иначе)."""
    acc = 0.0
    for x in v:
        acc += float(x)
    return acc / len(v)


def point_in_polygon(pn, pe, n, e):
    """Лучевой тест (чётность пересечений) для точек (n, e) в многоугольнике (pn, pe)."""
    n, e = np.asarray(n, float), np.asarray(e, float)
    inside = np.zeros(n.shape, bool)
    m = len(pn)
    for i in range(m):
        j = (i - 1) % m
        ni, ei, nj, ej = pn[i], pe[i], pn[j], pe[j]
        cross = (ni > n) != (nj > n)
        with np.errstate(divide="ignore", invalid="ignore"):
            ex = (ej - ei) * (n - ni) / (nj - ni) + ei
        inside ^= cross & (e < ex)
    return inside


# --- подбор ---

def _k0_dev(c, w, criterion):
    """k0 и значение критерия для c_i: минимакс — 2/(c_min + c_max); СКО — Σw·c / Σw·c²."""
    if criterion == "minimax":
        lo, hi = float(c.min()), float(c.max())
        return 2 / (lo + hi), (hi - lo) / (hi + lo)
    k = float(w @ c) / float(w @ (c * c))
    d = k * c - 1
    return k, math.sqrt(float(w @ (d * d)) / float(w.sum()))


def _rms_weights(S: Samples):
    return S.w if S.w.sum() > 0 else np.ones(len(S.w))


def _search(f, lo, hi):
    """Минимум f на [lo, hi]: перебор SCAN точек, затем золотое сечение вокруг лучшей (как в Kotlin)."""
    xs = [lo + (hi - lo) * i / (SCAN - 1) for i in range(SCAN)]
    fs = [f(x) for x in xs]
    ib = 0
    for i in range(1, SCAN):
        if fs[i] < fs[ib]:
            ib = i
    a, b = xs[max(ib - 1, 0)], xs[min(ib + 1, SCAN - 1)]
    g = (math.sqrt(5) - 1) / 2
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = f(c), f(d)
    for _ in range(GOLDEN):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = f(d)
    x = (a + b) / 2
    return x if f(x) <= fs[ib] else xs[ib]


def _round_near(v: float, step: float) -> float:
    """Ближайшее кратное step (step в тех же единицах); результат — целое·step без накопления ошибки."""
    return math.floor(v / step + 0.5) * step


def _round_k0(k: float, q: float) -> float:
    if not q:
        return k
    inv = round(1 / q)
    return math.floor(k * inv + 0.5) / inv


def _angle_candidates(v: float, minutes: float):
    """Кратные minutes (угловые минуты) снизу и сверху от v, градусы."""
    m = math.floor(v * 60 / minutes)
    return m * minutes / 60, (m + 1) * minutes / 60


def _offsets(N, E, x0, y0):
    """Ложные смещения: x ≥ 5 км (x0 кратно 10 км), y ≥ 5 км и y > max x + 20 км (y0 кратно 100 км); не меньше 0."""
    if x0 is None:
        x0 = max(0.0, math.ceil((MARGIN - float(N.min())) / 10000) * 10000.0) + 0.0
    if y0 is None:
        y0 = max(0.0, math.ceil(max(MARGIN - float(E.min()), x0 + float(N.max()) + GAP - float(E.min())) / 100000)
                 * 100000.0) + 0.0
    return float(x0), float(y0)


@dataclass
class FitOptions:
    criterion: str = "minimax"
    round_angle: float = 1.0       # угловые минуты (0 — без округления)
    round_k0: float = 1e-6         # 0 — без округления
    lon0: float | None = None      # заданный осевой меридиан (не подбирается)
    lat0: float | None = None
    k0: float | None = None
    x0: float | None = None
    y0: float | None = None


def fit_tm(S: Samples, datum: str, opt: FitOptions) -> LdpProjection:
    """Поперечный Меркатор под выборку: L0 (перебор + золотое сечение), k0 (замкнутая форма), округление."""
    el = datums.get_system(datum).ellipsoid
    hf = height_factor(el, S.B, S.h)
    w = _rms_weights(S)

    def c_of(l0):
        return datums.TransverseMercator(el, l0).scale(S.B, S.L) * hf

    def obj(l0):
        c = c_of(l0)
        if opt.k0 is not None:
            d = opt.k0 * c - 1
            return float(np.abs(d).max()) if opt.criterion == "minimax" else math.sqrt(float(w @ (d * d)) / w.sum())
        return _k0_dev(c, w, opt.criterion)[1]

    if opt.lon0 is not None:
        lon0 = float(opt.lon0)
    else:
        lmin, lmax = float(S.L.min()), float(S.L.max())
        bc = (float(S.B.min()) + float(S.B.max())) / 2
        pad = math.degrees(SEARCH_KM * 1000 / (el.a * math.cos(math.radians(bc))))
        lon0 = _search(obj, lmin - pad, lmax + pad)
        if opt.round_angle:
            lo, hi = _angle_candidates(lon0, opt.round_angle)
            lon0 = lo if obj(lo) <= obj(hi) else hi
    if opt.lat0 is not None:
        lat0 = float(opt.lat0)
    else:
        lat0 = (float(S.B.min()) + float(S.B.max())) / 2
        if opt.round_angle:
            lat0 = math.floor(lat0 * 60 / opt.round_angle + 0.5) * opt.round_angle / 60
    k0 = float(opt.k0) if opt.k0 is not None else _round_k0(_k0_dev(c_of(lon0), w, opt.criterion)[0], opt.round_k0)
    N, E = datums.TransverseMercator(el, lon0, lat0, k0).forward(S.B, S.L)
    x0, y0 = _offsets(np.asarray(N), np.asarray(E), opt.x0, opt.y0)
    return LdpProjection("tmerc", datums.get_system(datum).id, lat0, lon0, k0, x0, y0)


def _nelder_mead(f, x0, steps, iters=400, tol=1e-12):
    """Нелдер–Мид (отражение 1, растяжение 2, сжатие ½, редукция ½)."""
    pts = [np.array(x0, float)] + [np.array(x0, float) + np.eye(len(x0))[i] * steps[i] for i in range(len(x0))]
    vals = [f(p) for p in pts]
    for _ in range(iters):
        order = np.argsort(vals, kind="stable")
        pts, vals = [pts[i] for i in order], [vals[i] for i in order]
        if vals[-1] - vals[0] < tol and max(np.abs(p - pts[0]).max() for p in pts[1:]) < 1e-9:
            break
        cen = np.mean(pts[:-1], axis=0)
        xr = cen + (cen - pts[-1])
        fr = f(xr)
        if fr < vals[0]:
            xe = cen + 2 * (cen - pts[-1])
            fe = f(xe)
            pts[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = xr, fr
        else:
            xc = cen + 0.5 * (pts[-1] - cen)
            fc = f(xc)
            if fc < vals[-1]:
                pts[-1], vals[-1] = xc, fc
            else:
                pts = [pts[0]] + [pts[0] + 0.5 * (p - pts[0]) for p in pts[1:]]
                vals = [vals[0]] + [f(p) for p in pts[1:]]
    i = int(np.argmin(vals))
    return pts[i], vals[i]


def _axis(S: Samples):
    """Центр (взвешенный) и азимут главной оси точек выборки во вспомогательной проекции, градусы (−90, 90]."""
    w = _rms_weights(S)
    nc, ec = float(w @ S.n / w.sum()), float(w @ S.e / w.sum())
    dn, de = S.n - nc, S.e - ec
    snn, see, sne = float(w @ (dn * dn)), float(w @ (de * de)), float(w @ (dn * de))
    az = math.degrees(0.5 * math.atan2(2 * sne, snn - see))
    return nc, ec, _norm_alpha(az)


def _norm_alpha(a: float) -> float:
    a = (a + 90) % 180 - 90
    return 90.0 if a == -90 else a


def fit_omerc(S: Samples, datum: str, opt: FitOptions, aux: datums.TransverseMercator) -> LdpProjection:
    """Косой Меркатор: азимут центральной линии и её сдвиг поперёк (Нелдер–Мид), k0 — замкнутая форма."""
    el = datums.get_system(datum).ellipsoid
    hf = height_factor(el, S.B, S.h)
    w = _rms_weights(S)
    nc, ec, a0 = _axis(S)
    ext = max(float(np.ptp(S.n)), float(np.ptp(S.e)), 1.0)

    def center(a, d):
        r = math.radians(a)
        B, L = aux.inverse(nc - d * math.sin(r), ec + d * math.cos(r))
        return float(B), float(L)

    def c_of(a, d):
        B, L = center(a, d)
        return ObliqueMercator(el, B, L, _clamp_alpha(_norm_alpha(a)), 1.0).scale(S.B, S.L) * hf

    def obj(p):
        c = c_of(p[0], p[1] * 1000)
        if opt.k0 is not None:
            dd = opt.k0 * c - 1
            return float(np.abs(dd).max()) if opt.criterion == "minimax" else math.sqrt(float(w @ (dd * dd)) / w.sum())
        return _k0_dev(c, w, opt.criterion)[1]

    (a, d), _ = _nelder_mead(obj, [a0, 0.0], [2.0, max(ext / 4000, 0.5)])
    alpha = _norm_alpha(a)
    lat0, lon0 = center(a, d * 1000)
    if opt.round_angle:
        q = opt.round_angle / 60
        lat0, lon0, alpha = _round_near(lat0, q), _round_near(lon0, q), _round_near(alpha, q)
    alpha = _clamp_alpha(alpha, opt.round_angle / 60 if opt.round_angle else 1 / 60)
    c = ObliqueMercator(el, lat0, lon0, alpha, 1.0).scale(S.B, S.L) * hf
    k0 = float(opt.k0) if opt.k0 is not None else _round_k0(_k0_dev(c, w, opt.criterion)[0], opt.round_k0)
    N, E = ObliqueMercator(el, lat0, lon0, alpha, k0).forward(S.B, S.L)
    x0, y0 = _offsets(np.asarray(N), np.asarray(E), opt.x0, opt.y0)
    return LdpProjection("omerc", datums.get_system(datum).id, lat0, lon0, k0, x0, y0, alpha)


def _clamp_alpha(a: float, q: float = 1e-6) -> float:
    """|α| = 90° PROJ обрабатывает отдельно — сдвигаем на шаг округления внутрь."""
    return math.copysign(90 - q, a) if abs(a) > 90 - q / 2 else a


# --- статистика ---

def stats(ppm, w, tol: float, measure: str) -> dict:
    """min/max/mean/RMS δ (ppm = мм/км), max|δ|, доля площади/длины с |δ| ≤ tol (по весам; без весов — по точкам)."""
    ppm = np.asarray(ppm, float)
    w = np.asarray(w, float)
    if w.sum() <= 0:
        w = np.ones(len(ppm))
    sw = float(w.sum())
    return {"n": int(len(ppm)), "min_ppm": float(ppm.min()), "max_ppm": float(ppm.max()),
            "mean_ppm": float(w @ ppm) / sw, "rms_ppm": math.sqrt(float(w @ (ppm * ppm)) / sw),
            "max_abs_ppm": float(np.abs(ppm).max()),
            "share_in_tolerance": float(w[np.abs(ppm) <= tol].sum()) / sw, "measure": measure}


def gk_distortion(S: Samples, el):
    """Искажение в зонах Гаусса–Крюгера 6° (каждая точка — в своей зоне, k0 = 1)."""
    zones = datums.gk_zone(S.L)
    k = np.empty(len(S.B))
    for z in np.unique(zones):
        m = zones == z
        k[m] = datums.TransverseMercator(el, 6.0 * int(z) - 3).scale(S.B[m], S.L[m])
    return distortion_ppm(k, height_factor(el, S.B, S.h)), sorted(int(z) for z in np.unique(zones))


def utm_distortion(S: Samples, el):
    """Искажение в зонах UTM (L0 = 6n − 183, k0 = 0.9996)."""
    zones = (np.floor((np.mod(S.L + 180, 360)) / 6) + 1).astype(int)
    k = np.empty(len(S.B))
    for z in np.unique(zones):
        m = zones == z
        k[m] = datums.TransverseMercator(el, 6.0 * int(z) - 183, 0, 0.9996).scale(S.B[m], S.L[m])
    return distortion_ppm(k, height_factor(el, S.B, S.h)), sorted(int(z) for z in np.unique(zones))


# --- результат ---

@dataclass
class Zone:
    """Зона: участок key ∈ [start, end] (пикетаж полилинии или координата поперёк, м), проекция, статистика,
    граница с предыдущей зоной — точки (B, L) (полилиния — одна точка, полигон — отрезок поперёк)."""

    name: str
    start: float
    end: float
    projection: LdpProjection
    stats: dict
    boundary: list[list[float]] | None = None


@dataclass
class LdpResult:
    contour: Contour
    datum: str
    tolerance: float
    criterion: str
    requested: str
    step: float
    projection: LdpProjection
    stats: dict
    alternatives: list[tuple[LdpProjection, dict]]
    comparison: dict
    zones: list[Zone]
    zone_key: str | None
    warnings: list[str]
    object_info: dict
    zone_axis: float | None = None
    _site: _Site = None
    _samples: Samples = None

    @property
    def fits(self) -> bool:
        return self.stats["max_abs_ppm"] <= self.tolerance + 1e-9

    def to_dict(self) -> dict:
        def proj(p, st):
            return {**p.to_dict(), "stats": st}
        return {
            "format": FORMAT, "version": VERSION, "datum": self.datum,
            "ellipsoid": datums.get_system(self.datum).ellipsoid.proj,
            "tolerance_ppm": self.tolerance, "criterion": self.criterion, "type_requested": self.requested,
            "step_m": self.step, "object": self.object_info, "fits_tolerance": self.fits,
            "projection": proj(self.projection, self.stats),
            "alternatives": [proj(p, st) for p, st in self.alternatives],
            "comparison": self.comparison,
            "zones": [{"name": z.name, "from_m": z.start, "to_m": z.end, "key": self.zone_key, "boundary": z.boundary,
                       "projection": proj(z.projection, z.stats)} for z in self.zones],
            "warnings": self.warnings,
        }

    def save(self, path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    def report(self) -> str:
        return report(self)

    def distortion_map(self, size: int = 60, margin: float = 0.05) -> "DistortionMap":
        return distortion_map(self, size, margin)


def design(contour: Contour, heights: Heights, datum: str = DEFAULT_DATUM, tolerance: float = 20.0,
           criterion: str = "minimax", type: str = "auto", step: float | None = None,
           options: FitOptions | None = None) -> LdpResult:
    """Проектирует LDP под объект. type: tm | omerc | auto (TM; если не укладывается — ещё omerc,
    при успехе он рекомендуется, а зоны TM остаются запасным вариантом). Если допуск не выполнен —
    предлагаются зоны (минимакс). options — округление и заданные параметры (FitOptions)."""
    if criterion not in CRITERIA:
        raise LdpError(f"Критерий «{criterion}»: ожидается minimax или rms.")
    if type not in TYPES:
        raise LdpError(f"Тип проекции «{type}»: ожидается tm, omerc или auto.")
    if not tolerance > 0:
        raise LdpError("Допуск должен быть > 0 ppm.")
    system = datums.get_system(datum)
    el = system.ellipsoid
    opt = FitOptions(**{**(options.__dict__ if options else {}), "criterion": criterion})
    site = _Site(contour, heights, el, step)
    S = site.samples()
    measure = "area" if site.polygon and S.w.sum() > 0 and (S.w > 0).sum() < len(S.w) else "length"
    warns = list(site.notes)
    hf = height_factor(el, S.B, S.h)

    def evaluate(p):
        return stats(p.distortion(S.B, S.L, S.h), S.w, tolerance, measure)

    def fit(kind, sub, o):
        return fit_tm(sub, system.id, o) if kind == "tm" else fit_omerc(sub, system.id, o, site.aux)

    first = "omerc" if type == "omerc" else "tm"
    best = fit(first, S, opt)
    best_st = evaluate(best)
    alts = []
    if type == "auto" and best_st["max_abs_ppm"] > tolerance:
        om = fit("omerc", S, opt)
        om_st = evaluate(om)
        if om_st["max_abs_ppm"] <= tolerance:
            alts.append((best, best_st))
            best, best_st = om, om_st
            warns.append("Поперечный Меркатор не укладывается в допуск одной зоной, косая проекция Меркатора "
                         "(omerc) — укладывается. Для локализации и Kotlin/веб нужен TM — см. зоны TM.")
        else:
            alts.append((om, om_st))
    # Разброс только от высот — оценка достижимости.
    hspread = float((hf.max() - hf.min()) / (hf.max() + hf.min()) * 1e6)
    if hspread > tolerance:
        warns.append(f"Перепад высот {np.ptp(S.h):.0f} м сам по себе даёт ±{hspread:.1f} ppm — больше допуска: "
                     "одна проекция не уложится; нужны зоны по высоте (участки с меньшим перепадом).")

    gk_ppm, gk_z = gk_distortion(S, el)
    utm_ppm, utm_z = utm_distortion(S, el)
    comparison = {"gk": {"zones": gk_z, "stats": stats(gk_ppm, S.w, tolerance, measure)},
                  "utm": {"zones": utm_z, "stats": stats(utm_ppm, S.w, tolerance, measure)}}

    zones, key_name, axis = [], None, None
    zone_kind = "omerc" if best.type == "omerc" and type == "omerc" else "tm"
    if best_st["max_abs_ppm"] > tolerance or (alts and best.type == "omerc"):
        key, key_name, axis = _zone_key(site, S, zone_kind)
        zopt = FitOptions(**{**opt.__dict__, "criterion": "minimax", "lon0": None, "lat0": None, "x0": None, "y0": None})
        res = split_zones(S, key, lambda sub: fit(zone_kind, sub, zopt), tolerance, measure)
        if res is None:
            warns.append("Допуск недостижим даже на отрезке длиной в шаг выборки (перепад высот): зоны не предложены.")
        elif len(res) > 1:
            for i, (ka, kb, p, st) in enumerate(res, 1):
                zones.append(Zone(f"Зона {i}", ka, kb, p, st, None if i == 1 else _boundary(site, ka, key_name, axis)))
        elif best_st["max_abs_ppm"] > tolerance:
            ka, kb, p, st = res[0]
            warns.append("По минимаксу объект укладывается в допуск одной зоной (критерий СКО допускает превышение "
                         "на краях): проекция зоны 1.")
            zones.append(Zone("Зона 1", ka, kb, p, st))
    info = _object_info(site, S)
    return LdpResult(contour, system.id, float(tolerance), criterion, type, site.step, best, best_st, alts, comparison,
                     zones, key_name, warns, info, axis, site, S)


def _object_info(site: _Site, S: Samples) -> dict:
    d = {"kind": site.c.kind, "vertices": int(len(site.vn)), "samples": int(len(S.B)),
         "B_center": float((S.B.min() + S.B.max()) / 2), "L_center": float((S.L.min() + S.L.max()) / 2),
         "extent_north_m": float(np.ptp(S.n)), "extent_east_m": float(np.ptp(S.e)),
         "h_min": float(S.h.min()), "h_max": float(S.h.max()),
         "h_mean": float(_rms_weights(S) @ S.h / _rms_weights(S).sum()),
         "height_source": ("сетка рельефа" if site.hs.dem is not None else
                           "высоты вершин" if site.vz is not None else "средняя высота")}
    if site.polygon:
        d["area_m2"], d["perimeter_m"] = site.area, site.perimeter
    else:
        d["length_m"] = site.length
    return d


def _zone_key(site: _Site, S: Samples, kind: str):
    if not site.polygon:
        return S.s, "chainage", None
    if kind == "tm":
        return S.e, "easting", None
    _, _, a = _axis(S)
    return _across(S.n, S.e, a), "across", a


def _across(n, e, alpha):
    """Координата поперёк оси с азимутом alpha (во вспомогательной проекции), м."""
    r = math.radians(alpha)
    return -n * math.sin(r) + e * math.cos(r)


def split_zones(S: Samples, key, fit_fn, tol: float, measure: str):
    """Деление выборки по key на зоны с max|δ| ≤ tol (минимакс): жадно по уникальным значениям key
    (бинарный поиск конца зоны, соседние зоны делят граничное значение), затем попытка n равных зон.
    Возвращает [(key_from, key_to, проекция, статистика)] или None (недостижимо)."""
    uk = np.unique(key)
    cache = {}

    def check(i, j):
        if (i, j) not in cache:
            m = (key >= uk[i]) & (key <= uk[j])
            sub = S.subset(m)
            p = fit_fn(sub)
            st = stats(p.distortion(sub.B, sub.L, sub.h), sub.w, tol, measure)
            cache[(i, j)] = (st["max_abs_ppm"] <= tol + 1e-9, p, st)
        return cache[(i, j)]

    if len(uk) == 1:
        ok, p, st = check(0, 0)
        return [(float(uk[0]), float(uk[0]), p, st)] if ok else None
    cuts, i = [], 0
    while i < len(uk) - 1:
        if not check(i, i + 1)[0]:
            return None
        lo, hi = i + 1, len(uk) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if check(i, mid)[0]:
                lo = mid
            else:
                hi = mid - 1
        cuts.append((i, lo))
        i = lo
        if len(cuts) > MAX_ZONES:
            return None
    n = len(cuts)
    if n > 1:
        span = uk[-1] - uk[0]
        idx = [0]
        for m in range(1, n):
            t = uk[0] + span * m / n
            idx.append(int(np.argmin(np.abs(uk - t))))
        idx.append(len(uk) - 1)
        if all(b > a for a, b in zip(idx, idx[1:])):
            eq = list(zip(idx[:-1], idx[1:]))
            if all(check(a, b)[0] for a, b in eq):
                cuts = eq
    return [(float(uk[a]), float(uk[b]), check(a, b)[1], check(a, b)[2]) for a, b in cuts]


def _boundary(site: _Site, k: float, key_name: str, alpha: float | None):
    """Граница зон: точка трассы на пикетаже k или отрезок поперёк полигона (по его габариту)."""
    if key_name == "chainage":
        n = np.interp(k, site.chain, site.vn)
        e = np.interp(k, site.chain, site.ve)
        B, L = site.aux.inverse(n, e)
        return [[float(B), float(L)]]
    n0, n1, e0, e1 = site.vn.min(), site.vn.max(), site.ve.min(), site.ve.max()
    if key_name == "easting":
        pts = [(n0, k), (n1, k)]
    else:
        nc, ec = (n0 + n1) / 2, (e0 + e1) / 2
        r = math.radians(alpha)
        half = math.hypot(n1 - n0, e1 - e0) / 2
        # точка линии key = k, ближайшая к центру габарита; отрезок вдоль оси
        base = _across(nc, ec, alpha)
        pn, pe = nc - (k - base) * math.sin(r), ec + (k - base) * math.cos(r)
        pts = [(pn - half * math.cos(r), pe - half * math.sin(r)), (pn + half * math.cos(r), pe + half * math.sin(r))]
    out = []
    for n, e in pts:
        B, L = site.aux.inverse(n, e)
        out.append([float(B), float(L)])
    return out


# --- карта искажений ---

@dataclass
class DistortionMap:
    """Сетка узлов (ny × nx) вокруг объекта: B, L, h, номер зоны (0 — одна проекция), k, R/(R+h), δ (ppm),
    расстояние до объекта (0 — внутри полигона), м."""

    B: np.ndarray
    L: np.ndarray
    h: np.ndarray
    zone: np.ndarray
    k: np.ndarray
    hf: np.ndarray
    ppm: np.ndarray
    dist: np.ndarray
    result: LdpResult

    def to_csv(self, path) -> None:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write("row;col;B;L;h;zone;k;height_factor;ppm;dist_m\n")
            ny, nx = self.B.shape
            for j in range(ny):
                for i in range(nx):
                    f.write(f"{j};{i};{self.B[j, i]:.8f};{self.L[j, i]:.8f};{self.h[j, i]:.3f};{int(self.zone[j, i])};"
                            f"{self.k[j, i]:.10f};{self.hf[j, i]:.10f};{self.ppm[j, i]:.3f};{self.dist[j, i]:.1f}\n")

    def levels(self) -> list[float]:
        """Уровни изолиний: «круглый» шаг (1, 2, 5·10ⁿ ppm) на ~8 интервалов размаха, плюс ±допуск."""
        lo, hi = float(np.nanmin(self.ppm)), float(np.nanmax(self.ppm))
        if hi - lo <= 0:
            return []
        raw = (hi - lo) / 8
        p = 10 ** math.floor(math.log10(raw))
        st = next(m * p for m in (1, 2, 5, 10) if m * p >= raw)
        lv = [st * i for i in range(math.ceil(lo / st), math.floor(hi / st) + 1)]
        tol = self.result.tolerance
        lv += [v for v in (-tol, tol) if lo < v < hi and v not in lv]
        return sorted(lv)

    def isolines(self, level: float) -> list[list[list[float]]]:
        """Изолиния δ = level (marching squares; ячейки на границе зон пропускаются) — список линий [[L, B], …]."""
        v, ny, nx = self.ppm, *self.ppm.shape
        segs = []
        def edge_pt(a, b):
            (ja, ia), (jb, ib) = min(a, b), max(a, b)  # ребро — одинаково из обеих соседних ячеек
            t = (level - v[ja, ia]) / (v[jb, ib] - v[ja, ia])
            return ("%d,%d,%d,%d" % (ja, ia, jb, ib), (self.L[ja, ia] + t * (self.L[jb, ib] - self.L[ja, ia]),
                                                     self.B[ja, ia] + t * (self.B[jb, ib] - self.B[ja, ia])))
        for j in range(ny - 1):
            for i in range(nx - 1):
                c = [(j, i), (j, i + 1), (j + 1, i + 1), (j + 1, i)]
                if len({int(self.zone[q]) for q in c}) > 1:
                    continue
                vals = [v[q] for q in c]
                cut = [k for k in range(4) if (vals[k] >= level) != (vals[(k + 1) % 4] >= level)]
                if len(cut) == 2:
                    segs.append([edge_pt(c[cut[0]], c[(cut[0] + 1) % 4]), edge_pt(c[cut[1]], c[(cut[1] + 1) % 4])])
                elif len(cut) == 4:
                    above = (sum(vals) / 4) >= level
                    pairs = ((0, 1), (2, 3)) if above == (vals[0] >= level) else ((0, 3), (1, 2))
                    for a, b in pairs:
                        segs.append([edge_pt(c[cut[a]], c[(cut[a] + 1) % 4]), edge_pt(c[cut[b]], c[(cut[b] + 1) % 4])])
        return _chain(segs)

    def to_geojson(self, path) -> None:
        r = self.result
        feats = []
        if r.contour.kind == "polygon":
            ring = [[float(l), float(b)] for b, l in zip(r.contour.B, r.contour.L)]
            geom = {"type": "Polygon", "coordinates": [ring + ring[:1]]}
        else:
            geom = {"type": "LineString", "coordinates": [[float(l), float(b)] for b, l in zip(r.contour.B, r.contour.L)]}
        feats.append({"type": "Feature", "geometry": geom, "properties": {"role": "object"}})
        for z in ([] if r.fits else r.zones):
            if z.boundary:
                g = ({"type": "Point", "coordinates": [z.boundary[0][1], z.boundary[0][0]]} if len(z.boundary) == 1 else
                     {"type": "LineString", "coordinates": [[p[1], p[0]] for p in z.boundary]})
                feats.append({"type": "Feature", "geometry": g, "properties": {"role": "zone_boundary", "zone": z.name}})
        for lv in self.levels():
            lines = self.isolines(lv)
            if lines:
                feats.append({"type": "Feature", "geometry": {"type": "MultiLineString", "coordinates": lines},
                              "properties": {"role": "isoline", "ppm": lv,
                                             "in_tolerance": abs(lv) <= r.tolerance}})
        out = {"type": "FeatureCollection", "name": "ldp_distortion",
               "properties": {"tolerance_ppm": r.tolerance, "projection": r.projection.proj}, "features": feats}
        Path(path).write_text(json.dumps(out, ensure_ascii=False) + "\n", encoding="utf-8")


def _chain(segs):
    """Сборка отрезков изолинии в линии по общим рёбрам сетки."""
    by_edge = {}
    for k, (a, b) in enumerate(segs):
        by_edge.setdefault(a[0], []).append(k)
        by_edge.setdefault(b[0], []).append(k)
    used = [False] * len(segs)
    lines = []
    for k in range(len(segs)):
        if used[k]:
            continue
        used[k] = True
        line = [segs[k][0], segs[k][1]]
        for forward in (True, False):
            while True:
                end = line[-1] if forward else line[0]
                nxt = next((q for q in by_edge.get(end[0], []) if not used[q]), None)
                if nxt is None:
                    break
                used[nxt] = True
                a, b = segs[nxt]
                p = b if a[0] == end[0] else a
                if forward:
                    line.append(p)
                else:
                    line.insert(0, p)
        lines.append([[round(float(x), 9), round(float(y), 9)] for _, (x, y) in line])
    return lines


def distortion_map(r: LdpResult, size: int = 60, margin: float = 0.05) -> DistortionMap:
    """Карта искажений по сетке вокруг объекта (длинная сторона — size узлов, запас margin габарита).
    Высоты — как у выборки (полилиния — по пикетажу ближайшей точки трассы); при зонах — проекция своей зоны."""
    site, el = r._site, datums.get_system(r.datum).ellipsoid
    n0, n1, e0, e1 = site.vn.min(), site.vn.max(), site.ve.min(), site.ve.max()
    pad = max(margin * max(n1 - n0, e1 - e0), 100.0)
    n0, n1, e0, e1 = n0 - pad, n1 + pad, e0 - pad, e1 + pad
    if e1 - e0 >= n1 - n0:
        nx, ny = size, max(4, math.floor(size * (n1 - n0) / (e1 - e0) + 0.5))
    else:
        ny, nx = size, max(4, math.floor(size * (e1 - e0) / (n1 - n0) + 0.5))
    nn = n0 + (n1 - n0) * np.arange(ny)[::-1] / (ny - 1)   # строка 0 — северная
    ee = e0 + (e1 - e0) * np.arange(nx) / (nx - 1)
    gn, ge = np.meshgrid(nn, ee, indexing="ij")
    fn, fe = gn.ravel(), ge.ravel()
    B, L = (np.asarray(v, float) for v in site.aux.inverse(fn, fe))
    if site.polygon:
        dist = np.where(point_in_polygon(site.vn, site.ve, fn, fe), 0.0, site.boundary_distance(fn, fe))
        base = None if site.vz is None else site.idw(fn, fe)
        s = None
    else:
        s, dist = site.nearest_on_line(fn, fe)
        base = None if site.vz is None else site.line_height(s)
    h = np.asarray(site.heights(B, L, base), float)
    zone = np.zeros(len(B), int)
    zoned = bool(r.zones) and not r.fits
    if zoned:
        key = s if r.zone_key == "chainage" else fe if r.zone_key == "easting" else _across(fn, fe, r.zone_axis)
        zone[:] = len(r.zones)
        for i in range(len(r.zones) - 1, -1, -1):
            zone[key <= r.zones[i].end] = i + 1
    k = np.empty(len(B))
    if zoned:
        for i, z in enumerate(r.zones, 1):
            m = zone == i
            k[m] = z.projection.scale(B[m], L[m])
    else:
        k = np.asarray(r.projection.scale(B, L), float)
    hf = height_factor(el, B, h)
    shp = (ny, nx)
    return DistortionMap(B.reshape(shp), L.reshape(shp), h.reshape(shp), zone.reshape(shp), k.reshape(shp),
                         hf.reshape(shp), distortion_ppm(k, hf).reshape(shp), dist.reshape(shp), r)


# --- чтение спроектированной проекции ---

def load_projection(src, zone: int | None = None) -> LdpProjection:
    """Проекция из JSON ldp (файл или dict): основная или зона zone (1…n). Если в файле есть зоны, а основная
    проекция не укладывается в допуск, нужно указать зону. Понимает и «голую» запись проекции (type, lat0, …)."""
    d = src if isinstance(src, dict) else json.loads(Path(src).read_text(encoding="utf-8"))
    if "lat0" in d and "projection" not in d:
        return LdpProjection.from_dict(d)
    if d.get("format") not in (None, FORMAT):
        raise LdpError(f"Файл не ldp-проекция (format = {d.get('format')}).")
    zones = d.get("zones") or []
    if zone is not None:
        if not 1 <= zone <= len(zones):
            raise LdpError(f"Зона {zone}: в файле зон {len(zones)}.")
        return LdpProjection.from_dict(zones[zone - 1]["projection"])
    if zones and not d.get("fits_tolerance", True) and len(zones) > 1:
        raise LdpError(f"Одна проекция не укладывается в допуск, в файле {len(zones)} зон — укажите зону.")
    return LdpProjection.from_dict(d["projection"])


# --- отчёт ---

def _dms(v: float) -> str:
    s = "-" if v < 0 else ""
    v = abs(v) * 3600
    d, rem = divmod(round(v, 2), 3600)
    m, sec = divmod(rem, 60)
    return f"{s}{int(d)}°{int(m):02d}′{sec:05.2f}″"


def _stat_line(name, st):
    return (f"{name:<22}{st['min_ppm']:>9.2f}{st['max_ppm']:>9.2f}{st['mean_ppm']:>9.2f}{st['rms_ppm']:>9.2f}"
            f"{st['max_abs_ppm']:>10.2f}{st['share_in_tolerance'] * 100:>9.1f}%")


def _proj_lines(p: LdpProjection) -> list[str]:
    s = [f"  тип {p.type}, система {datums.get_system(p.datum).name} (эллипсоид {p.ellipsoid.name})"]
    if p.type == "tmerc":
        s.append(f"  осевой меридиан L0 = {p.lon0!r}° ({_dms(p.lon0)}), широта начала B0 = {p.lat0!r}° ({_dms(p.lat0)})")
    else:
        s.append(f"  центр B0 = {p.lat0!r}°, L0 = {p.lon0!r}°, азимут центральной линии α = {p.alpha!r}° ({_dms(p.alpha)})")
    s += [f"  k0 = {p.k0!r} ({(p.k0 - 1) * 1e6:+.1f} ppm), x0 (север) = {_num(p.x0)} м, y0 (восток) = {_num(p.y0)} м",
          f"  PROJ: {p.proj}"]
    return s


def report(r: LdpResult) -> str:
    o = r.object_info
    size = (f"площадь {o['area_m2'] / 1e6:.2f} км², периметр {o['perimeter_m'] / 1e3:.2f} км" if o["kind"] == "polygon"
            else f"длина {o['length_m'] / 1e3:.2f} км")
    lines = [
        f"Объект: {'полигон' if o['kind'] == 'polygon' else 'полилиния (трасса)'}, вершин {o['vertices']}, {size}; "
        f"габарит N×E {o['extent_north_m'] / 1e3:.2f} × {o['extent_east_m'] / 1e3:.2f} км",
        f"Высоты ({o['height_source']}): h = {o['h_min']:.1f} … {o['h_max']:.1f} м, средняя {o['h_mean']:.1f} м; "
        f"выборка {o['samples']} точек, шаг {r.step:.0f} м",
        f"Допуск ±{r.tolerance:g} ppm (= мм/км), критерий {r.criterion}",
        "",
        "Проекция" + (" (укладывается в допуск):" if r.fits else " (НЕ укладывается в допуск одной зоной):"),
        *_proj_lines(r.projection),
        "",
        "Искажение δ = k·R/(R+h) − 1, ppm (= мм/км); доля — " + ("площади" if r.stats["measure"] == "area" else "длины")
        + " с |δ| ≤ допуска:",
        f"{'':<22}{'min':>9}{'max':>9}{'mean':>9}{'RMS':>9}{'max|δ|':>10}{'доля':>10}",
        _stat_line("LDP", r.stats),
    ]
    for p, st in r.alternatives:
        lines.append(_stat_line(f"альтернатива {p.type}", st))
    g, u = r.comparison["gk"], r.comparison["utm"]
    lines.append(_stat_line("ГК 6°, зона " + ",".join(map(str, g["zones"])), g["stats"]))
    lines.append(_stat_line("UTM, зона " + ",".join(map(str, u["zones"])), u["stats"]))
    if r.zones:
        lines += ["", (f"Запасной вариант — {len(r.zones)} зон(ы) TM (для локализации и Kotlin/веб; минимакс, "
                       f"каждая ≤ ±{r.tolerance:g} ppm):" if r.fits else
                       f"Предлагается {len(r.zones)} зон(ы) (минимакс, каждая ≤ ±{r.tolerance:g} ppm):")]
        unit = {"chainage": "пикетаж", "easting": "восточная координата (вспом.)", "across": "поперёк оси"}[r.zone_key]
        for z in r.zones:
            p = z.projection
            par = (f"L0 = {p.lon0!r}°" if p.type == "tmerc" else f"центр {p.lat0!r}°, {p.lon0!r}°, α = {p.alpha!r}°")
            lines.append(f"  {z.name}: {unit} {z.start / 1e3:.3f} … {z.end / 1e3:.3f} км; {par}, k0 = {p.k0!r}, "
                         f"x0 = {_num(p.x0)}, y0 = {_num(p.y0)}; δ {z.stats['min_ppm']:+.2f} … {z.stats['max_ppm']:+.2f} ppm")
            if z.boundary:
                lines.append("     граница с предыдущей: " + "; ".join(f"B {b:.6f}, L {l:.6f}" for b, l in z.boundary))
    if r.warnings:
        lines += ["", "Замечания:"] + [f"  - {w}" for w in r.warnings]
    return "\n".join(lines)
