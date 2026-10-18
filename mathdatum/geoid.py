"""Сетки высот геоида / аномалий высоты (квазигеоида): чтение, интерполяция, запись.

Форматы:
  GGF     — Trimble Grid Factory (основной формат полевого ПО Trimble), бинарный little-endian; открытого
            описания нет, раскладка восстановлена по файлам (OSM wiki «Trimble GGF» и разбор EGM08-R61.GGF):
              0  int16 версия (1);  2  "TNL GRID FILE\0";  16  имя модели, 32 байта ASCII;
              48 6×float64: latMin, latMax, lonMin, lonMax, dlat, dlon (градусы, узлы);
              96 2×int32: rows (по широте), cols (по долготе);
              104, 112 float64 — значения на полюсах (не используются); 120 float64 — NODATA (0 — не задано);
              128 float64 — масштаб значений (0 → 1); 136 10 байт флагов (смысл неизвестен; у известных
              файлов 02 00 80 00 02 08 02 01 00 00, иные — предупреждение);
              146 rows·cols float32 (или int16 — определяется по размеру файла) по строкам С СЕВЕРА НА ЮГ,
              внутри — с запада на восток; в конце может быть 2×float64 (min, max значений).
  GTX     — NOAA/PROJ, бинарный big-endian: заголовок lat0, lon0, dlat, dlon (float64, градусы, юго-западный
            узел), rows, cols (int32), затем rows·cols float32 по строкам с юга на север, внутри — с запада
            на восток. NODATA — −88.8888.
  ISG     — International Service for the Geoid (ISG 1.0 / 2.0), текст: заголовок begin_of_head …
            end_of_head, затем значения по строкам с севера на юг, внутри — с запада на восток.
  GeoTIFF — сетки PROJ (cdn.proj.org): только чтение, без сжатия или deflate, предиктор 1/2/3, первый канал
            (только в Python; Kotlin читает GTX и ISG).

Значение N(B, L) — высота геоида (аномалия высоты ζ) над эллипсоидом, м: H = h − N.
Интерполяция: bilinear (по 4 узлам ячейки) или bicubic (свёртка Кейса, a = −0.5, по 16 узлам;
узлы воспроизводятся точно, квадратичная поверхность — тоже). Точка вне сетки, NODATA среди
нужных узлов, а для bicubic — точка в крайней ячейке (нет окрестности 4×4) — исключение GeoidError,
а не тихое отключение поправки. Те же формулы — в Kotlin (Geoid.kt), результаты совпадают до 1e-12 м.
"""

from __future__ import annotations

import hashlib
import math
import struct
import warnings
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

GTX_NODATA = -88.8888
GGF_SIGNATURE = b"TNL GRID FILE\0"
GGF_HEADER = 146
GGF_KNOWN_FLAGS = bytes.fromhex("02008000020802010000")
INTERPOLATIONS = ("bilinear", "bicubic")
EDGE_EPS = 1e-9  # допуск выхода за край сетки, в долях шага


class GeoidError(ValueError):
    pass


@dataclass
class GeoidRef:
    """Ссылка на сетку в датуме: имя файла, SHA-256 содержимого, интерполяция. Сама сетка не хранится."""

    file: str
    sha256: str
    interpolation: str = "bilinear"


