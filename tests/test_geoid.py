"""Сетки геоида (mathdatum.geoid) и модели высот локализации geoid / geoid_plane."""

import hashlib
import json
import math
import struct
import sys
import zlib
from pathlib import Path

import numpy as np
import pytest
from pyproj import Transformer

from mathdatum import LocalizationDatum, LocalizationError, Pair, localize, suggest_exclusions
from mathdatum.__main__ import main as cli
from mathdatum.geoid import GeoidError, GeoidGrid, parse_grid, read_grid

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "tests/data/geoid"
REGIONS = sorted((ROOT / "data/geodetic/regions").glob("*.json"))
sys.path.insert(0, str(ROOT / "tools"))
import make_geoid_test_grids as mg  # noqa: E402

TRUTH, TRUTH_ISG, BUMP = DATA / "RU-MOW_truth.gtx", DATA / "RU-MOW_truth.isg", DATA / "RU-MOW_bump.gtx"
TRUTH_GGF, BUMP_GGF = DATA / "RU-MOW_truth.ggf", DATA / "RU-MOW_bump.ggf"


def vgridshift(path, lat, lon):
    """N по PROJ (vgridshift, билинейная интерполяция)."""
    t = Transformer.from_pipeline(f"+proj=pipeline +step +proj=unitconvert +xy_in=deg +xy_out=rad "
                                  f"+step +proj=vgridshift +grids={path} +multiplier=1")
    return t.transform(np.asarray(lon, float), np.asarray(lat, float), np.zeros(np.shape(lat)))[2]


def poly_grid(f, lat0=55.0, lon0=37.0, dlat=0.1, dlon=0.2, rows=8, cols=9, name="poly"):
    B, L = np.meshgrid(lat0 + dlat * np.arange(rows), lon0 + dlon * np.arange(cols), indexing="ij")
    return GeoidGrid(lat0, lon0, dlat, dlon, f(B, L), name=name)


# --- чтение ---

def test_gtx_and_isg_same_grid():
    a, b = read_grid(TRUTH), read_grid(TRUTH_ISG)
    assert (a.fmt, b.fmt) == ("gtx", "isg") and (a.rows, a.cols) == (b.rows, b.cols) == (10, 18)
    assert np.abs(a.values - b.values).max() < 1e-6          # ISG — 6 знаков
    assert abs(a.lat0 - b.lat0) < 1e-9 and abs(a.lon0 - b.lon0) < 1e-9
    assert a.sha256 == hashlib.sha256(TRUTH.read_bytes()).hexdigest() != b.sha256
    rng = np.random.default_rng(3)
    lat = rng.uniform(a.lat0, a.lat1, 50)
    lon = rng.uniform(a.lon0, a.lon1, 50)
    assert np.abs(a.value(lat, lon) - b.value(lat, lon)).max() < 2e-6


@pytest.mark.parametrize("stem", ["RU-MOW_truth", "RU-MOW_bump", "nodata"])
def test_ggf_same_as_gtx(stem):
    a, b = read_grid(DATA / f"{stem}.ggf"), read_grid(DATA / f"{stem}.gtx")
    assert a.fmt == "ggf" and (a.rows, a.cols, a.lat0, a.lon0, a.dlat, a.dlon) == (b.rows, b.cols, b.lat0, b.lon0, b.dlat, b.dlon)
    assert np.array_equal(np.isnan(a.values), np.isnan(b.values))
    assert np.nanmax(np.abs(a.values - b.values)) == 0 and not a.notes


def test_ggf_layout():
    """Раскладка GGF: little-endian, строки с севера на юг (строка 0 файла — latMax)."""
    raw = TRUTH_GGF.read_bytes()
    assert raw[2:16] == b"TNL GRID FILE\0" and struct.unpack("<h", raw[:2]) == (1,)
    lat_min, lat_max, lon_min, lon_max, dlat, dlon = struct.unpack("<6d", raw[48:96])
    rows, cols = struct.unpack("<2i", raw[96:104])
    v = np.frombuffer(raw, "<f4", rows * cols, 146).reshape(rows, cols)
    g = read_grid(TRUTH_GGF)
    assert len(raw) == 146 + 4 * rows * cols + 16
    assert g.value(lat_max, lon_min) == pytest.approx(float(v[0, 0]), abs=1e-12)          # северо-западный узел
    assert g.value(lat_min, lon_max) == pytest.approx(float(v[-1, -1]), abs=1e-12)        # юго-восточный
    assert struct.unpack("<2d", raw[-16:]) == pytest.approx((np.nanmin(g.values), np.nanmax(g.values)))


