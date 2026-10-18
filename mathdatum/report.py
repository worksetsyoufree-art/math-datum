"""HTML-отчёт о локализации для исполнительной документации.

Один самодостаточный файл (без внешних ресурсов), печатается из браузера в PDF на A4 (@media print,
разрывы страниц, колонтитулы через @page). Разделы: титул с метаданными; 1 — исходные данные; 2 — модель
и параметры; 3 — точность (невязки, |w|, leave-one-out, контрольные пункты); 4 — предупреждения; 5 — схема
расположения пунктов (inline SVG: оболочка, векторы невязок, СКО прогноза цветом, север, масштаб);
6 — экспорт (форматы, ограничения, контрольные точки JobXML).

Ключевые величины помечены атрибутом data-k (сверка Python ↔ Kotlin, Report.kt — тот же отчёт).
Весь пользовательский текст (имена точек, объект, …) экранируется.
"""

from __future__ import annotations

import math

import numpy as np

from . import datums, export as export_mod
from .meta import LIBRARY, now_utc

USE_TEXT = {"both": "план и высота", "plan": "план", "height": "высота", "none": "контроль"}
FIELD_K = (0.5, 0.75, 1.0, 1.5, 2.0)   # границы классов СКО прогноза, в долях σ0 плана
FIELD_COLORS = ("#edf3fa", "#d3e2f2", "#b2cbe7", "#8bb0da", "#6693c9", "#4474b5")


# --- форматирование (одинаково с Kotlin: Report.kt) ---

def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def css_str(s: str, limit: int = 80) -> str:
    """Текст для content: "…" в @page (экранирование кавычек, \\, < >, переводов строк)."""
    s = s if len(s) <= limit else s[:limit - 1] + "…"
    out = []
    for ch in s:
        if ch in '"\\':
            out.append("\\" + ch)
        elif ch in "<>" or ord(ch) < 0x20:
            out.append(f"\\{ord(ch):x} ")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def fx(v, n: int) -> str:
    """Число с n знаками; None / nan — «—»; без «-0.0»."""
    if v is None or v != v:
        return "—"
    s = f"{float(v):.{n}f}"
    return s[1:] if s.startswith("-") and not s.strip("-0.") else s


def mm(v, n: int = 1) -> str:
    return "—" if v is None or v != v else fx(v * 1000, n)


def trim(v: float) -> str:
    """Короткая запись «красивого» числа (1, 2.5, 0.05): до 6 знаков, без хвостовых нулей."""
    s = fx(v, 6).rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def dms(deg: float) -> str:
    sign = "-" if deg < 0 else ""
    t = round(abs(deg) * 3600 * 1000)
    d, rest = divmod(t, 3600 * 1000)
    m, sec = divmod(rest, 60 * 1000)
    return f"{sign}{d}°{m:02d}′{sec // 1000:02d}.{sec % 1000:03d}″"


def nice_floor(v: float) -> float:
    """Наибольшее 1·10ᵏ, 2·10ᵏ, 5·10ᵏ ≤ v."""
    if not v > 0:
        return 0.0
    k = math.floor(math.log10(v))
    base = 10.0 ** k
    for m in (5, 2, 1):
        if m * base <= v * (1 + 1e-12):
            return m * base
    return base


