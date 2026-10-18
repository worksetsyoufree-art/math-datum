"""Экспорт датума локализации в форматы ГИС, ПО и контроллеров.

Датум = рабочая проекция (TM: lat0, lon0, k0, x0, y0 на эллипсоиде gnss_datum) + подобие в плане
(a, b, tx, ty относительно центроида Nc, Ec) + модель высоты (plane / shift / geoid / geoid_plane / none).

Форматы:
  wkt2      ISO 19162:2019 (WKT2), CRS. План — стандартные методы EPSG: DERIVEDPROJCRS = базовая TM
            (Transverse Mercator, EPSG 9807) + DERIVINGCONVERSION «Similarity transformation» (EPSG 9621),
            точно. Если разворот на объекте даёт < 0.1 мм — подобие сворачивается в TM (k0·масштаб,
            ложные смещения) и получается обычный PROJCRS. Высота — BOUNDCRS вертикальной системы к
            ГНСС-системе 3D с преобразованием «PROJ-based operation method» (наклонная плоскость, сетка
            геоида vgridshift): для такой модели нет метода EPSG от эллипсоидальной высоты, поэтому
            высоту точно поймёт только ПО на PROJ ≥ 6 (QGIS, GDAL, pyproj). Оси — восток (y), север (x).
  projjson  то же в PROJJSON (схема PROJ 0.7).
  jxl       Trimble JobXML 6.30 (Environment/CoordinateSystem): TM с k0·масштаб (масштаб подобия
            сворачивается точно), горизонтальная корректировка PlaneAdjustment (центр — tx, ty, сдвиг 0,
            масштаб 1, разворот), вертикальная InclinedPlane / GeoidModelAndInclinedPlane. Знак разворота и
            система координат наклона в открытой документации заданы неоднозначно — см. предупреждения.
  landxml   LandXML 1.2: CoordinateSystem без параметров локализации, датум — строкой WKT2 в ogcWktCode.
  proj      строка PROJ-пайплайна (как `proj`).
Закрытые форматы (Trimble .cal/.dc, Topcon .gc3/.tp3, Carlson .loc, Leica, gsimath) не пишутся:
ExportError с перечнем нужного для поддержки (docs/export.md).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from . import datums

FORMATS = ("wkt2", "projjson", "jxl", "landxml", "proj")
EXTENSIONS = {"wkt2": ".wkt", "projjson": ".json", "jxl": ".jxl", "landxml": ".xml", "proj": ".txt"}
FOLD_TOL = 1e-4      # м: разворот меньше этого на объекте — подобие сворачивается в TM (WKT2/PROJJSON)
JXL_TOL = 5e-4       # м: неоднозначность JobXML меньше этого на объекте — без предупреждения
DEG = "0.0174532925199433"
CLOSED = {
    "cal": "Trimble .cal (калибровка Trimble Survey Controller / Access) — закрытый двоичный формат",
    "dc": "Trimble .dc (Survey Controller) — закрытый формат записей",
    "gc3": "Topcon / Sokkia .gc3 (Magnet Field) — закрытый формат",
    "tp3": "Topcon .tp3 — закрытый формат",
    "loc": "Carlson SurvCE / SurvPC .loc — открытого описания нет",
    "hexml": "Leica HeXML / Captivate .xml — схема с параметрами локализации не опубликована",
    "gsimath": "проект gsimath — формат не описан",
    "csd": "Trimble .csd (база систем координат) — закрытый формат",
}


class ExportError(ValueError):
    pass


@dataclass
class ExportResult:
    """text — содержимое файла; warnings — ограничения и оценки погрешности по объекту."""

    format: str
    text: str
    warnings: list[str] = field(default_factory=list)

    @property
    def extension(self) -> str:
        return EXTENSIONS[self.format]


# --- числа (одинаково с Kotlin: кратчайшая запись, как repr в Python) ---

def fnum(v: float) -> str:
    v = float(v)
    if v == 0:
        return "0"
    if v == math.floor(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(v)


# --- эллипсоид и система ---

ELLIPSOID_NAMES = {"krass": "Krassowsky 1940", "pz90": "PZ-90", "gsk2011": "GSK-2011", "wgs84": "WGS 84",
                   "grs80": "GRS 1980"}
DATUM_NAMES = {"SK-42": "Pulkovo 1942", "SK-95": "Pulkovo 1995", "GSK-2011": "Geodezicheskaya Sistema Koordinat 2011",
               "PZ-90": "Parametry Zemli 1990", "PZ-90.02": "Parametry Zemli 1990.02",
               "PZ-90.11": "Parametry Zemli 1990.11", "WGS-84": "World Geodetic System 1984",
               "ITRF-2008": "International Terrestrial Reference Frame 2008"}


def ellipsoid_of(d) -> tuple[str, float, float]:
    """(название, a, 1/f) эллипсоида рабочей проекции датума."""
    for key, e in datums.ELLIPSOIDS.items():
        if d.ellipsoid.strip() == e.proj:
            return ELLIPSOID_NAMES[key], e.a, e.rf
    m = dict(re.findall(r"\+(a|rf)=([-+0-9.eE]+)", d.ellipsoid))
    if "a" in m and "rf" in m:
        return "unknown", float(m["a"]), float(m["rf"])
    raise ExportError(f"Эллипсоид рабочей проекции «{d.ellipsoid}» не распознан: нужен +ellps= из "
                      f"{', '.join(e.proj for e in datums.ELLIPSOIDS.values())} или +a= +rf=.")


def datum_name(d) -> str:
    sysid = d.gnss_system
    if sysid is None:
        return f"Unknown based on {ellipsoid_of(d)[0]} ellipsoid"
    return DATUM_NAMES[sysid]


# --- геометрия объекта и оценки ---

def object_radius(d) -> float | None:
    """Наибольшее расстояние от центроида до вершин оболочки опорных пунктов, м (None — оболочки нет)."""
    if not d.plan_hull:
        return None
    return max(math.hypot(n - d.Nc, e - d.Ec) for n, e in d.plan_hull)


def rotation(d) -> float:
    """Разворот подобия, рад (положительный — по часовой стрелке: дирекционные углы растут)."""
    return math.atan2(d.b, d.a)


def scale(d) -> float:
    return math.hypot(d.a, d.b)


def fold_error(d) -> float | None:
    """Погрешность свёртки подобия в TM (разворот отбрасывается), м: 2·k·R·sin(|θ|/2); None — не оценить."""
    if d.b == 0:
        return 0.0
    r = object_radius(d)
    return None if r is None else 2 * scale(d) * r * math.sin(abs(rotation(d)) / 2)


def folds(d) -> bool:
    e = fold_error(d)
    return e is not None and e < FOLD_TOL


def _q(s: str) -> str:
    return '"' + s.replace('"', '""') + '"'


# --- WKT2 ---

class _W:
    """Узел WKT: KEYWORD[простые значения, вложенные узлы]."""

    def __init__(self, kw: str, *items):
        self.kw, self.items = kw, [i for i in items if i is not None]

    def render(self, indent: int = 0) -> str:
        pad = " " * (indent + 4)
        out, first = self.kw + "[", True
        for it in self.items:
            if isinstance(it, _W):
                out += ("" if first else ",") + "\n" + pad + it.render(indent + 4)
            else:
                out += ("" if first else ",") + (_q(it) if isinstance(it, str) else it.raw if isinstance(it, _Raw)
                                                 else fnum(it))
            first = False
        return out + "]"


class _Raw:
    def __init__(self, raw: str):
        self.raw = raw


def _unit(kind: str):
    return {"deg": _W("ANGLEUNIT", "degree", _Raw(DEG)), "m": _W("LENGTHUNIT", "metre", 1),
            "1": _W("SCALEUNIT", "unity", 1)}[kind]


def _param(name: str, value: float, unit: str, code: int):
    return _W("PARAMETER", name, value, _unit(unit), _W("ID", "EPSG", code))


def _geog(d, name: str, three_d: bool):
    en, a, rf = ellipsoid_of(d)
    datum = _W("DATUM", datum_name(d), _W("ELLIPSOID", en, a, rf, _unit("m")))
    prime = _W("PRIMEM", "Greenwich", 0, _unit("deg"))
    if not three_d:
        return _W("BASEGEOGCRS", name, datum, prime)
    return _W("GEOGCRS", name, datum, prime, _W("CS", _Raw("ellipsoidal"), 3),
              _W("AXIS", "geodetic latitude (Lat)", _Raw("north"), _W("ORDER", 1), _unit("deg")),
              _W("AXIS", "geodetic longitude (Lon)", _Raw("east"), _W("ORDER", 2), _unit("deg")),
              _W("AXIS", "ellipsoidal height (h)", _Raw("up"), _W("ORDER", 3), _unit("m")))


def _tm_conversion(name: str, lat0, lon0, k0, fe, fn):
    return _W("CONVERSION", name, _W("METHOD", "Transverse Mercator", _W("ID", "EPSG", 9807)),
              _param("Latitude of natural origin", lat0, "deg", 8801),
              _param("Longitude of natural origin", lon0, "deg", 8802),
              _param("Scale factor at natural origin", k0, "1", 8805),
              _param("False easting", fe, "m", 8806),
              _param("False northing", fn, "m", 8807))


def _cs_en():
    return [_W("CS", _Raw("Cartesian"), 2),
            _W("AXIS", "easting (Y)", _Raw("east"), _W("ORDER", 1), _unit("m")),
            _W("AXIS", "northing (X)", _Raw("north"), _W("ORDER", 2), _unit("m"))]


def similarity_params(d) -> tuple[float, float, float, float]:
    """Параметры EPSG 9621 для осей (восток, север): XT0 (восток), YT0 (север), масштаб M, разворот θ, градусы.
    y = XT0 + M·cosθ·E + M·sinθ·N,  x = YT0 − M·sinθ·E + M·cosθ·N  (E, N — рабочая TM)."""
    a, b = d.a, d.b
    return (d.ty - a * d.Ec - b * d.Nc, d.tx - a * d.Nc + b * d.Ec, scale(d), math.degrees(rotation(d)))


def folded_tm(d) -> tuple[float, float, float]:
    """TM со свёрнутым масштабом подобия: (k0·M, ложное восточное, ложное северное)."""
    m = scale(d)
    return d.k0 * m, d.ty + m * (d.y0 - d.Ec), d.tx + m * (d.x0 - d.Nc)


def _tm_proj(d, inv=False) -> str:
    """tmerc рабочей проекции в синтаксисе PROJ (радианы на входе)."""
    return (("+inv " if inv else "") + f"+proj=tmerc +lat_0={fnum(d.lat0)} +lon_0={fnum(d.lon0)} +k={fnum(d.k0)} "
            f"+x_0={fnum(d.y0)} +y_0={fnum(d.x0)} {d.ellipsoid}")


def height_pipeline(d, grid_file: str | None) -> str:
    """PROJ-пайплайн H → h (вход — долгота, широта в радианах, как PROJ передаёт в BOUNDCRS)."""
    zoff = d.c0 - d.c1 * d.Nc - d.c2 * d.Ec
    out = (f"+proj=pipeline +step {_tm_proj(d)} "
           f"+step +proj=affine +zoff={fnum(-zoff)} +s31={fnum(-d.c2)} +s32={fnum(-d.c1)} +s33=1 "
           f"+step {_tm_proj(d, inv=True)}")
    if grid_file:
        out += f" +step +proj=vgridshift +grids={grid_file} +multiplier=1"
    return out


def _geoid_target(d, geoid_file: str | None, warnings: list[str], proj_reads=("gtx", "tif", "tiff")) -> str | None:
    """Имя файла сетки для PROJ (vgridshift) с предупреждениями о формате и интерполяции."""
    if d.geoid is None:
        return None
    src = d.geoid.file
    stem, _, ext = src.rpartition(".")
    if geoid_file:
        target = geoid_file
    elif ext.lower() in proj_reads:
        target = src
    else:
        target = (stem or src) + ".gtx"
        warnings.append(f"Сетка {src}: PROJ не читает {ext.upper() or 'этот формат'} — в файле указана {target}. "
                        f"Переведите: python -m mathdatum geoid {src} -o {target} (узлы те же, float32).")
    if d.geoid.interpolation != "bilinear":
        est = interp_difference(d)
        warnings.append(f"Датум использует интерполяцию {d.geoid.interpolation}, PROJ vgridshift — билинейную"
                        + (f": разница на объекте до {est * 1000:.1f} мм." if est is not None
                           else " (сетка не загружена — разницу на объекте не оценить)."))
    return target


def _sample_points(d):
    """Точки объекта для оценок: вершины оболочки и центроид (N, E рабочей проекции)."""
    pts = [(d.Nc, d.Ec)]
    if d.plan_hull:
        pts += [(n, e) for n, e in d.plan_hull]
        for (n1, e1), (n2, e2) in zip(d.plan_hull, d.plan_hull[1:] + d.plan_hull[:1]):
            pts.append(((n1 + n2) / 2, (e1 + e2) / 2))
    return pts


def interp_difference(d) -> float | None:
    """max |N_bicubic − N_bilinear| по точкам объекта, м (None — сетка не загружена)."""
    g = d.geoid_grid
    if g is None:
        return None
    from .datums import TransverseMercator
    tm = TransverseMercator(datums.Ellipsoid("e", *ellipsoid_of(d)[1:], d.ellipsoid), lon0=d.lon0, lat0=d.lat0,
                            k0=d.k0, x0=d.x0, y0=d.y0)
    out = 0.0
    for n, e in _sample_points(d):
        B, L = tm.inverse(n, e)
        try:
            out = max(out, abs(g.value1(B, L, "bicubic") - g.value1(B, L, "bilinear")))
        except Exception:
            pass
    return out


def _plan_crs(d, name: str, warnings: list[str]):
    base = _geog(d, f"{name} GNSS", three_d=False)
    if folds(d):
        k0, fe, fn = folded_tm(d)
        err = fold_error(d)
        if d.b != 0:
            warnings.append(f"Разворот {math.degrees(rotation(d)) * 3600:.3f}″ свёрнут в TM без поворота: "
                            f"погрешность на объекте ≤ {err * 1000:.3f} мм.")
        return _W("PROJCRS", f"{name} plan", base,
                  _tm_conversion(f"{name} TM (similarity folded)", d.lat0, d.lon0, k0, fe, fn), *_cs_en())
    xt0, yt0, m, theta = similarity_params(d)
    return _W("DERIVEDPROJCRS", f"{name} plan",
              _W("BASEPROJCRS", f"{name} working TM", base,
                 _tm_conversion(f"{name} working TM", d.lat0, d.lon0, d.k0, d.y0, d.x0)),
              _W("DERIVINGCONVERSION", f"{name} similarity",
                 _W("METHOD", "Similarity transformation", _W("ID", "EPSG", 9621)),
                 _param("Ordinate 1 of evaluation point in target CRS", xt0, "m", 8621),
                 _param("Ordinate 2 of evaluation point in target CRS", yt0, "m", 8622),
                 _param("Scale factor for source coordinate reference system axes", m, "1", 1061),
                 _param("Rotation angle of source coordinate reference system axes", theta, "deg", 8614)),
              *_cs_en())


REMARK = ("mathdatum localization: x = tx + a*(N-Nc) - b*(E-Ec), y = ty + b*(N-Nc) + a*(E-Ec) "
          "(N, E - working TM); H = h - N_geoid + c0 + c1*(N-Nc) + c2*(E-Ec). Axes: easting (y), northing (x).")


def _height_parts(d, name, geoid_file, warnings):
    if d.height_model == "none":
        warnings.append("Модели высоты нет (не было точек для высоты): экспортирован только план.")
        return None
    grid = _geoid_target(d, geoid_file, warnings)
    return grid, height_pipeline(d, grid)


def to_wkt2(d, name: str = "Localization", geoid_file: str | None = None) -> ExportResult:
    w: list[str] = []
    plan = _plan_crs(d, name, w)
    h = _height_parts(d, name, geoid_file, w)
    if h is None:
        plan.items.append(_W("REMARK", REMARK))
        return ExportResult("wkt2", plan.render() + "\n", w)
    _, pipe = h
    vert = _W("BOUNDCRS",
              _W("SOURCECRS", _W("VERTCRS", f"{name} height", _W("VDATUM", f"{name} local height"),
                                 _W("CS", _Raw("vertical"), 1),
                                 _W("AXIS", "gravity-related height (H)", _Raw("up"), _unit("m")))),
              _W("TARGETCRS", _geog(d, f"{name} GNSS", three_d=True)),
              _W("ABRIDGEDTRANSFORMATION", f"{name} height to ellipsoidal height",
                 _W("METHOD", "PROJ-based operation method: " + pipe)))
    crs = _W("COMPOUNDCRS", name, plan, vert, _W("REMARK", REMARK))
    w.append("Высота задана методом «PROJ-based operation method» (наклонная плоскость от эллипсоидальной "
             "высоты в EPSG не описана): её применит только ПО на PROJ ≥ 6; план — стандартные методы EPSG.")
    return ExportResult("wkt2", crs.render() + "\n", w)


# --- PROJJSON ---

def _jdump(v, indent=0) -> str:
    pad, pad1 = " " * indent, " " * (indent + 2)
    if isinstance(v, dict):
        if not v:
            return "{}"
        return "{\n" + ",\n".join(f"{pad1}{_jstr(k)}: {_jdump(x, indent + 2)}" for k, x in v.items()) + "\n" + pad + "}"
    if isinstance(v, list):
        if not v:
            return "[]"
        return "[\n" + ",\n".join(pad1 + _jdump(x, indent + 2) for x in v) + "\n" + pad + "]"
    if isinstance(v, str):
        return _jstr(v)
    if isinstance(v, bool):
        return "true" if v else "false"
    return fnum(v)


def _jstr(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch in '"\\':
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join(out) + '"'


def _jp(name, value, unit, code):
    u = {"deg": "degree", "m": "metre", "1": "unity"}[unit]
    return {"name": name, "value": value, "unit": u, "id": {"authority": "EPSG", "code": code}}


def _jgeog(d, name, three_d):
    en, a, rf = ellipsoid_of(d)
    out = {"type": "GeographicCRS", "name": name,
           "datum": {"type": "GeodeticReferenceFrame", "name": datum_name(d),
                     "ellipsoid": {"name": en, "semi_major_axis": a, "inverse_flattening": rf}},
           "coordinate_system": {"subtype": "ellipsoidal", "axis": [
               {"name": "Geodetic latitude", "abbreviation": "Lat", "direction": "north", "unit": "degree"},
               {"name": "Geodetic longitude", "abbreviation": "Lon", "direction": "east", "unit": "degree"}]}}
    if three_d:
        out["coordinate_system"]["axis"].append(
            {"name": "Ellipsoidal height", "abbreviation": "h", "direction": "up", "unit": "metre"})
    return out


def _jtm(name, lat0, lon0, k0, fe, fn):
    return {"name": name, "method": {"name": "Transverse Mercator", "id": {"authority": "EPSG", "code": 9807}},
            "parameters": [_jp("Latitude of natural origin", lat0, "deg", 8801),
                           _jp("Longitude of natural origin", lon0, "deg", 8802),
                           _jp("Scale factor at natural origin", k0, "1", 8805),
                           _jp("False easting", fe, "m", 8806), _jp("False northing", fn, "m", 8807)]}


def _jcs_en():
    return {"subtype": "Cartesian", "axis": [
        {"name": "Easting", "abbreviation": "Y", "direction": "east", "unit": "metre"},
        {"name": "Northing", "abbreviation": "X", "direction": "north", "unit": "metre"}]}


def to_projjson(d, name: str = "Localization", geoid_file: str | None = None) -> ExportResult:
    w: list[str] = []
    base = _jgeog(d, f"{name} GNSS", False)
    if folds(d):
        k0, fe, fn = folded_tm(d)
        if d.b != 0:
            w.append(f"Разворот {math.degrees(rotation(d)) * 3600:.3f}″ свёрнут в TM без поворота: "
                     f"погрешность на объекте ≤ {fold_error(d) * 1000:.3f} мм.")
        plan = {"type": "ProjectedCRS", "name": f"{name} plan", "base_crs": base,
                "conversion": _jtm(f"{name} TM (similarity folded)", d.lat0, d.lon0, k0, fe, fn),
                "coordinate_system": _jcs_en()}
    else:
        xt0, yt0, m, theta = similarity_params(d)
        plan = {"type": "DerivedProjectedCRS", "name": f"{name} plan",
                "base_crs": {"type": "ProjectedCRS", "name": f"{name} working TM", "base_crs": base,
                             "conversion": _jtm(f"{name} working TM", d.lat0, d.lon0, d.k0, d.y0, d.x0),
                             "coordinate_system": _jcs_en()},
                "conversion": {"name": f"{name} similarity",
                               "method": {"name": "Similarity transformation",
                                          "id": {"authority": "EPSG", "code": 9621}},
                               "parameters": [
                                   _jp("Ordinate 1 of evaluation point in target CRS", xt0, "m", 8621),
                                   _jp("Ordinate 2 of evaluation point in target CRS", yt0, "m", 8622),
                                   _jp("Scale factor for source coordinate reference system axes", m, "1", 1061),
                                   _jp("Rotation angle of source coordinate reference system axes", theta, "deg",
                                       8614)]},
                "coordinate_system": _jcs_en()}
    h = _height_parts(d, name, geoid_file, w)
    schema = "https://proj.org/schemas/v0.7/projjson.schema.json"
    if h is None:
        out = {"$schema": schema, **plan, "remarks": REMARK}
        return ExportResult("projjson", _jdump(out) + "\n", w)
    _, pipe = h
    vert = {"type": "BoundCRS",
            "source_crs": {"type": "VerticalCRS", "name": f"{name} height",
                           "datum": {"type": "VerticalReferenceFrame", "name": f"{name} local height"},
                           "coordinate_system": {"subtype": "vertical", "axis": [
                               {"name": "Gravity-related height", "abbreviation": "H", "direction": "up",
                                "unit": "metre"}]}},
            "target_crs": _jgeog(d, f"{name} GNSS", True),
            "transformation": {"name": f"{name} height to ellipsoidal height",
                               "method": {"name": "PROJ-based operation method: " + pipe}, "parameters": []}}
    out = {"$schema": schema, "type": "CompoundCRS", "name": name, "components": [plan, vert], "remarks": REMARK}
    w.append("Высота задана методом «PROJ-based operation method» (наклонная плоскость от эллипсоидальной "
             "высоты в EPSG не описана): её применит только ПО на PROJ ≥ 6; план — стандартные методы EPSG.")
    return ExportResult("projjson", _jdump(out) + "\n", w)


# --- Trimble JobXML ---

def jxl_parameters(d) -> dict:
    """Параметры JobXML: проекция (TM, масштаб подобия свёрнут), корректировки.

    План: TM с k0·M и ложными смещениями FN = tx + M·(x0 − Nc), FE = ty + M·(y0 − Ec) даёт
    «сетку» P = (tx, ty) + M·(dN, dE); остаётся поворот вокруг (tx, ty) на θ без сдвига и масштаба.
    Высота: H = h [− N] + c0 + (c1/M)·(P_N − tx) + (c2/M)·(P_E − ty)."""
    k0, fe, fn = folded_tm(d)
    m = scale(d)
    return {"scale": k0, "false_easting": fe, "false_northing": fn, "origin_north": d.tx, "origin_east": d.ty,
            "rotation_deg": math.degrees(rotation(d)), "slope_north": d.c1 / m, "slope_east": d.c2 / m,
            "constant": d.c0}


def _x(tag, value=None, children=None, indent=0):
    pad = "  " * indent
    if children is not None:
        return f"{pad}<{tag}>\n" + "".join(children) + f"{pad}</{tag}>\n"
    if value is None or value == "":
        return f"{pad}<{tag}/>\n"
    v = value if isinstance(value, str) else fnum(value)
    v = v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"{pad}<{tag}>{v}</{tag}>\n"


def jxl_warnings(d) -> list[str]:
    """Оценки неоднозначностей JobXML на объекте."""
    w = []
    r = object_radius(d)
    th = rotation(d)
    if th != 0:
        if r is None:
            w.append("Нет оболочки опорных пунктов (старый датум): влияние знака разворота не оценить — "
                     "проверьте контрольной точкой.")
        else:
            wrong = 2 * r * math.sin(abs(th))
            if wrong >= JXL_TOL:
                w.append(f"Знак разворота ({math.degrees(th) * 3600:.2f}″, по часовой стрелке) взят по Trimble Access "
                         f"Calculations Reference (N′E′ — сетка, NE — опорные, a = k·cos φ, b = k·sin φ); если "
                         f"контроллер трактует его наоборот, ошибка в плане до {wrong:.3f} м — проверьте контрольной "
                         "точкой (export печатает их).")
        if d.height_model in ("plane", "geoid_plane") and r is not None:
            dv = math.hypot(d.c1, d.c2) * 2 * r * math.sin(abs(th) / 2)
            if dv >= JXL_TOL:
                w.append(f"Наклон высот задан в сетке до горизонтальной корректировки; если Trimble берёт "
                         f"координаты после неё, ошибка высоты до {dv * 1000:.1f} мм.")
    if d.geoid is not None:
        src = d.geoid.file
        if not src.lower().endswith(".ggf"):
            w.append(f"Trimble читает геоид только в GGF: в файле указано имя {src.rpartition('.')[0] or src}; "
                     f"переведите: python -m mathdatum geoid {src} -o {(src.rpartition('.')[0] or src)}.ggf.")
        w.append("Интерполяцию сетки геоида Trimble не документирует (у датума — "
                 f"{d.geoid.interpolation}): сверьте высоту на контрольной точке.")
    if d.gnss_system not in (None, "WGS-84"):
        w.append(f"Преобразование датума — нулевое, эллипсоид {ellipsoid_of(d)[0]}: координаты ГНСС на контроллере "
                 f"должны быть в {d.gnss_system} (базовая станция в этой системе), как при расчёте датума.")
    return w


def to_jxl(d, name: str = "Localization", timestamp: str = "2000-01-01T00:00:00") -> ExportResult:
    if d.gnss_system is None and ellipsoid_of(d)[0] == "unknown":
        raise ExportError("Датум без системы ГНСС и с нестандартным эллипсоидом: JobXML не составить.")
    p = jxl_parameters(d)
    en, a, rf = ellipsoid_of(d)
    wgs = datums.ELLIPSOIDS["wgs84"]
    hm = d.height_model
    if hm == "none":
        vert = [_x("Type", "NoAdjustment", indent=4)]
    else:
        vt = "GeoidModelAndInclinedPlane" if d.geoid is not None else "InclinedPlane"
        vert = [_x("Type", vt, indent=4), _x("OriginNorth", p["origin_north"], indent=4),
                _x("OriginEast", p["origin_east"], indent=4), _x("SlopeNorthPerUnit", p["slope_north"], indent=4),
                _x("SlopeEastPerUnit", p["slope_east"], indent=4), _x("ConstantAdjustment", p["constant"], indent=4)]
        if d.geoid is not None:
            vert.append(_x("GeoidName", d.geoid.file.rpartition(".")[0] or d.geoid.file, indent=4))
    horiz = ([_x("Type", "NoAdjustment", indent=4)] if d.b == 0 else
             [_x("Type", "PlaneAdjustment", indent=4), _x("OriginNorth", p["origin_north"], indent=4),
              _x("OriginEast", p["origin_east"], indent=4), _x("TranslationNorth", 0, indent=4),
              _x("TranslationEast", 0, indent=4), _x("Rotation", p["rotation_deg"], indent=4),
              _x("ScaleFactor", 1, indent=4)])
    cs = [
        _x("SystemName", name, indent=3), _x("ZoneName", name, indent=3), _x("DatumName", datum_name(d), indent=3),
        _x("ZoneID", "", indent=3), _x("ProjectedCoordinateReferenceSystemEPSG", "", indent=3),
        _x("CompoundCoordinateReferenceSystemEPSG", "", indent=3),
        _x("Ellipsoid", children=[_x("EarthRadius", a, indent=4), _x("Flattening", 1 / rf, indent=4)], indent=3),
        _x("Projection", children=[
            _x("Type", "TransverseMercator", indent=4), _x("Scale", p["scale"], indent=4),
            _x("CentralLatitude", d.lat0, indent=4), _x("CentralLongitude", d.lon0, indent=4),
            _x("FalseNorthing", p["false_northing"], indent=4), _x("FalseEasting", p["false_easting"], indent=4),
            _x("SouthAzimuth", "false", indent=4), _x("GridOrientation", "IncreasingNorthEast", indent=4),
            _x("ApplySeaLevelCorrection", "true", indent=4)], indent=3),
        _x("LocalSite", children=[_x("Type", "Grid", indent=4), _x("ProjectLocationLatitude", "", indent=4),
                                  _x("ProjectLocationLongitude", "", indent=4),
                                  _x("ProjectLocationHeight", "", indent=4)], indent=3),
        _x("Datum", children=[
            _x("Type", "SevenParameter", indent=4), _x("Direction", "WGS84ToLocal", indent=4),
            _x("EarthRadius", wgs.a, indent=4), _x("Flattening", 1 / wgs.rf, indent=4),
            _x("RotationX", 0, indent=4), _x("RotationY", 0, indent=4), _x("RotationZ", 0, indent=4),
            _x("TranslationX", 0, indent=4), _x("TranslationY", 0, indent=4), _x("TranslationZ", 0, indent=4),
            _x("Scale", 1, indent=4)], indent=3),
        _x("HorizontalAdjustment", children=horiz, indent=3),
        _x("VerticalAdjustment", children=vert, indent=3),
        _x("CombinedScaleFactor", children=[
            _x("Location", children=[_x("Latitude", "", indent=5), _x("Longitude", "", indent=5),
                                     _x("Height", "", indent=5)], indent=4),
            _x("Scale", "", indent=4)], indent=3),
    ]
    display = [_x(k, v, indent=3) for k, v in (
        ("DistanceUnits", "Metres"), ("HeightUnits", "Metres"), ("AngleUnits", "DMSDegrees"),
        ("AzimuthFormat", "Azimuth"), ("LatitudeLongitudeUnits", "DMSDegrees"),
        ("CoordinateOrder", "North-East-Elevation"), ("TemperatureUnits", "Celsius"), ("PressureUnits", "MilliBar"),
        ("GradeUnits", "Percentage"), ("AreaUnits", "SquareMetres"), ("VolumeUnits", "CubicMetres"),
        ("MassUnits", "Kilograms"), ("StationingFormat", "1+000.0"), ("StationIndexIncrement", ""),
        ("PrecisionUnits", "1Sigma"), ("DistanceDisplayDPs", "3"), ("CoordinateDisplayDPs", "3"),
        ("AreaDisplayDPs", "3"), ("VolumeDisplayDPs", "3"), ("MassDisplayDPs", "3"), ("AngleDisplayDPs", "1"),
        ("LaserVADisplay", "VerticalAngle"), ("TimeFormat", "Local"))]
    props = [_x(k, v, indent=3) for k, v in (
        ("Reference", ""), ("Description", "mathdatum localization export"), ("Operator", ""), ("JobNote", ""),
        ("TectonicPlate", "Unknown"), ("ApplyJobPointNameRange", "false"), ("MinimumJobPointName", ""),
        ("MaximumJobPointName", ""))]
    env = [
        _x("DisplaySettings", children=display, indent=2),
        _x("CoordinateSystem", children=cs, indent=2),
        _x("JobProperties", children=props, indent=2),
        _x("JobSettings", children=[
            _x("NeighbourhoodAdjustment", children=[_x("Applied", "false", indent=4),
                                                    _x("WeightExponent", 0.5, indent=4)], indent=3),
            _x("Averaging", "Weighted", indent=3), _x("UseAttributesOfBaseCode", "false", indent=3)], indent=2),
        _x("TimeZone", children=[_x("ZoneName", "UTC", indent=3), _x("HoursToUTC", 0, indent=3)], indent=2),
    ]
    job = re.sub(r"[^\w\-]", "_", name) or "Localization"
    text = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<JOBFile jobName="{job}" version="6.30" product="mathdatum" productVersion="1" '
            f'TimeStamp="{timestamp}">\n'
            "  <FieldBook/>\n  <Reductions/>\n" + _x("Environment", children=env, indent=1) + "</JOBFile>\n")
    return ExportResult("jxl", text, jxl_warnings(d))


# --- LandXML ---

def _xattr(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def to_landxml(d, name: str = "Localization", geoid_file: str | None = None,
               timestamp: str = "2000-01-01T00:00:00") -> ExportResult:
    wk = to_wkt2(d, name, geoid_file)
    one_line = re.sub(r"\n\s*", "", wk.text)
    attr = _xattr(one_line)
    date, _, time = timestamp.partition("T")
    text = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<LandXML xmlns="http://www.landxml.org/schema/LandXML-1.2" version="1.2" '
            f'date="{date}" time="{time or "00:00:00"}">\n'
            '  <Units><Metric linearUnit="meter" areaUnit="squareMeter" volumeUnit="cubicMeter" '
            'temperatureUnit="celsius" pressureUnit="milliBars" angularUnit="decimal degrees" directionUnit="decimal degrees"/></Units>\n'
            f'  <CoordinateSystem name="{_xattr(name)}" desc="mathdatum localization (WKT2 in ogcWktCode)" '
            f'ogcWktCode="{attr}"/>\n'
            '  <Application name="mathdatum" manufacturer="math-datum" version="1"/>\n'
            "</LandXML>\n")
    w = ["LandXML 1.2 не описывает проекцию + подобие + плоскость высот: датум передан строкой WKT2 в ogcWktCode "
         "(атрибут рассчитан на WKT1) — поймёт только ПО, отдающее его в PROJ; Civil 3D / TBC его, вероятно, "
         "проигнорируют."] + wk.warnings
    return ExportResult("landxml", text, w)


def export(d, fmt: str, name: str = "Localization", geoid_file: str | None = None,
           timestamp: str = "2000-01-01T00:00:00") -> ExportResult:
    """Экспорт датума в формат fmt (FORMATS); закрытые форматы — ExportError с объяснением."""
    f = fmt.lower().lstrip(".")
    if f in CLOSED:
        raise ExportError(f"{CLOSED[f]}: экспорт не поддерживается — угадывать байты нельзя. Что нужно для "
                          "поддержки (образцы файлов, документация) — docs/export.md.")
    if f == "wkt2":
        return to_wkt2(d, name, geoid_file)
    if f == "projjson":
        return to_projjson(d, name, geoid_file)
    if f == "jxl":
        return to_jxl(d, name, timestamp)
    if f == "landxml":
        return to_landxml(d, name, geoid_file, timestamp)
    if f == "proj":
        return ExportResult("proj", d.to_proj_pipeline() + "\n", [])
    raise ExportError(f"Формат «{fmt}»: ожидается {', '.join(FORMATS)}.")


def check_points(d, rotation_sign: int = 1):
    """Контрольные точки для проверки на контроллере: вершины оболочки и центроид → (B, L) и (x, y)
    датума; rotation_sign = −1 — что получилось бы при обратном знаке разворота."""
    from .datums import TransverseMercator
    tm = TransverseMercator(datums.Ellipsoid("e", *ellipsoid_of(d)[1:], d.ellipsoid), lon0=d.lon0, lat0=d.lat0,
                            k0=d.k0, x0=d.x0, y0=d.y0)
    a, b = d.a, d.b * rotation_sign
    out = []
    for i, (n, e) in enumerate(_sample_points(d)[: 1 + len(d.plan_hull or [])]):
        B, L = tm.inverse(n, e)
        dn, de = n - d.Nc, e - d.Ec
        out.append(("C" if i == 0 else f"V{i}", float(B), float(L), d.tx + a * dn - b * de, d.ty + b * dn + a * de))
    return out
