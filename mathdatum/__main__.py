"""Командная строка.

  python -m mathdatum localize pairs.csv -o datum.json
      Рассчитать локализацию по парам точек и сохранить датум; печатает отчёт.

      Параметры надёжности: --sigma-plan 0.02 --sigma-height 0.03 (априорные СКО, м),
      --w-limit 3.29 (порог теста Баарда), --max-scale-ppm 200, --max-rotation-deg 3;
      σ точки из столбцов sigma_plan / sigma_height даёт вес p = σ0² / σi² (пусто — p = 1).
      --suggest — дополнительно предложить, какие точки исключить (итеративно, по худшему |w|).
      --gnss-datum PZ-90.11 — система ГНСС-координат пар (по умолчанию WGS-84); рабочая проекция
      строится на её эллипсоиде, система сохраняется в датуме.
      --height-model plane | geoid | geoid_plane, --geoid сетка.gtx|.isg|.tif [--geoid-interpolation bicubic]:
      высота по модели геоида H = h − N(B, L) + c0 (geoid) или с остаточной плоскостью (geoid_plane;
      по умолчанию при --geoid). В датуме — ссылка на сетку (имя файла и SHA-256), не сама сетка.
      --projection ldp.json [--zone 2] | tm:lon0=..,lat0=..,k0=..,x0=..,y0=.. — своя рабочая проекция
      (например, спроектированная командой ldp: масштаб подобия остаётся ≈ 1).

  python -m mathdatum to-local datum.json wgs.csv -o local.csv [--quality]
      Пересчитать точки name;B;L;h → name;x;y;H.

  python -m mathdatum to-wgs datum.json local.csv -o wgs.csv [--quality]
      Пересчитать точки name;x;y;H → name;B;L;h.

  Датум с моделью геоида ищет сетку рядом с JSON или в текущем каталоге; --geoid файл — явно.
  Нет файла или другая SHA-256, точка вне сетки или в ячейке NODATA — ошибка (без тихого отключения поправки).
  --height-model — проверка: модель датума должна совпадать.
  --gnss-datum X — точки B;L;h заданы (to-local) или нужны (to-wgs) в системе X, а не в системе
  датума: пересчёт по 7 параметрам ГОСТ 32453-2017.
  Точки вне выпуклой оболочки опорных пунктов (экстраполяция) перечисляются в stderr.
  --quality добавляет столбцы outside_m (расстояние до оболочки, 0 — внутри), m_plan, m_H
  (ожидаемая СКО прогноза по априорной точности, м). Без флага формат файла прежний.

  python -m mathdatum proj datum.json
      Напечатать строку PROJ (WGS-84 → местная) для QGIS / cs2cs / pyproj.

  python -m mathdatum export datum.json --format wkt2|projjson|jxl|landxml|proj [-o файл] [--name Имя]
      Экспорт датума: WKT2 / PROJJSON (QGIS, GDAL, pyproj), Trimble JobXML, LandXML 1.2, строка PROJ.
      Ограничения и оценки погрешности по объекту — в stderr; для jxl — контрольные точки (B, L → x, y)
      для проверки на контроллере. --geoid-file — имя сетки в файле (по умолчанию из датума; GGF/ISG →
      .gtx для PROJ). Закрытые форматы (cal, dc, gc3, tp3, loc, hexml) — ошибка со ссылкой на docs/export.md.

  python -m mathdatum transform points.csv -o out.csv --from SK-42 --to WGS-84 [--in gk] [--out-format blh]
      Пересчёт между системами по ГОСТ 32453-2017 (цепочка по графу параметров).
      Форматы (--in, --out-format): blh — name;B;L;h (градусы, геодезическая высота),
      xyz — name;X;Y;Z, gk — name;x;y;H (Гаусс–Крюгер 6°, y с номером зоны; gk:7 — зона 7),
      tm:lon0=38.5,x0=-5000000,y0=1250000[,k0=1][,lat0=0] — поперечный Меркатор с параметрами.
      H плоских форматов — геодезическая высота; если известна только нормальная, план
      искажается на ~ζ·2e-5 (ζ — аномалия высоты, ~0.5 мм при ζ = 25 м).
      --epoch 2005.0 [--target-epoch 2013.9] и столбцы VX;VY;VZ (м/год) — перенос эпохи по ГОСТ.

  python -m mathdatum systems
      Системы координат и параметры ГОСТ 32453-2017.

  python -m mathdatum ldp contour.csv|.geojson --height 500 [--tolerance 20] [-o ldp.json] [--map map.csv]
      Проектирование малоискажающей проекции (LDP) под объект: δ = k·R/(R + h) − 1 → 0.
      Контур: CSV name;B;L[;h|;H] (полигон, если первая вершина = последней, иначе трасса; --kind) или GeoJSON.
      Высоты: --height (средняя), столбец h/H вершин или --dem сетка рельефа (.gtx/.ggf/.isg/.tif);
      --height-type normal --geoid сетка — нормальные высоты → эллипсоидальные (h = H + N).
      --datum GSK-2011 (по умолчанию), --type tm | omerc | auto, --criterion minimax | rms, --step м,
      --lon0/--lat0/--k0/--x0/--y0 — задать вместо подбора, --round-angle 1 (′), --round-k0 1e-6.
      Печатает параметры, статистику (min/max/mean/RMS, доля в допуске), сравнение с ГК 6° и UTM, зоны;
      -o — JSON проекции; --map файл.csv (сетка значений) и/или --map файл.geojson (изолинии) — карта искажений.

  python -m mathdatum geoid grid.tif [--at 55.75,37.62] [--points pts.csv -o out.csv]
                                      [--crop 55,56,37,39 -o site.gtx]
      Сведения о сетке геоида, N в точке (точках name;B;L → name;B;L;N), вырезка / перевод в .gtx или .isg.
"""