def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class GeoidGrid:
    """Регулярная сетка в градусах: узел (j, i) — широта lat0 + j·dlat, долгота lon0 + i·dlon;
    values[j, i], строка 0 — южная; NODATA → NaN."""

    def __init__(self, lat0, lon0, dlat, dlon, values, name="grid", sha256=None, fmt=None, notes=None):
        values = np.array(values, float)
        if values.ndim != 2 or values.shape[0] < 2 or values.shape[1] < 2:
            raise GeoidError(f"{name}: сетка должна быть не меньше 2×2 узлов")
        if not (dlat > 0 and dlon > 0):
            raise GeoidError(f"{name}: шаг сетки должен быть > 0")
        self.lat0, self.lon0, self.dlat, self.dlon = float(lat0), float(lon0), float(dlat), float(dlon)
        self.values = values
        self.rows, self.cols = values.shape
        self.name, self.sha256, self.fmt = name, sha256, fmt
        self.notes = list(notes or [])  # замечания читателя (например, неизвестные флаги GGF)
        # Глобальная по долготе: период 360° укладывается в целое число шагов и сетка его покрывает.
        period = round(360.0 / self.dlon)
        self.period = period if abs(period * self.dlon - 360.0) < 1e-6 and self.cols >= period else 0

    @property
    def lat1(self) -> float:
        return self.lat0 + (self.rows - 1) * self.dlat

    @property
    def lon1(self) -> float:
        return self.lon0 + (self.cols - 1) * self.dlon

    def describe(self) -> str:
        nodata = int(np.isnan(self.values).sum())
        return (f"{self.name} ({self.fmt}): {self.rows}×{self.cols} узлов, B {self.lat0:g}…{self.lat1:g}°, "
                f"L {self.lon0:g}…{self.lon1:g}°, шаг {self.dlat * 60:g}′×{self.dlon * 60:g}′"
                + (", глобальная по долготе" if self.period else "") + (f", NODATA: {nodata}" if nodata else "")
                + f"; N {np.nanmin(self.values):.3f}…{np.nanmax(self.values):.3f} м; sha256 {self.sha256}"
                + "".join(f"\n  внимание: {n}" for n in self.notes))

    # --- интерполяция ---
    def _index(self, lat: float, lon: float):
        """(y, x) — дробные индексы узла; ошибка, если точка вне сетки."""
        y = (lat - self.lat0) / self.dlat
        if not (math.isfinite(y) and -EDGE_EPS <= y <= self.rows - 1 + EDGE_EPS):
            raise GeoidError(f"Точка B = {lat:.8f}, L = {lon:.8f} вне сетки геоида {self.name} "
                             f"(B {self.lat0:g}…{self.lat1:g}°, L {self.lon0:g}…{self.lon1:g}°).")
        y = min(max(y, 0.0), self.rows - 1.0)
        t = lon - self.lon0
        if self.period:
            t = t - 360.0 * math.floor(t / 360.0)
            return y, t / self.dlon
        for shift in (0.0, 360.0, -360.0):
            x = (t + shift) / self.dlon
            if -EDGE_EPS <= x <= self.cols - 1 + EDGE_EPS:
                return y, min(max(x, 0.0), self.cols - 1.0)
        raise GeoidError(f"Точка B = {lat:.8f}, L = {lon:.8f} вне сетки геоида {self.name} "
                         f"(B {self.lat0:g}…{self.lat1:g}°, L {self.lon0:g}…{self.lon1:g}°).")

    def _col(self, i: int) -> int:
        return i % self.period if self.period else i

    def _node(self, j: int, i: int, lat, lon) -> float:
        v = self.values[j, self._col(i)]
        if v != v:
            raise GeoidError(f"Точка B = {lat:.8f}, L = {lon:.8f}: в ячейке сетки геоида {self.name} нет данных (NODATA).")
        return float(v)

    def value1(self, lat: float, lon: float, interpolation: str = "bilinear") -> float:
        """N в одной точке, м."""
        y, x = self._index(float(lat), float(lon))
        if interpolation == "bilinear":
            j0 = min(int(math.floor(y)), self.rows - 2)
            i0 = int(math.floor(x)) if self.period else min(int(math.floor(x)), self.cols - 2)
            fy, fx = y - j0, x - i0
            v00, v10 = self._node(j0, i0, lat, lon), self._node(j0, i0 + 1, lat, lon)
            v01, v11 = self._node(j0 + 1, i0, lat, lon), self._node(j0 + 1, i0 + 1, lat, lon)
            return (1 - fx) * ((1 - fy) * v00 + fy * v01) + fx * ((1 - fy) * v10 + fy * v11)
        if interpolation == "bicubic":
            j0, i0 = int(math.floor(y)), int(math.floor(x))
            if j0 == self.rows - 1:
                j0 -= 1
            if not self.period and i0 == self.cols - 1:
                i0 -= 1
            if j0 < 1 or j0 + 2 > self.rows - 1 or (not self.period and (i0 < 1 or i0 + 2 > self.cols - 1)):
                raise GeoidError(f"Точка B = {lat:.8f}, L = {lon:.8f} в крайней ячейке сетки геоида {self.name}: "
                                 "для бикубической интерполяции нужна окрестность 4×4 узла.")
            wy, wx = _keys(y - j0), _keys(x - i0)
            s = 0.0
            for a in range(4):
                r = 0.0
                for b in range(4):
                    r += wx[b] * self._node(j0 - 1 + a, i0 - 1 + b, lat, lon)
                s += wy[a] * r
            return s
        raise GeoidError(f"Интерполяция «{interpolation}»: ожидается bilinear или bicubic.")

    def value(self, lat, lon, interpolation: str = "bilinear"):
        """N(B, L), м; числа или массивы. Вне сетки / NODATA — GeoidError."""
        lat_a, lon_a = np.broadcast_arrays(np.asarray(lat, float), np.asarray(lon, float))
        out = np.array([self.value1(b, l, interpolation) for b, l in zip(lat_a.ravel(), lon_a.ravel())], float)
        return out.reshape(lat_a.shape) if lat_a.ndim else float(out[0])

    def crop(self, lat_min, lat_max, lon_min, lon_max, margin: int = 2) -> "GeoidGrid":
        """Вырезка по охвату (градусы) с запасом margin узлов (для бикубической нужно ≥ 2)."""
        j0 = max(int(math.floor((lat_min - self.lat0) / self.dlat)) - margin, 0)
        j1 = min(int(math.ceil((lat_max - self.lat0) / self.dlat)) + margin, self.rows - 1)
        t0 = lon_min - self.lon0
        if self.period:
            t0 -= 360.0 * math.floor(t0 / 360.0)
        i0 = int(math.floor(t0 / self.dlon)) - margin
        i1 = int(math.ceil((t0 + (lon_max - lon_min)) / self.dlon)) + margin
        if not self.period:
            i0, i1 = max(i0, 0), min(i1, self.cols - 1)
        if j1 - j0 < 1 or i1 - i0 < 1:
            raise GeoidError(f"Охват {lat_min}…{lat_max}, {lon_min}…{lon_max} не пересекает сетку {self.name}.")
        cols = [self._col(i) for i in range(i0, i1 + 1)]
        vals = self.values[j0:j1 + 1][:, cols]
        return GeoidGrid(self.lat0 + j0 * self.dlat, self.lon0 + i0 * self.dlon, self.dlat, self.dlon, vals,
                         name=self.name, fmt=self.fmt)

    # --- запись ---
    def to_gtx(self) -> bytes:
        v = np.where(np.isnan(self.values), GTX_NODATA, self.values).astype(">f4")
        return struct.pack(">4d2i", self.lat0, self.lon0, self.dlat, self.dlon, self.rows, self.cols) + v.tobytes()

    def to_ggf(self, model_name: str = "synthetic", nodata: float = -9999.0) -> bytes:
        """GGF той же раскладки, что у файлов Trimble (float32, строки с севера, хвост min/max)."""
        v = np.where(np.isnan(self.values), nodata, self.values)[::-1].astype("<f4")
        head = (struct.pack("<h", 1) + GGF_SIGNATURE + model_name.encode("ascii")[:31].ljust(32, b"\0")
                + struct.pack("<6d2i", self.lat0, self.lat1, self.lon0, self.lon1, self.dlat, self.dlon,
                              self.rows, self.cols)
                + struct.pack("<4d", 0.0, 0.0, nodata if np.isnan(self.values).any() else 0.0, 1.0) + GGF_KNOWN_FLAGS)
        assert len(head) == GGF_HEADER
        return head + v.tobytes() + struct.pack("<2d", float(np.nanmin(self.values)), float(np.nanmax(self.values)))

    def to_isg(self, model_name: str = "synthetic", digits: int = 6, nodata: float = -9999.0) -> str:
        head = [
            "begin_of_head ================================================",
            f"model name     : {model_name}",
            "model type     : synthetic",
            "data type      : quasi-geoid",
            "data units     : meters",
            "data format    : grid",
            "data ordering  : N-to-S, W-to-E",
            "coord type     : geodetic",
            "coord units    : deg",
            f"lat min        = {self.lat0:.10f}",
            f"lat max        = {self.lat1:.10f}",
            f"lon min        = {self.lon0:.10f}",
            f"lon max        = {self.lon1:.10f}",
            f"delta lat      = {self.dlat:.10f}",
            f"delta lon      = {self.dlon:.10f}",
            f"nrows          = {self.rows:10d}",
            f"ncols          = {self.cols:10d}",
            f"nodata         = {nodata:.4f}",
            "creation date  = ",
            "ISG format     = 2.0",
            "end_of_head ==================================================",
        ]
        rows = []
        for j in range(self.rows - 1, -1, -1):
            rows.append(" ".join(f"{nodata:.4f}" if v != v else f"{v:.{digits}f}" for v in self.values[j]))
        return "\n".join(head + rows) + "\n"

    def save(self, path) -> None:
        path = Path(path)
        ext = path.suffix.lower()
        if ext == ".gtx":
            path.write_bytes(self.to_gtx())
        elif ext == ".ggf":
            path.write_bytes(self.to_ggf())
        elif ext == ".isg":
            path.write_text(self.to_isg(), encoding="utf-8")
        else:
            raise GeoidError(f"{path.name}: запись поддерживается в .ggf, .gtx и .isg")


