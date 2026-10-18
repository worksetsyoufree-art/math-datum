"""Экспорт датума: WKT2 / PROJJSON (сверка через pyproj), Trimble JobXML и LandXML (схема, ручной пример)."""

import copy
import json
import math
import urllib.request
from pathlib import Path

import numpy as np
import pytest
from lxml import etree
from pyproj import CRS, Transformer

from mathdatum import LocalizationDatum, Pair, localize
from mathdatum.__main__ import main as cli
from mathdatum.export import (CLOSED, ExportError, export, fnum, fold_error, jxl_parameters, object_radius,
                              rotation)
from mathdatum.geoid import read_grid

ROOT = Path(__file__).resolve().parents[1]
REGIONS = sorted((ROOT / "data/geodetic/regions").glob("*.json"))
GRIDS = ROOT / "tests/data/geoid"
SCHEMAS = {
    "jxl": "http://www.trimble.com/schema/JobXML/6_2/JobXMLSchema-6.30.xsd",
    "landxml": "http://www.landxml.org/schema/LandXML-1.2/LandXML-1.2.xsd",
}


def site(path):
    case = json.loads(path.read_text(encoding="utf-8"))
    return next(t for t in case["tasks"] if t["type"] == "site_localization")


def pairs_of(points):
    return [Pair(p["id"], *p["gnss_B_L_h"], *p["local_x_y_H"]) for p in points]


def points_of(s):
    return np.array([p["gnss_B_L_h"] for p in s["control_points"] + s["check_points"]]).T


def crs_and_geog(text, fmt):
    c = CRS.from_wkt(text) if fmt == "wkt2" else CRS.from_json(text)
    g = c.sub_crs_list[1].target_crs if c.is_compound else c.geodetic_crs
    return c, g


def check_pyproj(d, fmt, B, L, h, tol=1e-6, **kw):
    """Пересчёт через pyproj по экспорту совпадает с to_local / to_wgs; возвращает max расхождение, м."""
    c, g = crs_and_geog(export(d, fmt, **kw).text, fmt)
    t = Transformer.from_crs(g, c)
    x, y, H = d.to_local(B, L, h)
    out = t.transform(B, L, h)
    py, px = out[0], out[1]   # оси экспорта: восток (y), север (x)
    err = max(np.abs(px - x).max(), np.abs(py - y).max())
    if c.is_compound:
        err = max(err, np.abs(out[2] - H).max())
        bb, ll, hh = t.transform(y, x, H, direction="INVERSE")
        err = max(err, np.abs(hh - h).max(), np.abs(bb - B).max() * 1.1e5, (np.abs(ll - L) * np.cos(np.radians(B))).max() * 1.1e5)
    assert err < tol, (fmt, err)
    return err


@pytest.mark.parametrize("path", REGIONS, ids=lambda p: p.stem)
def test_regions_wkt2_projjson_match_to_local(path):
    """83 региона: WKT2 и PROJJSON, прочитанные pyproj, дают те же x, y, H, что to_local (< 1 мм; фактически < 1e-6 м),
    и обратно — те же B, L, h."""
    s = site(path)
    d = localize(pairs_of(s["control_points"]))
    B, L, h = points_of(s)
    for fmt in ("wkt2", "projjson"):
        check_pyproj(d, fmt, B, L, h)
    # С WGS 84 из базы EPSG (QGIS: слой в EPSG:4979) — тоже без сдвига: датум по имени тот же.
    c = CRS.from_wkt(export(d, "wkt2").text)
    y, x, H = Transformer.from_crs("EPSG:4979", c).transform(B, L, h)
    x2, y2, H2 = d.to_local(B, L, h)
    assert max(np.abs(x - x2).max(), np.abs(y - y2).max(), np.abs(H - H2).max()) < 1e-6


def mow():
    s = site(ROOT / "data/geodetic/regions/RU-MOW.json")
    return s, pairs_of(s["control_points"]), points_of(s)