import argparse
import sys

import numpy as np

from . import datums, export as export_mod, geoid as geoid_mod, ldp as ldp_mod
from .io import read_columns, read_pairs, read_points, write_points
from .localization import LocalizationDatum, LocalizationError, localize, suggest_exclusions

OUTSIDE_TOL = 1e-3  # м: точка дальше от оболочки опорных пунктов — экстраполяция


def report(d: LocalizationDatum) -> str:
    lines = []
    if d.gnss_system not in (None, "WGS-84"):
        s = datums.get_system(d.gnss_system)
        lines.append(f"ГНСС:   {s.name}, рабочая проекция на эллипсоиде {s.ellipsoid.name} ({d.ellipsoid})")
    g = d.geoid
    if (d.k0, d.x0, d.y0) != (1.0, 0.0, 0.0):
        lines.append(f"Рабочая проекция задана: {d.projection}")
    lines += [
        f"План:   модель {d.plan_model}; масштаб {d.scale:.9f} ({d.scale_ppm:+.2f} ppm), "
        f"разворот {d.rotation_arcsec:+.2f}″",
        f"Высота: модель {d.height_model}; c0 = {d.c0:+.4f} м, "
        f"наклон N {d.c1 * 1e6:+.2f} мм/км, E {d.c2 * 1e6:+.2f} мм/км"
        + ("" if g is None else " (после геоида: H = h − N + …)"),
    ]
    if g is not None:
        lines.append(f"Геоид:  сетка {g.file}, интерполяция {g.interpolation}, sha256 {g.sha256}")
    lines += [
        f"СКО:    план {fmt(d.rms_plan)} м, высота {fmt(d.rms_height)} м",
    ]
    if d.redundancy_plan is not None:
        lines.append(f"Избыточность: план {d.redundancy_plan}, высота {fmt(d.redundancy_height, 'd')}; "
                     f"СКО ед. веса (на координату): план {fmt(d.s0_plan)} м "
                     f"(априори {fmt(d.sigma0_plan)}), высота {fmt(d.s0_height)} м (априори {fmt(d.sigma0_height)})")
    weighted = d.weighted
    lines += [
        "",
        f"{'точка':<12}{'use':<8}{'dx, м':>10}{'dy, м':>10}{'dH, м':>10}"
        + (f"{'σ план':>9}{'σ выс':>8}" if weighted else "")
        + f"{'|w|план':>9}{'|w|выс':>8}{'LOO план':>10}{'LOO dH':>9}",
    ]
    for r in d.residuals:
        mark = ("  !" if r.suspect else "") + ("" if r.use != "none" else "  (контроль)")
        sig = f"{fmt(r.sigma_plan):>9}{fmt(r.sigma_height):>8}" if weighted else ""
        lines.append(f"{r.name:<12}{r.use:<8}{r.dx:>10.4f}{r.dy:>10.4f}{r.dH:>10.4f}{sig}"
                     f"{fmt(r.w_plan, '.2f'):>9}{fmt(None if r.wH is None else abs(r.wH), '.2f'):>8}"
                     f"{fmt(r.loo_plan):>10}{fmt(r.loo_dH):>9}{mark}")
    if d.redundancy_plan is not None:
        lines.append(f"|w| — нормированная поправка (тест Баарда, порог {fmt(d.w_limit, 'g')}, «!» — подозрение); "
                     "LOO — ошибка прогноза без точки, м; «—» — нельзя проверить."
                     + (" σ — априорная СКО точки, м (вес p = σ0² / σ²)." if weighted else ""))
    if d.warnings:
        lines += ["", "Предупреждения:"] + [f"  - {w.message}" for w in d.warnings]
    return "\n".join(lines)