def test_ggf_variants_and_errors():
    raw = bytearray(TRUTH_GGF.read_bytes())
    g = read_grid(TRUTH_GGF)
    # Неизвестные флаги — читается, но с предупреждением.
    other = bytearray(raw)
    other[136] = 7
    with pytest.warns(UserWarning, match="флаги GGF"):
        g2 = parse_grid(bytes(other), "flags.ggf")
    assert g2.notes and np.array_equal(g2.values, g.values) and "внимание" in g2.describe()
    # Без хвоста min/max, int16 с масштабом.
    assert np.array_equal(parse_grid(bytes(raw[:-16]), "short.ggf").values, g.values)
    n = g.rows * g.cols
    ints = np.round(g.values[::-1] * 1000).astype("<i2")
    i16 = bytearray(raw[:146])
    i16[128:136] = struct.pack("<d", 0.001)
    gi = parse_grid(bytes(i16) + ints.tobytes(), "osu.ggf")
    assert np.abs(gi.values - g.values).max() < 6e-4
    # NODATA из заголовка (смещение 120).
    nd = read_grid(DATA / "nodata.ggf")
    assert struct.unpack("<d", (DATA / "nodata.ggf").read_bytes()[120:128]) == (-9999.0,) and np.isnan(nd.values).sum() == 1
    with pytest.raises(GeoidError, match="размер GGF"):
        parse_grid(bytes(raw[:-20]), "cut.ggf")
    with pytest.raises(GeoidError, match="не GGF"):
        parse_grid(b"\0" * 200, "x.ggf")
    bad = bytearray(raw)
    bad[96:100] = struct.pack("<i", g.rows + 1)
    with pytest.raises(GeoidError):
        parse_grid(bytes(bad), "rows.ggf")
    # Формат по подписи, даже без расширения.
    assert parse_grid(bytes(raw), "grid.bin").fmt == "ggf"
    # Точно в узлах и на границах — без вырождения (в отличие от решения системы 4×4 по floor/ceil).
    for j in (0, g.rows - 1):
        for i in (0, 5, g.cols - 1):
            assert g.value(g.lat0 + j * g.dlat, g.lon0 + i * g.dlon) == pytest.approx(g.values[j, i], abs=1e-12)
    # Долгота считается по шагу dlon (а не dlat): сетка с разными шагами.
    rect = poly_grid(lambda B, L: 3 * B + 7 * L, dlat=0.1, dlon=0.25)
    rr = parse_grid(rect.to_ggf(), "rect.ggf")
    assert rr.value(55.33, 38.71) == pytest.approx(3 * 55.33 + 7 * 38.71, abs=1e-4)
    # За последним столбцом — ошибка, а не переход на соседнюю строку.
    with pytest.raises(GeoidError, match="вне сетки"):
        rr.value(55.33, rr.lon1 + 0.01)


def test_node_values_and_header():
    raw = TRUTH.read_bytes()
    lat0, lon0, dlat, dlon, rows, cols = struct.unpack(">4d2i", raw[:40])
    vals = np.frombuffer(raw, ">f4", rows * cols, 40).reshape(rows, cols)
    g = read_grid(TRUTH)
    for j, i in ((0, 0), (rows - 1, cols - 1), (3, 7), (rows - 1, 0), (0, cols - 1)):
        assert g.value(lat0 + j * dlat, lon0 + i * dlon) == pytest.approx(float(vals[j, i]), abs=1e-12)
        assert g.values[j, i] == float(vals[j, i])


def test_bilinear_and_bicubic_reproduce_polynomials():
    lin = poly_grid(lambda B, L: 10 + 2 * (B - 55) - 3 * (L - 37))
    quad = poly_grid(lambda B, L: 10 + 2 * (B - 55) - 3 * (L - 37) + 4 * (B - 55) ** 2 - 1.5 * (B - 55) * (L - 37)
                     + 0.7 * (L - 37) ** 2)
    rng = np.random.default_rng(5)
    lat, lon = rng.uniform(55.1, 55.6, 200), rng.uniform(37.2, 38.4, 200)
    f_lin = 10 + 2 * (lat - 55) - 3 * (lon - 37)
    assert np.abs(lin.value(lat, lon) - f_lin).max() < 1e-12
    assert np.abs(lin.value(lat, lon, "bicubic") - f_lin).max() < 1e-12
    f_q = f_lin + 4 * (lat - 55) ** 2 - 1.5 * (lat - 55) * (lon - 37) + 0.7 * (lon - 37) ** 2
    assert np.abs(quad.value(lat, lon, "bicubic") - f_q).max() < 1e-12     # свёртка Кейса — точно до 2-й степени
    assert np.abs(quad.value(lat, lon) - f_q).max() > 1e-3                  # билинейная — нет
    # Центр ячейки — среднее четырёх узлов.
    v = quad.values
    assert quad.value(55.05, 37.1) == pytest.approx(v[0:2, 0:2].mean(), abs=1e-12)


def test_edges_and_outside():
    g = read_grid(TRUTH)
    assert math.isfinite(g.value(g.lat1, g.lon1)) and math.isfinite(g.value(g.lat0, g.lon0))
    for lat, lon in ((g.lat1 + 1e-6, g.lon0), (g.lat0 - 1e-6, g.lon1), (g.lat0, g.lon1 + 1e-6), (55.1, 41.0),
                     (float("nan"), 39.2)):
        with pytest.raises(GeoidError, match="вне сетки"):
            g.value(lat, lon)
    # Бикубическая — не ближе одной ячейки к краю (нужна окрестность 4×4).
    assert math.isfinite(g.value(g.lat0 + 1.5 * g.dlat, g.lon0 + 1.5 * g.dlon, "bicubic"))
    with pytest.raises(GeoidError, match="крайней ячейке"):
        g.value(g.lat0 + 0.5 * g.dlat, g.lon0 + 5 * g.dlon, "bicubic")
    with pytest.raises(GeoidError, match="крайней ячейке"):
        g.value(g.lat1, g.lon0 + 5 * g.dlon, "bicubic")
    with pytest.raises(GeoidError, match="Интерполяция"):
        g.value(55.1, 39.3, "nearest")


@pytest.mark.parametrize("name", ["nodata.ggf", "nodata.gtx", "nodata.isg"])
def test_nodata(name):
    g = read_grid(DATA / name)
    assert np.isnan(g.values).sum() == 1 and np.isnan(g.values[3, 4])   # B = 55.75, L = 39.0
    for lat, lon in ((55.75, 39.0), (55.6, 38.8), (55.9, 39.4), (55.8, 38.6)):
        with pytest.raises(GeoidError, match="NODATA"):
            g.value(lat, lon)
    assert math.isfinite(g.value(55.4, 38.6))
    assert math.isfinite(g.value(55.6, 38.4))
    with pytest.raises(GeoidError, match="NODATA"):
        g.value(55.4, 38.2, "bicubic")      # окрестность 4×4 задевает NODATA
    other = read_grid(DATA / ("nodata.isg" if not name.endswith("isg") else "nodata.gtx"))
    assert g.value(55.3, 37.7) == pytest.approx(other.value(55.3, 37.7), abs=1e-6)


