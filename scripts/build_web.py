"""Pack the Russian MSK dataset for the web app: docs/data/ru.js

MSK area of use is not published as geometry, so it is approximated by a circle around the regional capital
(region) or around the city (city / district systems) and converted to a bounding box (heuristic, documented in the UI).
"""
import csv, datetime, json, math, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "docs/data"
OUT.mkdir(parents=True, exist_ok=True)

MISSING_REGIONS = {"17": ["Республика Тыва", "Tuva Republic"], "79": ["Еврейская автономная область", "Jewish Autonomous Oblast"],
                   "89": ["Ямало-Ненецкий автономный округ", "Yamalo-Nenets Autonomous Okrug"]}
REGION_EN = {
    "01": "Adygea", "02": "Bashkortostan", "03": "Buryatia", "04": "Altai Republic", "05": "Dagestan", "06": "Ingushetia",
    "07": "Kabardino-Balkaria", "08": "Kalmykia", "09": "Karachay-Cherkessia", "10": "Karelia", "11": "Komi", "12": "Mari El",
    "13": "Mordovia", "14": "Sakha (Yakutia)", "15": "North Ossetia-Alania", "16": "Tatarstan", "18": "Udmurtia",
    "19": "Khakassia", "20": "Chechnya", "21": "Chuvashia", "22": "Altai Krai", "23": "Krasnodar Krai", "24": "Krasnoyarsk Krai",
    "25": "Primorsky Krai", "26": "Stavropol Krai", "27": "Khabarovsk Krai", "28": "Amur Oblast", "29": "Arkhangelsk Oblast",
    "30": "Astrakhan Oblast", "31": "Belgorod Oblast", "32": "Bryansk Oblast", "33": "Vladimir Oblast", "34": "Volgograd Oblast",
    "35": "Vologda Oblast", "36": "Voronezh Oblast", "37": "Ivanovo Oblast", "38": "Irkutsk Oblast", "39": "Kaliningrad Oblast",
    "40": "Kaluga Oblast", "41": "Kamchatka Krai", "42": "Kemerovo Oblast", "43": "Kirov Oblast", "44": "Kostroma Oblast",
    "45": "Kurgan Oblast", "46": "Kursk Oblast", "47": "Leningrad Oblast", "48": "Lipetsk Oblast", "49": "Magadan Oblast",
    "50": "Moscow Oblast", "51": "Murmansk Oblast", "52": "Nizhny Novgorod Oblast", "53": "Novgorod Oblast",
    "54": "Novosibirsk Oblast", "55": "Omsk Oblast", "56": "Orenburg Oblast", "57": "Oryol Oblast", "58": "Penza Oblast",
    "59": "Perm Krai", "60": "Pskov Oblast", "61": "Rostov Oblast", "62": "Ryazan Oblast", "63": "Samara Oblast",
    "64": "Saratov Oblast", "65": "Sakhalin Oblast", "66": "Sverdlovsk Oblast", "67": "Smolensk Oblast", "68": "Tambov Oblast",
    "69": "Tver Oblast", "70": "Tomsk Oblast", "71": "Tula Oblast", "72": "Tyumen Oblast", "73": "Ulyanovsk Oblast",
    "74": "Chelyabinsk Oblast", "75": "Zabaykalsky Krai", "76": "Yaroslavl Oblast", "77": "Moscow", "78": "Saint Petersburg",
    "83": "Nenets Autonomous Okrug", "86": "Khanty-Mansi Autonomous Okrug", "87": "Chukotka Autonomous Okrug", "90": "Crimea",
}
BIG = {"14", "24", "27", "38", "49", "87", "83", "29", "86", "72", "11", "41", "59", "75", "25", "65"}  # large regions: wider circle
R_REGION, R_BIG, R_CITY = 450, 900, 60


def pick_title(names):
    cyr = [n for n in names if re.search("[А-Яа-я]", n)]
    return (cyr or names)[0].replace("_", " ")


def zone_halfwidth(o, peers):
    """Half-width (deg) of the zone strip: from the name ("6 градусная"), else from the spacing of the region's zones, else 3 deg."""
    m = re.search(r"(1\.5|\d)\s*градусная", " ".join(o["names"]))
    if m:
        w = float(m.group(1))
    else:
        lons = sorted({round(x["geometry"]["lon0"], 4) for x in peers if abs(x["geometry"]["fn"] - o["geometry"]["fn"]) < 1 and x["ellipsoid"] == o["ellipsoid"]})
        diffs = [b - a for a, b in zip(lons, lons[1:]) if b - a > 0.9]
        w = min(diffs) if diffs else 3.0
    return w / 2 + 0.25  # margin: neighbouring zones overlap slightly in practice


