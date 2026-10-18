"""Чтение и запись CSV с точками.

Разделитель — «;» или «,» (определяется автоматически), первая строка — заголовок.
Десятичный разделитель — точка; при разделителе полей «;» допускается и запятая.

Пары для локализации:   name;B;L;h;x;y;H[;use][;sigma_plan][;sigma_height]
   B, L — градусы WGS-84 (десятичные), h — эллипсоидальная высота, м;
   x — север, y — восток, H — местная высота, м;
   use — both (по умолчанию) | plan | height | none (точка только для контроля);
   sigma_plan, sigma_height — априорные СКО точки, м (план — на координату); пусто — глобальная σ.
Точки для пересчёта:    name;B;L;h  или  name;x;y;H
"""

from __future__ import annotations

import csv
from pathlib import Path

from .localization import USE_BOTH, Pair


def _rows(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    delim = ";" if text.splitlines()[0].count(";") >= text.splitlines()[0].count(",") else ","
    rows = list(csv.DictReader(text.splitlines(), delimiter=delim))
    return rows, delim


def _num(s: str, delim: str) -> float:
    s = s.strip().replace(" ", "")
    return float(s.replace(",", ".") if delim == ";" else s)


def read_pairs(path) -> list[Pair]:
    rows, d = _rows(path)
    pairs = []
    for i, r in enumerate(rows, 1):
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        try:
            pairs.append(Pair(
                name=r.get("name") or f"P{i}",
                B=_num(r["B"], d), L=_num(r["L"], d), h=_num(r["h"], d),
                x=_num(r["x"], d), y=_num(r["y"], d), H=_num(r["H"], d),
                use=(r.get("use") or USE_BOTH).lower(),
                sigma_plan=_num(r["sigma_plan"], d) if r.get("sigma_plan") else None,
                sigma_height=_num(r["sigma_height"], d) if r.get("sigma_height") else None,
            ))
        except (KeyError, ValueError) as e:
            raise ValueError(f"{path}: строка {i + 1}: {e}") from None
    return pairs


def read_points(path, columns: tuple[str, str, str]):
    rows, d = _rows(path)
    names, a, b, c = [], [], [], []
    for i, r in enumerate(rows, 1):
        r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
        names.append(r.get("name") or f"P{i}")
        a.append(_num(r[columns[0]], d))
        b.append(_num(r[columns[1]], d))
        c.append(_num(r[columns[2]], d))
    return names, a, b, c


def write_points(path, names, columns, *values, digits=(4, 4, 4)) -> None:
    """Пишет name и столбцы columns (значения — по массиву на столбец); nan → пустая ячейка."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["name", *columns])
        for n, *v in zip(names, *values):
            w.writerow([n] + ["" if x != x else f"{float(x):.{dg}f}" for x, dg in zip(v, digits)])