def test_global_longitude_wrap(tmp_path):
    f = lambda B, L: 20 * np.cos(np.radians(B)) * np.sin(np.radians(L)) + 5   # noqa: E731
    lat = -90 + 10 * np.arange(19)
    lon = -180 + 10 * np.arange(36)          # без повторного столбца 180°
    B, L = np.meshgrid(lat, lon, indexing="ij")
    g = GeoidGrid(-90, -180, 10, 10, f(B, L), "global")
    assert g.period == 36
    assert g.value(45, 175) == pytest.approx(g.value(45, -185), abs=1e-12) == pytest.approx(g.value(45, 535), abs=1e-12)
    # Через антимеридиан — между столбцами 170° и −180°.
    assert g.value(45, 175) == pytest.approx((g.value(45, 170) + g.value(45, 180)) / 2, abs=1e-12)
    assert g.value(45, 180) == pytest.approx(g.value(45, -180), abs=1e-12)
    assert math.isfinite(g.value(45, 179, "bicubic"))
    # Сетка 0…360° и долготы −180…180.
    g2 = GeoidGrid(0, 0, 1, 1, np.arange(20 * 31, dtype=float).reshape(20, 31), "east")
    assert g2.value(5, 10.5) == pytest.approx(g2.value(5, 10.5 - 360), abs=1e-12)
    # Сверка с PROJ (GTX).
    path = tmp_path / "global.gtx"
    path.write_bytes(g.to_gtx())
    rng = np.random.default_rng(9)
    la, lo = rng.uniform(-89, 89, 300), rng.uniform(-180, 180, 300)
    assert np.abs(read_grid(path).value(la, lo) - vgridshift(path, la, lo)).max() < 1e-5   # float32 в файле


@pytest.mark.parametrize("path", [TRUTH, BUMP, DATA / "nodata.gtx"], ids=lambda p: p.name)
def test_gtx_matches_proj_vgridshift(path):
    g = read_grid(path)
    rng = np.random.default_rng(11)
    lat = rng.uniform(g.lat0, g.lat1, 400)
    lon = rng.uniform(g.lon0, g.lon1, 400)
    ok = []
    for b, l in zip(lat, lon):
        try:
            ok.append((b, l, g.value(b, l)))
        except GeoidError:
            pass
    b, l, mine = np.array(ok).T
    assert len(mine) > 200
    assert np.abs(mine - vgridshift(path, b, l)).max() < 1e-9


def test_isg_variants(tmp_path):
    g = poly_grid(lambda B, L: 10 + B - L, rows=4, cols=5)
    text = g.to_isg()
    # ISG 1.0: «:» вместо «=», углы в DMS, узлы в центрах ячеек (node offset).
    t = (text.replace("lat min        = 55.0000000000", "lat min        :  54°57'00\"")
         .replace("lat max        = 55.3000000000", "lat max        :  55°21'00\"")
         .replace("lon min        = 37.0000000000", "lon min        :  36°54'00\"")
         .replace("lon max        = 37.8000000000", "lon max        :  37°54'00\"")
         .replace("ISG format     = 2.0", "ISG format     = 2.0\nnode offset    : yes"))
    g2 = parse_grid(t.encode(), "dms.isg")
    assert (g2.lat0, g2.lon0, g2.rows, g2.cols) == pytest.approx((55.0, 37.0, 4, 5))
    assert g2.value(55.13, 37.31) == pytest.approx(10 + 55.13 - 37.31, abs=1e-6)
    with pytest.raises(GeoidError, match="значений"):
        parse_grid(text.rsplit("\n", 2)[0].encode(), "short.isg")
    with pytest.raises(GeoidError, match="порядок"):
        parse_grid(text.replace("N-to-S, W-to-E", "S-to-N, W-to-E").encode(), "order.isg")
    with pytest.raises(GeoidError, match="nrows"):
        parse_grid(text.replace("nrows          =          4", "nrows          =          5").encode(), "rows.isg")
    with pytest.raises(GeoidError, match="заголовка"):
        parse_grid(b"1 2 3", "bad.isg")
    with pytest.raises(GeoidError, match="GTX"):
        parse_grid(g.to_gtx()[:-4], "cut.gtx")
    with pytest.raises(GeoidError, match="не найден"):
        read_grid(tmp_path / "missing.gtx")
    # Запись и чтение.
    for ext in ("gtx", "isg"):
        g.save(tmp_path / f"p.{ext}")
        assert np.abs(read_grid(tmp_path / f"p.{ext}").values - g.values).max() < 1e-5