def _keys(t: float):
    """Веса свёртки Кейса (a = −0.5) для узлов −1, 0, 1, 2 при дробной части t."""
    t2, t3 = t * t, t * t * t
    return ((-t3 + 2 * t2 - t) / 2, (3 * t3 - 5 * t2 + 2) / 2, (-3 * t3 + 4 * t2 + t) / 2, (t3 - t2) / 2)


# --- чтение ---
def read_grid(path) -> GeoidGrid:
    """Читает .ggf, .gtx, .isg или .tif/.tiff; формат — по расширению (иначе по содержимому)."""
    path = Path(path)
    if not path.is_file():
        raise GeoidError(f"Файл сетки геоида не найден: {path}")
    return parse_grid(path.read_bytes(), path.name)


def parse_grid(data: bytes, name: str) -> GeoidGrid:
    ext = Path(name).suffix.lower()
    sha = hashlib.sha256(data).hexdigest()
    if ext == ".ggf" or data[2:16] == GGF_SIGNATURE:
        g = _parse_ggf(data, name)
    elif ext == ".gtx":
        g = _parse_gtx(data, name)
    elif ext == ".isg":
        g = _parse_isg(data.decode("utf-8", errors="replace"), name)
    elif ext in (".tif", ".tiff") or data[:4] in (b"II*\0", b"MM\0*"):
        g = _parse_tiff(data, name)
    elif b"begin_of_head" in data[:4096]:
        g = _parse_isg(data.decode("utf-8", errors="replace"), name)
    else:
        g = _parse_gtx(data, name)
    g.sha256 = sha
    return g


