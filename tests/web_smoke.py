"""Headless smoke test of docs/index.html (file:// works because data is shipped as data.js)."""
import pathlib, sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
shot = sys.argv[1] if len(sys.argv) > 1 else None
errors = []
with sync_playwright() as p:
    import os
    b = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
    pg = b.new_page(viewport={"width": 1100, "height": 900})
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto((ROOT / "docs/index.html").as_uri())
    pg.wait_for_selector("#out .big")
    out = pg.inner_text("#out")
    assert "X (север)" in out and "Y (восток)" in out, out
    # MSK-50 zone 1 -> Krasnogorsk reference computed earlier with pyproj: E=1365816.032, N=478559.171
    pg.select_option("#region", "50")
    pg.fill("#lat", "55.8317"); pg.fill("#lon", "37.33")
    names = pg.eval_on_selector_all("#system option", "o=>o.map(x=>x.textContent)")
    print("systems in region 50:", len(names))
    pg.click("#find")
    print("zones:", pg.inner_text("#zones")[:200])
    pg.click("[data-tab=sys]")
    n_ver = pg.inner_text("#count")
    pg.select_option("#f-status", "all")
    n_all = pg.inner_text("#count")
    print(n_ver, "|", n_all)
    pg.click("#tbl tbody tr[data-id]")
    assert pg.query_selector("tr.detail pre")
    pg.click("[data-tab=chk]")
    assert "EPSG:5044" in pg.inner_text("#chk")
    pg.click("[data-tab=dat]")
    assert pg.locator("#tbl-dt tbody tr").count() == 21
    pg.click("[data-tab=conv]")
    pg.click("#m-inv"); pg.fill("#xin", "478559.171"); pg.fill("#yin", "1365816.032")
    print("inverse:", pg.inner_text("#out").replace("\n", " | "))
    if shot:
        pg.screenshot(path=shot, full_page=False)
    b.close()
print("console errors:", errors)
sys.exit(1 if errors else 0)