def write_geotiff(path, g: GeoidGrid, tile=8, nodata=-32768.0, point=True):
    """Минимальный GeoTIFF как у сеток PROJ: float32, тайлы, deflate, предиктор 3."""
    v = np.where(np.isnan(g.values), nodata, g.values)[::-1].astype(">f4")   # строки с севера
    h, w = v.shape
    tiles = []
    for r in range(0, h, tile):
        for c in range(0, w, tile):
            t = np.full((tile, tile), nodata, ">f4")
            part = v[r:r + tile, c:c + tile]
            t[:part.shape[0], :part.shape[1]] = part
            b = t.view(np.uint8).reshape(tile, tile, 4).transpose(0, 2, 1).reshape(tile, 4 * tile)
            d = np.diff(b.astype(np.int16), axis=1, prepend=0).astype(np.uint8)   # разности байтов
            tiles.append(zlib.compress(d.tobytes()))
    area_shift = 0 if point else 0.5
    geokeys = [1, 1, 0, 4, 1024, 0, 1, 2, 1025, 0, 1, 2 if point else 1, 2048, 0, 1, 4326, 4096, 0, 1, 5773]
    entries = {256: (4, [w]), 257: (4, [h]), 258: (3, [32]), 259: (3, [8]), 277: (3, [1]), 284: (3, [1]),
               317: (3, [3]), 339: (3, [3]), 322: (3, [tile]), 323: (3, [tile]),
               324: (4, [0] * len(tiles)), 325: (4, [len(t) for t in tiles]),
               33550: (12, [g.dlon, g.dlat, 0.0]),
               33922: (12, [0.0, 0.0, 0.0, g.lon0 - area_shift * g.dlon, g.lat1 + area_shift * g.dlat, 0.0]),
               34735: (3, geokeys), 42113: (2, f"{nodata:g}")}
    fmt = {3: "H", 4: "I", 12: "d"}

    def pack(tag, typ, val):
        return (val.encode() + b"\0") if typ == 2 else struct.pack("<" + fmt[typ] * len(val), *val)

    tags = sorted(entries)
    pos = 8 + 2 + 12 * len(tags) + 4                    # данные тегов сразу за IFD, затем тайлы
    offsets = {}
    for tag in tags:
        raw = pack(tag, *entries[tag])
        if len(raw) > 4:
            offsets[tag] = pos
            pos += len(raw)
    tile_pos = []
    for t in tiles:
        tile_pos.append(pos)
        pos += len(t)
    entries[324] = (4, tile_pos)
    ifd, blobs = b"", b""
    for tag in tags:
        typ, val = entries[tag]
        raw = pack(tag, typ, val)
        cnt = len(raw) if typ == 2 else len(val)
        ifd += struct.pack("<HHI", tag, typ, cnt) + (raw.ljust(4, b"\0") if len(raw) <= 4 else struct.pack("<I", offsets[tag]))
        if len(raw) > 4:
            blobs += raw
    path.write_bytes(b"II*\0" + struct.pack("<IH", 8, len(tags)) + ifd + b"\0\0\0\0" + blobs + b"".join(tiles))


@pytest.mark.parametrize("point", [True, False], ids=["PixelIsPoint", "PixelIsArea"])
def test_geotiff_reader(tmp_path, point):
    g = read_grid(BUMP)
    g.values[5, 7] = np.nan
    path = tmp_path / "bump.tif"
    write_geotiff(path, g, point=point)
    t = read_grid(path)
    assert (t.fmt, t.rows, t.cols) == ("tif", g.rows, g.cols)
    assert (t.lat0, t.lon0) == pytest.approx((g.lat0, g.lon0), abs=1e-12)
    assert np.array_equal(np.isnan(t.values), np.isnan(g.values))
    assert np.nanmax(np.abs(t.values - g.values)) == 0
    rng = np.random.default_rng(2)
    lat, lon = rng.uniform(g.lat0, g.lat1, 300), rng.uniform(g.lon0, g.lon1, 300)
    mine = np.array([t.value1(b, l) if not _hits_nodata(t, b, l) else np.nan for b, l in zip(lat, lon)])
    ok = ~np.isnan(mine)
    assert np.abs(mine[ok] - vgridshift(path, lat[ok], lon[ok])).max() < 1e-9   # PROJ читает тот же файл


def _hits_nodata(g, b, l):
    try:
        g.value1(b, l)
        return False
    except GeoidError:
        return True


# --- локализация с геоидом ---

def site():
    return mg.site_task("RU-MOW")


def pairs_of(task, use="both"):
    return [Pair(p["id"], *p["gnss_B_L_h"], *p["local_x_y_H"], use=use) for p in task["control_points"]]


def check_points(task):
    return (np.array([p["gnss_B_L_h"] for p in task["check_points"]]),
            np.array([p["local_x_y_H"] for p in task["check_points"]]))


def check_errors(d, task, dH=None):
    chk, cat = check_points(task)
    H = d.to_local(*chk.T)[2]
    e = cat[:, 2] - (0 if dH is None else dH) - H
    return float(np.sqrt(np.mean(e ** 2)))


def test_default_unchanged_and_json_key():
    t = site()
    d = localize(pairs_of(t), gnss_datum="PZ-90.11")
    assert d.height_model == "plane" and d.geoid is None and d.to_dict()["geoid"] is None
    d2 = localize(pairs_of(t), gnss_datum="PZ-90.11", height_model="plane")
    assert d2 == d


