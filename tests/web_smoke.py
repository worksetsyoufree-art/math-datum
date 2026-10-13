"""Headless smoke test of the general app (file:// works: all data ships as .js)."""
import os, pathlib, sys
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
shot = sys.argv[1] if len(sys.argv) > 1 else None
errors = []
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
    ctx = b.new_context(viewport={"width": 1100, "height": 900}, locale="ru-RU")
    pg = ctx.new_page()
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto((ROOT / "docs/index.html").as_uri())
    # --- finder (ru, default locale) ---
    pg.wait_for_selector(".dcard")
    assert "Подбор датума" in pg.inner_text("h1"), pg.inner_text("h1")
    cards = pg.locator(".dcard").count()
    top = pg.inner_text(".dcard >> nth=0")
    print("finder Moscow/survey:", cards, "cards; top:", top.split("\n")[0:2])
    assert cards >= 3 and "GSK-2011" in top
    pg.wait_for_selector("#projs .prow", timeout=20000)   # lazy-loaded projections
    assert pg.locator("#projs .prow").count() >= 3
    print("projections:", pg.inner_text("#projs .prow >> nth=0").split("\n")[0])
    pg.select_option("#example", label="Berlin")
    pg.wait_for_function("document.querySelector('.dcard') && /DREF|ETRS89|DB_REF/.test(document.querySelector('.dcard').innerText)")
    print("Berlin top:", pg.inner_text(".dcard >> nth=0").split("\n")[0:2])
    pg.check("input[name=purpose][value=gnss]")
    pg.wait_for_timeout(200)
    print("Berlin GNSS top:", pg.inner_text(".dcard >> nth=0").split("\n")[0:2])
    pg.fill("#place", "Россия"); pg.wait_for_selector("#placeres button")
    ps = pg.inner_text("#placeres button >> nth=0"); print("place search:", ps[:60]); assert ps.startswith("Russian Federation"), ps[:80]
    # --- language switch ---
    pg.select_option("#lang", "en")
    assert "Datum & CRS Finder" in pg.inner_text("h1")
    assert "Recommended datums" in pg.inner_text("#tab-finder")
    # --- identify ---
    pg.click("[data-tab=identify]"); pg.click("#id-ex")
    pg.wait_for_selector("#id-out table", timeout=30000)
    pg.wait_for_selector("#id-tbl tr.detail", timeout=10000)        # first row auto-expanded with all points
    ident = pg.inner_text("#id-tbl")
    print("identify:", ident.split("\n")[3:7])
    assert "МСК-50 зона 2" in ident, ident[:400]
    assert pg.locator("#id-tbl tr.detail tbody tr").count() == 6, "six converted points expected"
    first = pg.inner_text("#id-tbl tr.detail tbody tr >> nth=0")
    print("first point:", first.replace("\n", " "))
    assert "55.62" in first and "38.30" in first, first
    # --- convert ---
    pg.click("[data-tab=convert]")
    pg.wait_for_function("document.querySelector('#pk-to .pk-in').value.includes('32637')", timeout=20000)
    out = pg.inner_text("#cv-out")
    print("convert 4326 -> 32637:", out)
    assert "Easting" in out
    # --- catalog ---
    pg.click("[data-tab=catalog]"); pg.fill("#c-q", "Pulkovo 1995"); pg.wait_for_timeout(300)
    n = pg.locator("#c-tbl tbody tr").count(); print("catalog rows for 'Pulkovo 1995':", n); assert n > 3
    pg.click("#c-tbl tbody tr >> nth=0"); pg.wait_for_timeout(100); assert pg.locator("#c-tbl tr.detail").count() == 1
    # --- about: no unresolved tokens ---
    pg.click("[data-tab=about]")
    about = pg.inner_text("#about")
    assert "{" not in about and "}" not in about, about[:300]
    n_proj = pg.evaluate("window.__META__.proj")
    assert str(n_proj) in about.replace("\u00a0", "").replace(",", "").replace(" ", ""), (n_proj, about[:400])
    pg.select_option("#lang", "ru"); assert "Как работает подбор" in pg.inner_text("#about")
    # --- mobile width: no horizontal page scroll ---
    pg.set_viewport_size({"width": 390, "height": 800}); pg.click("[data-tab=finder]")
    assert not pg.evaluate("document.documentElement.scrollWidth > innerWidth"), "horizontal scroll on mobile"
    if shot:
        pg.set_viewport_size({"width": 1100, "height": 1300}); pg.screenshot(path=shot, full_page=True)
    b.close()
print("console errors:", errors)
sys.exit(1 if errors else 0)