def fmt(v, spec=".4f"):
    return "—" if v is None else format(v, spec)


def load_datum(a, require_geoid=True) -> LocalizationDatum:
    d = LocalizationDatum.load(a.datum, geoid=getattr(a, "geoid", None), require_geoid=require_geoid)
    want = getattr(a, "height_model", None)
    if want is not None:
        # geoid_plane при малом числе точек упрощается до geoid — это та же модель.
        ok = (d.geoid is None if want == "plane" else
              d.geoid is not None and (want == "geoid_plane" or d.height_model != "geoid_plane"))
        if not ok:
            raise ValueError(f"--height-model {want}: в датуме модель высоты {d.height_model}"
                             + (f" (сетка {d.geoid.file})" if d.geoid else "") + ".")
    return d


def export_cmd(a) -> None:
    try:
        d = load_datum(a)
    except geoid_mod.GeoidError:
        d = load_datum(a, require_geoid=False)   # без сетки: файл пишется, оценки по сетке не считаются
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    r = export_mod.export(d, a.format, name=a.name, geoid_file=a.geoid_file, timestamp=ts)
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(r.text)
        print(f"Записано: {a.out} ({a.format})", file=sys.stderr)
    else:
        sys.stdout.write(r.text)
    for w in r.warnings:
        print(f"Внимание: {w}", file=sys.stderr)
    if a.format == "jxl" and d.b != 0:
        print("Контрольные точки (ввести B, L на контроллере и сравнить x, y; x′, y′ — при обратном знаке разворота):",
              file=sys.stderr)
        for (n, B, L, x, y), (*_, x2, y2) in zip(export_mod.check_points(d), export_mod.check_points(d, -1)):
            print(f"  {n}: B = {B:.9f}, L = {L:.9f} → x = {x:.3f}, y = {y:.3f}   (x′ = {x2:.3f}, y′ = {y2:.3f})",
                  file=sys.stderr)


def geoid_cmd(a) -> None:
    g = geoid_mod.read_grid(a.grid)
    print(g.describe())
    interp = a.interpolation
    if a.at:
        B, L = (float(v) for v in a.at.split(","))
        print(f"N({B:g}, {L:g}) = {g.value(B, L, interp):.4f} м ({interp})")
    if a.points:
        if not a.out:
            raise ValueError("--points: нужен -o файл.csv")
        names, (B, L) = read_columns(a.points, ("B", "L"))
        write_points(a.out, names, ("B", "L", "N"), B, L, g.value(B, L, interp), digits=(10, 10, 4))
        print(f"Точек: {len(names)} → {a.out}")
    elif a.out:
        if a.crop:
            s, n, w, e = (float(v) for v in a.crop.split(","))
            g = g.crop(s, n, w, e)
        g.save(a.out)
        print(f"Сетка {g.rows}×{g.cols} → {a.out} (sha256 {geoid_mod.sha256_file(a.out)})")


