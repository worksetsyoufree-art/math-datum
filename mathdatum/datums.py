"""Государственные системы координат и пересчёты между ними (ГОСТ 32453-2017).

Свои формулы, без PROJ, чтобы Kotlin-модуль (Datums.kt) повторял их 1:1; PROJ — только в тестах.

  Эллипсоиды: Красовского, ПЗ-90, ГСК-2011, WGS-84, GRS80.
  Системы:    СК-42, СК-95 (Красовский), ПЗ-90, ПЗ-90.02, ПЗ-90.11 (ПЗ-90), ГСК-2011,
              WGS-84 (реализация G1150, как в ГОСТ, прил. Г), ITRF-2008 (GRS80).
  BLH ↔ XYZ на эллипсоиде: blh_to_xyz, xyz_to_blh.
  7 параметров (ГОСТ 32453-2017, формула (1), малые углы, поворот системы координат —
  в PROJ +convention=coordinate_frame):
      X2 = (1 + m) · R · X1 + ΔX,   R = [[1, ωz, −ωy], [−ωz, 1, ωx], [ωy, −ωx, 1]].
  Обратный переход — точное обращение той же формулы:
      X1 = R⁻¹ · (X2 − ΔX) / (1 + m),   R⁻¹ = (Rᵀ + ω·ωᵀ) / (1 + |ω|²),
  поэтому туда-обратно сходится до ~1e-9 м. Упрощённое обращение сменой знаков (ГОСТ Р 51794)
  отличается от точного на ~(|ω| + |m|)·|ΔX| — до 0.6 мм для СК-42.
  Цепочки: путь по графу параметров (поиск в ширину), например СК-42 → ПЗ-90.11 → WGS-84.
  Эпоха (только то, что определено ГОСТ): у параметров ГСК-2011 (2011.0), ПЗ-90.02 → ПЗ-90.11 и
  ПЗ-90.11 → ITRF-2008 (2010.0) есть эпоха. Если заданы эпоха координат и скорость пункта, перед
  таким шагом координаты линейно переносятся на эпоху параметров  X(t) = X(t0) + V·(t − t0),
  а в конце — на целевую эпоху (как в контрольном примере ГОСТ, прил. Е). Скорость пункта
  при переходе между системами не меняется (поворот и масштаб меняют её на ~1e-7 м/год).
  Моделей скоростей нет: без скорости координаты считаются отнесёнными к эпохе параметров.
  Плоские координаты: поперечный Меркатор (ряды Крюгера 6-го порядка, как +proj=tmerc),
  зоны Гаусса–Крюгера 6° (СК-42, СК-95, ГСК-2011): L0 = 6n − 3, y = n·10⁶ + 500 000 + E, x = N;
  и произвольные осевой меридиан, масштаб и смещения («МСК-подобные» системы).
  x — север, y — восток, как в остальной библиотеке.
"""

from __future__ import annotations

import math
import re
from collections import deque
from dataclasses import dataclass

import numpy as np

ARCSEC = math.pi / (180 * 3600)


@dataclass(frozen=True)
class Ellipsoid:
    """Эллипсоид: большая полуось a (м), обратное сжатие rf; proj — запись в синтаксисе PROJ."""

    name: str
    a: float
    rf: float
    proj: str

    @property
    def f(self) -> float:
        return 1 / self.rf

    @property
    def e2(self) -> float:
        return self.f * (2 - self.f)


ELLIPSOIDS = {
    "krass": Ellipsoid("Красовского", 6378245.0, 298.3, "+ellps=krass"),
    "pz90": Ellipsoid("ПЗ-90", 6378136.0, 298.25784, "+a=6378136 +rf=298.25784"),
    "gsk2011": Ellipsoid("ГСК-2011", 6378136.5, 298.2564151, "+a=6378136.5 +rf=298.2564151"),
    "wgs84": Ellipsoid("WGS-84", 6378137.0, 298.257223563, "+ellps=WGS84"),
    "grs80": Ellipsoid("GRS80", 6378137.0, 298.257222101, "+ellps=GRS80"),
}


