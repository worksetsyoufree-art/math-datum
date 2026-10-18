"""Выгрузка задач site_localization в текст для Java-обвязки.

sites.txt:    ISO C|K B L h x y H       (ГНСС B L h → местные x y H)
sites_ne.txt: ISO C|K N E h x y H       (рабочая проекция N E → местные x y H)

Запуск:  python tools/kotlin_check/export_sites.py <sites.txt> <sites_ne.txt>
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    geo, ne = [], []
    for f in sorted((ROOT / "data/geodetic/regions").glob("*.json")):
        case = json.loads(f.read_text(encoding="utf-8"))
        site = next(t for t in case["tasks"] if t["type"] == "site_localization")
        iso = case["region"]["iso_3166_2"]
        for kind, pts in (("C", site["control_points"]), ("K", site["check_points"])):
            for p in pts:
                b, l, h = p["gnss_B_L_h"]
                n, e = p["work_N_E"]
                x, y, H = p["local_x_y_H"]
                geo.append(f"{iso} {kind} {b!r} {l!r} {h!r} {x!r} {y!r} {H!r}")
                ne.append(f"{iso} {kind} {n!r} {e!r} {h!r} {x!r} {y!r} {H!r}")
    Path(sys.argv[1]).write_text("\n".join(geo) + "\n")
    Path(sys.argv[2]).write_text("\n".join(ne) + "\n")


if __name__ == "__main__":
    main()