def test_variants_pz90_ldp_geoid_shift_none(tmp_path):
    s, pairs, (B, L, h) = mow()
    # ПЗ-90.11 (эллипсоид ПЗ-90), LDP с k0, x0, y0.
    d = localize(pairs, gnss_datum="PZ-90.11", lat0=55.1, lon0=39.0, k0=1.000035, x0=20000.0, y0=100000.0)
    for fmt in ("wkt2", "projjson"):
        check_pyproj(d, fmt, B, L, h)
    assert "Parametry Zemli 1990.11" in export(d, "wkt2").text
    # Геоид + плоскость: сетка GTX читается PROJ (vgridshift).
    g = read_grid(GRIDS / "RU-MOW_truth.gtx")
    d = localize(pairs, height_model="geoid_plane", geoid=g)
    for fmt in ("wkt2", "projjson"):
        check_pyproj(d, fmt, B, L, h, geoid_file=str(GRIDS / "RU-MOW_truth.gtx"))
    # Сдвиг по высоте (2 точки), без высоты (use = plan).
    d = localize(pairs[:2])
    assert d.height_model == "shift"
    check_pyproj(d, "wkt2", B, L, h)
    d = localize([Pair(p.name, p.B, p.L, p.h, p.x, p.y, p.H, use="plan") for p in pairs])
    r = export(d, "wkt2")
    assert d.height_model == "none" and r.text.startswith("DERIVEDPROJCRS") and "только план" in r.warnings[0]
    check_pyproj(d, "projjson", B, L, h)


def test_ggf_geoid_points_to_gtx_and_bicubic_estimate(tmp_path):
    s, pairs, (B, L, h) = mow()
    g = read_grid(GRIDS / "RU-MOW_bump.ggf")
    d = localize(pairs, height_model="geoid", geoid=g, geoid_interpolation="bicubic")
    r = export(d, "wkt2")
    assert "+grids=RU-MOW_bump.gtx" in r.text
    assert any("PROJ не читает GGF" in w and "geoid RU-MOW_bump.ggf -o RU-MOW_bump.gtx" in w for w in r.warnings)
    est = next(w for w in r.warnings if "билинейную" in w)
    assert "разница на объекте до" in est
    # Перевод командой geoid → GTX; PROJ (билинейная) против датума (бикубическая) — в пределах оценки.
    assert cli(["geoid", str(GRIDS / "RU-MOW_bump.ggf"), "-o", str(tmp_path / "RU-MOW_bump.gtx")]) == 0
    c, gg = crs_and_geog(export(d, "wkt2", geoid_file=str(tmp_path / "RU-MOW_bump.gtx")).text, "wkt2")
    H = Transformer.from_crs(gg, c).transform(B, L, h)[2]
    lim = float(est.split("до ")[1].split(" мм")[0]) / 1000
    assert np.abs(H - d.to_local(B, L, h)[2]).max() <= lim + 2e-4
    # С билинейной — точно.
    d = localize(pairs, height_model="geoid", geoid=g)
    check_pyproj(d, "wkt2", B, L, h, geoid_file=str(tmp_path / "RU-MOW_bump.gtx"))


def test_fold_rotation_into_tm():
    """Без разворота подобие точно сворачивается в TM (k0·M, ложные смещения) → обычный PROJCRS."""
    s, pairs, (B, L, h) = mow()
    d = localize(pairs)
    assert fold_error(d) > 1  # разворот −434″ на ~4 км — не сворачивается
    assert export(d, "wkt2").text.split("\n")[1].strip().startswith("DERIVEDPROJCRS")
    d2 = copy.deepcopy(d)
    d2.b = 0.0
    r = export(d2, "wkt2")
    assert "PROJCRS[" in r.text and "DERIVEDPROJCRS" not in r.text and "Similarity" not in r.text
    check_pyproj(d2, "wkt2", B, L, h)
    check_pyproj(d2, "projjson", B, L, h)
    # Разворот 0.001″: ошибка ≤ 2·M·R·sin(θ/2) < 0.1 мм — сворачивается с предупреждением.
    d3 = copy.deepcopy(d)
    d3.b = d3.a * math.tan(0.001 / 206264.806)
    e = fold_error(d3)
    assert e == pytest.approx(object_radius(d3) * abs(rotation(d3)), rel=1e-6) and e < 1e-4
    r = export(d3, "wkt2")
    assert "DERIVEDPROJCRS" not in r.text and "свёрнут в TM" in r.warnings[0]
    # Оценка — для объекта (оболочка опорных пунктов): проверяем на опорных пунктах.
    Bc, Lc, hc = np.array([p["gnss_B_L_h"] for p in s["control_points"]]).T
    check_pyproj(d3, "wkt2", Bc, Lc, hc, tol=e + 1e-6)