def _parse_ggf(data: bytes, name: str) -> GeoidGrid:
    if len(data) < GGF_HEADER or data[2:16] != GGF_SIGNATURE:
        raise GeoidError(f"{name}: не GGF (нет подписи «TNL GRID FILE» в заголовке)")
    lat_min, lat_max, lon_min, lon_max, dlat, dlon = struct.unpack("<6d", data[48:96])
    rows, cols = struct.unpack("<2i", data[96:104])
    nodata, scale = struct.unpack("<2d", data[120:136])
    flags = data[136:146]
    n = rows * cols
    if rows < 2 or cols < 2:
        raise GeoidError(f"{name}: GGF {rows}×{cols} — сетка должна быть не меньше 2×2")
    rest = len(data) - GGF_HEADER
    if rest in (4 * n, 4 * n + 16):
        v = np.frombuffer(data, "<f4", n, GGF_HEADER).astype(float)
    elif rest in (2 * n, 2 * n + 16):
        v = np.frombuffer(data, "<i2", n, GGF_HEADER).astype(float)
    else:
        raise GeoidError(f"{name}: размер GGF {len(data)} байт не соответствует сетке {rows}×{cols}")
    if not (dlat > 0 and dlon > 0) or abs((lat_max - lat_min) / dlat - (rows - 1)) > 1e-3 \
            or abs((lon_max - lon_min) / dlon - (cols - 1)) > 1e-3:
        raise GeoidError(f"{name}: охват и шаг заголовка GGF не соответствуют {rows}×{cols} узлам")
    notes = []
    if flags != GGF_KNOWN_FLAGS:
        notes.append(f"флаги GGF {flags.hex(' ')} отличаются от известных ({GGF_KNOWN_FLAGS.hex(' ')}) — "
                     "проверьте значения сетки по контрольным пунктам")
        warnings.warn(f"{name}: {notes[-1]}", stacklevel=3)
    bad = ~np.isfinite(v)
    if nodata != 0.0:
        bad |= np.abs(v - nodata) <= 1e-6 * max(1.0, abs(nodata))
    v = v * (scale if scale not in (0.0,) and math.isfinite(scale) else 1.0)
    v[bad] = np.nan
    if lon_min >= 180.0:
        lon_min -= 360.0
    return GeoidGrid(lat_min, lon_min, dlat, dlon, v.reshape(rows, cols)[::-1].copy(), name, fmt="ggf", notes=notes)