def test_models_parameters_and_diagnostics():
    t = site()
    g = read_grid(TRUTH)
    pairs = pairs_of(t) + [Pair(p["id"], *p["gnss_B_L_h"], *p["local_x_y_H"], use="none") for p in t["check_points"]]
    for model, k in (("geoid", 1), ("geoid_plane", 3)):
        d = localize(pairs, gnss_datum="PZ-90.11", height_model=model, geoid=g)
        assert d.height_model == model and d.geoid.file == "RU-MOW_truth.gtx" and d.geoid.sha256 == g.sha256
        assert d.redundancy_height == 6 - k
        q = np.array(d.q_height)
        if k == 1:
            assert d.c1 == d.c2 == 0 and np.allclose(q, np.diag([1 / 6, 0, 0]))
        # Σ p·q_vv = r по опорным, w = v / (σ0·√q_vv).
        used = [r for r in d.residuals if r.use == "both"]
        assert sum(r.p_height * r.qvv_height for r in used) == pytest.approx(6 - k, abs=1e-9)
        for r in d.residuals:
            assert r.wH == pytest.approx(r.dH / (0.03 * math.sqrt(r.qvv_height)), rel=1e-12)
        # Leave-one-out = пересчёт без точки = v / (p·q_vv).
        for i, r in enumerate(used):
            sub = [Pair(**{**vars(p), "use": "plan" if j == i else p.use}) for j, p in enumerate(pairs)]
            d_i = localize(sub, gnss_datum="PZ-90.11", height_model=model, geoid=g, lat0=d.lat0, lon0=d.lon0)
            assert r.loo_dH == pytest.approx(d_i.residuals[i].dH, abs=1e-9)
            assert r.loo_dH == pytest.approx(r.dH / (r.p_height * r.qvv_height), abs=1e-9)
        # Контрольные — сама невязка; s0, ковариация, СКО прогноза.
        assert all(r.loo_dH == r.dH for r in d.residuals if r.use == "none")
        assert d.s0_height == pytest.approx(math.sqrt(sum(r.dH ** 2 for r in used) / (6 - k)), rel=1e-12)
        assert np.allclose(d.covariance_height(), 0.03 ** 2 * q)
        chk, _ = check_points(t)
        mh = d.prediction_sigma(chk[:, 0], chk[:, 1])[1]
        if k == 1:
            assert np.allclose(mh, 0.03 / math.sqrt(6))
        assert not d.warnings


def test_geoid_plane_beats_plane_on_bump_and_wrong_grid_shows():
    """Аномалия с «бугром» (неплоская): plane оставляет ошибки ~5 см, geoid_plane с верной сеткой — шум;
    geoid с неверной сеткой (без бугра) — заметные остатки и подозрительные точки."""
    t = site()
    good, wrong = read_grid(BUMP_GGF), read_grid(TRUTH_GGF)
    pairs = [Pair(p.name, p.B, p.L, p.h, p.x, p.y, p.H - float(mg.bump(t, p.B, p.L))) for p in pairs_of(t)]
    chk, _ = check_points(t)
    dH = mg.bump(t, chk[:, 0], chk[:, 1])
    plane = localize(pairs, gnss_datum="PZ-90.11")
    gp = localize(pairs, gnss_datum="PZ-90.11", height_model="geoid_plane", geoid=good)
    gpc = localize(pairs, gnss_datum="PZ-90.11", height_model="geoid_plane", geoid=good, geoid_interpolation="bicubic")
    gw = localize(pairs, gnss_datum="PZ-90.11", height_model="geoid", geoid=wrong)
    e_plane, e_gp, e_gpc, e_gw = (check_errors(d, t, dH) for d in (plane, gp, gpc, gw))
    assert e_plane > 0.04 and e_gp < 0.01 and e_gpc < 0.01 and e_plane > 4 * e_gp
    assert plane.rms_height > 0.04 and gp.rms_height < 0.005
    assert e_gw > 0.04 and gw.rms_height > 0.04 and any(r.suspect for r in gw.residuals)
    assert any(w.code == "suspect_height" for w in gw.warnings)


def test_wrong_tilt_absorbed_only_by_geoid_plane():
    t = site()
    g = read_grid(TRUTH)
    B, L = np.meshgrid(g.lat0 + g.dlat * np.arange(g.rows), g.lon0 + g.dlon * np.arange(g.cols), indexing="ij")
    tilted = GeoidGrid(g.lat0, g.lon0, g.dlat, g.dlon, g.values + 3.0 * (B - 55.09), name="tilted")  # 27 мм/км
    tilted.sha256 = "0" * 64
    pairs = pairs_of(t)
    d1 = localize(pairs, gnss_datum="PZ-90.11", height_model="geoid", geoid=tilted)
    d3 = localize(pairs, gnss_datum="PZ-90.11", height_model="geoid_plane", geoid=tilted)
    assert d1.rms_height > 0.02 and check_errors(d1, t) > 0.02
    assert d3.rms_height < 0.005 and check_errors(d3, t) < 0.015
    assert d3.c1 * 1e6 == pytest.approx(3.0 / 111.2 * 1e3, abs=1.0)   # наклон сетки поглощён, мм/км


@pytest.mark.parametrize("path", REGIONS, ids=lambda p: p.stem)
def test_regions_truth_grid(path):
    """Сетка по блоку truth (на лету, шаг 1′): geoid даёт ошибки на контрольных в пределах шума и c0 ≈ 0."""
    t = mg.site_task(path.stem)
    g = mg.site_grid(t, 1 / 60, name=f"{path.stem}.gtx")
    g.sha256 = "0" * 64
    pairs = pairs_of(t)
    d = localize(pairs, gnss_datum="PZ-90.11", height_model="geoid", geoid=g)
    assert abs(d.c0) < 0.03 and d.rms_height < 0.04
    assert check_errors(d, t) < 0.05
    dp = localize(pairs, gnss_datum="PZ-90.11", height_model="geoid_plane", geoid=g)
    assert dp.height_model == "geoid_plane" and check_errors(dp, t) < 0.06