def _transform(d: LocalizationDatum, a, src, dst, digits, forward: bool):
    names, p, q, r = read_points(a.points, src)
    if a.gnss_datum:
        _note_datum(d, a.gnss_datum)
    if forward:
        p, q, r = d._from_system(p, q, r, a.gnss_datum)   # → система датума
        res = d.to_local(p, q, r)
        out, m_plan, m_h = d.quality_wgs(p, q)
    else:
        res = d.to_wgs(p, q, r, a.gnss_datum)
        out, m_plan, m_h = d.quality_local(p, q)
    cols, extra = dst, ()
    if a.quality:
        cols, extra = dst + ("outside_m", "m_plan", "m_H"), (out, m_plan, m_h)
    write_points(a.out, names, cols, *res, *extra, digits=digits + (3, 4, 4))
    if d.plan_hull is None:
        print("Внимание: в датуме нет сведений о надёжности (старый формат) — экстраполяция не проверяется; "
              "пересчитайте датум командой localize.", file=sys.stderr)
    far = [f"{n} ({o:.0f} м)" for n, o in zip(names, out) if o > OUTSIDE_TOL]
    if far:
        print(f"Внимание: {len(far)} из {len(names)} точек вне выпуклой оболочки опорных пунктов "
              f"(экстраполяция, точность падает): " + ", ".join(far), file=sys.stderr)


def _note_datum(d: LocalizationDatum, system: str) -> None:
    own = d.gnss_system
    if own is not None and datums.get_system(system).id != own:
        print(f"Пересчёт по ГОСТ 32453-2017: {datums.describe_path(datums.find_path(system, own))}", file=sys.stderr)


FORMAT_COLUMNS = {"blh": ("B", "L", "h"), "xyz": ("X", "Y", "Z"), "gk": ("x", "y", "H"), "tm": ("x", "y", "H")}
FORMAT_DIGITS = {"blh": (10, 10, 4), "xyz": (4, 4, 4), "gk": (4, 4, 4), "tm": (4, 4, 4)}


def parse_format(spec: str):
    """blh | xyz | gk | gk:<зона> | tm:lon0=..,x0=..,y0=..,k0=..,lat0=.. → (вид, параметры)."""
    kind, _, rest = spec.strip().lower().partition(":")
    if kind not in FORMAT_COLUMNS:
        raise ValueError(f"Формат «{spec}»: ожидается blh, xyz, gk[:зона] или tm:lon0=…")
    if kind == "gk":
        return kind, {"zone": int(rest)} if rest else {}
    if kind == "tm":
        kw = {}
        for item in filter(None, rest.split(",")):
            k, _, v = item.partition("=")
            if k.strip() not in ("lon0", "lat0", "k0", "x0", "y0"):
                raise ValueError(f"tm: неизвестный параметр «{k}» (есть lon0, lat0, k0, x0, y0)")
            kw[k.strip()] = float(v)
        if "lon0" not in kw:
            raise ValueError("tm: нужен осевой меридиан lon0=…")
        return kind, kw
    if rest:
        raise ValueError(f"Формат «{spec}»: у {kind} нет параметров")
    return kind, {}


def to_xyz(fmt, a, b, c, system):
    """Значения столбцов формата → геоцентрические XYZ (n, 3) в system."""
    kind, kw = fmt
    if kind == "xyz":
        return np.column_stack([a, b, c])
    if kind == "gk":
        a, b = datums.gk_inverse(a, b, system, **kw)
    elif kind == "tm":
        a, b = datums.TransverseMercator(system, **kw).inverse(a, b)
    return np.column_stack(datums.blh_to_xyz(a, b, c, system))


def from_xyz(fmt, xyz, system):
    kind, kw = fmt
    if kind == "xyz":
        return xyz[:, 0], xyz[:, 1], xyz[:, 2]
    B, L, h = datums.xyz_to_blh(xyz[:, 0], xyz[:, 1], xyz[:, 2], system)
    if kind == "gk":
        return (*datums.gk_forward(B, L, system, **kw), h)
    if kind == "tm":
        return (*datums.TransverseMercator(system, **kw).forward(B, L), h)
    return B, L, h


