"""Метаданные датума, контрольная сумма исходных данных и HTML-отчёт."""

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path

import pytest

from mathdatum import LocalizationDatum, localize, read_pairs
from mathdatum.__main__ import main as cli
from mathdatum.geoid import read_grid
from mathdatum.localization import relocalize
from mathdatum.meta import LIBRARY, DatumMeta, Inputs, canonical, inputs_checksum
from mathdatum.report import css_str, html_report

ROOT = Path(__file__).resolve().parents[1]
PAIRS = ROOT / "examples/pairs.csv"
DATA = ROOT / "tests/data"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
T = "2026-10-18T12:00:00Z"


@pytest.fixture(scope="module")
def pairs():
    return read_pairs(PAIRS)


def values(html):
    """data-k → текст листовых элементов (как в Kotlin-тесте)."""
    return dict((m.group(2), m.group(3))
                for m in re.finditer(r'<(td|span|text)\b[^>]*?data-k="([^"]*)"[^>]*>([^<]*)', html))


# --- метаданные и ревизии ---

def test_meta_defaults(pairs):
    d = localize(pairs, meta=DatumMeta(object="Объект", author="Иванов"))
    m = d.meta
    assert m.object == "Объект" and m.author == "Иванов" and m.organization is None
    assert UUID.fullmatch(m.datum_id) and m.revision == 1 and m.previous_id is None
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", m.computed_at)
    assert m.library_version == LIBRARY
    assert m.inputs_sha256 == d.checksum() and d.verify_checksum() is True
    assert d.pairs == pairs and d.inputs == Inputs()
    assert localize(pairs).meta.datum_id != m.datum_id


def test_revisions(pairs):
    d1 = localize(pairs, meta=DatumMeta(object="О", organization="Орг", catalog_source="Каталог", note="первая"))
    m2 = d1.meta.next_revision(note="вторая")
    d2 = localize(pairs, meta=m2)
    assert d2.meta.revision == 2 and d2.meta.previous_id == d1.meta.datum_id
    assert d2.meta.datum_id != d1.meta.datum_id and UUID.fullmatch(d2.meta.datum_id)
    assert (d2.meta.object, d2.meta.organization, d2.meta.catalog_source, d2.meta.note) == ("О", "Орг", "Каталог", "вторая")
    assert d1.meta.next_revision().note is None   # примечание не наследуется
    assert localize(pairs, meta=d2.meta.next_revision()).meta.revision == 3
    with pytest.raises(ValueError):
        DatumMeta().next_revision()


def test_cli_metadata_and_revision(tmp_path, capsys):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    assert cli(["localize", str(PAIRS), "-o", str(a), "--object", "ЖК «Север»", "--author", "Иванов И. И.",
                "--organization", "ООО", "--catalog-source", "МСК-50", "--gnss-equipment", "R12i, база B1",
                "--note", "n1"]) == 0
    da = LocalizationDatum.load(a)
    assert (da.meta.object, da.meta.author, da.meta.gnss_equipment, da.meta.note) == ("ЖК «Север»", "Иванов И. И.",
                                                                                      "R12i, база B1", "n1")
    assert cli(["localize", str(PAIRS), "-o", str(b), "--previous", str(a), "--author", "Петров",
                "--report", str(tmp_path / "r.html")]) == 0
    db = LocalizationDatum.load(b)
    assert db.meta.revision == 2 and db.meta.previous_id == da.meta.datum_id
    assert db.meta.object == "ЖК «Север»" and db.meta.author == "Петров" and db.meta.note is None
    assert db.meta.datum_id in (tmp_path / "r.html").read_text(encoding="utf-8")
    capsys.readouterr()
    assert cli(["info", str(b)]) == 0
    out = capsys.readouterr().out
    assert f"2 (предыдущая {da.meta.datum_id})" in out
    assert "совпадает" in out and "воспроизводятся" in out and "Петров" in out


# --- JSON: совместимость ---