def clip_lon(b, lon0, hw):
    """Intersect the lat/lon box with the zone strip lon0 +- hw (keep the strip itself if the circle misses it)."""
    lo, hi = lon0 - hw, lon0 + hw
    w, e = max(b[0], lo), min(b[2], hi)
    if w > e:
        w, e = lo, hi
    return [round(w, 2), b[1], round(e, 2), b[3]]


REGION_BOX = json.load(open(DATA / "regions_bbox.json")) if (DATA / "regions_bbox.json").exists() else {}


def area_box(o, g, pts, radius, is_city, by_region):
    """Area of use of an MSK: city circle | real region box clipped to the zone strip | (no borders) circle around the capital."""
    if is_city:
        return box(pts, radius)
    rb = REGION_BOX.get(o["region_code"])
    zoned = g["fe"] >= 1e6  # zone number is encoded in the false easting
    if rb and rb[0] <= rb[2]:
        return clip_lon(rb, g["lon0"], zone_halfwidth(o, by_region.get(o["region_code"], []))) if zoned else rb
    base = box(pts, radius)
    return clip_lon(base, g["lon0"], zone_halfwidth(o, by_region.get(o["region_code"], []))) if zoned and base[0] <= base[2] else (rb or base)


def box(points, radius_km):
    w = s = 1e9; e = n = -1e9
    for lat, lon in points:
        dlat = radius_km / 111.0
        dlon = min(60.0, radius_km / (111.32 * max(0.2, math.cos(math.radians(lat)))))
        w, s, e, n = min(w, lon - dlon), min(s, lat - dlat), max(e, lon + dlon), max(n, lat + dlat)
    w = ((w + 180) % 360) - 180
    e = ((e + 180) % 360) - 180
    return [round(w, 2), round(max(-90, s), 2), round(e, 2), round(min(90, n), 2)]


def main():
    caps = {}
    for r in csv.DictReader(open(DATA / "region_capitals.csv", encoding="utf-8")):
        caps.setdefault(r["region_code"], []).append((float(r["lat"]), float(r["lon"])))
    extras = [(r["name_key"], (float(r["lat"]), float(r["lon"]))) for r in csv.DictReader(open(DATA / "extra_points.csv", encoding="utf-8"))]
    systems = json.load(open(DATA / "systems.json")) + json.load(open(DATA / "systems_unverified.json"))
    out = []
    by_region = {}
    for o in systems:
        by_region.setdefault(o["region_code"], []).append(o)
    for o in systems:
        pts = [p for k, p in extras if any(k in nm for nm in o["names"])]
        pts_city = bool(pts)
        radius = R_CITY if pts else (R_BIG if o["region_code"] in BIG else R_REGION)
        pts = pts or caps.get(o["region_code"], [])
        if not pts:
            continue  # no location hint (railway, highway): cannot be recommended by place
        g = o["geometry"]
        out.append(dict(id=o["id"], src="msk", t=pick_title(o["names"]), n=pick_title(o["names"]), rc=o["region_code"],
                        ar=o["region"], are=REGION_EN.get(o["region_code"], o["region"]),
                        b=area_box(o, g, pts, radius, pts_city, by_region), m="tmerc", p=o["proj4"],
                        st=o["status"], fe=g["fe"], fn=g["fn"], lon0=g["lon0"], lat0=g["lat0"], e=o["ellipsoid"], d=o["datum_gost_form"],
                        db=o["datum_basis"], s=o["sources"], u=o["source_urls"], fl=o["flags"], ur=o["unverified_reasons"], ck=o["checks"]))
    dts = json.load(open(DATA / "datum_transforms.json"))
    summ = json.load(open(DATA / "validation_summary.json"))
    payload = dict(
        built=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"), systems=out, transforms=dts,
        checks=dict(rotation_sign=summ["rotation_sign"], missing_regions=MISSING_REGIONS,
                    total=len(systems), verified=sum(1 for o in systems if o["status"] == "verified")),
    )
    (OUT / "ru.js").write_text("window.__RU__=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print("docs/data/ru.js", round((OUT / "ru.js").stat().st_size / 1024), "KB;", len(out), "systems with area of", len(systems))


if __name__ == "__main__":
    main()
