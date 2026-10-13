"""Regional borders for the Russian MSK areas (Natural Earth 1:50m admin-1, simplified to 0.1 deg).

Writes docs/data/regions.js (polygons for the browser) and data/regions_bbox.json (boxes for build_web.py).
The MSK area of use is then region polygon (+25 km tolerance) intersected with the zone strip, instead of a circle around the capital.
"""
import json, pathlib, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "build/ne50_admin1.geojson"
URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_1_states_provinces.geojson"
ISO = {"RU-AD": "01", "RU-BA": "02", "RU-BU": "03", "RU-AL": "04", "RU-DA": "05", "RU-IN": "06", "RU-KB": "07", "RU-KL": "08", "RU-KC": "09",
       "RU-KR": "10", "RU-KO": "11", "RU-ME": "12", "RU-MO": "13", "RU-SA": "14", "RU-SE": "15", "RU-TA": "16", "RU-UD": "18", "RU-KK": "19",
       "RU-CE": "20", "RU-CU": "21", "RU-ALT": "22", "RU-KDA": "23", "RU-KYA": "24", "RU-PRI": "25", "RU-STA": "26", "RU-KHA": "27", "RU-AMU": "28",
       "RU-ARK": "29", "RU-AST": "30", "RU-BEL": "31", "RU-BRY": "32", "RU-VLA": "33", "RU-VGG": "34", "RU-VLG": "35", "RU-VOR": "36", "RU-IVA": "37",
       "RU-IRK": "38", "RU-KGD": "39", "RU-KLU": "40", "RU-KAM": "41", "RU-KEM": "42", "RU-KIR": "43", "RU-KOS": "44", "RU-KGN": "45", "RU-KRS": "46",
       "RU-LEN": "47", "RU-LIP": "48", "RU-MAG": "49", "RU-MUR": "51", "RU-NIZ": "52", "RU-NGR": "53", "RU-NVS": "54", "RU-OMS": "55", "RU-ORE": "56",
       "RU-ORL": "57", "RU-PNZ": "58", "RU-PER": "59", "RU-PSK": "60", "RU-ROS": "61", "RU-RYA": "62", "RU-SAM": "63", "RU-SAR": "64", "RU-SAK": "65",
       "RU-SVE": "66", "RU-SMO": "67", "RU-TAM": "68", "RU-TVE": "69", "RU-TOM": "70", "RU-TUL": "71", "RU-TYU": "72", "RU-ULY": "73", "RU-CHE": "74",
       "RU-ZAB": "75", "RU-YAR": "76", "RU-SPE": "78", "RU-NEN": "83", "RU-KHM": "86", "RU-CHU": "87", "RU-TY": "17", "RU-YAN": "89", "RU-YEV": "79",
       "UA-43": "90", "UA-40": "90"}
CROSS = {"87"}
NAME = {"Moskva": "77", "Moskovskaya": "50"}  # NE swaps the ISO codes of Moscow city and Moscow oblast; the names are right


def simplify(ring):
    pts, last = [], None
    for lon, lat in ring:
        q = (round(lon * 10), round(lat * 10))
        if q != last:
            pts.append(q); last = q
    return pts


def main():
    if not SRC.exists():
        urllib.request.urlretrieve(URL, SRC)
    out, boxes, seen = {}, {}, set()
    for f in json.load(open(SRC))["features"]:
        p = f["properties"]
        code = NAME.get(p.get("name")) or ISO.get(p.get("iso_3166_2"))
        if not code:
            continue
        seen.add(code)
        geom = f["geometry"]
        for poly in (geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]):
            ring = simplify(poly[0])
            if len(ring) < 4:
                continue
            out.setdefault(code, []).append([v for pt in ring for v in pt])
            lons = [pt[0] / 10 for pt in ring]; lats = [pt[1] / 10 for pt in ring]
            b = boxes.setdefault(code, [1e9, 1e9, -1e9, -1e9])
            if code in CROSS:  # Chukotka crosses the antimeridian: take the box in 0..360 space
                lons = [l % 360 for l in lons]
            boxes[code] = [min(b[0], min(lons)), min(b[1], min(lats)), max(b[2], max(lons)), max(b[3], max(lats))]
    for k, b in boxes.items():
        b[0] = ((b[0] + 180) % 360) - 180
        b[2] = ((b[2] + 180) % 360) - 180
        boxes[k] = [round(v, 2) for v in b]
    (ROOT / "data/regions_bbox.json").write_text(json.dumps(boxes, ensure_ascii=False, indent=0))
    js = "window.__REGIONS__=" + json.dumps(out, separators=(",", ":")) + ";\n"
    (ROOT / "docs/data/regions.js").write_text(js)
    print(f"regions {len(out)}; docs/data/regions.js {len(js)//1024} KB; boxes e.g. 50: {boxes.get('50')}, 18: {boxes.get('18')}, 87: {boxes.get('87')}")


if __name__ == "__main__":
    main()