def manual_datum():
    """Датум с круглыми числами для ручного расчёта параметров JobXML."""
    m, th = 1.00002, math.radians(30 / 3600)
    return LocalizationDatum(lat0=55.0, lon0=38.0, Nc=1000.0, Ec=-500.0, a=m * math.cos(th), b=m * math.sin(th),
                             tx=10000.0, ty=20000.0, c0=-14.2, c1=2e-5, c2=-3e-5, k0=1.000078, x0=20000.0,
                             y0=100000.0, gnss_datum="WGS-84", plan_hull=[[0.0, -1500.0], [2000.0, -1500.0],
                                                                          [2000.0, 500.0], [0.0, 500.0]])


def test_jxl_manual_example():
    """Ручной расчёт: TM k = 1.000078·1.00002 = 1.00009800156; FN = 10000 + 1.00002·(20000 − 1000) = 29000.38;
    FE = 20000 + 1.00002·(100000 + 500) = 120502.01; поворот +30″ = 0.0083333…° вокруг (10000, 20000) без сдвига;
    наклоны 2e-5/1.00002 = 1.9999600008e-5, −3e-5/1.00002 = −2.9999400012e-5; постоянная −14.2."""
    d = manual_datum()
    p = jxl_parameters(d)
    assert p["scale"] == pytest.approx(1.00009800156, abs=1e-14)
    assert p["false_northing"] == pytest.approx(29000.38, abs=1e-9)
    assert p["false_easting"] == pytest.approx(120502.01, abs=1e-9)
    assert p["rotation_deg"] == pytest.approx(30 / 3600, abs=1e-15)
    assert (p["origin_north"], p["origin_east"]) == (10000.0, 20000.0)
    assert p["slope_north"] == pytest.approx(1.99996000080e-5, abs=1e-16)
    assert p["slope_east"] == pytest.approx(-2.99994000120e-5, abs=1e-16)
    xml = etree.fromstring(export(d, "jxl").text.encode())
    cs = xml.find("Environment/CoordinateSystem")
    assert cs.findtext("Projection/Type") == "TransverseMercator"
    assert float(cs.findtext("Projection/Scale")) == p["scale"]
    assert cs.findtext("HorizontalAdjustment/Type") == "PlaneAdjustment"
    assert float(cs.findtext("HorizontalAdjustment/Rotation")) == p["rotation_deg"]
    assert float(cs.findtext("HorizontalAdjustment/ScaleFactor")) == 1.0
    assert float(cs.findtext("HorizontalAdjustment/TranslationNorth")) == 0.0
    assert cs.findtext("VerticalAdjustment/Type") == "InclinedPlane"
    assert float(cs.findtext("VerticalAdjustment/ConstantAdjustment")) == -14.2
    # Точка dN = 100, dE = 0 от центроида: сетка Trimble P = (10000 + 100.002, 20000); поворот на +30″ по часовой:
    # x = 10000 + 100.002·cos 30″ = 10100.00199894, y = 20000 + 100.002·sin 30″ = 20000.01454470 (вектор на север
    # уходит к востоку). То же даёт to_local.
    x, y, _ = trimble_local(cs, *d._proj().transform(d.Ec, d.Nc + 100, direction="INVERSE")[::-1], 0.0)
    assert x == pytest.approx(10100.00199894, abs=1e-8) and y == pytest.approx(20000.01454470, abs=1e-8)
    xd, yd, _ = d.to_local(*d._proj().transform(d.Ec, d.Nc + 100, direction="INVERSE")[::-1], 0.0)
    assert (x, y) == pytest.approx((float(xd), float(yd)), abs=1e-8)


