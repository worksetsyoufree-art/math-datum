"""Pack the datasets into docs/data/data.js (works on GitHub Pages and from file://)."""
import json, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "docs/data"
OUT.mkdir(parents=True, exist_ok=True)

MISSING_REGIONS = {  # no open source found
    "17": "Республика Тыва", "79": "Еврейская автономная область", "89": "Ямало-Ненецкий автономный округ",
}


def pick_title(names):
    cyr = [n for n in names if re.search("[А-Яа-я]", n)]
    return (cyr or names)[0].replace("_", " ")


def slim(o):
    return dict(id=o["id"], t=pick_title(o["names"]), rc=o["region_code"], r=o["region"], n=o["names"], g=o["geometry"], e=o["ellipsoid"],
                d=o["datum_gost_form"], db=o["datum_basis"], s=o["sources"], u=o["source_urls"], st=o["status"],
                fl=o["flags"], ur=o["unverified_reasons"], ck=o["checks"], p4=o["proj4"])


def main():
    ver = json.load(open(DATA / "systems.json"))
    unv = json.load(open(DATA / "systems_unverified.json"))
    fed = json.load(open(DATA / "federal_datums.json"))
    dts = json.load(open(DATA / "datum_transforms.json"))
    summ = json.load(open(DATA / "validation_summary.json"))
    payload = dict(
        built=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d"),
        systems=[slim(o) for o in ver + unv],
        federal=[dict(epsg=f["epsg"], name=f["name"], datum=f["datum"], ellipsoid=f["ellipsoid"], a=f["a"], inv_f=f["inv_f"],
                      type=f["type"], ops=[dict(name=x.get("name", "").replace(" (with axis order normalized for visualization)", ""),
                                                accuracy=x.get("accuracy")) for x in f["to_wgs84"]]) for f in fed],
        transforms=dts,
        checks=dict(rotation_sign=summ["rotation_sign"], federal_shifts=summ["federal_shifts"],
                    missing_regions=MISSING_REGIONS),
    )
    (OUT / "data.js").write_text("window.__DATA__=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    print("docs/data/data.js", round((OUT / "data.js").stat().st_size / 1024), "KB;", len(ver), "verified,", len(unv), "unverified")


if __name__ == "__main__":
    main()