@dataclass(frozen=True)
class System:
    """Геодезическая система координат: код, название, эллипсоид, другие написания."""

    id: str
    name: str
    ellipsoid: Ellipsoid
    aliases: tuple[str, ...] = ()
    gk_zones: bool = False  # государственные плоские координаты — зоны Гаусса–Крюгера 6°


SYSTEMS = {s.id: s for s in (
    System("SK-42", "СК-42", ELLIPSOIDS["krass"], ("Pulkovo 1942",), True),
    System("SK-95", "СК-95", ELLIPSOIDS["krass"], ("Pulkovo 1995",), True),
    System("GSK-2011", "ГСК-2011", ELLIPSOIDS["gsk2011"], (), True),
    System("PZ-90", "ПЗ-90", ELLIPSOIDS["pz90"]),
    System("PZ-90.02", "ПЗ-90.02", ELLIPSOIDS["pz90"]),
    System("PZ-90.11", "ПЗ-90.11", ELLIPSOIDS["pz90"]),
    System("WGS-84", "WGS-84 (G1150)", ELLIPSOIDS["wgs84"], ("WGS-84 (G1150)", "WGS 84")),
    System("ITRF-2008", "ITRF-2008", ELLIPSOIDS["grs80"], ("ITRF2008",)),
)}


@dataclass(frozen=True)
class Helmert:
    """7 параметров src → dst: ΔX, ΔY, ΔZ (м), ωx, ωy, ωz (″), m (ppm); epoch — эпоха параметров."""

    src: str
    dst: str
    dX: float
    dY: float
    dZ: float
    wx: float
    wy: float
    wz: float
    m: float
    epoch: float | None = None
    source: str = ""


# ГОСТ 32453-2017, приложения А–Д (совпадают с data/geodetic/gost_32453_parameters.json — проверяется тестом).
# Все наборы, кроме ГСК-2011 и ITRF-2008, — композиция параметров ГОСТ Р 51794-2008 (→ ПЗ-90.02) с прил. Б.1.
TRANSFORMATIONS = (
    Helmert("SK-42", "PZ-90.11", 23.557, -140.844, -79.778, -0.00230, -0.34646, -0.79421, -0.228, None, "А.1"),
    Helmert("SK-95", "PZ-90.11", 24.457, -130.784, -81.538, -0.00230, 0.00354, -0.13421, -0.228, None, "А.3"),
    Helmert("GSK-2011", "PZ-90.11", 0.000, 0.014, -0.008, -0.000562, -0.000019, 0.000053, -0.0006, 2011.0, "А.5"),
    Helmert("PZ-90.02", "PZ-90.11", -0.373, 0.186, 0.202, -0.00230, 0.00354, -0.00421, -0.008, 2010.0, "Б.1"),
    Helmert("PZ-90", "PZ-90.11", -1.443, 0.156, 0.222, -0.00230, 0.00354, -0.134210, -0.228, None, "В.1"),
    Helmert("WGS-84", "PZ-90.11", -0.013, 0.106, 0.022, -0.00230, 0.00354, -0.00421, -0.008, None, "Г.1"),
    Helmert("PZ-90.11", "ITRF-2008", -0.003, -0.001, 0.000, 0.000019, -0.000042, 0.000002, 0.000, 2010.0, "Д.1"),
)

_CYR = str.maketrans("СКГПЗ", "SKGPZ")


def _key(name: str) -> str:
    return re.sub(r"[\s\-_()]", "", name.upper()).translate(_CYR)


_LOOKUP = {}
for _s in SYSTEMS.values():
    for _n in (_s.id, _s.name, *_s.aliases):
        _LOOKUP[_key(_n)] = _s.id


def get_system(name: str | System) -> System:
    """Система по коду или названию: "SK-42", "СК-42", "ск42", "WGS-84 (G1150)", "ITRF2008"…"""
    if isinstance(name, System):
        return name
    sid = _LOOKUP.get(_key(name))
    if sid is None:
        raise ValueError(f"Неизвестная система координат «{name}». Есть: {', '.join(SYSTEMS)}")
    return SYSTEMS[sid]


def get_ellipsoid(e: str | Ellipsoid | System) -> Ellipsoid:
    """Эллипсоид по объекту, ключу ELLIPSOIDS (krass, pz90, …) или системе (её эллипсоид)."""
    if isinstance(e, Ellipsoid):
        return e
    if isinstance(e, System):
        return e.ellipsoid
    if e.lower() in ELLIPSOIDS:
        return ELLIPSOIDS[e.lower()]
    return get_system(e).ellipsoid


