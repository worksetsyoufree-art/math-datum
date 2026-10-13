"""Country geometry for EPSG areas of use -> docs/data/areas.js

EPSG area-of-use texts list countries ("Europe - onshore and offshore: Albania; Andorra; ..."), but the registry only carries a
bounding box. Bounding boxes overstate the real area (ETRS89's box contains Moscow). This script parses the country lists and
maps them to Natural Earth 110m polygons (simplified to 0.1 deg) plus a small table of micro-states/islands (centre, radius).
The engine then tests the point against the real countries (with a tolerance for coast/offshore).
"""
import json, pathlib, re, urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
NE = BUILD / "ne110.geojson"
URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"

ABBR = [(r"\brep\.", "republic"), (r"\bis\.", "islands"), (r"\bs\.", "south"), (r"\bn\.", "north"), (r"\bdem\.", "democratic"),
        (r"\beq\.", "equatorial"), (r"\bherz\.", "herzegovina"), (r"\bw\.", "western"), (r"\bfr\.", "french"), (r"\bcent\.", "central")]
ALIAS = {
    "russian federation": "russia", "united states (usa)": "united states of america", "united states": "united states of america",
    "united kingdom (uk)": "united kingdom", "türkiye (turkey)": "turkey", "turkiye": "turkey", "turkey": "turkey",
    "congo dr (zaire)": "democratic republic of the congo", "the democratic republic of the congo": "democratic republic of the congo", "congo": "republic of the congo", "côte d'ivoire (ivory coast)": "ivory coast",
    "cote d'ivoire": "ivory coast", "north macedonia": "macedonia", "eswatini (swaziland)": "swaziland", "eswatini": "swaziland",
    "czechia": "czech republic", "myanmar (burma)": "myanmar", "east timor": "timor-leste", "cape verde": "cabo verde",
    "korea, republic of (south korea)": "south korea", "democratic people's republic of korea (north korea)": "north korea",
    "korea, south": "south korea", "korea, north": "north korea", "laos": "laos", "brunei": "brunei", "macao": "macau",
    "the gambia": "gambia", "bahamas": "bahamas", "bosnia and herzegovina": "bosnia and herzegovina", "iran": "iran", "syria": "syria",
    "viet nam": "vietnam", "serbia": "republic of serbia", "tanzania": "united republic of tanzania", "somaliland": "somaliland",
    "palestine": "west bank", "greenland": "greenland", "libya": "libya", "falkland islands (malvinas)": "falkland islands",
    "french southern territories": "french southern and antarctic lands", "western sahara": "western sahara", "kosovo": "kosovo",
    "guinea-bissau": "guinea-bissau", "st helena, ascension and tristan da cunha": "__micro__", "bahrain": "__micro__",
}
MICRO = {  # name: (lat, lon, radius km)
    "andorra": (42.55, 1.58, 40), "luxembourg": (49.8, 6.1, 50), "monaco": (43.74, 7.42, 30), "liechtenstein": (47.14, 9.55, 30),
    "malta": (35.9, 14.45, 40), "gibraltar": (36.14, -5.35, 30), "san marino": (43.94, 12.46, 30), "vatican city state": (41.9, 12.45, 30),
    "holy see (vatican city state)": (41.9, 12.45, 30), "faroe islands": (62.0, -6.8, 100), "singapore": (1.35, 103.82, 40),
    "bahrain": (26.05, 50.55, 50), "maldives": (3.2, 73.2, 450), "mauritius": (-20.3, 57.6, 120), "seychelles": (-4.6, 55.5, 300),
    "comoros": (-11.7, 43.3, 120), "sao tome and principe": (0.3, 6.7, 100), "barbados": (13.2, -59.55, 40), "antigua and barbuda": (17.1, -61.8, 60),
    "st kitts and nevis": (17.3, -62.7, 50), "st lucia": (13.9, -60.98, 40), "st vincent and the grenadines": (13.2, -61.2, 60), "grenada": (12.1, -61.7, 50),
    "dominica": (15.4, -61.35, 40), "tonga": (-21.2, -175.2, 400), "samoa": (-13.76, -172.1, 120), "kiribati": (1.9, -157.4, 2500), "tuvalu": (-8.5, 179.2, 400),
    "nauru": (-0.53, 166.93, 30), "palau": (7.5, 134.6, 150), "marshall islands": (7.1, 171.4, 800), "micronesia": (6.9, 158.2, 1500), "cayman islands": (19.3, -81.25, 100),
    "bermuda": (32.3, -64.75, 50), "aruba": (12.5, -69.97, 30), "curacao": (12.17, -68.98, 40), "anguilla": (18.22, -63.05, 30), "montserrat": (16.74, -62.19, 30),
    "british virgin islands": (18.42, -64.64, 50), "us virgin islands": (18.34, -64.9, 50), "puerto rico": (18.2, -66.5, 100), "guam": (13.44, 144.79, 40),
    "northern mariana islands": (15.2, 145.75, 150), "american samoa": (-14.3, -170.7, 100), "cook islands": (-21.2, -159.8, 600), "niue": (-19.05, -169.87, 40),
    "tokelau": (-9.2, -171.8, 100), "wallis and futuna": (-13.77, -177.15, 100), "french polynesia": (-17.7, -149.4, 1500), "new caledonia": (-21.3, 165.5, 400),
    "reunion": (-21.1, 55.5, 60), "mayotte": (-12.8, 45.15, 40), "martinique": (14.65, -61.0, 40), "guadeloupe": (16.25, -61.55, 70), "st pierre and miquelon": (46.9, -56.3, 50),
    "svalbard and jan mayen": (78.0, 16.0, 700), "jersey": (49.2, -2.13, 20), "guernsey": (49.45, -2.58, 20), "isle of man": (54.24, -4.55, 30), "macau": (22.2, 113.55, 20),
    "hong kong": (22.3, 114.17, 30), "st barthelemy": (17.9, -62.85, 20), "st martin": (18.07, -63.05, 20), "st maarten": (18.04, -63.06, 20), "turks and caicos islands": (21.7, -71.8, 120),
    "kosovo": (42.6, 20.9, 80), "north macedonia": (41.6, 21.7, 90), "montenegro": (42.75, 19.3, 90), "pitcairn": (-25.07, -130.1, 50), "norfolk island": (-29.04, 167.95, 30),
    "christmas island": (-10.5, 105.65, 30), "cocos (keeling) islands": (-12.15, 96.85, 40), "british indian ocean territory": (-7.3, 72.4, 300), "cyprus": (35.1, 33.4, 130),
    "bouvet island": (-54.4, 3.4, 30), "heard island and mcdonald islands": (-53.1, 73.5, 80), "south georgia and the south sandwich islands": (-54.4, -36.6, 500),
    "st helena, ascension and tristan da cunha": (-15.95, -5.7, 3000), "mauritania": None,
}
MICRO = {k: v for k, v in MICRO.items() if v}