def test_json_roundtrip_and_old_formats(tmp_path, pairs):
    d = localize(pairs, meta=DatumMeta(object="x"))
    d.save(tmp_path / "d.json")
    back = LocalizationDatum.load(tmp_path / "d.json")
    assert back == d and back.meta == d.meta and back.inputs == d.inputs and back.pairs == d.pairs
    assert back.verify_checksum() is True
    # Старые датумы: без пар, параметров и метаданных.
    for path in (DATA / "datum_old_format.json", ROOT / "examples/datum.json"):
        old = LocalizationDatum.load(path)
        assert old.pairs is None and old.inputs is None and old.meta is None
        assert old.checksum() is None and old.verify_checksum() is None
    # Поля будущих версий пропускаются.
    raw = json.loads((tmp_path / "d.json").read_text(encoding="utf-8"))
    raw["future"] = {"x": 1}
    raw["meta"]["future_meta"] = 1
    raw["inputs"]["future_param"] = 2
    raw["pairs"][0]["future_pair"] = 3
    (tmp_path / "f.json").write_text(json.dumps(raw), encoding="utf-8")
    f = LocalizationDatum.load(tmp_path / "f.json")
    assert f == d and f.verify_checksum() is True


def test_kotlin_json_with_meta():
    """Датум, сохранённый Kotlin-модулем (ПЗ-90.11, своя σ точки): метаданные и сумма сверяются в Python."""
    d = LocalizationDatum.load(DATA / "datum_kotlin_meta.json")
    assert d.meta.library_version.startswith("mathdatum (Kotlin)") and d.meta.object == "Kotlin «тест»"
    assert d.verify_checksum() is True and d.inputs.gnss_datum == "PZ-90.11" and d.pairs[0].sigma_plan == 0.01
    r = relocalize(d)
    assert r.meta.inputs_sha256 == d.meta.inputs_sha256 and r.meta.datum_id == d.meta.datum_id
    for k in ("a", "b", "tx", "ty", "c0", "c1", "c2", "Nc", "Ec"):
        assert getattr(r, k) == pytest.approx(getattr(d, k), rel=1e-12, abs=1e-9), k


# --- контрольная сумма ---

def test_canonical_format():
    from mathdatum import Pair
    p = [Pair('A"\\\n', 55.0, 37.5, 150.25, -1e-05, 2.0, 3.0, "plan", 0.01, None)]
    text = canonical(p, Inputs(lat0=55.0))
    assert text.startswith("mathdatum inputs v1\ngnss_datum=\"WGS-84\"\nsigma_plan=0.02\n")
    assert "\nlat0=55.0\nlon0=null\nellipsoid=null\nk0=1.0\n" in text
    assert text.endswith('pair="A\\"\\\\\\u000a";55.0;37.5;150.25;-1e-05;2.0;3.0;"plan";0.01;null\n')


def test_checksum_sensitivity(pairs):
    base = localize(pairs).meta.inputs_sha256
    assert localize(list(pairs)).meta.inputs_sha256 == base
    changed = [
        [replace(p, x=p.x + 0.001) if i == 3 else p for i, p in enumerate(pairs)],
        [replace(p, use="plan") if i == 0 else p for i, p in enumerate(pairs)],
        [replace(p, sigma_height=0.05) if i == 0 else p for i, p in enumerate(pairs)],
        [replace(p, name="R1a") if i == 0 else p for i, p in enumerate(pairs)],
        pairs[::-1],
    ]
    sums = {localize(c).meta.inputs_sha256 for c in changed} | {
        localize(pairs, sigma_plan=0.021).meta.inputs_sha256, localize(pairs, w_limit=3.0).meta.inputs_sha256,
        localize(pairs, gnss_datum="PZ-90.11").meta.inputs_sha256, localize(pairs, lat0=55.07).meta.inputs_sha256}
    assert base not in sums and len(sums) == len(changed) + 4


