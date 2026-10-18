"""Командная строка.

  python -m mathdatum localize pairs.csv -o datum.json
      Рассчитать локализацию по парам точек и сохранить датум; печатает отчёт.

      Параметры надёжности: --sigma-plan 0.02 --sigma-height 0.03 (априорные СКО, м),
      --w-limit 3.29 (порог теста Баарда), --max-scale-ppm 200, --max-rotation-deg 1;
      --suggest — дополнительно предложить, какие точки исключить (итеративно, по худшему |w|).

  python -m mathdatum to-local datum.json wgs.csv -o local.csv [--quality]
      Пересчитать точки name;B;L;h → name;x;y;H.

  python -m mathdatum to-wgs datum.json local.csv -o wgs.csv [--quality]
      Пересчитать точки name;x;y;H → name;B;L;h.

  Точки вне выпуклой оболочки опорных пунктов (экстраполяция) перечисляются в stderr.
  --quality добавляет столбцы outside_m (расстояние до оболочки, 0 — внутри), m_plan, m_H
  (ожидаемая СКО прогноза по априорной точности, м). Без флага формат файла прежний.

  python -m mathdatum proj datum.json
      Напечатать строку PROJ (WGS-84 → местная) для QGIS / cs2cs / pyproj.
"""

import argparse
import sys

from .io import read_pairs, read_points, write_points
from .localization import LocalizationDatum, LocalizationError, localize, suggest_exclusions

OUTSIDE_TOL = 1e-3  # м: точка дальше от оболочки опорных пунктов — экстраполяция


def report(d: LocalizationDatum) -> str:
    lines = [
        f"План:   модель {d.plan_model}; масштаб {d.scale:.9f} ({d.scale_ppm:+.2f} ppm), "
        f"разворот {d.rotation_arcsec:+.2f}″",
        f"Высота: модель {d.height_model}; c0 = {d.c0:+.4f} м, "
        f"наклон N {d.c1 * 1e6:+.2f} мм/км, E {d.c2 * 1e6:+.2f} мм/км",
        f"СКО:    план {fmt(d.rms_plan)} м, высота {fmt(d.rms_height)} м",
    ]
    if d.redundancy_plan is not None:
        lines.append(f"Избыточность: план {d.redundancy_plan}, высота {fmt(d.redundancy_height, 'd')}; "
                     f"СКО ед. веса (на координату): план {fmt(d.s0_plan)} м "
                     f"(априори {fmt(d.sigma0_plan)}), высота {fmt(d.s0_height)} м (априори {fmt(d.sigma0_height)})")
    lines += [
        "",
        f"{'точка':<12}{'use':<8}{'dx, м':>10}{'dy, м':>10}{'dH, м':>10}"
        f"{'|w|план':>9}{'|w|выс':>8}{'LOO план':>10}{'LOO dH':>9}",
    ]
    for r in d.residuals:
        mark = ("  !" if r.suspect else "") + ("" if r.use != "none" else "  (контроль)")
        lines.append(f"{r.name:<12}{r.use:<8}{r.dx:>10.4f}{r.dy:>10.4f}{r.dH:>10.4f}"
                     f"{fmt(r.w_plan, '.2f'):>9}{fmt(None if r.wH is None else abs(r.wH), '.2f'):>8}"
                     f"{fmt(r.loo_plan):>10}{fmt(r.loo_dH):>9}{mark}")
    if d.redundancy_plan is not None:
        lines.append(f"|w| — нормированная поправка (тест Баарда, порог {fmt(d.w_limit, 'g')}, «!» — подозрение); "
                     "LOO — ошибка прогноза без точки, м; «—» — нельзя проверить.")
    if d.warnings:
        lines += ["", "Предупреждения:"] + [f"  - {w.message}" for w in d.warnings]
    return "\n".join(lines)


def fmt(v, spec=".4f"):
    return "—" if v is None else format(v, spec)


def _transform(d: LocalizationDatum, a, src, dst, digits, forward: bool):
    names, p, q, r = read_points(a.points, src)
    res = d.to_local(p, q, r) if forward else d.to_wgs(p, q, r)
    out, m_plan, m_h = d.quality_wgs(p, q) if forward else d.quality_local(p, q)
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


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m mathdatum", description="Локализация ГНСС и пересчёты.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("localize", help="рассчитать датум по парам точек")
    p.add_argument("pairs")
    p.add_argument("-o", "--out", default="datum.json")
    p.add_argument("--sigma-plan", type=float, default=0.02, help="априорная СКО координаты в плане, м")
    p.add_argument("--sigma-height", type=float, default=0.03, help="априорная СКО высоты, м")
    p.add_argument("--w-limit", type=float, default=3.29, help="порог нормированной поправки")
    p.add_argument("--max-scale-ppm", type=float, default=200.0)
    p.add_argument("--max-rotation-deg", type=float, default=1.0)
    p.add_argument("--suggest", action="store_true", help="предложить точки к исключению")
    for name, cols in (("to-local", "B L h → x y H"), ("to-wgs", "x y H → B L h")):
        p = sub.add_parser(name, help=f"пересчёт {cols}")
        p.add_argument("datum")
        p.add_argument("points")
        p.add_argument("-o", "--out", required=True)
        p.add_argument("--quality", action="store_true",
                       help="добавить столбцы outside_m, m_plan, m_H")
    p = sub.add_parser("proj", help="строка PROJ для датума")
    p.add_argument("datum")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "localize":
            pairs = read_pairs(a.pairs)
            kw = dict(sigma_plan=a.sigma_plan, sigma_height=a.sigma_height, w_limit=a.w_limit,
                      max_scale_ppm=a.max_scale_ppm, max_rotation_deg=a.max_rotation_deg)
            d = localize(pairs, **kw)
            d.save(a.out)
            print(report(d))
            if a.suggest:
                ex = suggest_exclusions(pairs, **kw)
                print("\nПредлагается исключить (по порядку): " + (
                    ", ".join(f"{n} ({'план' if part == 'plan' else 'высота'}, |w| = {w:.2f})" for n, part, w in ex)
                    if ex else "ничего — подозрительных точек нет."))
            print(f"\nДатум сохранён: {a.out}")
        elif a.cmd == "to-local":
            _transform(LocalizationDatum.load(a.datum), a, ("B", "L", "h"), ("x", "y", "H"), (4, 4, 4), True)
        elif a.cmd == "to-wgs":
            _transform(LocalizationDatum.load(a.datum), a, ("x", "y", "H"), ("B", "L", "h"), (10, 10, 4), False)
        elif a.cmd == "proj":
            print(LocalizationDatum.load(a.datum).to_proj_pipeline())
    except (LocalizationError, ValueError, KeyError, FileNotFoundError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