def test_round_trip_and_exact_recovery():
    g = read_grid(BUMP)
    rng = np.random.default_rng(4)
    B = rng.uniform(g.lat0 + 0.02, g.lat1 - 0.02, 7)
    L = rng.uniform(g.lon0 + 0.02, g.lon1 - 0.02, 7)
    h = rng.uniform(150, 250, 7)
    base = LocalizationDatum(float(B.mean()), float(L.mean()), 0, 0, 1, 0, 0, 0, 0, 0, 0, ellipsoid="+a=6378136 +rf=298.25784")
    E, N = base._proj().transform(L, B)
    dN, dE = N - N.mean(), E - E.mean()
    for interp in ("bilinear", "bicubic"):
        H = h - g.value(B, L, interp) + 0.123 + 4e-5 * dN - 2e-5 * dE
        pairs = [Pair(f"P{i}", B[i], L[i], h[i], 1000 + N[i], 2000 + E[i], H[i]) for i in range(7)]
        d = localize(pairs, gnss_datum="PZ-90.11", height_model="geoid_plane", geoid=g, geoid_interpolation=interp)
        assert (d.c0, d.c1, d.c2) == pytest.approx((0.123, 4e-5, -2e-5), abs=1e-9)
        assert d.rms_height < 1e-9
        for model in ("geoid", "geoid_plane"):
            dd = localize(pairs, gnss_datum="PZ-90.11", height_model=model, geoid=g, geoid_interpolation=interp)
            Bq = rng.uniform(g.lat0 + 0.01, g.lat1 - 0.01, 20)
            Lq = rng.uniform(g.lon0 + 0.01, g.lon1 - 0.01, 20)
            hq = rng.uniform(100, 300, 20)
            B2, L2, h2 = dd.to_wgs(*dd.to_local(Bq, Lq, hq))
            assert np.abs(h2 - hq).max() < 1e-6 and np.abs(B2 - Bq).max() < 1e-11 and np.abs(L2 - Lq).max() < 1e-11
            x, y, H2 = dd.to_local(B2, L2, h2)
            assert np.abs(H2 - dd.to_local(Bq, Lq, hq)[2]).max() < 1e-6


def test_few_points_fall_back_to_geoid():
    t = site()
    g = read_grid(TRUTH)
    p = pairs_of(t)
    assert localize(p[:2], gnss_datum="PZ-90.11", height_model="geoid_plane", geoid=g).height_model == "geoid"
    d1 = localize(p[:1], gnss_datum="PZ-90.11", height_model="geoid", geoid=g)
    assert d1.height_model == "geoid" and d1.redundancy_height == 0
    assert "height_no_redundancy" in [w.code for w in d1.warnings]
    d3 = localize(p[:3], gnss_datum="PZ-90.11", height_model="geoid_plane", geoid=g)
    assert d3.redundancy_height == 0 and all(r.loo_dH is None for r in d3.residuals)
    d4 = localize(p[:4], gnss_datum="PZ-90.11", height_model="geoid_plane", geoid=g)
    assert d4.redundancy_height == 1
    # Без точек высоты: H = h − N, модель none.
    dn = localize([Pair(**{**vars(q), "use": "plan"}) for q in p], gnss_datum="PZ-90.11", height_model="geoid", geoid=g)
    assert dn.height_model == "none" and dn.to_local(p[0].B, p[0].L, p[0].h)[2] == pytest.approx(p[0].h - g.value(p[0].B, p[0].L))


def test_weighted_geoid_plane_matches_direct_lsq():
    t = site()
    g = read_grid(TRUTH)
    pairs = pairs_of(t)
    for q, s in zip(pairs, (0.01, 0.05, None, 0.02, 0.08, 0.03)):
        q.sigma_height = s
    d = localize(pairs, gnss_datum="PZ-90.11", height_model="geoid_plane", geoid=g)
    E, N = d._proj().transform([q.L for q in pairs], [q.B for q in pairs])
    A = np.column_stack([np.ones(6), np.asarray(N) - d.Nc, np.asarray(E) - d.Ec])
    y = np.array([q.H - q.h for q in pairs]) + g.value([q.B for q in pairs], [q.L for q in pairs])
    w = np.array([(0.03 / s) ** 2 if s else 1.0 for s in (0.01, 0.05, None, 0.02, 0.08, 0.03)])
    sol = np.linalg.solve(A.T @ (w[:, None] * A), A.T @ (w * y))
    assert (d.c0, d.c1, d.c2) == pytest.approx(tuple(sol), abs=1e-10)
    assert np.allclose(d.q_height, np.linalg.inv(A.T @ (w[:, None] * A)), rtol=1e-8, atol=1e-16)


def test_suggest_exclusions_with_geoid():
    t = site()
    pairs = pairs_of(t)
    pairs[2].H += 0.3
    ex = suggest_exclusions(pairs, gnss_datum="PZ-90.11", height_model="geoid", geoid=read_grid(TRUTH))
    assert ex and ex[0][:2] == (pairs[2].name, "height")


def test_outside_grid_and_nodata_are_errors():
    t = site()
    g = read_grid(TRUTH)
    pairs = pairs_of(t)
    far = Pair("FAR", 56.5, 39.3, 200, 0, 0, 0, use="none")
    with pytest.raises(GeoidError, match="вне сетки"):
        localize(pairs + [far], gnss_datum="PZ-90.11", height_model="geoid", geoid=g)
    d = localize(pairs, gnss_datum="PZ-90.11", height_model="geoid_plane", geoid=g)
    with pytest.raises(GeoidError, match="вне сетки"):
        d.to_local(56.5, 39.3, 200.0)
    with pytest.raises(GeoidError, match="вне сетки"):
        d.to_local([55.09, 56.5], [39.3, 39.3], [200.0, 200.0])       # одна точка из массива — тоже ошибка
    with pytest.raises(GeoidError, match="вне сетки"):
        d.to_wgs(d.tx + 200_000, d.ty, 150.0)
    # NODATA.
    nd = read_grid(DATA / "nodata.gtx")
    pts = [Pair("A", 55.3, 37.6, 200, 0, 0, 186.0), Pair("B", 55.4, 38.6, 200, 9000, 70000, 186.0),
           Pair("C", 55.9, 37.4, 200, 66000, -15000, 186.0)]
    dn = localize(pts, height_model="geoid", geoid=nd)
    assert math.isfinite(dn.to_local(55.5, 38.0, 200.0)[2])
    with pytest.raises(GeoidError, match="NODATA"):
        dn.to_local(55.7, 38.9, 200.0)
    with pytest.raises(GeoidError, match="NODATA"):
        localize(pts + [Pair("D", 55.8, 39.2, 200, 0, 0, 0, use="plan")], height_model="geoid", geoid=nd)