def trimble_local(cs, B, L, h, geoid=None):
    """Пересчёт по параметрам JobXML так, как их описывает Trimble Access Calculations Reference:
    TM → сетка P; N′ = a·N + b·E + ΔN (N′E′ — сетка, NE — опорные, a = k cos φ, b = k sin φ) с центром O,
    отсюда опорные X = O + R(φ)ᵀ·(P − O)/k; высота H = h [− N] + ΔH + sN·(P_N − O_N) + sE·(P_E − O_E)."""
    f = lambda path: float(cs.findtext(path))
    a, fl = f("Ellipsoid/EarthRadius"), f("Ellipsoid/Flattening")
    t = Transformer.from_pipeline(
        f"+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad +step +proj=tmerc "
        f"+lat_0={f('Projection/CentralLatitude')!r} +lon_0={f('Projection/CentralLongitude')!r} "
        f"+k={f('Projection/Scale')!r} +x_0={f('Projection/FalseEasting')!r} +y_0={f('Projection/FalseNorthing')!r} "
        f"+a={a!r} +rf={1 / fl!r}")
    pe, pn = t.transform(L, B)
    if cs.findtext("HorizontalAdjustment/Type") == "PlaneAdjustment":
        on, oe = f("HorizontalAdjustment/OriginNorth"), f("HorizontalAdjustment/OriginEast")
        phi, k = math.radians(f("HorizontalAdjustment/Rotation")), f("HorizontalAdjustment/ScaleFactor")
        tn, te = f("HorizontalAdjustment/TranslationNorth"), f("HorizontalAdjustment/TranslationEast")
        dn, de = pn - on, pe - oe
        x = on + tn + (math.cos(phi) * dn - math.sin(phi) * de) / k
        y = oe + te + (math.sin(phi) * dn + math.cos(phi) * de) / k
    else:
        x, y = pn, pe
    vt = cs.findtext("VerticalAdjustment/Type")
    H = h - (geoid(B, L) if geoid else 0.0)
    if vt in ("InclinedPlane", "GeoidModelAndInclinedPlane"):
        H = H + f("VerticalAdjustment/ConstantAdjustment") + f("VerticalAdjustment/SlopeNorthPerUnit") * (
            pn - f("VerticalAdjustment/OriginNorth")) + f("VerticalAdjustment/SlopeEastPerUnit") * (
            pe - f("VerticalAdjustment/OriginEast"))
    return x, y, H


@pytest.mark.parametrize("path", REGIONS[::8], ids=lambda p: p.stem)
def test_jxl_interpretation_matches_to_local(path):
    """Параметры JobXML, применённые по формулам Trimble (в нашем прочтении), воспроизводят to_local (< 1e-6 м)."""
    s = site(path)
    d = localize(pairs_of(s["control_points"]))
    cs = etree.fromstring(export(d, "jxl").text.encode()).find("Environment/CoordinateSystem")
    B, L, h = points_of(s)
    x, y, H = trimble_local(cs, B, L, h)
    x2, y2, H2 = d.to_local(B, L, h)
    assert max(np.abs(x - x2).max(), np.abs(y - y2).max(), np.abs(H - H2).max()) < 1e-6


def test_jxl_geoid_and_warnings():
    s, pairs, (B, L, h) = mow()
    g = read_grid(GRIDS / "RU-MOW_truth.ggf")
    d = localize(pairs, height_model="geoid_plane", geoid=g, gnss_datum="PZ-90.11")
    r = export(d, "jxl")
    cs = etree.fromstring(r.text.encode()).find("Environment/CoordinateSystem")
    assert cs.findtext("VerticalAdjustment/Type") == "GeoidModelAndInclinedPlane"
    assert cs.findtext("VerticalAdjustment/GeoidName") == "RU-MOW_truth"   # без .ggf, как в схеме
    assert float(cs.findtext("Ellipsoid/EarthRadius")) == 6378136.0          # эллипсоид ПЗ-90
    x, y, H = trimble_local(cs, B, L, h, geoid=lambda b, l: g.value(b, l))
    assert np.abs(H - d.to_local(B, L, h)[2]).max() < 1e-6
    text = " ".join(r.warnings)
    assert "Знак разворота" in text and "ошибка в плане до" in text
    assert "Интерполяцию сетки геоида Trimble не документирует" in text
    assert "должны быть в PZ-90.11" in text
    assert "Trimble читает геоид только в GGF" not in text
    # Сетка GTX — предупреждение о переводе в GGF.
    d = localize(pairs, height_model="geoid", geoid=read_grid(GRIDS / "RU-MOW_truth.gtx"))
    assert any("только в GGF" in w for w in export(d, "jxl").warnings)
    # Без разворота — без корректировки и без предупреждения о знаке.
    d2 = copy.deepcopy(localize(pairs))
    d2.b = 0.0
    r = export(d2, "jxl")
    assert "<Type>NoAdjustment</Type>" in r.text and not any("Знак" in w for w in r.warnings)


def test_jxl_plane_frame_estimate():
    d = manual_datum()
    d.b = d.a * math.tan(math.radians(1.0))  # разворот 1°
    w = " ".join(export(d, "jxl").warnings)
    r = object_radius(d)
    assert "ошибка в плане до" in w
    dv = math.hypot(d.c1, d.c2) * 2 * r * math.sin(math.radians(0.5))
    assert f"{dv * 1000:.1f} мм" in w