# --- BLH ↔ XYZ ---

def blh_to_xyz(B, L, h, ellipsoid):
    """B, L (градусы), h (м) → геоцентрические X, Y, Z (м)."""
    el = get_ellipsoid(ellipsoid)
    b, l = np.radians(np.asarray(B, float)), np.radians(np.asarray(L, float))
    h = np.asarray(h, float)
    sb = np.sin(b)
    n = el.a / np.sqrt(1 - el.e2 * sb * sb)
    return (n + h) * np.cos(b) * np.cos(l), (n + h) * np.cos(b) * np.sin(l), (n * (1 - el.e2) + h) * sb


def xyz_to_blh(X, Y, Z, ellipsoid):
    """X, Y, Z (м) → B, L (градусы), h (м). Начальное приближение Боуринга и 3 итерации
    tg B = (Z + e²·N·sin B) / p; h = p·cos B + Z·sin B − a²/N (устойчиво и у полюса)."""
    el = get_ellipsoid(ellipsoid)
    X, Y, Z = np.asarray(X, float), np.asarray(Y, float), np.asarray(Z, float)
    a, e2 = el.a, el.e2
    b = a * (1 - el.f)
    ep2 = e2 / (1 - e2)
    p = np.hypot(X, Y)
    u = np.arctan2(Z * a, p * b)
    lat = np.arctan2(Z + ep2 * b * np.sin(u) ** 3, p - e2 * a * np.cos(u) ** 3)
    for _ in range(3):
        n = a / np.sqrt(1 - e2 * np.sin(lat) ** 2)
        lat = np.arctan2(Z + e2 * n * np.sin(lat), p)
    sl = np.sin(lat)
    n = a / np.sqrt(1 - e2 * sl * sl)
    h = p * np.cos(lat) + Z * sl - a * a / n
    return np.degrees(lat), np.degrees(np.arctan2(Y, X)), h


# --- 7 параметров ---

def _rotation(p: Helmert):
    wx, wy, wz = p.wx * ARCSEC, p.wy * ARCSEC, p.wz * ARCSEC
    return np.array([[1, wz, -wy], [-wz, 1, wx], [wy, -wx, 1]]), np.array([wx, wy, wz])


def helmert_forward(xyz, p: Helmert):
    """Формула ГОСТ 32453: X2 = (1 + m) · R · X1 + ΔX. xyz — (3,) или (n, 3)."""
    R, _ = _rotation(p)
    return (1 + p.m * 1e-6) * np.asarray(xyz, float) @ R.T + np.array([p.dX, p.dY, p.dZ])


def helmert_inverse(xyz, p: Helmert):
    """Точное обращение helmert_forward: X1 = (Rᵀ + ω·ωᵀ) · (X2 − ΔX) / ((1 + |ω|²)·(1 + m))."""
    R, w = _rotation(p)
    Ri = (R.T + np.outer(w, w)) / (1 + w @ w)
    return (np.asarray(xyz, float) - np.array([p.dX, p.dY, p.dZ])) @ Ri.T / (1 + p.m * 1e-6)


@dataclass(frozen=True)
class Step:
    """Шаг цепочки: параметры и направление (forward — src → dst как в ГОСТ, иначе обратный)."""

    params: Helmert
    forward: bool

    @property
    def src(self) -> str:
        return self.params.src if self.forward else self.params.dst

    @property
    def dst(self) -> str:
        return self.params.dst if self.forward else self.params.src

    def __str__(self):
        return f"{SYSTEMS[self.src].name} → {SYSTEMS[self.dst].name} (прил. {self.params.source}" + \
            ("" if self.forward else ", обратный") + ")"


def describe_path(path: list[Step]) -> str:
    """«СК-42 → ПЗ-90.11 → WGS-84 (G1150) (прил. А.1; Г.1, обратный)»; пустой путь — «без пересчёта»."""
    if not path:
        return "без пересчёта"
    names = [SYSTEMS[path[0].src].name] + [SYSTEMS[st.dst].name for st in path]
    refs = "; ".join(st.params.source + ("" if st.forward else ", обратный") for st in path)
    return " → ".join(names) + f" (прил. {refs})"