def norm(s):
    s = s.lower().strip()
    s = re.sub(r"\s+", " ", s)
    return s


def expand(s):
    s = norm(s)
    for pat, rep in ABBR:
        s = re.sub(pat, rep, s)
    return s


def tokens(area):
    body = area.split(":", 1)[1] if ":" in area else area
    out = []
    for tok in re.split(r";|\.\s|\.$", body):
        tok = tok.strip().strip(".")
        if not tok:
            continue
        head = re.split(r" - | including | excluding |, ", tok)[0].strip()
        # keep "Türkiye (Turkey)" style names, drop other parentheses
        out.append(head)
    return out


def simplify(ring):
    pts, last = [], None
    for lon, lat in ring:
        q = (round(lon * 10), round(lat * 10))
        if q != last:
            pts.append(q); last = q
    return pts


def main():
    BUILD.mkdir(exist_ok=True)
    if not NE.exists():
        urllib.request.urlretrieve(URL, NE)
    feats = json.load(open(NE))["features"]
    names, polys, index = [], [], {}
    for i, f in enumerate(feats):
        p = f["properties"]
        names.append(p["NAME"])
        geom = f["geometry"]
        rings = []
        for poly in (geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]):
            r = simplify(poly[0])
            if len(r) >= 4:
                rings.append([v for pt in r for v in pt])
        polys.append(rings)
        for k in ("NAME", "NAME_LONG", "ADMIN", "FORMAL_EN", "BRK_NAME", "SOVEREIGNT", "NAME_EN"):
            if p.get(k):
                index.setdefault(expand(p[k]), i)
    cands = json.load(open(BUILD / "world_candidates.json"))
    all_areas = sorted({g["area"] for g in cands["geo"]} | {p["area"] for p in cands["proj"]})
    areas, unmatched = {}, {}
    for a in all_areas:
        toks = tokens(a)
        c, m = [], []
        for tok in toks:
            n = norm(tok)
            key = ALIAS.get(n, n)
            key_exp = expand(key)
            if key_exp in index:
                if index[key_exp] not in c:
                    c.append(index[key_exp])
                continue
            base = re.sub(r"\s*\(.*?\)", "", n).strip()
            if expand(ALIAS.get(base, base)) in index:
                i = index[expand(ALIAS.get(base, base))]
                if i not in c:
                    c.append(i)
                continue
            if base in MICRO:
                m.append(list(MICRO[base]))
                continue
            unmatched[tok] = unmatched.get(tok, 0) + 1
        bb = None
        m_ = re.search(r"approximately\s+(\d+)°\s*([WE])\s+to\s+(\d+)°\s*([WE])\s+and\s+(\d+)°\s*([NS])\s+to\s+(\d+)°\s*([NS])", a)
        if m_:
            sg = lambda v, h: -float(v) if h in "WS" else float(v)
            bb = [sg(m_.group(1), m_.group(2)), sg(m_.group(5), m_.group(6)), sg(m_.group(3), m_.group(4)), sg(m_.group(7), m_.group(8))]
        total = len(toks)
        ok = bool(total) and (len(c) + len(m)) / total >= 0.6 and (len(c) + len(m)) >= 1
        if ok:
            areas[a] = dict(c=c, m=m, o=1 if "offshore" in a.lower() else 0)
        elif bb:
            areas[a] = dict(c=[], m=[], o=0, bb=bb, bbonly=1)
    out = dict(names=names, polys=polys)
    js = "window.__COUNTRIES__=" + json.dumps(out, separators=(",", ":")) + ";\nwindow.__AREAS__=" + json.dumps(areas, ensure_ascii=False, separators=(",", ":")) + ";\n"
    (ROOT / "docs/data/areas.js").write_text(js, encoding="utf-8")
    print(f"areas {len(all_areas)}; with usable country list: {len(areas)}; file {len(js)//1024} KB; countries {len(names)}")
    top = sorted(unmatched.items(), key=lambda kv: -kv[1])[:60]
    print("top unmatched tokens:", top)


if __name__ == "__main__":
    main()
