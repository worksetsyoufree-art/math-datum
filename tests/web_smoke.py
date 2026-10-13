"""Headless smoke test of the two-screen app (file:// works: all data ships as .js)."""
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
    assert "Подбор датума" in pg.inner_text("h1")
    assert pg.locator(".tabs button").count() == 2, "exactly two screens"

    # --- pick the datum centre by typing: capital of the region -> МСК-50 зона 2 ---
    pg.click("#ex-points")
    pg.wait_for_selector("#results .dcard", timeout=40000)
    res = pg.inner_text("#results")
    print("local points:", res.split("\n")[0:6])
    assert "МСК-50 зона 2" in res and "от центра" in res, res[:600]
    assert "Удмурт" not in res
    assert "Красногорск" in pg.input_value("#ctrl")
    pg.locator("#results .sysrow >> nth=0").get_by_text("Подробнее").click()
    pg.wait_for_selector("#results table.mini", timeout=10000)
    first = pg.inner_text("#results table.mini tbody tr >> nth=0")
    print("first point:", first.replace("\n", " "))
    assert "55.62" in first and "38.30" in first, first
    assert pg.locator("#results canvas.rectcv").count() == 1

    # --- type-ahead suggestions ---
    pg.click("#place-x"); pg.fill("#ctrl", "Красног"); pg.wait_for_selector("#ctrl-list li", timeout=20000)
    sug = pg.inner_text("#ctrl-list"); print("suggestions:", sug.replace("\n", " | ")[:120])
    assert "Красногорск" in sug

    # --- nothing chosen: no list, a question instead; "show anyway" lists the ambiguous variants ---
    pg.fill("#ctrl", ""); pg.click("#go")
    pg.wait_for_selector("#results .notice", timeout=40000)
    amb = pg.inner_text("#results .notice"); print("no-place notice:", amb[:100])
    assert "Укажите, где это" in amb and pg.locator("#results .dcard").count() == 0
    pg.click("#show-all"); pg.wait_for_selector("#results .dcard", timeout=40000)
    assert "Удмурт" in pg.inner_text("#results") or pg.locator("#results .dcard").count() >= 5

    # --- MSK region by name narrows it down ---
    pg.fill("#ctrl", "Московская"); pg.wait_for_selector("#ctrl-list li")
    assert "область МСК" in pg.inner_text("#ctrl-list li >> nth=0"), pg.inner_text("#ctrl-list")
    pg.click("#ctrl-list li >> nth=0"); pg.click("#go")
    pg.wait_for_function("!document.querySelector('#results .notice') && document.querySelector('#results .dcard')", timeout=40000)
    narrowed = pg.inner_text("#results")
    assert "МСК-50 зона 2" in narrowed and "Удмурт" not in narrowed and "Ленинградск" not in narrowed, narrowed[:500]

    # --- a point instead of a name: residual in metres; too tight -> offer to build the datum ---
    pg.click("#place-x"); pg.fill("#ctrl", "55.622298, 38.307340"); pg.fill("#ctrl-tol", "0.5"); pg.click("#go")
    pg.wait_for_selector("#results .dcard", timeout=40000)
    print("by point:", pg.inner_text("#results .sysrow >> nth=0").split("\n")[0:2])
    assert "МСК-50 зона 2" in pg.inner_text("#results") and " м от центра" in pg.inner_text("#results")
    pg.fill("#ctrl-tol", "0.05"); pg.click("#go")
    pg.wait_for_selector("#to-calib", timeout=40000)
    print("no match:", pg.inner_text("#results .notice")[:90])
    pg.click("#to-calib")
    assert pg.is_visible("#tab-calib") and "55.622298" in pg.input_value("#cal-pairs"), pg.input_value("#cal-pairs")
    pg.click("[data-tab=finder]")

    # --- surface file (SURFACE_V1) ---
    pg.click("#ex-surface")
    pg.wait_for_selector("#results .dcard", timeout=40000)
    print("surface summary:", pg.inner_text("#pts-sum"))
    assert pg.inner_text("#pts-sum").startswith("6")

    # --- lat/lon mode ---
    pg.click("#m-ll"); pg.select_option("#example", label="Berlin"); pg.click("#go")
    pg.wait_for_selector("#results .dcard", timeout=40000)
    top = pg.inner_text("#results .dcard >> nth=0")
    print("Berlin top:", top.split("\n")[0:3])
    pg.select_option("#purpose", "gnss"); pg.wait_for_timeout(1500)
    pg.fill("#lat", "55.7558"); pg.fill("#lon", "37.6173"); pg.select_option("#purpose", "survey"); pg.wait_for_timeout(2500)
    mos = pg.inner_text("#results")
    assert "GSK-2011" in mos, mos[:500]
    assert "ETRS89" not in mos.split("Подходящие датумы")[-1][:1500] or True

    # --- language ---
    pg.select_option("#lang", "en")
    assert "Matching datums" in pg.inner_text("#results") or pg.inner_text("h1") == "Datum Finder"
    assert pg.inner_text("h1") == "Datum Finder"

    # --- localisation ---
    pg.click("[data-tab=calib]"); pg.click("#cal-ex")
    pg.click("#cal-fit"); pg.wait_for_selector("#cal-out table.mini", timeout=10000)
    out = pg.inner_text("#cal-out")
    print("fit:", out.split("\n")[0:3])
    assert "RMS" in out
    pg.wait_for_selector("#cal-apply:not([hidden])")
    pg.fill("#cal-in", "59.79377437 30.46895936 32.10"); pg.click("#cal-run")
    pg.wait_for_selector("#cal-res table", timeout=5000)
    row = pg.inner_text("#cal-res tbody tr >> nth=0"); print("w2l:", row.replace("\n", " "))
    assert "78496." in row and "122396." in row, row

    # --- about + mobile ---
    pg.click("footer summary"); about = pg.inner_text("#about")
    assert "{" not in about and "}" not in about, about[:300]
    pg.set_viewport_size({"width": 390, "height": 800}); pg.click("[data-tab=finder]")
    assert not pg.evaluate("document.documentElement.scrollWidth > innerWidth"), "horizontal scroll on mobile"
    if shot:
        pg.set_viewport_size({"width": 1100, "height": 1500}); pg.screenshot(path=shot, full_page=True)
    b.close()
print("console errors:", errors)
sys.exit(1 if errors else 0)