def find_path(src, dst, transformations=TRANSFORMATIONS) -> list[Step]:
    """Кратчайшая цепочка шагов src → dst по графу параметров (каждый набор — ребро в обе стороны)."""
    a, b = get_system(src).id, get_system(dst).id
    prev = {a: None}
    queue = deque([a])
    while queue:
        cur = queue.popleft()
        if cur == b:
            break
        for t in transformations:
            for fwd, s, d in ((True, t.src, t.dst), (False, t.dst, t.src)):
                if s == cur and d not in prev:
                    prev[d] = (cur, Step(t, fwd))
                    queue.append(d)
    if b not in prev:
        raise ValueError(f"Нет цепочки параметров {a} → {b}.")
    path = []
    while prev[b] is not None:
        b, step = prev[b]
        path.append(step)
    return path[::-1]


def propagate_epoch(xyz, velocity, t_from: float, t_to: float):
    """Линейный перенос эпохи: X(t_to) = X(t_from) + V·(t_to − t_from); V — м/год."""
    return np.asarray(xyz, float) + np.asarray(velocity, float) * (t_to - t_from)


def transform_xyz(xyz, src, dst, epoch: float | None = None, velocity=None, target_epoch: float | None = None,
                  path: list[Step] | None = None):
    """Геоцентрические XYZ (3,) или (n, 3) из src в dst по цепочке find_path (или заданной path).

    epoch, velocity — эпоха координат (десятичный год) и скорость пункта (м/год, (3,) или (n, 3)):
    перед шагом с эпохой параметров координаты переносятся на неё, в конце — на target_epoch
    (по умолчанию — последняя эпоха). Без скорости эпохи не учитываются."""
    x = np.asarray(xyz, float)
    if velocity is not None and epoch is None:
        raise ValueError("Для учёта скорости нужна эпоха координат (epoch).")
    t = epoch
    for st in (find_path(src, dst) if path is None else path):
        te = st.params.epoch
        if velocity is not None and te is not None:
            x, t = propagate_epoch(x, velocity, t, te), te
        x = helmert_forward(x, st.params) if st.forward else helmert_inverse(x, st.params)
    if velocity is not None and target_epoch is not None:
        x = propagate_epoch(x, velocity, t, target_epoch)
    return x


def transform_blh(B, L, h, src, dst, **kw):
    """B, L (градусы), h (м) в src → то же в dst (через XYZ, эллипсоиды систем). kw — как у transform_xyz."""
    s, d = get_system(src), get_system(dst)
    if s.id == d.id and kw.get("velocity") is None:
        return np.asarray(B, float), np.asarray(L, float), np.asarray(h, float)
    xyz = np.stack(blh_to_xyz(B, L, h, s), axis=-1)
    out = transform_xyz(xyz, s, d, **kw)
    return xyz_to_blh(out[..., 0], out[..., 1], out[..., 2], d)


# --- поперечный Меркатор (Крюгер, 6-й порядок) и Гаусс–Крюгер ---