def test_checksum_detects_edit(tmp_path, pairs, capsys):
    d = localize(pairs)
    d.save(tmp_path / "d.json")
    raw = json.loads((tmp_path / "d.json").read_text(encoding="utf-8"))
    raw["pairs"][2]["x"] += 0.01
    (tmp_path / "e.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    e = LocalizationDatum.load(tmp_path / "e.json")
    assert e.verify_checksum() is False
    capsys.readouterr()
    assert cli(["info", str(tmp_path / "e.json")]) == 1
    assert "НЕ СОВПАДАЕТ" in capsys.readouterr().out
    # Сумма цела, но параметры датума подменены — пересчёт по исходным данным это обнаруживает.
    raw = json.loads((tmp_path / "d.json").read_text(encoding="utf-8"))
    raw["tx"] += 0.05
    (tmp_path / "t.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    assert cli(["info", str(tmp_path / "t.json")]) == 1
    out = capsys.readouterr().out
    assert "совпадает с сохранёнными" in out and "НЕ СОВПАДАЕТ с параметрами датума" in out
    html = html_report(e, generated_at=T)
    assert values(html)["checksum_status"].startswith("НЕ СОВПАДАЕТ")


# --- отчёт ---

def test_report_content(pairs):
    meta = DatumMeta(object="Объект 1", organization="Орг", author="Иванов", catalog_source="Каталог",
                     gnss_equipment="R12i", note="Примечание")
    bad = [replace(p, x=p.x + 0.15) if p.name == "R4" else p for p in pairs]
    d = localize(bad, meta=meta)
    html = html_report(d, generated_at=T)
    v = values(html)
    m = d.meta
    for k in ("object", "organization", "author", "catalog_source", "gnss_equipment", "note", "computed_at",
              "datum_id", "inputs_sha256", "library_version"):
        assert v[k] == getattr(m, k), k
    assert v["revision"] == "1" and v["checksum_status"] == "совпадает с исходными данными датума"
    assert v["rms_plan_mm"] == f"{d.rms_plan * 1000:.1f}" and v["rms_height_mm"] == f"{d.rms_height * 1000:.1f}"
    assert v["scale_ppm"] == f"{d.scale_ppm:.3f}" and v["rotation_arcsec"] == f"{d.rotation_arcsec:.3f}"
    assert v["tx"] == f"{d.tx:.4f}" and v["c0"] == f"{d.c0:.4f}" and v["c1_mmkm"] == f"{d.c1 * 1e6:.3f}"
    assert v["redundancy_plan"] == str(d.redundancy_plan) and v["s0_plan_mm"] == f"{d.s0_plan * 1000:.1f}"
    assert v["n_ref"] == "6" and v["n_control"] == "4" and int(v["n_suspect"]) == sum(r.suspect for r in d.residuals) >= 1
    for i, (p, r) in enumerate(zip(bad, d.residuals)):
        assert v[f"p{i}.name"] == p.name and v[f"p{i}.x"] == f"{p.x:.4f}" and v[f"p{i}.B"] == f"{p.B:.10f}"
        assert v[f"svg.{i}"] == p.name
        pre = "c" if p.use == "none" else "r"
        assert v[f"{pre}{i}.dx"] == f"{r.dx * 1000:.1f}" and v[f"{pre}{i}.dH"] == f"{r.dH * 1000:.1f}"
        if r.w_plan is not None:
            assert v[f"{pre}{i}.wp"] == f"{r.w_plan:.2f}"
        if pre == "r" and r.loo_plan is not None:
            assert v[f"r{i}.loop"] == f"{r.loo_plan * 1000:.1f}"
        assert ("⚠" in v[f"{pre}{i}.flag"]) == r.suspect
    # Контрольные пункты: СКО прогноза и расстояние до оболочки.
    out, mp, _ = d.quality_wgs([bad[6].B], [bad[6].L])
    assert v["c6.mp"] == f"{mp[0] * 1000:.1f}" and v["c6.out"] == f"{out[0]:.1f}"
    # Предупреждения, JobXML: предупреждение и контрольные точки x/y и x′/y′.
    assert all(w.message.replace("″", "") .split(":")[0] in html.replace("″", "") for w in d.warnings)
    assert "Знак разворота в JobXML не подтверждён на контроллере" in html
    from mathdatum.export import check_points
    for k, ((n, B, L, x, y), (*_, x2, y2)) in enumerate(zip(check_points(d), check_points(d, -1))):
        assert (v[f"chk{k}.x"], v[f"chk{k}.y"], v[f"chk{k}.x2"], v[f"chk{k}.y2"]) == (
            f"{x:.3f}", f"{y:.3f}", f"{x2:.3f}", f"{y2:.3f}")
    for sec in ("1. Исходные данные", "2. Модель и параметры", "3. Точность", "3.2. Контрольные пункты",
                "4. Предупреждения", "5. Схема расположения пунктов", "6. Экспорт датума", "@page", "@media print"):
        assert sec in html
    assert not re.search(r"(src|href)\s*=\s*\"?(https?:)?//", html) and "@import" not in html   # без внешних ресурсов


def test_svg_is_xml(pairs):
    for d in (localize(pairs), localize(pairs[:2] + pairs[6:]), localize(pairs[:1]),
              localize(pairs, lat0=55.1, lon0=39.0, k0=1.000035, x0=20000.0, y0=100000.0)):
        html = html_report(d, generated_at=T)
        svg = html[html.index("<svg"):html.index("</svg>") + 6]
        root = ET.fromstring(svg)
        assert root.tag == "{http://www.w3.org/2000/svg}svg"
        names = [t.text for t in root.iter("{http://www.w3.org/2000/svg}text") if t.get("data-k", "").startswith("svg.")]
        assert names == [p.name for p in d.pairs]
        assert any(t.text and t.text.startswith("С") for t in root.iter("{http://www.w3.org/2000/svg}text"))
        assert root.find(".//*[@data-k='scalebar']") is not None


def test_report_geoid_and_ldp():
    g = read_grid(ROOT / "tests/data/geoid/RU-MOW_truth.ggf")
    path = ROOT / "data/geodetic/regions/RU-MOW.json"
    task = next(t for t in json.loads(path.read_text(encoding="utf-8"))["tasks"] if t["type"] == "site_localization")
    from mathdatum import Pair
    mow = [Pair(q["id"], *q["gnss_B_L_h"], *q["local_x_y_H"]) for q in task["control_points"]]
    d = localize(mow, height_model="geoid_plane", geoid=g, gnss_datum="PZ-90.11", k0=1.00002, lat0=55.0, lon0=39.3)
    v = values(html_report(d, generated_at=T))
    assert v["geoid_file"] == "RU-MOW_truth.ggf" and v["geoid_sha256"] == g.sha256 and v["geoid_interp"] == "билинейная"
    assert v["k0"] == "1.000020000" and v["lon0"] == "39.300000000"


def test_report_escapes_user_text(pairs):
    evil = '<img src=x onerror=alert(1)>&"'
    p2 = [replace(p, name=evil) if i == 0 else p for i, p in enumerate(pairs)]
    d = localize(p2, meta=DatumMeta(object="</style><script>alert(1)</script>", author="<b>A</b>",
                                    note="\"'><svg onload=alert(1)>", organization="</title><h1>x"))
    html = html_report(d, generated_at=T)

    class Tags(HTMLParser):
        def __init__(self):
            super().__init__()
            self.tags = []

        def handle_starttag(self, tag, attrs):
            self.tags.append((tag, dict(attrs)))

    t = Tags()
    t.feed(html)
    tags = {x for x, _ in t.tags}
    assert "script" not in tags and "img" not in tags and "<b>A</b>" not in html and "h1" in tags
    assert sum(x == "svg" for x, _ in t.tags) == 1 and sum(x == "h1" for x, _ in t.tags) == 1
    assert not any(k.startswith("on") for _, a in t.tags for k in a)
    assert "&lt;img src=x onerror=alert(1)&gt;&amp;&quot;" in html
    style = html[html.index("<style>") + 7:html.index("</style>")]
    assert "<" not in style and "\\3c /style\\3e " in style
    assert css_str('a"b\\c\n<') == '"a\\"b\\\\c\\a \\3c "'
    assert values(html)["p0.name"] == "&lt;img src=x onerror=alert(1)&gt;&amp;&quot;"


def test_report_old_datum_and_cli(tmp_path, pairs, capsys):
    old = LocalizationDatum.load(DATA / "datum_old_format.json")
    html = html_report(old, generated_at=T)
    v = values(html)
    assert "<svg" not in html and "нет исходных пар" in html and v["checksum_status"].startswith("сверить нельзя")
    assert v["r0.dx"] == f"{old.residuals[0].dx * 1000:.1f}"
    # С CSV пар — исходные данные и схема есть.
    out = tmp_path / "r.html"
    assert cli(["report", str(DATA / "datum_old_format.json"), "-o", str(out), "--pairs", str(PAIRS)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "<svg" in text and all(p.name in text for p in pairs)
    # Новый датум: пары из JSON; CSV с другими парами — ошибка.
    d = localize(pairs)
    d.save(tmp_path / "d.json")
    assert cli(["report", str(tmp_path / "d.json"), "-o", str(out)]) == 0
    assert d.meta.inputs_sha256 in out.read_text(encoding="utf-8")
    bad = tmp_path / "bad.csv"
    bad.write_text(PAIRS.read_text(encoding="utf-8").replace("-200498.0340", "-200498.0350"), encoding="utf-8")
    capsys.readouterr()
    assert cli(["report", str(tmp_path / "d.json"), "-o", str(out), "--pairs", str(bad)]) == 1
    assert "не совпадают" in capsys.readouterr().err
    assert cli(["info", str(DATA / "datum_old_format.json")]) == 0
    assert "старого формата" in capsys.readouterr().out