def transform_file(a) -> None:
    src, dst = datums.get_system(a.src), datums.get_system(a.dst)
    fin, fout = parse_format(a.fmt_in), parse_format(a.fmt_out)
    names, cols = read_columns(a.points, FORMAT_COLUMNS[fin[0]], ("VX", "VY", "VZ"))
    vel = cols[3:]
    if a.epoch is None and a.target_epoch is not None:
        raise ValueError("--target-epoch требует --epoch.")
    velocity = None
    if a.epoch is not None:
        if any(v is None for v in vel):
            raise ValueError("--epoch: нужны столбцы скорости пункта VX;VY;VZ (м/год).")
        velocity = np.column_stack(vel)
    xyz = to_xyz(fin, *cols[:3], src)
    path = datums.find_path(src, dst)
    out = datums.transform_xyz(xyz, src, dst, epoch=a.epoch, velocity=velocity, target_epoch=a.target_epoch)
    write_points(a.out, names, FORMAT_COLUMNS[fout[0]], *from_xyz(fout, out, dst), digits=FORMAT_DIGITS[fout[0]])
    print(f"Точек: {len(names)}; {src.name} → {dst.name}: {datums.describe_path(path)}", file=sys.stderr)


def ldp_cmd(a) -> None:
    contour = ldp_mod.read_contour(a.contour, a.kind)
    heights = ldp_mod.Heights(constant=a.height, dem=a.dem, geoid=a.geoid, height_type=a.height_type)
    opt = ldp_mod.FitOptions(round_angle=a.round_angle, round_k0=a.round_k0, lon0=a.lon0, lat0=a.lat0, k0=a.k0,
                             x0=a.x0, y0=a.y0)
    r = ldp_mod.design(contour, heights, datum=a.datum, tolerance=a.tolerance, criterion=a.criterion, type=a.type,
                       step=a.step, options=opt)
    print(r.report())
    r.save(a.out)
    print(f"\nПроекция сохранена: {a.out}")
    for path in a.map or []:
        m = r.distortion_map(a.map_size)
        if path.lower().endswith((".geojson", ".json")):
            m.to_geojson(path)
        else:
            m.to_csv(path)
        print(f"Карта искажений ({m.ppm.shape[0]}×{m.ppm.shape[1]} узлов): {path}")


def work_projection(spec: str, zone, system):
    """--projection: файл ldp (JSON) или tm:lon0=…,k0=… на эллипсоиде системы ГНСС."""
    if spec.lower().startswith("tm:"):
        return datums.TransverseMercator(datums.get_system(system), **parse_format(spec)[1])
    return ldp_mod.load_projection(spec, zone)