class TransverseMercator:
    """Поперечный Меркатор: осевой меридиан lon0, широта начала lat0, масштаб k0, ложные смещения
    x0 (на север) и y0 (на восток). Те же ряды, что в Kotlin (TransverseMercator.kt) и в PROJ tmerc."""

    def __init__(self, ellipsoid, lon0: float, lat0: float = 0.0, k0: float = 1.0, x0: float = 0.0,
                 y0: float = 0.0):
        el = get_ellipsoid(ellipsoid)
        self.ellipsoid, self.lon0, self.lat0, self.k0, self.x0, self.y0 = el, lon0, lat0, k0, x0, y0
        self.e = math.sqrt(el.e2)
        n = el.f / (2 - el.f)
        n2, n3, n4, n5, n6 = n ** 2, n ** 3, n ** 4, n ** 5, n ** 6
        self.A = el.a / (1 + n) * (1 + n2 / 4 + n4 / 64 + n6 / 256)
        self.alpha = (
            n / 2 - 2 * n2 / 3 + 5 * n3 / 16 + 41 * n4 / 180 - 127 * n5 / 288 + 7891 * n6 / 37800,
            13 * n2 / 48 - 3 * n3 / 5 + 557 * n4 / 1440 + 281 * n5 / 630 - 1983433 * n6 / 1935360,
            61 * n3 / 240 - 103 * n4 / 140 + 15061 * n5 / 26880 + 167603 * n6 / 181440,
            49561 * n4 / 161280 - 179 * n5 / 168 + 6601661 * n6 / 7257600,
            34729 * n5 / 80640 - 3418889 * n6 / 1995840,
            212378941 * n6 / 319334400,
        )
        self.beta = (
            n / 2 - 2 * n2 / 3 + 37 * n3 / 96 - n4 / 360 - 81 * n5 / 512 + 96199 * n6 / 604800,
            n2 / 48 + n3 / 15 - 437 * n4 / 1440 + 46 * n5 / 105 - 1118711 * n6 / 3870720,
            17 * n3 / 480 - 37 * n4 / 840 - 209 * n5 / 4480 + 5569 * n6 / 90720,
            4397 * n4 / 161280 - 11 * n5 / 504 - 830251 * n6 / 7257600,
            4583 * n5 / 161280 - 108847 * n6 / 3991680,
            20648693 * n6 / 638668800,
        )
        self.n0 = float(self._raw(np.asarray(lat0, float), np.asarray(lon0, float))[0])

    def _raw(self, B, L):
        phi, lam = np.radians(B), np.radians(L - self.lon0)
        e = self.e
        t = np.sinh(np.arctanh(np.sin(phi)) - e * np.arctanh(e * np.sin(phi)))
        xi_p = np.arctan2(t, np.cos(lam))
        eta_p = np.arcsinh(np.sin(lam) / np.sqrt(t * t + np.cos(lam) ** 2))
        xi, eta = xi_p, eta_p
        for j, a in enumerate(self.alpha, 1):
            xi = xi + a * np.sin(2 * j * xi_p) * np.cosh(2 * j * eta_p)
            eta = eta + a * np.cos(2 * j * xi_p) * np.sinh(2 * j * eta_p)
        return self.A * xi, self.A * eta

    def forward(self, B, L):
        """B, L (градусы) → x (север), y (восток), м."""
        n, e = self._raw(np.asarray(B, float), np.asarray(L, float))
        return self.x0 + self.k0 * (n - self.n0), self.y0 + self.k0 * e

    def _factors(self, B, L):
        phi, lam = np.radians(np.asarray(B, float)), np.radians(np.asarray(L, float) - self.lon0)
        e, e2 = self.e, self.ellipsoid.e2
        t = np.sinh(np.arctanh(np.sin(phi)) - e * np.arctanh(e * np.sin(phi)))
        c = np.cos(lam)
        xi_p = np.arctan2(t, c)
        eta_p = np.arcsinh(np.sin(lam) / np.sqrt(t * t + c * c))
        p, q = 1.0, 0.0
        for j, a in enumerate(self.alpha, 1):
            p = p + 2 * j * a * np.cos(2 * j * xi_p) * np.cosh(2 * j * eta_p)
            q = q + 2 * j * a * np.sin(2 * j * xi_p) * np.sinh(2 * j * eta_p)
        k = self.k0 * self.A / self.ellipsoid.a * np.sqrt(1 + (1 - e2) * np.tan(phi) ** 2) \
            / np.sqrt(t * t + c * c) * np.hypot(p, q)
        gamma = np.arctan2(q, p) + np.arctan2(t * np.tan(lam), np.sqrt(1 + t * t))
        return k, np.degrees(gamma)

    def scale(self, B, L):
        """Масштаб в точке (Karney 2011, (25)): k = k0·(A/a)·√(1 + (1 − e²)·tg²B) / √(τ'² + cos²l) · √(p² + q²),
        τ' = sh(arth sin B − e·arth(e·sin B)), p = 1 + Σ 2j·αj·cos 2jξ'·ch 2jη', q = Σ 2j·αj·sin 2jξ'·sh 2jη'
        (ξ', η' — как в forward); у осевого меридиана k ≈ k0·(1 + y²/(2R²))."""
        return self._factors(B, L)[0]

    def convergence(self, B, L):
        """Сближение меридианов γ, градусы (угол от оси x сетки до направления на север, как в PROJ):
        γ = atan2(q, p) + atan2(τ'·tg l, √(1 + τ'²))."""
        return self._factors(B, L)[1]

    def inverse(self, x, y):
        """x (север), y (восток) → B, L (градусы)."""
        xi = ((np.asarray(x, float) - self.x0) / self.k0 + self.n0) / self.A
        eta = (np.asarray(y, float) - self.y0) / self.k0 / self.A
        xi_p, eta_p = xi, eta
        for j, b in enumerate(self.beta, 1):
            xi_p = xi_p - b * np.sin(2 * j * xi) * np.cosh(2 * j * eta)
            eta_p = eta_p - b * np.cos(2 * j * xi) * np.sinh(2 * j * eta)
        chi = np.arcsin(np.sin(xi_p) / np.cosh(eta_p))
        dlon = np.arctan2(np.sinh(eta_p), np.cos(xi_p))
        # Конформная широта → геодезическая (итерации, как в Kotlin).
        phi, e = chi, self.e
        for _ in range(15):
            es = e * np.sin(phi)
            phi = 2 * np.arctan(np.tan(np.pi / 4 + chi / 2) * ((1 + es) / (1 - es)) ** (e / 2)) - np.pi / 2
        return np.degrees(phi), self.lon0 + np.degrees(dlon)

    @property
    def proj(self) -> str:
        """То же в синтаксисе PROJ (x_0 в PROJ — восток, y_0 — север)."""
        return (f"+proj=tmerc +lat_0={self.lat0!r} +lon_0={self.lon0!r} +k={self.k0!r} +x_0={self.y0!r} "
                f"+y_0={self.x0!r} {self.ellipsoid.proj} +units=m")