def _parse_gtx(data: bytes, name: str) -> GeoidGrid:
    if len(data) < 40:
        raise GeoidError(f"{name}: файл GTX короче заголовка (40 байт)")
    lat0, lon0, dlat, dlon, rows, cols = struct.unpack(">4d2i", data[:40])
    if rows < 2 or cols < 2 or len(data) != 40 + 4 * rows * cols:
        raise GeoidError(f"{name}: заголовок GTX ({rows}×{cols}) не соответствует размеру файла {len(data)} байт")
    v = np.frombuffer(data, ">f4", rows * cols, 40).astype(float).reshape(rows, cols)
    v[np.abs(v - GTX_NODATA) < 1e-4] = np.nan
    if lon0 >= 180.0:  # PROJ: долготы 180…360 → −180…0
        lon0 -= 360.0
    return GeoidGrid(lat0, lon0, dlat, dlon, v, name, fmt="gtx")


def _isg_number(s: str) -> float:
    """Число или угол в формате ISG: 45.5 | 45°30'00\" | -10°00'00\"."""
    s = s.strip()
    if "°" not in s:
        return float(s)
    sign = -1.0 if s.startswith("-") else 1.0
    s = s.lstrip("+-")
    deg, _, rest = s.partition("°")
    mins, _, rest = rest.partition("'")
    secs = rest.replace('"', "").strip()
    return sign * (float(deg) + float(mins or 0) / 60 + float(secs or 0) / 3600)


def _parse_isg(text: str, name: str) -> GeoidGrid:
    lines = text.splitlines()
    try:
        b = next(i for i, ln in enumerate(lines) if ln.strip().lower().startswith("begin_of_head"))
        e = next(i for i, ln in enumerate(lines) if ln.strip().lower().startswith("end_of_head"))
    except StopIteration:
        raise GeoidError(f"{name}: нет заголовка ISG (begin_of_head … end_of_head)") from None
    head = {}
    for ln in lines[b + 1:e]:
        pos = [p for p in (ln.find(":"), ln.find("=")) if p >= 0]
        if pos:
            k = ln[:min(pos)].strip().lower()
            head[k] = ln[min(pos) + 1:].strip()

    def num(key):
        if not head.get(key):
            raise GeoidError(f"{name}: в заголовке ISG нет «{key}»")
        try:
            return _isg_number(head[key])
        except ValueError:
            raise GeoidError(f"{name}: «{key}» = {head[key]!r} — не число") from None

    order = head.get("data ordering", "N-to-S, W-to-E").replace(" ", "").lower()
    if order not in ("n-to-s,w-to-e", ""):
        raise GeoidError(f"{name}: порядок данных «{head['data ordering']}» не поддерживается (нужен N-to-S, W-to-E)")
    if head.get("coord type", "geodetic").lower() not in ("geodetic", ""):
        raise GeoidError(f"{name}: координаты «{head['coord type']}» — поддерживаются только геодезические")
    units = (head.get("data units") or head.get("units") or "meters").lower()
    if units not in ("meters", "metres", "m"):
        raise GeoidError(f"{name}: единицы «{units}» — поддерживаются только метры")
    rows, cols = int(num("nrows")), int(num("ncols"))
    dlat, dlon = num("delta lat"), num("delta lon")
    lat_min, lon_min = num("lat min"), num("lon min")
    lat_max, lon_max = num("lat max"), num("lon max")
    nodata = num("nodata") if head.get("nodata") else None
    # node offset = yes — узлы в центрах ячеек: охват шире сетки узлов на полшага.
    if head.get("node offset", "no").strip().lower() in ("yes", "1", "true"):
        lat_min, lon_min, lat_max, lon_max = lat_min + dlat / 2, lon_min + dlon / 2, lat_max - dlat / 2, lon_max - dlon / 2
    if abs((lat_max - lat_min) / dlat - (rows - 1)) > 1e-3 or abs((lon_max - lon_min) / dlon - (cols - 1)) > 1e-3:
        raise GeoidError(f"{name}: охват и шаг заголовка ISG не соответствуют nrows = {rows}, ncols = {cols}")
    vals = []
    for ln in lines[e + 1:]:
        vals.extend(ln.split())
    if len(vals) != rows * cols:
        raise GeoidError(f"{name}: в ISG {len(vals)} значений, ожидалось {rows}×{cols} = {rows * cols}")
    try:
        v = np.array([float(s) for s in vals], float).reshape(rows, cols)[::-1].copy()
    except ValueError as ex:
        raise GeoidError(f"{name}: {ex}") from None
    if nodata is not None:
        v[np.abs(v - nodata) <= 1e-6 * max(1.0, abs(nodata))] = np.nan
    return GeoidGrid(lat_min, lon_min, dlat, dlon, v, name, fmt="isg")