def K(key: str, text: str, tag: str = "span", cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f'<{tag} data-k="{esc(key)}"{c}>{text}</{tag}>'


def _row(cells, cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f"<tr{c}>" + "".join(cells) + "</tr>"


def _td(key: str | None, text: str, cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    k = f' data-k="{esc(key)}"' if key else ""
    return f"<td{k}{c}>{text}</td>"


def _table(head: list[str], rows: list[str], cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return (f'<div class="tw"><table{c}><thead><tr>' + "".join(f"<th>{h}</th>" for h in head)
            + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>")


def _kv(rows: list[tuple[str, str, str | None]]) -> str:
    """Таблица «название — значение»; key — data-k значения (None — без метки)."""
    return ('<table class="kv"><tbody>'
            + "".join(f"<tr><th>{k}</th>{_td(key, v)}</tr>" for k, v, key in rows) + "</tbody></table>")


def _opt(v) -> str:
    return "—" if v is None or v == "" else esc(v)


# --- данные отчёта ---

def _system_name(d) -> str:
    s = d.gnss_system
    if s is None:
        return "не указана (старый датум)"
    sy = datums.get_system(s)
    return f"{sy.name} (эллипсоид {sy.ellipsoid.name})"


def _hull_local(d):
    if not d.plan_hull:
        return []
    out = []
    for n, e in d.plan_hull:
        dn, de = n - d.Nc, e - d.Ec
        out.append((d.tx + d.a * dn - d.b * de, d.ty + d.b * dn + d.a * de))
    return out


def _param_sigmas(d):
    """СКО параметров по априорной σ0: tx, ty (м), масштаб (ppm), разворот (″), c0 (м), c1, c2 (1)."""
    cp, ch = d.covariance_plan(), d.covariance_height()
    out = {}
    if cp is not None:
        out["s_tx"], out["s_ty"] = math.sqrt(cp[0][0]), math.sqrt(cp[1][1])
        if d.plan_model == "similarity":
            out["s_scale_ppm"] = math.sqrt(cp[2][2]) * 1e6
            out["s_rot_arcsec"] = math.sqrt(cp[3][3]) / d.scale * 180 * 3600 / math.pi
    if ch is not None:
        out["s_c0"] = math.sqrt(ch[0][0])
        if d.height_model in ("plane", "geoid_plane"):
            out["s_c1"], out["s_c2"] = math.sqrt(ch[1][1]), math.sqrt(ch[2][2])
    return out


def checksum_status(d) -> tuple[str, str]:
    """(код, текст) сверки контрольной суммы: ok | mismatch | none."""
    v = d.verify_checksum()
    if v is None:
        return "none", "сверить нельзя: в датуме нет исходных данных или суммы (старый формат)"
    if v:
        return "ok", "совпадает с исходными данными датума"
    return "mismatch", "НЕ СОВПАДАЕТ: исходные данные или параметры в файле изменены после расчёта"


# --- схема (SVG) ---

def scheme_svg(d, pairs) -> str:
    """Схема расположения пунктов в местной системе (x — север вверх, y — восток вправо)."""
    pts = []
    for i, (p, r) in enumerate(zip(pairs, d.residuals)):
        pts.append((i, p.name, p.x, p.y, p.use, r.dx, r.dy, r.suspect))
    hull = _hull_local(d)
    xs = [q[2] for q in pts] + [h[0] for h in hull]
    ys = [q[3] for q in pts] + [h[1] for h in hull]
    ext_n, ext_e = max(max(xs) - min(xs), 1.0), max(max(ys) - min(ys), 1.0)
    pad = 0.1 * max(ext_n, ext_e)
    n0, n1 = min(xs) - pad, min(xs) + ext_n + pad
    e0, e1 = min(ys) - pad, min(ys) + ext_e + pad
    s = min(640 / (e1 - e0), 560 / (n1 - n0))
    pw, ph = (e1 - e0) * s, (n1 - n0) * s
    ox, oy = 20 + (640 - pw) / 2, 20.0
    W, H = 680.0, oy + ph + 120

    def X(e):
        return ox + (e - e0) * s

    def Y(n):
        return oy + (n1 - n) * s

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {fx(W, 1)} {fx(H, 1)}" '
         f'width="680" height="{fx(H, 0)}" font-family="Arial, Helvetica, sans-serif" font-size="11" '
         'role="img" aria-label="Схема расположения пунктов">',
         '<defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
         'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#c0392b"/></marker></defs>',
         f'<rect x="{fx(ox, 1)}" y="{fx(oy, 1)}" width="{fx(pw, 1)}" height="{fx(ph, 1)}" fill="#ffffff" '
         'stroke="#999999" stroke-width="0.8"/>']

    # СКО прогноза в плане (априори) — цветом по классам σ0·(0.5, 0.75, 1, 1.5, 2).
    s0 = d.sigma0_plan
    field = d.q_plan is not None and s0 is not None and d.plan_model == "similarity"
    edges = [s0 * k for k in FIELD_K] if field else []
    if field:
        cols = 48
        rows = max(8, min(64, round(cols * ph / pw)))
        cw, chh = pw / cols, ph / rows
        o.append('<g fill-opacity="0.7" data-k="field">')
        for j in range(rows):
            n = n1 - (j + 0.5) * (n1 - n0) / rows
            e = np.array([e0 + (i + 0.5) * (e1 - e0) / cols for i in range(cols)])
            m = d.quality_local(np.full(cols, n), e)[1]
            cls = [sum(1 for t in edges if v > t) for v in m]
            i = 0
            while i < cols:
                k = i
                while k + 1 < cols and cls[k + 1] == cls[i]:
                    k += 1
                o.append(f'<rect x="{fx(ox + i * cw, 1)}" y="{fx(oy + j * chh, 1)}" width="{fx((k - i + 1) * cw + 0.3, 1)}" '
                         f'height="{fx(chh + 0.3, 1)}" fill="{FIELD_COLORS[cls[i]]}"/>')
                i = k + 1
        o.append("</g>")

    if len(hull) >= 3:
        o.append('<polygon points="' + " ".join(f"{fx(X(e), 1)},{fx(Y(n), 1)}" for n, e in hull)
                 + '" fill="none" stroke="#333333" stroke-width="1.2" stroke-dasharray="6 4"/>')
    elif len(hull) == 2:
        (na, ea), (nb, eb) = hull
        o.append(f'<line x1="{fx(X(ea), 1)}" y1="{fx(Y(na), 1)}" x2="{fx(X(eb), 1)}" y2="{fx(Y(nb), 1)}" '
                 'stroke="#333333" stroke-width="1.2" stroke-dasharray="6 4"/>')

    # Векторы невязок (каталог − вычисленное) в увеличенном масштабе.
    maxv = max((math.hypot(q[5], q[6]) for q in pts if q[4] != "height"), default=0.0)
    exag = nice_floor(0.12 * max(n1 - n0, e1 - e0) / maxv) if maxv > 1e-6 else 0.0
    if exag > 0:
        for i, name, x, y, use, dx, dy, sus in pts:
            if use == "height" or math.hypot(dx, dy) * exag * s < 0.5:
                continue
            o.append(f'<line x1="{fx(X(y), 1)}" y1="{fx(Y(x), 1)}" x2="{fx(X(y + dy * exag), 1)}" '
                     f'y2="{fx(Y(x + dx * exag), 1)}" stroke="#c0392b" stroke-width="1.6" marker-end="url(#arr)"/>')

    for i, name, x, y, use, dx, dy, sus in pts:
        cx, cy = X(y), Y(x)
        if use == "none":
            o.append(f'<circle cx="{fx(cx, 1)}" cy="{fx(cy, 1)}" r="5" fill="#ffffff" stroke="#1d1d1b" stroke-width="1.6"/>')
        else:
            o.append(f'<polygon points="{fx(cx, 1)},{fx(cy - 6, 1)} {fx(cx + 5.5, 1)},{fx(cy + 4, 1)} '
                     f'{fx(cx - 5.5, 1)},{fx(cy + 4, 1)}" fill="#1d1d1b"/>')
        if sus:
            o.append(f'<circle cx="{fx(cx, 1)}" cy="{fx(cy, 1)}" r="10" fill="none" stroke="#c0392b" stroke-width="1.6"/>')
        o.append(f'<text x="{fx(cx + 8, 1)}" y="{fx(cy - 7, 1)}" data-k="svg.{i}">{esc(name)}</text>')

    # Север (ось x) — справа вверху.
    ax, ay = ox + pw - 22, oy + 14
    o.append(f'<g stroke="#1d1d1b" fill="#1d1d1b"><line x1="{fx(ax, 1)}" y1="{fx(ay + 40, 1)}" x2="{fx(ax, 1)}" '
             f'y2="{fx(ay + 6, 1)}" stroke-width="1.6"/><polygon points="{fx(ax, 1)},{fx(ay, 1)} {fx(ax + 6, 1)},'
             f'{fx(ay + 12, 1)} {fx(ax - 6, 1)},{fx(ay + 12, 1)}" stroke="none"/></g>'
             f'<text x="{fx(ax, 1)}" y="{fx(ay + 54, 1)}" text-anchor="middle" font-weight="bold">С (x)</text>')

    # Масштабная линейка.
    L = nice_floor(0.25 * (e1 - e0))
    lp = L * s
    by = oy + ph + 26
    o.append(f'<g data-k="scalebar"><rect x="20" y="{fx(by, 1)}" width="{fx(lp / 2, 1)}" height="6" fill="#1d1d1b"/>'
             f'<rect x="{fx(20 + lp / 2, 1)}" y="{fx(by, 1)}" width="{fx(lp / 2, 1)}" height="6" fill="#ffffff" '
             f'stroke="#1d1d1b" stroke-width="1"/>'
             f'<text x="20" y="{fx(by - 4, 1)}">0</text>'
             f'<text x="{fx(20 + lp, 1)}" y="{fx(by - 4, 1)}" text-anchor="middle">{_dist(L)}</text></g>')
    lx = 40 + lp + 30
    if exag > 0:
        ref = nice_floor(maxv)
        rl = ref * exag * s
        o.append(f'<line x1="{fx(lx, 1)}" y1="{fx(by + 3, 1)}" x2="{fx(lx + rl, 1)}" y2="{fx(by + 3, 1)}" '
                 'stroke="#c0392b" stroke-width="1.6" marker-end="url(#arr)"/>'
                 f'<text x="{fx(lx + rl + 8, 1)}" y="{fx(by + 7, 1)}">невязка {trim(ref * 1000)} мм '
                 f'(векторы увеличены в {trim(exag)} раз)</text>')
    else:
        o.append(f'<text x="{fx(lx, 1)}" y="{fx(by + 7, 1)}">невязки в плане нулевые (нет избыточности)</text>')

    ly = by + 34
    o.append(f'<polygon points="26,{fx(ly - 6, 1)} 31.5,{fx(ly + 4, 1)} 20.5,{fx(ly + 4, 1)}" fill="#1d1d1b"/>'
             f'<text x="38" y="{fx(ly + 4, 1)}">опорный пункт</text>'
             f'<circle cx="146" cy="{fx(ly, 1)}" r="5" fill="#ffffff" stroke="#1d1d1b" stroke-width="1.6"/>'
             f'<text x="156" y="{fx(ly + 4, 1)}">контрольный пункт</text>'
             f'<circle cx="286" cy="{fx(ly, 1)}" r="8" fill="none" stroke="#c0392b" stroke-width="1.6"/>'
             f'<text x="298" y="{fx(ly + 4, 1)}">подозрение на грубую ошибку</text>'
             f'<line x1="480" y1="{fx(ly, 1)}" x2="510" y2="{fx(ly, 1)}" stroke="#333333" stroke-width="1.2" '
             f'stroke-dasharray="6 4"/><text x="516" y="{fx(ly + 4, 1)}">выпуклая оболочка</text>')
    if field:
        fy = ly + 26
        o.append(f'<text x="20" y="{fx(fy + 4, 1)}">СКО прогноза в плане, мм:</text>')
        labels = [f"≤ {mm(edges[0], 0)}"] + [f"{mm(a, 0)}–{mm(b, 0)}" for a, b in zip(edges, edges[1:])] \
            + [f"&gt; {mm(edges[-1], 0)}"]
        for k, (c, t) in enumerate(zip(FIELD_COLORS, labels)):
            x = 180 + k * 80
            o.append(f'<rect x="{x}" y="{fx(fy - 6, 1)}" width="16" height="12" fill="{c}" stroke="#999999" '
                     f'stroke-width="0.5"/><text x="{x + 21}" y="{fx(fy + 4, 1)}">{t}</text>')
    o.append("</svg>")
    return "".join(o)


def _dist(m: float) -> str:
    return f"{trim(m / 1000)} км" if m >= 1000 else f"{trim(m)} м"


# --- отчёт ---

CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #ecebe7; color: #1d1d1b; font: 10pt/1.45 Arial, Helvetica, sans-serif; }
.page { max-width: 210mm; margin: 0 auto; background: #ffffff; padding: 14mm 14mm 18mm; }
h1 { font-size: 18pt; margin: 2mm 0 4mm; overflow-wrap: anywhere; }
h2 { font-size: 13pt; margin: 8mm 0 3mm; border-bottom: 1.5px solid #1d1d1b; padding-bottom: 1mm; break-after: avoid; }
h3 { font-size: 11pt; margin: 5mm 0 2mm; break-after: avoid; }
p { margin: 0 0 2.5mm; }
.kicker { text-transform: uppercase; letter-spacing: .08em; color: #555; font-size: 9pt; }
.hint { color: #555; font-size: 8.5pt; }
.tw { overflow-x: auto; margin: 0 0 3mm; }
table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
th, td { border: 0.6pt solid #b8b6ae; padding: 1.2mm 1.6mm; text-align: right; vertical-align: top; }
thead th { background: #f0efea; font-weight: bold; text-align: center; }
td.l, th.l { text-align: left; }
td.nw { white-space: nowrap; }
tr.ctl td { color: #555; }
table.data { font-size: 8pt; }
table.data td:nth-child(2) { text-align: left; overflow-wrap: anywhere; }
table.kv th { text-align: left; font-weight: normal; color: #444; width: 42%; background: #f7f6f2; }
table.kv td { text-align: left; overflow-wrap: anywhere; }
tr { break-inside: avoid; }
thead { display: table-header-group; }
tr.sus td { background: #fbe9e7; }
tr.sus td.flag { color: #b3261e; font-weight: bold; }
td.bad { color: #b3261e; font-weight: bold; }
.mono { font-family: "Courier New", monospace; font-size: 8pt; overflow-wrap: anywhere; word-break: break-all; }
.summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 2mm; margin: 4mm 0; }
.summary div { border: 0.6pt solid #b8b6ae; padding: 2mm; }
.summary b { display: block; font-size: 12pt; }
.summary span.k { color: #555; font-size: 8pt; }
.alert { border: 1.5pt solid #b3261e; background: #fdf1ef; padding: 3mm; margin: 3mm 0; break-inside: avoid; }
.ok { color: #1e7a3c; font-weight: bold; }
.badtxt { color: #b3261e; font-weight: bold; }
ul.warn { margin: 0 0 3mm; padding-left: 6mm; }
ul.warn li { margin: 1mm 0; overflow-wrap: anywhere; }
figure { margin: 0; break-inside: avoid; }
figure svg { display: block; width: 100%; height: auto; max-height: 230mm; }
figcaption { font-size: 8.5pt; color: #444; margin-top: 2mm; }
.title { break-after: page; }
.sign { margin-top: 10mm; break-inside: avoid; }
.sign td, .sign th { border: none; text-align: left; padding: 3mm 2mm; }
.newpage { break-before: page; }
.foot { margin-top: 8mm; font-size: 8pt; color: #666; border-top: 0.6pt solid #b8b6ae; padding-top: 2mm; overflow-wrap: anywhere; }
@media (max-width: 600px) {
  .page { padding: 16px; }
  .summary { grid-template-columns: repeat(2, 1fr); }
}
@media print {
  body { background: #ffffff; font-size: 9.5pt; }
  .page { max-width: none; padding: 0; margin: 0; }
  .tw { overflow: visible; }
  table.data { font-size: 7.5pt; }
  th, td { padding: 0.8mm 1.2mm; }
  a { color: inherit; text-decoration: none; }
}
"""


def _page_css(d) -> str:
    m = d.meta
    obj = (m.object if m and m.object else "Объект не указан")
    did = (m.datum_id if m and m.datum_id else "без идентификатора")
    rev = f", ревизия {m.revision}" if m and m.revision else ""
    return ("@page { size: A4; margin: 16mm 14mm 18mm 16mm;"
            ' @top-left { content: "Отчёт о локализации ГНСС"; font: 8pt Arial, sans-serif; color: #666; }'
            f" @top-right {{ content: {css_str(obj)}; font: 8pt Arial, sans-serif; color: #666; }}"
            f" @bottom-left {{ content: {css_str('Датум ' + did + rev)}; font: 7.5pt Arial, sans-serif; color: #666; }}"
            ' @bottom-right { content: "стр. " counter(page) " из " counter(pages); font: 8pt Arial, sans-serif; color: #666; } }')


def html_report(d, pairs=None, generated_at: str | None = None, library: str = LIBRARY) -> str:
    """HTML-отчёт по датуму d. pairs — исходные пары (по умолчанию d.pairs; для старого датума — из CSV)."""
    pairs = d.pairs if pairs is None else pairs
    notes = []
    if pairs is not None and [p.name for p in pairs] != [r.name for r in d.residuals]:
        notes.append("Пары точек не соответствуют невязкам датума (другие имена или порядок) — исходные данные "
                     "и схема не показаны.")
        pairs = None
    if pairs is None and d.pairs is None:
        notes.append("В датуме нет исходных пар точек (старый формат): разделы «Исходные данные» и «Схема» неполные — "
                     "укажите исходные пары (CSV) или пересчитайте датум.")
    m = d.meta
    gen = generated_at or now_utc()
    cs_code, cs_text = checksum_status(d)
    if cs_code == "mismatch":
        notes.append("Контрольная сумма исходных данных не совпадает: файл датума изменён после расчёта.")
    obj = m.object if m and m.object else None
    res = d.residuals
    ref = [r for r in res if r.use != "none"]
    ctl = [(i, r) for i, r in enumerate(res) if r.use == "none"]
    o = ["<!DOCTYPE html>", '<html lang="ru"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         f"<title>Отчёт о локализации ГНСС — {esc(obj or 'объект не указан')}</title>",
         f"<style>{CSS}{_page_css(d)}</style></head><body><div class=\"page\">"]

    # --- титул ---
    o.append('<header class="title"><div class="kicker">Отчёт о локализации ГНСС</div>')
    o.append(f"<h1>{K('object', esc(obj) if obj else 'Объект не указан')}</h1>")
    rev = "—"
    if m and m.revision:
        rev = K("revision", str(m.revision)) + (
            f" (предыдущая ревизия: {K('previous_id', esc(m.previous_id), cls='mono')})" if m.previous_id else "")
    cs_cls = {"ok": "ok", "mismatch": "badtxt"}.get(cs_code, "hint")
    o.append(_kv([
        ("Организация", _opt(m and m.organization), "organization"),
        ("Исполнитель", _opt(m and m.author), "author"),
        ("Дата и время расчёта (UTC)", _opt(m and m.computed_at), "computed_at"),
        ("Отчёт сформирован (UTC)", esc(gen), None),
        ("Идентификатор датума (UUID)", K("datum_id", _opt(m and m.datum_id), cls="mono"), None),
        ("Ревизия", rev, None),
        ("Источник каталога пунктов", _opt(m and m.catalog_source), "catalog_source"),
        ("Система ГНСС, оборудование, базовая станция", _opt(m and m.gnss_equipment), "gnss_equipment"),
        ("Система ГНСС-координат пар", esc(_system_name(d)), None),
        ("Расчёт выполнен", _opt(m and m.library_version), "library_version"),
        ("Отчёт составлен", esc(library), None),
        ("Контрольная сумма исходных данных (SHA-256 пар и параметров)",
         K("inputs_sha256", _opt(m and m.inputs_sha256), cls="mono") + "<br>"
         + K("checksum_status", esc(cs_text), cls=cs_cls), None),
        ("Примечание", _opt(m and m.note), "note"),
    ]))
    n_sus = sum(r.suspect for r in res)
    o.append('<div class="summary">'
             f'<div><span class="k">СКО в плане</span><b>{K("rms_plan_mm", mm(d.rms_plan))} мм</b></div>'
             f'<div><span class="k">СКО по высоте</span><b>{K("rms_height_mm", mm(d.rms_height))} мм</b></div>'
             f'<div><span class="k">Масштаб</span><b>{K("scale_ppm", fx(d.scale_ppm, 3))} ppm</b></div>'
             f'<div><span class="k">Разворот</span><b>{K("rotation_arcsec", fx(d.rotation_arcsec, 3))}″</b></div>'
             f'<div><span class="k">Опорных пунктов</span><b>{K("n_ref", str(len(ref)))}</b></div>'
             f'<div><span class="k">Контрольных пунктов</span><b>{K("n_control", str(len(ctl)))}</b></div>'
             f'<div><span class="k">Подозрительных точек</span><b>{K("n_suspect", str(n_sus))}</b></div>'
             f'<div><span class="k">Предупреждений</span><b>{K("n_warnings", str(len(d.warnings)))}</b></div></div>')
    if notes:
        o.append('<div class="alert">' + "<br>".join(esc(t) for t in notes) + "</div>")
    o.append('<p class="hint">Единицы: координаты и высоты — м, невязки и СКО в таблицах — мм, B и L — градусы, '
             "масштаб — ppm (мм/км), разворот — угловые секунды. x — север, y — восток. Невязка = каталог − вычисленное.</p>")
    o.append("</header>")

    # --- 1. исходные данные ---
    i_ = d.inputs
    o.append("<section><h2>1. Исходные данные</h2><h3>1.1. Параметры расчёта</h3>")
    o.append(_kv([
        ("Система ГНСС-координат", esc(_system_name(d)), None),
        ("Априорная СКО координаты в плане σ0 (единица веса), мм", mm(d.sigma0_plan), "sigma0_plan_mm"),
        ("Априорная СКО высоты σ0, мм", mm(d.sigma0_height), "sigma0_height_mm"),
        ("Порог нормированной поправки |w| (тест Баарда)", fx(d.w_limit, 2), "w_limit"),
        ("Пределы правдоподобия: масштаб, ppm / разворот, °",
         "—" if i_ is None else f"{fx(i_.max_scale_ppm, 0)} / {fx(i_.max_rotation_deg, 1)}", None),
        ("Запрошенная модель высоты", "—" if i_ is None else esc(i_.height_model), None),
    ]))
    o.append("<h3>1.2. Пары точек</h3>")
    if pairs is None:
        o.append('<p class="hint">Исходные пары в датуме не сохранены.</p>')
    else:
        rows = []
        for i, p in enumerate(pairs):
            own_p = p.sigma_plan is not None
            own_h = p.sigma_height is not None
            rows.append(_row([
                _td(None, str(i + 1)), _td(f"p{i}.name", esc(p.name)), _td(f"p{i}.B", fx(p.B, 10)),
                _td(f"p{i}.L", fx(p.L, 10)), _td(f"p{i}.h", fx(p.h, 4)), _td(f"p{i}.x", fx(p.x, 4)),
                _td(f"p{i}.y", fx(p.y, 4)), _td(f"p{i}.H", fx(p.H, 4)), _td(f"p{i}.use", USE_TEXT.get(p.use, esc(p.use)), "l"),
                _td(f"p{i}.sp", mm(p.sigma_plan if own_p else d.sigma0_plan) + ("*" if own_p else "")),
                _td(f"p{i}.sh", mm(p.sigma_height if own_h else d.sigma0_height) + ("*" if own_h else "")),
            ], "ctl" if p.use == "none" else ""))
        o.append(_table(["№", "Пункт", "B, °", "L, °", "h, м", "x, м", "y, м", "H, м", "Использование",
                         "σ план, мм", "σ выс., мм"], rows, "data"))
        o.append('<p class="hint">B, L, h — ГНСС (h — эллипсоидальная высота); x, y, H — каталог местной системы. '
                 "σ — априорная СКО точки (план — на одну координату); * — своя σ точки (вес p = σ0²/σ²), без * — σ0. "
                 "«Контроль» — точка не участвует в расчёте, по ней оценивается датум.</p>")
    o.append("</section>")

    # --- 2. модель ---
    sg = _param_sigmas(d)
    default_tm = (d.k0, d.x0, d.y0) == (1.0, 0.0, 0.0)
    o.append("<section><h2>2. Модель и параметры</h2><h3>2.1. Рабочая проекция</h3>")
    o.append(_kv([
        ("Тип", "поперечная Меркатора по центру точек, k = 1" if default_tm
         else "поперечная Меркатора с заданными параметрами (малоискажающая проекция, LDP)", None),
        ("Широта начала B0, °", fx(d.lat0, 9), "lat0"),
        ("Осевой меридиан L0, °", fx(d.lon0, 9), "lon0"),
        ("Масштаб на осевом меридиане k0", fx(d.k0, 9), "k0"),
        ("Ложные смещения x0 (север) / y0 (восток), м", f"{K('x0', fx(d.x0, 3))} / {K('y0', fx(d.y0, 3))}", None),
        ("Эллипсоид (PROJ)", esc(d.ellipsoid), None),
        ("Строка PROJ", f'<span class="mono">{esc(d.projection)}</span>', None),
    ]))
    o.append('<h3>2.2. План: преобразование подобия</h3><p class="hint">x = tx + a·(N − Nc) − b·(E − Ec), '
             "y = ty + b·(N − Nc) + a·(E − Ec); N, E — рабочая проекция, Nc, Ec — взвешенный центроид. "
             "СКО параметров — по априорной σ0.</p>")
    o.append(_kv([
        ("Модель", "подобие (4 параметра)" if d.plan_model == "similarity" else "только сдвиг (1 точка)", "plan_model"),
        ("Масштаб m = √(a² + b²)", f"{K('scale', fx(d.scale, 10))} ({K('scale_ppm2', fx(d.scale_ppm, 3))} ppm; "
                                    f"СКО {K('s_scale_ppm', fx(sg.get('s_scale_ppm'), 3))} ppm)", None),
        ("Разворот θ = atan2(b, a)", f"{K('rotation_arcsec2', fx(d.rotation_arcsec, 3))}″ = {dms(d.rotation_arcsec / 3600)} "
                                    f"(СКО {K('s_rot_arcsec', fx(sg.get('s_rot_arcsec'), 3))}″)", None),
        ("a / b", f"{K('a', fx(d.a, 12))} / {K('b', fx(d.b, 12))}", None),
        ("Сдвиг tx (север), м", f"{K('tx', fx(d.tx, 4))} (СКО {K('s_tx_mm', mm(sg.get('s_tx')))} мм)", None),
        ("Сдвиг ty (восток), м", f"{K('ty', fx(d.ty, 4))} (СКО {K('s_ty_mm', mm(sg.get('s_ty')))} мм)", None),
        ("Центроид Nc / Ec, м", f"{K('Nc', fx(d.Nc, 4))} / {K('Ec', fx(d.Ec, 4))}", None),
    ]))
    hm_text = {"plane": "наклонная плоскость: H = h + c0 + c1·dN + c2·dE",
               "shift": "сдвиг: H = h + c0 (мало точек для плоскости)",
               "geoid": "геоид и сдвиг: H = h − N(B, L) + c0",
               "geoid_plane": "геоид и остаточная плоскость: H = h − N(B, L) + c0 + c1·dN + c2·dE",
               "none": "нет (не было точек для высоты)"}.get(d.height_model, d.height_model)
    o.append("<h3>2.3. Высота</h3>")
    hrows = [("Модель", esc(hm_text), "height_model")]
    if d.height_model != "none":
        hrows += [
            ("Сдвиг c0, м", f"{K('c0', fx(d.c0, 4))} (СКО {K('s_c0_mm', mm(sg.get('s_c0')))} мм)", None),
            ("Наклон по северу c1, мм/км", f"{K('c1_mmkm', fx(d.c1 * 1e6, 3))} (СКО {K('s_c1_mmkm', fx(None if 's_c1' not in sg else sg['s_c1'] * 1e6, 3))})", None),
            ("Наклон по востоку c2, мм/км", f"{K('c2_mmkm', fx(d.c2 * 1e6, 3))} (СКО {K('s_c2_mmkm', fx(None if 's_c2' not in sg else sg['s_c2'] * 1e6, 3))})", None),
        ]
    g = d.geoid
    if g is not None:
        hrows += [("Сетка геоида", esc(g.file), "geoid_file"),
                  ("SHA-256 сетки", K("geoid_sha256", esc(g.sha256), cls="mono"), None),
                  ("Интерполяция", "билинейная" if g.interpolation == "bilinear" else "бикубическая", "geoid_interp")]
    o.append(_kv(hrows) + "</section>")

    # --- 3. точность ---
    o.append("<section><h2>3. Точность</h2>")
    o.append(_kv([
        ("СКО в плане (радиальная) / по высоте, мм", f"{K('rms_plan_mm2', mm(d.rms_plan))} / {K('rms_height_mm2', mm(d.rms_height))}", None),
        ("Избыточность: план / высота", f"{K('redundancy_plan', fx_int(d.redundancy_plan))} / "
                                        f"{K('redundancy_height', fx_int(d.redundancy_height))}", None),
        ("СКО единицы веса s0 (апостериори, на координату): план / высота, мм",
         f"{K('s0_plan_mm', mm(d.s0_plan))} / {K('s0_height_mm', mm(d.s0_height))}", None),
    ]))
    lim = d.w_limit if d.w_limit is not None else float("inf")
    rows = []
    for i, r in enumerate(res):
        if r.use == "none":
            continue
        bp = r.w_plan is not None and r.w_plan > lim
        bh = r.wH is not None and abs(r.wH) > lim
        rows.append(_row([
            _td(None, str(i + 1)), _td(f"r{i}.name", esc(r.name)), _td(None, USE_TEXT.get(r.use, esc(r.use)), "l nw"),
            _td(f"r{i}.dx", mm(r.dx), "bad" if bp else ""), _td(f"r{i}.dy", mm(r.dy), "bad" if bp else ""),
            _td(f"r{i}.dp", mm(math.hypot(r.dx, r.dy)), "bad" if bp else ""), _td(f"r{i}.dH", mm(r.dH), "bad" if bh else ""),
            _td(f"r{i}.wp", fx(r.w_plan, 2), "bad" if bp else ""),
            _td(f"r{i}.wH", fx(None if r.wH is None else abs(r.wH), 2), "bad" if bh else ""),
            _td(f"r{i}.loop", mm(r.loo_plan)), _td(f"r{i}.looH", mm(None if r.loo_dH is None else abs(r.loo_dH))),
            _td(f"r{i}.flag", "⚠ подозрение" if r.suspect else "", "flag l"),
        ], "sus" if r.suspect else ""))
    o.append("<h3>3.1. Невязки на опорных пунктах</h3>")
    o.append(_table(["№", "Пункт", "Исп.", "dx, мм", "dy, мм", "Δплан, мм", "dH, мм", "|w| план", "|w| выс.",
                     "Без точки: план, мм", "Без точки: |dH|, мм", "Отметка"], rows, "data")
             if rows else '<p class="hint">Опорных пунктов нет.</p>')
    o.append(f'<p class="hint">|w| — нормированная поправка (тест Баарда), план — max(|wx|, |wy|); порог {fx(d.w_limit, 2)} '
             "(α ≈ 0.001): выше — вероятна грубая ошибка («⚠», точки автоматически не исключаются). «Без точки» — "
             "ошибка прогноза в точке датумом, рассчитанным без неё (leave-one-out); «—» — проверить нельзя.</p>")

    o.append("<h3>3.2. Контрольные пункты</h3>")
    if not ctl:
        o.append('<p class="hint">Контрольных пунктов (use = none) нет — независимой проверки датума нет.</p>')
    else:
        q = None
        if pairs is not None:
            B = np.array([pairs[i].B for i, _ in ctl])
            L = np.array([pairs[i].L for i, _ in ctl])
            q = d.quality_wgs(B, L)
        rows = []
        for k, (i, r) in enumerate(ctl):
            bp = r.w_plan is not None and r.w_plan > lim
            bh = r.wH is not None and abs(r.wH) > lim
            out, mp, mh = (None, None, None) if q is None else (float(q[0][k]), float(q[1][k]), float(q[2][k]))
            rows.append(_row([
                _td(None, str(i + 1)), _td(f"c{i}.name", esc(r.name)),
                _td(f"c{i}.dx", mm(r.dx), "bad" if bp else ""), _td(f"c{i}.dy", mm(r.dy), "bad" if bp else ""),
                _td(f"c{i}.dp", mm(math.hypot(r.dx, r.dy)), "bad" if bp else ""), _td(f"c{i}.dH", mm(r.dH), "bad" if bh else ""),
                _td(f"c{i}.wp", fx(r.w_plan, 2), "bad" if bp else ""),
                _td(f"c{i}.wH", fx(None if r.wH is None else abs(r.wH), 2), "bad" if bh else ""),
                _td(f"c{i}.mp", mm(mp)), _td(f"c{i}.mH", mm(mh)),
                _td(f"c{i}.out", fx(out, 1)),
                _td(f"c{i}.flag", "⚠ превышение" if r.suspect else "норма", "flag l"),
            ], "sus" if r.suspect else ""))
        o.append(_table(["№", "Пункт", "dx, мм", "dy, мм", "Δплан, мм", "dH, мм", "|w| план", "|w| выс.",
                         "СКО прогноза план, мм", "СКО прогноза H, мм", "Вне оболочки, м", "Оценка"], rows, "data"))
        o.append('<p class="hint">Для контрольных пунктов невязка — ошибка прогноза датума; |w| — она же, нормированная '
                 "по ожидаемой СКО (σ0 точки и прогноза); «Вне оболочки» — расстояние до выпуклой оболочки опорных пунктов "
                 "(0 — внутри, иначе экстраполяция). СКО прогноза — по априорной σ0.</p>")
    o.append("</section>")

    # --- 4. предупреждения ---
    o.append("<section><h2>4. Предупреждения</h2>")
    if d.warnings or notes:
        o.append('<ul class="warn" data-k="warnings">' + "".join(f"<li>{esc(w.message)}</li>" for w in d.warnings)
                 + "".join(f"<li>{esc(t)}</li>" for t in notes) + "</ul>")
    else:
        o.append('<p data-k="warnings">Предупреждений нет.</p>')
    o.append("</section>")

    # --- 5. схема ---
    o.append('<section class="newpage"><h2>5. Схема расположения пунктов</h2>')
    if pairs is None:
        o.append('<p class="hint">Схема не построена: нет координат пунктов (исходных пар).</p>')
    else:
        o.append("<figure>" + scheme_svg(d, pairs) + "<figcaption>Местная система: x — север (вверх), y — восток. "
                 "Векторы — невязки в плане (каталог − вычисленное) в увеличенном масштабе; фон — ожидаемая СКО "
                 "прогноза в плане по априорной σ0 (растёт при удалении от опорных пунктов и за оболочкой).</figcaption></figure>")
    o.append("</section>")

    # --- 6. экспорт ---
    o.append(export_section(d))

    # --- подписи ---
    o.append('<table class="sign"><tbody>'
             f"<tr><th>Исполнитель</th><td>_______________ / {_opt(m and m.author)} /</td><td>Дата: ____________</td></tr>"
             "<tr><th>Проверил</th><td>_______________ / ____________________ /</td><td>Дата: ____________</td></tr>"
             "</tbody></table>")
    o.append(f'<div class="foot">Датум {_opt(m and m.datum_id)}; SHA-256 исходных данных {_opt(m and m.inputs_sha256)}. '
             f"Отчёт сформирован {esc(gen)} ({esc(library)}).</div>")
    o.append("</div></body></html>\n")
    return "\n".join(o)


def fx_int(v) -> str:
    return "—" if v is None else str(int(v))


def export_section(d) -> str:
    o = ['<section class="newpage"><h2>6. Экспорт датума</h2>',
         '<p class="hint">Датум можно передать в ПО командой <code>python -m mathdatum export datum.json --format …</code> '
         "(или кнопками веб-приложения). Ограничения форматов и оценки по объекту:</p>"]
    desc = {
        "wkt2": ("WKT2 (ISO 19162:2019)", "План — стандартные методы EPSG (TM + подобие EPSG 9621; при развороте "
                 "< 0.1 мм на объекте — обычный PROJCRS). Высота — «PROJ-based operation method»: применит только ПО на "
                 "PROJ ≥ 6 (QGIS, GDAL, pyproj)."),
        "projjson": ("PROJJSON", "То же, что WKT2, в JSON (схема PROJ 0.7)."),
        "jxl": ("Trimble JobXML 6.30", "TM с масштабом подобия, горизонтальная корректировка (разворот вокруг tx, ty), "
                "вертикальная — наклонная плоскость / геоид и плоскость. Знак разворота — по документации Trimble."),
        "landxml": ("LandXML 1.2", "Параметров локализации в схеме нет: WKT2 передаётся строкой в ogcWktCode."),
        "proj": ("Строка PROJ", "Пайплайн для cs2cs / pyproj / QGIS — точно."),
    }
    rows = []
    for f in export_mod.FORMATS:
        name, text = desc[f]
        try:
            w = export_mod.export(d, f).warnings
        except export_mod.ExportError as e:
            w = [f"Экспорт невозможен: {e}"]
        items = "".join(f"<li>{esc(x)}</li>" for x in w)
        rows.append(_row([_td(None, f"<b>{name}</b>", "l"),
                          _td(f"export.{f}", esc(text) + (f'<ul class="warn">{items}</ul>' if items else ""), "l")]))
    o.append(_table(["Формат", "Ограничения и оценки по объекту"], rows, "data exp"))
    o.append('<p class="hint">Закрытые форматы (Trimble .cal/.dc, Topcon .gc3/.tp3, Carlson .loc, Leica HeXML, gsimath) '
             "не поддерживаются — что нужно для их поддержки, см. docs/export.md.</p>")

    th = math.degrees(math.atan2(d.b, d.a)) * 3600
    o.append('<div class="alert" data-k="jxl_alert"><b>ВНИМАНИЕ (Trimble JobXML).</b> Знак разворота в JobXML не '
             "подтверждён на контроллере: он взят по Trimble Access Calculations Reference, образца JobXML с калибровкой "
             f"в открытом доступе нет. Разворот датума {fx(th, 3)}″. Перед работой введите на контроллере B, L "
             "контрольных точек из таблицы ниже и сравните полученные x, y. Совпали x, y — экспорт верен; совпали x′, y′ "
             "(обратный знак разворота) — файл JobXML не использовать."
             + (" Разворот равен 0 — знак на результат не влияет, проверка всё равно рекомендуется." if d.b == 0 else "")
             + "</div>")
    try:
        cp, cf = export_mod.check_points(d), export_mod.check_points(d, -1)
    except Exception as e:   # нестандартный эллипсоид
        o.append(f'<p class="hint">Контрольные точки не вычислены: {esc(e)}</p>')
        cp, cf = [], []
    if cp:
        rows = []
        for k, ((n, B, L, x, y), (*_, x2, y2)) in enumerate(zip(cp, cf)):
            rows.append(_row([_td(f"chk{k}.name", esc(n), "l"), _td(f"chk{k}.B", fx(B, 10)), _td(f"chk{k}.L", fx(L, 10)),
                              _td(f"chk{k}.x", fx(x, 3)), _td(f"chk{k}.y", fx(y, 3)),
                              _td(f"chk{k}.x2", fx(x2, 3)), _td(f"chk{k}.y2", fx(y2, 3))]))
        o.append(_table(["Точка", "B, °", "L, °", "x, м", "y, м", "x′, м", "y′, м"], rows, "data"))
        o.append('<p class="hint">C — центроид опорных пунктов, V1… — вершины их выпуклой оболочки; B, L — в системе ГНСС '
                 "датума; x, y — по датуму; x′, y′ — что покажет контроллер при обратной трактовке знака разворота.</p>")
    o.append(f'<h3>Строка PROJ (ГНСС → местная)</h3><p class="mono">{esc(d.to_proj_pipeline())}</p></section>')
    return "".join(o)
