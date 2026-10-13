"""Normalise scraped MapInfo CoordSys lines into structured MSK records."""
import json, re, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ELLIPSOIDS = {  # MapInfo ellipsoid id -> (PROJ name, a, 1/f)
    3: ("krass", 6378245.0, 298.3),
    10: ("bessel", 6377397.155, 299.1528128),
}
LINE = re.compile(r'^\s*[«"“](?P<name>.+?)[»"”]\s*,\s*(?P<rest>8\s*,.*)$')


def num(x):
    return float(x.strip().replace(" ", ""))


def parse_line(line):
    m = LINE.match(line)
    if not m:
        return None
    name = m["name"].strip()
    f = [x.strip() for x in m["rest"].split(",")]
    if f[0] != "8":
        return None
    datum = int(f[1])
    if datum == 1001:  # 8,1001,units,lon0,lat0,k,fe,fn
        if len(f) != 8:
            return None
        h, ell = None, None
        units, lon0, lat0, k, fe, fn = f[2:8]
    elif datum == 9999:  # 8,9999,ell,dx,dy,dz,rx,ry,rz,ds,pm,units,lon0,lat0,k,fe,fn
        if len(f) != 17:
            return None
        ell = int(f[2])
        h = [num(x) for x in f[3:10]]
        units, lon0, lat0, k, fe, fn = f[11:17]
    else:
        return None
    return dict(
        name=name,
        mapinfo_datum=datum,
        ellipsoid_id=ell,
        helmert_mapinfo=h,  # dx,dy,dz [m], rx,ry,rz ["], ds [ppm]; coordinate-frame convention
        lon0=num(lon0), lat0=num(lat0), k0=num(k), fe=num(fe), fn=num(fn),
        units=int(units),
    )


def main():
    recs = []
    for src, fn in (("geoprof.nethouse.ru", "geoprof_raw.json"), ("terraingis.ru", "tg_raw.json")):
        for page in json.load(open(ROOT / "data/raw" / fn)):
            for line in page["lines"]:
                r = parse_line(line)
                if r is None:
                    print("SKIP", src, page["title"], line, file=sys.stderr)
                    continue
                r.update(source=src, page_title=page["title"], page_url=page["url"], raw=line)
                recs.append(r)
    json.dump(recs, open(ROOT / "data/raw/parsed_lines.json", "w"), ensure_ascii=False, indent=1)
    print(len(recs), "records")


if __name__ == "__main__":
    main()