def schema(fmt, tmp_path_factory):
    """Схема скачивается во временный каталог (в репозиторий не кладётся); без сети — skip."""
    path = tmp_path_factory.getbasetemp() / Path(SCHEMAS[fmt]).name
    if not path.exists():
        try:
            data = urllib.request.urlopen(SCHEMAS[fmt], timeout=30).read()
        except Exception as e:  # сеть недоступна
            pytest.skip(f"схема {SCHEMAS[fmt]} недоступна: {e}")
        if b"<xsd:schema" not in data and b"<xs:schema" not in data:
            pytest.skip(f"по адресу {SCHEMAS[fmt]} не схема")
        path.write_bytes(data)
    return etree.XMLSchema(etree.parse(str(path)))


@pytest.mark.parametrize("fmt", ["jxl", "landxml"])
def test_xml_valid_against_schema(fmt, tmp_path_factory):
    sch = schema(fmt, tmp_path_factory)
    s, pairs, _ = mow()
    for d in (localize(pairs), localize(pairs, height_model="geoid_plane", geoid=read_grid(GRIDS / "RU-MOW_truth.ggf")),
              localize(pairs[:1]), localize([Pair(p.name, p.B, p.L, p.h, p.x, p.y, p.H, use="plan") for p in pairs]),
              manual_datum()):
        doc = etree.fromstring(export(d, fmt, name="Участок 1").text.encode())
        assert sch.validate(doc), sch.error_log


def test_landxml_carries_wkt2():
    s, pairs, (B, L, h) = mow()
    d = localize(pairs)
    doc = etree.fromstring(export(d, "landxml").text.encode())
    cs = doc.find("{http://www.landxml.org/schema/LandXML-1.2}CoordinateSystem")
    c = CRS.from_wkt(cs.get("ogcWktCode"))
    y, x, H = Transformer.from_crs(c.sub_crs_list[1].target_crs, c).transform(B, L, h)
    assert np.abs(x - d.to_local(B, L, h)[0]).max() < 1e-6


def test_closed_formats_and_unknown():
    d = manual_datum()
    for f in CLOSED:
        with pytest.raises(ExportError, match="docs/export.md"):
            export(d, f)
    with pytest.raises(ExportError, match="ожидается"):
        export(d, "dxf")
    assert (ROOT / "docs/export.md").is_file()


def test_number_format():
    assert [fnum(v) for v in (0.0, -0.0, 1.0, 20000.0, 1e-05, 0.0001, 55.06991640959999, 1e16, -2.5e-07, 1e15)] == \
        ["0", "0", "1", "20000", "1e-05", "0.0001", "55.06991640959999", "1e+16", "-2.5e-07", "1000000000000000.0"]


def test_cli_export(tmp_path, capsys):
    s, pairs, _ = mow()
    localize(pairs).save(tmp_path / "datum.json")
    assert cli(["export", str(tmp_path / "datum.json"), "--format", "wkt2", "-o", str(tmp_path / "d.wkt")]) == 0
    CRS.from_wkt((tmp_path / "d.wkt").read_text(encoding="utf-8"))
    assert cli(["export", str(tmp_path / "datum.json"), "-f", "jxl", "-o", str(tmp_path / "d.jxl")]) == 0
    err = capsys.readouterr().err
    assert "Контрольные точки" in err and "x′ =" in err and "Знак разворота" in err
    assert cli(["export", str(tmp_path / "datum.json"), "-f", "projjson"]) == 0
    assert json.loads(capsys.readouterr().out)["type"] == "CompoundCRS"
    assert cli(["export", str(tmp_path / "datum.json"), "-f", "gc3"]) == 1
    assert "закрытый" in capsys.readouterr().err
    # Датум с геоидом без файла сетки рядом: экспорт всё равно пишется (сетка нужна только для оценок).
    g = read_grid(GRIDS / "RU-MOW_truth.gtx")
    localize(pairs, height_model="geoid", geoid=g).save(tmp_path / "dg.json")
    assert cli(["export", str(tmp_path / "dg.json"), "-f", "wkt2", "-o", str(tmp_path / "dg.wkt")]) == 0
    assert "vgridshift +grids=RU-MOW_truth.gtx" in (tmp_path / "dg.wkt").read_text(encoding="utf-8")
