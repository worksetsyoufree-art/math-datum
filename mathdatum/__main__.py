"""Командная строка.

  python -m mathdatum localize pairs.csv -o datum.json
      Рассчитать локализацию по парам точек и сохранить датум; печатает отчёт.

  python -m mathdatum to-local datum.json wgs.csv -o local.csv
      Пересчитать точки name;B;L;h → name;x;y;H.

  python -m mathdatum to-wgs datum.json local.csv -o wgs.csv
      Пересчитать точки name;x;y;H → name;B;L;h.

  python -m mathdatum proj datum.json
      Напечатать строку PROJ (WGS-84 → местная) для QGIS / cs2cs / pyproj.
"""

import argparse
import sys

from .io import read_pairs, read_points, write_points
from .localization import LocalizationDatum, LocalizationError, localize


def report(d: LocalizationDatum) -> str:
    lines = [
        f"План:   модель {d.plan_model}; масштаб {d.scale:.9f} ({d.scale_ppm:+.2f} ppm), "
        f"разворот {d.rotation_arcsec:+.2f}″",
        f"Высота: модель {d.height_model}; c0 = {d.c0:+.4f} м, "
        f"наклон N {d.c1 * 1e6:+.2f} мм/км, E {d.c2 * 1e6:+.2f} мм/км",
        f"СКО:    план {fmt(d.rms_plan)} м, высота {fmt(d.rms_height)} м",
        "",
        f"{'точка':<12}{'use':<8}{'dx, м':>10}{'dy, м':>10}{'dH, м':>10}",
    ]
    for r in d.residuals:
        mark = "" if r.use != "none" else "  (контроль)"
        lines.append(f"{r.name:<12}{r.use:<8}{r.dx:>10.4f}{r.dy:>10.4f}{r.dH:>10.4f}{mark}")
    return "\n".join(lines)


def fmt(v):
    return "—" if v is None else f"{v:.4f}"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m mathdatum", description="Локализация ГНСС и пересчёты.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("localize", help="рассчитать датум по парам точек")
    p.add_argument("pairs")
    p.add_argument("-o", "--out", default="datum.json")
    for name, cols in (("to-local", "B L h → x y H"), ("to-wgs", "x y H → B L h")):
        p = sub.add_parser(name, help=f"пересчёт {cols}")
        p.add_argument("datum")
        p.add_argument("points")
        p.add_argument("-o", "--out", required=True)
    p = sub.add_parser("proj", help="строка PROJ для датума")
    p.add_argument("datum")
    a = ap.parse_args(argv)

    try:
        if a.cmd == "localize":
            d = localize(read_pairs(a.pairs))
            d.save(a.out)
            print(report(d))
            print(f"\nДатум сохранён: {a.out}")
        elif a.cmd == "to-local":
            d = LocalizationDatum.load(a.datum)
            names, B, L, h = read_points(a.points, ("B", "L", "h"))
            write_points(a.out, names, ("x", "y", "H"), *d.to_local(B, L, h))
        elif a.cmd == "to-wgs":
            d = LocalizationDatum.load(a.datum)
            names, x, y, H = read_points(a.points, ("x", "y", "H"))
            write_points(a.out, names, ("B", "L", "h"), *d.to_wgs(x, y, H), digits=(10, 10, 4))
        elif a.cmd == "proj":
            print(LocalizationDatum.load(a.datum).to_proj_pipeline())
    except (LocalizationError, ValueError, KeyError, FileNotFoundError) as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