# --- GeoTIFF (сетки PROJ) ---
_TIFF_TYPES = {1: "B", 2: "s", 3: "H", 4: "I", 5: "II", 6: "b", 7: "B", 8: "h", 9: "i", 10: "ii", 11: "f", 12: "d",
               16: "Q"}
_TIFF_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 16: 8}


def _parse_tiff(data: bytes, name: str) -> GeoidGrid:
    """Первый канал первого изображения GeoTIFF (как сетки геоида PROJ). Сжатие: нет или deflate;
    предиктор 1, 2 (целые) или 3 (плавающая точка); полосы или тайлы."""
    bo = {b"II": "<", b"MM": ">"}.get(data[:2])
    if bo is None or struct.unpack(bo + "H", data[2:4])[0] != 42:
        raise GeoidError(f"{name}: не TIFF (BigTIFF не поддерживается)")
    off = struct.unpack(bo + "I", data[4:8])[0]
    n = struct.unpack(bo + "H", data[off:off + 2])[0]
    tags = {}
    for k in range(n):
        tag, typ, cnt, val = struct.unpack(bo + "HHI4s", data[off + 2 + 12 * k: off + 14 + 12 * k])
        size = _TIFF_SIZES.get(typ, 1) * cnt
        raw = val[:size] if size <= 4 else data[struct.unpack(bo + "I", val)[0]:][:size]
        if typ == 2:
            tags[tag] = raw.rstrip(b"\0").decode("latin-1")
        elif typ in _TIFF_TYPES:
            fmt = _TIFF_TYPES[typ]
            items = struct.unpack(bo + fmt * cnt if len(fmt) == 1 else bo + fmt * cnt, raw)
            if typ in (5, 10):
                items = tuple(items[i] / items[i + 1] for i in range(0, len(items), 2))
            tags[tag] = items
    try:
        width, height = tags[256][0], tags[257][0]
        bits = tags.get(258, (32,))[0]
        comp = tags.get(259, (1,))[0]
        spp = tags.get(277, (1,))[0]
        planar = tags.get(284, (1,))[0]
        pred = tags.get(317, (1,))[0]
        sfmt = tags.get(339, (1,))[0]
        scale, tie = tags[33550], tags[33922]
    except KeyError as ex:
        raise GeoidError(f"{name}: в GeoTIFF нет тега {ex}") from None
    if comp not in (1, 8, 32946):
        raise GeoidError(f"{name}: сжатие TIFF {comp} не поддерживается (нужно без сжатия или deflate)")
    dtype = {(3, 32): "f4", (3, 64): "f8", (1, 16): "u2", (2, 16): "i2", (1, 32): "u4", (2, 32): "i4",
             (1, 8): "u1", (2, 8): "i1"}.get((sfmt, bits))
    if dtype is None:
        raise GeoidError(f"{name}: тип данных TIFF (формат {sfmt}, {bits} бит) не поддерживается")
    itemsize = bits // 8
    bands = spp if planar == 1 else 1
    if 322 in tags:
        tw, th = tags[322][0], tags[323][0]
        offsets, counts = tags[324], tags[325]
    else:
        tw, th = width, tags.get(278, (height,))[0]
        offsets, counts = tags[273], tags[279]
    out = np.empty((height, width), float)
    across = -(-width // tw)
    down = -(-height // th)
    for k in range(across * down):  # только первая плоскость (канал) при planar = 2
        chunk = data[offsets[k]:offsets[k] + counts[k]]
        if comp != 1:
            chunk = zlib.decompress(chunk)
        rows_in = th if 322 in tags else min(th, height - (k // across) * th)
        cols_in = tw
        buf = np.frombuffer(chunk, np.uint8, rows_in * cols_in * bands * itemsize).reshape(rows_in, cols_in * bands * itemsize)
        if pred == 3:  # плавающая точка: разности байтов, затем байты разнесены по старшинству
            b = np.cumsum(buf, axis=1, dtype=np.uint8).reshape(rows_in, itemsize, cols_in * bands)
            arr = b.transpose(0, 2, 1).reshape(rows_in, cols_in * bands * itemsize)
            vals = arr.copy().view(">" + dtype).reshape(rows_in, cols_in * bands)
        else:
            vals = buf.copy().view(bo + dtype).reshape(rows_in, cols_in * bands).astype(np.int64 if dtype[0] in "iu" else float)
            if pred == 2:
                vals = np.cumsum(vals.reshape(rows_in, cols_in, bands), axis=1).reshape(rows_in, cols_in * bands)
                if dtype[0] in "iu":
                    vals = vals.astype(np.int64) & ((1 << bits) - 1)
                    if dtype[0] == "i":
                        vals = np.where(vals >= 1 << (bits - 1), vals - (1 << bits), vals)
        vals = np.asarray(vals, float).reshape(rows_in, cols_in, bands)[:, :, 0]
        r0, c0 = (k // across) * th, (k % across) * tw
        r1, c1 = min(r0 + rows_in, height), min(c0 + cols_in, width)
        out[r0:r1, c0:c1] = vals[:r1 - r0, :c1 - c0]
    nodata = tags.get(42113)
    if nodata:
        nv = float(nodata.strip())
        out[(out == nv) | (np.isnan(out) if math.isnan(nv) else False)] = np.nan
    meta = tags.get(42112, "")
    sc, of = _gdal_item(meta, "SCALE"), _gdal_item(meta, "OFFSET")
    if sc is not None or of is not None:
        out = out * (1.0 if sc is None else sc) + (0.0 if of is None else of)
    # GeoKey 1025 (GTRasterTypeGeoKey): 1 — PixelIsArea (привязка к углу пикселя), 2 — PixelIsPoint.
    gk = tags.get(34735, ())
    area = True
    for i in range(4, len(gk), 4):
        if gk[i] == 1025 and gk[i + 1] == 0:
            area = gk[i + 3] == 1
    if len(tie) < 6 or len(scale) < 2:
        raise GeoidError(f"{name}: нет привязки GeoTIFF (ModelTiepoint / ModelPixelScale)")
    dlon, dlat = scale[0], scale[1]
    lon_left = tie[3] - tie[0] * dlon + (dlon / 2 if area else 0)
    lat_top = tie[4] + tie[1] * dlat - (dlat / 2 if area else 0)
    lat0 = lat_top - (height - 1) * dlat
    if lon_left >= 180.0:
        lon_left -= 360.0
    return GeoidGrid(lat0, lon_left, dlat, dlon, out[::-1].copy(), name, fmt="tif")


def _gdal_item(meta: str, role: str):
    """Значение <Item name="…" role="SCALE"> для первого канала из GDAL_METADATA."""
    import re
    m = re.search(r'<Item[^>]*role="' + role + r'"[^>]*>([^<]*)</Item>', meta or "")
    if not m:
        return None
    sample = re.search(r'sample="(\d+)"', m.group(0))
    if sample and sample.group(1) != "0":
        return None
    return float(m.group(1))