def systems_report() -> str:
    lines = ["Системы координат:"]
    for s in datums.SYSTEMS.values():
        e = s.ellipsoid
        lines.append(f"  {s.id:<10} {s.name:<16} эллипсоид {e.name} (a = {e.a:.1f}, 1/f = {e.rf!r})"
                     + ("; зоны Гаусса–Крюгера 6°" if s.gk_zones else ""))
    lines += ["", "Параметры ГОСТ 32453-2017 (ΔX ΔY ΔZ, м; ωx ωy ωz, ″; m, ppm; поворот системы координат):"]
    for t in datums.TRANSFORMATIONS:
        lines.append(f"  {t.source:<4} {datums.SYSTEMS[t.src].name:>14} → {datums.SYSTEMS[t.dst].name:<10}"
                     f"{t.dX:9.3f}{t.dY:9.3f}{t.dZ:9.3f}  {t.wx:+.6f} {t.wy:+.6f} {t.wz:+.6f}  {t.m:+.4f}"
                     + (f"  эпоха {t.epoch:g}" if t.epoch else ""))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m mathdatum", description="Локализация ГНСС и пересчёты.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("localize", help="рассчитать датум по парам точек")
    p.add_argument("pairs")
    p.add_argument("-o", "--out", default="datum.json")
    p.add_argument("--sigma-plan", type=float, default=0.02,
                   help="априорная СКО координаты в плане (единицы веса и для точек без sigma_plan), м")
    p.add_argument("--sigma-height", type=float, default=0.03,
                   help="априорная СКО высоты (единицы веса и для точек без sigma_height), м")
    p.add_argument("--w-limit", type=float, default=3.29, help="порог нормированной поправки")
    p.add_argument("--max-scale-ppm", type=float, default=200.0)
    p.add_argument("--max-rotation-deg", type=float, default=3.0)
    p.add_argument("--suggest", action="store_true", help="предложить точки к исключению")
    p.add_argument("--gnss-datum", default="WGS-84", help="система ГНСС-координат пар (WGS-84, PZ-90.11, GSK-2011, …)")
    p.add_argument("--height-model", choices=("plane", "geoid", "geoid_plane"),
                   help="модель высоты (по умолчанию plane, с --geoid — geoid_plane)")
    p.add_argument("--geoid", help="сетка высот геоида / аномалий высоты (.gtx, .isg, .tif)")
    p.add_argument("--geoid-interpolation", choices=geoid_mod.INTERPOLATIONS, default="bilinear")
    p.add_argument("--projection", help="рабочая проекция: JSON ldp или tm:lon0=…,lat0=…,k0=…,x0=…,y0=…")
    p.add_argument("--zone", type=int, help="зона из JSON ldp (1…n)")
    for name, cols in (("to-local", "B L h → x y H"), ("to-wgs", "x y H → B L h")):
        p = sub.add_parser(name, help=f"пересчёт {cols}")
        p.add_argument("datum")
        p.add_argument("points")
        p.add_argument("-o", "--out", required=True)
        p.add_argument("--quality", action="store_true",
                       help="добавить столбцы outside_m, m_plan, m_H")
        p.add_argument("--gnss-datum", help="система точек B;L;h, если не совпадает с системой датума")
        p.add_argument("--geoid", help="файл сетки геоида датума (если он не рядом с JSON)")
        p.add_argument("--height-model", choices=("plane", "geoid", "geoid_plane"),
                       help="проверить, что модель высоты датума такая")
    p = sub.add_parser("proj", help="строка PROJ для датума")
    p.add_argument("datum")
    p = sub.add_parser("export", help="экспорт датума: wkt2, projjson, jxl, landxml, proj")
    p.add_argument("datum")
    p.add_argument("--format", "-f", required=True,
                   help=f"{', '.join(export_mod.FORMATS)} (закрытые: {', '.join(export_mod.CLOSED)} — ошибка)")
    p.add_argument("-o", "--out", help="файл (по умолчанию — stdout)")
    p.add_argument("--name", default="Localization", help="имя системы в файле")
    p.add_argument("--geoid", help="файл сетки геоида датума (для оценок; если он не рядом с JSON)")
    p.add_argument("--geoid-file", help="имя сетки в экспорте (по умолчанию — из датума; GGF/ISG → .gtx)")
    p = sub.add_parser("transform", help="пересчёт точек между системами (ГОСТ 32453-2017)")
    p.add_argument("points")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--from", dest="src", required=True, help="исходная система (SK-42, SK-95, GSK-2011, PZ-90.11, …)")
    p.add_argument("--to", dest="dst", required=True, help="целевая система")
    p.add_argument("--in", dest="fmt_in", default="blh", help="формат входа: blh, xyz, gk[:зона], tm:lon0=…")
    p.add_argument("--out-format", "--out-fmt", dest="fmt_out", default="blh", help="формат выхода (как --in)")
    p.add_argument("--epoch", type=float, help="эпоха координат (год); нужны столбцы VX;VY;VZ")
    p.add_argument("--target-epoch", type=float, help="эпоха результата")
    sub.add_parser("systems", help="системы координат и параметры ГОСТ 32453-2017")
    p = sub.add_parser("ldp", help="проектирование малоискажающей проекции (LDP) под объект")
    p.add_argument("contour", help="контур: CSV name;B;L[;h|;H] или GeoJSON")
    p.add_argument("--kind", choices=ldp_mod.KINDS, help="polygon | polyline (по умолчанию — по файлу)")
    p.add_argument("--height", type=float, help="средняя высота объекта, м")
    p.add_argument("--height-type", choices=ldp_mod.HEIGHT_TYPES, default="ellipsoidal",
                   help="высоты --height, z GeoJSON и --dem: эллипсоидальные или нормальные (нужен --geoid)")
    p.add_argument("--dem", help="сетка высот рельефа (.gtx, .ggf, .isg, .tif)")
    p.add_argument("--geoid", help="сетка геоида для нормальных высот: h = H + N")
    p.add_argument("--datum", default=ldp_mod.DEFAULT_DATUM, help="система (эллипсоид) проекции, по умолчанию GSK-2011")
    p.add_argument("--tolerance", type=float, default=20.0, help="допуск |δ|, ppm (= мм/км)")
    p.add_argument("--criterion", choices=ldp_mod.CRITERIA, default="minimax")
    p.add_argument("--type", choices=ldp_mod.TYPES, default="auto")
    p.add_argument("--step", type=float, help="шаг выборки точек объекта, м")
    for k in ("lon0", "lat0", "k0", "x0", "y0"):
        p.add_argument(f"--{k}", type=float, help=f"задать {k} (не подбирать)")
    p.add_argument("--round-angle", type=float, default=1.0, help="округление L0, B0, азимута, угл. минуты (0 — нет)")
    p.add_argument("--round-k0", type=float, default=1e-6, help="округление k0 (0 — нет)")
    p.add_argument("-o", "--out", default="ldp.json")
    p.add_argument("--map", action="append", help="карта искажений: .csv (сетка) или .geojson (изолинии)")
    p.add_argument("--map-size", type=int, default=60, help="узлов по длинной стороне карты")
    p = sub.add_parser("geoid", help="сетка геоида: сведения, N в точках, вырезка / перевод формата")
    p.add_argument("grid")
    p.add_argument("--at", help="B,L — значение N в точке")
    p.add_argument("--points", help="CSV name;B;L → name;B;L;N (нужен -o)")
    p.add_argument("--crop", help="S,N,W,E — вырезать охват (градусы, с запасом 2 узла)")
    p.add_argument("-o", "--out", help="файл результата: .csv для --points, иначе .gtx или .isg")
    p.add_argument("--interpolation", choices=geoid_mod.INTERPOLATIONS, default="bilinear")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "localize":
            pairs = read_pairs(a.pairs)
            kw = dict(sigma_plan=a.sigma_plan, sigma_height=a.sigma_height, w_limit=a.w_limit,
                      max_scale_ppm=a.max_scale_ppm, max_rotation_deg=a.max_rotation_deg)
            kw["gnss_datum"] = a.gnss_datum
            if a.geoid:
                kw.update(height_model=a.height_model or "geoid_plane", geoid=geoid_mod.read_grid(a.geoid),
                          geoid_interpolation=a.geoid_interpolation)
            elif a.height_model not in (None, "plane"):
                raise ValueError(f"--height-model {a.height_model}: нужна сетка --geoid.")
            if a.projection:
                kw["projection"] = work_projection(a.projection, a.zone, a.gnss_datum)
            elif a.zone is not None:
                raise ValueError("--zone: нужен --projection ldp.json.")
            d = localize(pairs, **kw)
            d.save(a.out)
            print(report(d))
            if a.suggest:
                ex = suggest_exclusions(pairs, **kw)
                print("\nПредлагается исключить (по порядку): " + (
                    ", ".join(f"{n} ({'план' if part == 'plan' else 'высота'}, |w| = {w:.2f})" for n, part, w in ex)
                    if ex else "ничего — подозрительных точек нет."))
            print(f"\nДатум сохранён: {a.out}")
            if d.geoid is not None:
                print(f"Сетка геоида в датуме — только ссылкой ({d.geoid.file}): держите файл рядом с датумом "
                      "или указывайте --geoid при пересчётах.")
        elif a.cmd == "to-local":
            _transform(load_datum(a), a, ("B", "L", "h"), ("x", "y", "H"), (4, 4, 4), True)
        elif a.cmd == "to-wgs":
            _transform(load_datum(a), a, ("x", "y", "H"), ("B", "L", "h"), (10, 10, 4), False)
        elif a.cmd == "proj":
            print(load_datum(a, require_geoid=False).to_proj_pipeline())
        elif a.cmd == "export":
            export_cmd(a)
        elif a.cmd == "transform":
            transform_file(a)
        elif a.cmd == "systems":
            print(systems_report())
        elif a.cmd == "geoid":
            geoid_cmd(a)
        elif a.cmd == "ldp":
            ldp_cmd(a)
    except (LocalizationError, ValueError, KeyError, FileNotFoundError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