def test_argument_errors():
    p = pairs_of(site())
    g = read_grid(TRUTH)
    with pytest.raises(LocalizationError, match="нужна сетка"):
        localize(p, height_model="geoid")
    with pytest.raises(LocalizationError, match="plane"):
        localize(p, geoid=g)
    with pytest.raises(LocalizationError, match="Модель высоты"):
        localize(p, height_model="quasi")
    with pytest.raises(LocalizationError, match="Интерполяция"):
        localize(p, height_model="geoid", geoid=g, geoid_interpolation="cubic")


def test_save_load_checksum(tmp_path):
    t = site()
    d = localize(pairs_of(t), gnss_datum="PZ-90.11", height_model="geoid_plane", geoid=TRUTH,
                 geoid_interpolation="bicubic")
    path = tmp_path / "datum.json"
    d.save(path)
    js = json.loads(path.read_text(encoding="utf-8"))
    assert js["geoid"] == {"file": "RU-MOW_truth.gtx", "sha256": read_grid(TRUTH).sha256, "interpolation": "bicubic"}
    assert "+proj=vgridshift +grids=RU-MOW_truth.gtx +multiplier=-1" in js["summary"]["proj_pipeline_wgs_to_local"]
    with pytest.raises(GeoidError, match="не найден"):
        LocalizationDatum.load(path)
    d0 = LocalizationDatum.load(path, require_geoid=False)
    assert d0 == d and d0.geoid_grid is None
    with pytest.raises(GeoidError, match="не загружена"):
        d0.to_local(55.09, 39.3, 200.0)
    chk, _ = check_points(t)
    ref = np.column_stack(d.to_local(*chk.T))
    d1 = LocalizationDatum.load(path, geoid=TRUTH)
    assert d1 == d and np.abs(np.column_stack(d1.to_local(*chk.T)) - ref).max() == 0
    (tmp_path / "RU-MOW_truth.gtx").write_bytes(TRUTH.read_bytes())      # рядом с JSON
    assert np.abs(np.column_stack(LocalizationDatum.load(path).to_local(*chk.T)) - ref).max() == 0
    bad = bytearray(TRUTH.read_bytes())
    bad[100] ^= 1
    (tmp_path / "RU-MOW_truth.gtx").write_bytes(bytes(bad))               # испорченная копия
    with pytest.raises(GeoidError, match="SHA-256"):
        LocalizationDatum.load(path)
    with pytest.raises(GeoidError, match="SHA-256"):
        LocalizationDatum.load(path, geoid=TRUTH_ISG)                       # те же значения, другой файл
    # Переименованный файл с тем же содержимым подходит.
    (tmp_path / "renamed.gtx").write_bytes(TRUTH.read_bytes())
    assert LocalizationDatum.load(path, geoid=tmp_path / "renamed.gtx").geoid_grid is not None
    with pytest.raises(GeoidError, match="не нужна"):
        LocalizationDatum.load(ROOT / "examples/datum.json", geoid=TRUTH)


def test_old_json_compatible():
    for f in (ROOT / "examples/datum.json", ROOT / "tests/data/datum_old_format.json"):
        d = LocalizationDatum.load(f)
        assert d.geoid is None and d.geoid_height(55.0, 39.0) == 0.0
        x, y, H = d.to_local(55.07, 39.3, 220.0)
        assert H == pytest.approx(220.0 + d.c0 + d.c1 * (d._dne_wgs(55.07, 39.3)[0]) + d.c2 * d._dne_wgs(55.07, 39.3)[1])


def test_proj_pipeline_with_vgridshift():
    t = site()
    d = localize(pairs_of(t), gnss_datum="PZ-90.11", height_model="geoid_plane", geoid=TRUTH)
    # В строке — имя файла (PROJ ищет его в своих каталогах); для теста — полный путь.
    tr = Transformer.from_pipeline(d.to_proj_pipeline().replace("grids=RU-MOW_truth.gtx", f"grids={TRUTH}"))
    chk, _ = check_points(t)
    px, py, pH = tr.transform(*chk.T)
    x, y, H = d.to_local(*chk.T)
    assert np.abs(np.column_stack([px - x, py - y, pH - H])).max() < 1e-6


# --- командная строка ---

def write_site_csv(tmp_path, task):
    rows = ["name;B;L;h;x;y;H;use"]
    for ps, use in ((task["control_points"], "both"), (task["check_points"], "none")):
        rows += [f"{p['id']};{';'.join(map(repr, p['gnss_B_L_h'] + p['local_x_y_H']))};{use}" for p in ps]
    (tmp_path / "pairs.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (tmp_path / "wgs.csv").write_text("name;B;L;h\n" + "".join(
        f"{p['id']};{';'.join(map(repr, p['gnss_B_L_h']))}\n" for p in task["check_points"]), encoding="utf-8")