def gk_zone(L) -> np.ndarray:
    """Номер 6-градусной зоны Гаусса–Крюгера по долготе: n = ⌊L/6⌋ + 1 (L в [0, 360))."""
    return (np.floor(np.mod(np.asarray(L, float), 360.0) / 6) + 1).astype(int)


def gk_projection(zone: int, ellipsoid="krass") -> TransverseMercator:
    """Зона n: L0 = 6n − 3, k0 = 1, ложное смещение на восток n·10⁶ + 500 000 м."""
    if not 1 <= int(zone) <= 60:
        raise ValueError(f"Номер зоны Гаусса–Крюгера {zone}: ожидается 1…60.")
    return TransverseMercator(ellipsoid, 6.0 * int(zone) - 3, 0.0, 1.0, 0.0, int(zone) * 1e6 + 500_000.0)


def gk_forward(B, L, ellipsoid="krass", zone: int | None = None):
    """B, L → x, y Гаусса–Крюгера (y с номером зоны). zone — принудительная зона (иначе по долготе)."""
    B, L = np.broadcast_arrays(np.asarray(B, float), np.asarray(L, float))
    zones = np.full(B.shape, int(zone)) if zone is not None else gk_zone(L)
    x, y = np.empty(B.shape), np.empty(B.shape)
    for z in np.unique(zones):
        m = zones == z
        x[m], y[m] = gk_projection(int(z), ellipsoid).forward(B[m], L[m])
    return (x, y) if x.ndim else (float(x), float(y))


def gk_inverse(x, y, ellipsoid="krass", zone: int | None = None):
    """x, y Гаусса–Крюгера → B, L. Зона — по первым цифрам y (y = n·10⁶ + 500 000 + E);
    если задана zone, y должен содержать тот же номер."""
    x, y = np.broadcast_arrays(np.asarray(x, float), np.asarray(y, float))
    zones = np.floor(y / 1e6).astype(int)
    if zone is not None and np.any(zones != int(zone)):
        raise ValueError(f"Координата y не из зоны {zone} (ожидается y = {zone}·10⁶ + 500 000 + E).")
    B, L = np.empty(x.shape), np.empty(x.shape)
    for z in np.unique(zones):
        m = zones == z
        B[m], L[m] = gk_projection(int(z), ellipsoid).inverse(x[m], y[m])
    return (B, L) if B.ndim else (float(B), float(L))