def test_cli_geoid(tmp_path, capsys):
    t = site()
    write_site_csv(tmp_path, t)
    datum = tmp_path / "d.json"
    assert cli(["localize", str(tmp_path / "pairs.csv"), "-o", str(datum), "--gnss-datum", "PZ-90.11",
                "--geoid", str(TRUTH_GGF)]) == 0
    out = capsys.readouterr().out
    assert "модель geoid_plane" in out and "Геоид:  сетка RU-MOW_truth.ggf, интерполяция bilinear" in out
    assert json.loads(datum.read_text(encoding="utf-8"))["height_model"] == "geoid_plane"
    # Сетки нет рядом с датумом — ошибка; с --geoid — пересчёт туда и обратно.
    assert cli(["to-local", str(datum), str(tmp_path / "wgs.csv"), "-o", str(tmp_path / "l.csv")]) == 1
    assert "не найден" in capsys.readouterr().err
    assert cli(["to-local", str(datum), str(tmp_path / "wgs.csv"), "-o", str(tmp_path / "l.csv"),
                "--geoid", str(TRUTH_GGF), "--height-model", "geoid_plane"]) == 0
    assert cli(["to-wgs", str(datum), str(tmp_path / "l.csv"), "-o", str(tmp_path / "w.csv"), "--geoid", str(TRUTH_GGF)]) == 0
    src = [ln.split(";") for ln in (tmp_path / "wgs.csv").read_text().splitlines()[1:]]
    back = [ln.split(";") for ln in (tmp_path / "w.csv").read_text().splitlines()[1:]]
    assert all(abs(float(a[3]) - float(b[3])) < 2e-4 for a, b in zip(src, back))
    loc = [ln.split(";") for ln in (tmp_path / "l.csv").read_text().splitlines()[1:]]
    cat = check_points(t)[1]
    assert max(abs(float(r[3]) - c) for r, c in zip(loc, cat[:, 2])) < 0.02
    # Проверки модели и сетки.
    capsys.readouterr()
    assert cli(["to-local", str(datum), str(tmp_path / "wgs.csv"), "-o", str(tmp_path / "l.csv"),
                "--geoid", str(TRUTH_GGF), "--height-model", "plane"]) == 1
    assert "--height-model plane" in capsys.readouterr().err
    assert cli(["to-local", str(datum), str(tmp_path / "wgs.csv"), "-o", str(tmp_path / "l.csv"),
                "--geoid", str(TRUTH)]) == 1          # те же значения в GTX — другой файл
    assert "SHA-256" in capsys.readouterr().err
    assert cli(["localize", str(tmp_path / "pairs.csv"), "-o", str(datum), "--height-model", "geoid"]) == 1
    assert "--geoid" in capsys.readouterr().err
    assert cli(["proj", str(datum)]) == 0
    assert "vgridshift" in capsys.readouterr().out
    # Модель geoid, бикубическая; ошибка вне сетки.
    assert cli(["localize", str(tmp_path / "pairs.csv"), "-o", str(datum), "--gnss-datum", "PZ-90.11",
                "--geoid", str(TRUTH), "--height-model", "geoid", "--geoid-interpolation", "bicubic"]) == 0
    assert "модель geoid;" in capsys.readouterr().out
    (tmp_path / "far.csv").write_text("name;B;L;h\nF;57.0;39.3;200\n", encoding="utf-8")
    assert cli(["to-local", str(datum), str(tmp_path / "far.csv"), "-o", str(tmp_path / "f.csv"), "--geoid", str(TRUTH)]) == 1
    assert "вне сетки" in capsys.readouterr().err
    # Датум без геоида: --geoid — ошибка.
    assert cli(["localize", str(tmp_path / "pairs.csv"), "-o", str(tmp_path / "p.json")]) == 0
    capsys.readouterr()
    assert cli(["to-local", str(tmp_path / "p.json"), str(tmp_path / "wgs.csv"), "-o", str(tmp_path / "l.csv"),
                "--geoid", str(TRUTH)]) == 1


def test_cli_geoid_command(tmp_path, capsys):
    assert cli(["geoid", str(TRUTH), "--at", "55.1,39.3"]) == 0
    out = capsys.readouterr().out
    assert "10×18 узлов" in out and f"N(55.1, 39.3) = {read_grid(TRUTH).value(55.1, 39.3):.4f} м" in out
    (tmp_path / "p.csv").write_text("name;B;L\nA;55.1;39.3\nB;55.05;39.2\n", encoding="utf-8")
    assert cli(["geoid", str(TRUTH), "--points", str(tmp_path / "p.csv"), "-o", str(tmp_path / "n.csv")]) == 0
    rows = (tmp_path / "n.csv").read_text().splitlines()
    assert rows[0] == "name;B;L;N" and float(rows[2].split(";")[3]) == pytest.approx(read_grid(TRUTH).value(55.05, 39.2), abs=1e-4)
    assert cli(["geoid", str(BUMP_GGF), "--crop", "55.05,55.1,39.2,39.3", "-o", str(tmp_path / "c.isg")]) == 0
    c, g = read_grid(tmp_path / "c.isg"), read_grid(BUMP)
    assert c.rows < g.rows and abs(c.value(55.07, 39.25) - g.value(55.07, 39.25)) < 1e-6
    assert cli(["geoid", str(TRUTH), "-o", str(tmp_path / "t.ggf")]) == 0      # перевод в GGF
    assert np.array_equal(read_grid(tmp_path / "t.ggf").values, read_grid(TRUTH).values)
    assert cli(["geoid", str(TRUTH), "--at", "60,39"]) == 1
    assert "вне сетки" in capsys.readouterr().err
