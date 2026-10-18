package ru.mathdatum.localization

import kotlin.math.abs
import kotlin.math.max
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** Сверка с Python-эталоном (ReferenceData.kt генерируется tools/gen_kotlin_reference.py). */
class LocalizationTest {

    @Test
    fun transverseMercatorMatchesProj() {
        for (c in TM_CASES) {
            val tm = TransverseMercator(Ellipsoid.fromProj(c.ellipsoid), c.lat0, c.lon0)
            val (n, e) = tm.forward(c.lat, c.lon)
            near(c.north, n, 1e-4, "N ${c.ellipsoid} ${c.lat},${c.lon}")
            near(c.east, e, 1e-4, "E ${c.ellipsoid} ${c.lat},${c.lon}")
            val (lat, lon) = tm.inverse(c.north, c.east)
            near(c.lat, lat, 1e-10, "B обратный")
            near(c.lon, lon, 1e-10, "L обратный")
        }
    }

    @Test
    fun regionsMatchPythonReference() {
        assertEquals(83, REGIONS.size)
        for (r in REGIONS) {
            val d = localize(r.pairs)
            checkParams(r.iso, d, r.expected)
            r.checkWgs.forEachIndexed { i, w ->
                val p = d.toLocal(WgsPoint(w[0], w[1], w[2]))
                near(r.checkLocal[i][0], p.x, 1e-4, "${r.iso} x")
                near(r.checkLocal[i][1], p.y, 1e-4, "${r.iso} y")
                near(r.checkLocal[i][2], p.height, 1e-4, "${r.iso} H")
            }
            r.catalogLocal.forEachIndexed { i, l ->
                val w = d.toWgs(LocalPoint(l[0], l[1], l[2]))
                near(r.catalogWgs[i][0], w.lat, 2e-9, "${r.iso} B")
                near(r.catalogWgs[i][1], w.lon, 2e-9, "${r.iso} L")
                near(r.catalogWgs[i][2], w.h, 1e-4, "${r.iso} h")
            }
            checkDiag(r.iso, d, r.diag, r.residDiag)
            checkQuality(r.iso, d, r.checkWgs, r.checkQuality)
            // Разворот до ~1.5° (сближение меридианов псевдо-МСК) ниже порога 3°: предупреждений нет.
            assertTrue(d.warnings.isEmpty(), "${r.iso}: ${d.warnings}")
        }
    }

    @Test
    fun reliabilityMatchesPythonReference() {
        for (c in DIAG_CASES) {
            val d = localize(c.pairs)
            checkParams(c.name, d, c.expected)
            checkDiag(c.name, d, c.diag, c.residDiag)
            checkQuality(c.name, d, c.points, c.quality)
            assertEquals(c.suspect, d.residuals.map { it.suspect }, "${c.name} suspect")
            assertEquals(c.warnings, d.warnings.map { it.code }, "${c.name} warnings")
            assertEquals(c.exclusions, suggestExclusions(c.pairs).map { "${it.name}:${it.part}" }, "${c.name} exclusions")
        }
        val blunder = localize(DIAG_CASES.first { it.name == "blunder_plan_10cm" }.pairs)
        assertEquals(listOf("R4"), blunder.residuals.filter { it.suspect }.map { it.name })
        assertEquals("R4", blunder.warnings.single().point)
        // Подсветка 3·СКО на 6 точках не срабатывает: max|v| ≤ √n·СКО.
        assertTrue(blunder.residuals.all { kotlin.math.hypot(it.dx, it.dy) < 3 * blunder.rmsPlan!! })
    }

    @Test
    fun leaveOneOutMatchesManualRefit() {
        val pairs = REGIONS[5].pairs
        val d = localize(pairs)
        pairs.forEachIndexed { i, p ->
            val m = localize(pairs.filterIndexed { j, _ -> j != i }, d.lat0, d.lon0)
            val q = m.toLocal(WgsPoint(p.lat, p.lon, p.h))
            val r = d.residuals[i]
            near(p.x - q.x, r.looDx!!, 1e-8, "looDx")
            near(p.y - q.y, r.looDy!!, 1e-8, "looDy")
            near(p.height - q.height, r.looDH!!, 1e-8, "looDH")
            near(r.dx / r.qvvPlan!!, r.looDx!!, 1e-8, "v/q")
        }
        assertEquals(d.redundancyPlan!!.toDouble(), d.residuals.sumOf { 2 * it.qvvPlan!! }, 1e-9)
    }

    @Test
    fun weightedLeastSquares() {
        // Равные веса: параметры как без весов, w масштабируются как σ0/σ.
        val base = DIAG_CASES.first { it.name == "example" }.pairs.take(6)
        val d = localize(base)
        val e = localize(base.map { it.copy(sigmaPlan = 0.05, sigmaHeight = 0.07) })
        for ((x, y) in listOf(d.a to e.a, d.b to e.b, d.c1 to e.c1, d.c2 to e.c2)) near(x, y, 1e-12, "равные веса")
        for ((x, y) in listOf(d.tx to e.tx, d.ty to e.ty, d.nc to e.nc, d.c0 to e.c0)) near(x, y, 1e-12 * max(1.0, abs(x)), "равные веса")
        d.residuals.zip(e.residuals).forEach { (r, q) -> near(r.wx!! * 0.02 / 0.05, q.wx!!, 1e-7, "w") }
        assertTrue(!d.weighted && e.weighted)
        // σ = σ0 у всех — то же, что без весов.
        val f = localize(base.map { it.copy(sigmaPlan = 0.02, sigmaHeight = 0.03) })
        assertEquals(d.residuals.map { it.wx }, f.residuals.map { it.wx })
        // Leave-one-out = v / (p·q_vv) = прямой пересчёт; Σ p·q_vv = r.
        val pairs = DIAG_CASES.first { it.name == "weighted" }.pairs
        val w = localize(pairs)
        pairs.forEachIndexed { i, p ->
            val r = w.residuals[i]
            if (!p.use.inPlan || !p.use.inHeight) return@forEachIndexed
            val m = localize(pairs.filterIndexed { j, _ -> j != i }, w.lat0, w.lon0)
            val q = m.toLocal(WgsPoint(p.lat, p.lon, p.h))
            near(p.x - q.x, r.looDx!!, 1e-8, "looDx")
            near(p.height - q.height, r.looDH!!, 1e-8, "looDH")
            near(r.dx / (r.pPlan!! * r.qvvPlan!!), r.looDx!!, 1e-8, "v/(p·q)")
            near(r.dH / (r.pHeight!! * r.qvvHeight!!), r.looDH!!, 1e-8, "v/(p·q) H")
        }
        val inP = w.residuals.filter { it.use.inPlan }
        val inH = w.residuals.filter { it.use.inHeight }
        assertEquals(w.redundancyPlan!!.toDouble(), inP.sumOf { 2 * it.pPlan!! * it.qvvPlan!! }, 1e-9)
        assertEquals(w.redundancyHeight!!.toDouble(), inH.sumOf { it.pHeight!! * it.qvvHeight!! }, 1e-9)
        assertEquals(0.005, w.residuals[0].sigmaPlan)
        assertEquals(0.03, w.residuals[1].sigmaHeight)
        // Точка с большой σ и ошибкой 0.5 м не помечена; с малой σ — помечена.
        assertTrue(localize(DIAG_CASES.first { it.name == "weighted_large_sigma_blunder" }.pairs).residuals.none { it.suspect })
        assertTrue(localize(DIAG_CASES.first { it.name == "weighted_small_sigma_blunder" }.pairs).residuals[3].suspect)
        assertFailsWith<LocalizationException> { localize(base.mapIndexed { i, p -> if (i == 0) p.copy(sigmaPlan = 0.0) else p }) }
        assertTrue("σ план" in w.report() && "σ план" !in d.report())
    }

    @Test
    fun convexHullAndOutside() {
        val hull = convexHull(listOf(0.0 to 0.0, 2.0 to 0.0, 1.0 to 1.0, 2.0 to 2.0, 0.0 to 2.0, 1.0 to 0.0))
        assertEquals(listOf(0.0 to 0.0, 2.0 to 0.0, 2.0 to 2.0, 0.0 to 2.0), hull)
        val h = hull.map { listOf(it.first, it.second) }
        assertEquals(0.0, outsideHull(h, 1.0, 1.0))
        assertEquals(1.0, outsideHull(h, 3.0, 1.0), 1e-12)
        assertEquals(0.5, outsideHull(h, 1.0, 2.5), 1e-12)
        assertEquals(3.0, outsideHull(listOf(listOf(0.0, 0.0), listOf(4.0, 0.0)), 2.0, 3.0), 1e-12)
        assertEquals(5.0, outsideHull(listOf(listOf(1.0, 1.0)), 4.0, 5.0), 1e-12)
    }

    @Test
    fun pythonDatumWithDiagnostics() {
        val py = LocalizationDatum.fromJson(PY_DATUM_JSON)
        val c = DIAG_CASES.first { it.name == "example" }
        val kt = localize(c.pairs)
        checkDiag("python json", py, c.diag, c.residDiag)
        checkQuality("python json", py, c.points, c.quality)
        assertEquals(kt.planHull!!.size, py.planHull!!.size)
        assertEquals(LocalizationDatum.fromJson(kt.toJson()), kt)
        // Python читает то, что пишет Kotlin: имена полей совпадают.
        for (key in listOf("\"sigma_plan\"", "\"p_height\"", "\"redundancy_plan\"", "\"q_height\"", "\"plan_hull\"", "\"loo_dH\"", "\"qvv_plan\"", "\"warnings\"")) {
            assertTrue(key in kt.toJson(), key)
        }
    }

    @Test
    fun roundTrip() {
        val d = localize(REGIONS.first().pairs)
        for (lat in listOf(44.5, 44.6, 44.7)) for (lon in listOf(39.9, 40.1)) {
            val w = WgsPoint(lat, lon, 150.0)
            val back = d.toWgs(d.toLocal(w))
            near(w.lat, back.lat, 1e-11, "B")
            near(w.lon, back.lon, 1e-11, "L")
            near(w.h, back.h, 1e-8, "h")
        }
    }

    @Test
    fun jsonRoundTripAndPythonCompatibility() {
        val d = localize(REGIONS[10].pairs)
        val back = LocalizationDatum.fromJson(d.toJson())
        assertEquals(d, back)
        // Датум, сохранённый Python-эталоном (лишнее поле summary игнорируется).
        val py = """{"lat0": 55.0, "lon0": 37.0, "Nc": 1.5, "Ec": -2.5, "a": 1.0, "b": 0.0, "tx": 10.0, "ty": 20.0,
            "c0": -5.0, "c1": 0.0, "c2": 0.0, "ellipsoid": "+ellps=WGS84", "plan_model": "similarity",
            "height_model": "plane", "residuals": [{"name": "R1", "use": "both", "dx": 0.0, "dy": 0.0, "dH": 0.0}],
            "rms_plan": 0.01, "rms_height": 0.002, "summary": {"scale": 1.0}}"""
        val p = LocalizationDatum.fromJson(py)
        assertEquals(-5.0, p.c0)
        assertEquals(Use.BOTH, p.residuals.single().use)
        // Старый формат без сведений о надёжности: поля пустые, точность не определена.
        assertTrue(p.warnings.isEmpty() && p.redundancyPlan == null && p.residuals.single().wx == null)
        assertEquals(PointQuality(null, null, null), p.quality(WgsPoint(55.0, 37.0, 0.0)))
    }

    @Test
    fun fewPointsFallBackToShift() {
        val pairs = REGIONS.first().pairs
        val one = localize(pairs.take(1))
        assertEquals("shift", one.planModel)
        assertEquals("shift", one.heightModel)
        assertEquals(1.0, one.a)
        val two = localize(pairs.take(2))
        assertEquals("similarity", two.planModel)
        assertEquals("shift", two.heightModel)
        val collinear = pairs.take(3).map { it.copy(lon = pairs[0].lon) }
        assertEquals("shift", localize(collinear).heightModel)
    }

    @Test
    fun useFlagsAndErrors() {
        val pairs = REGIONS.first().pairs
        val spoiled = pairs.mapIndexed { i, p -> if (i == 0) p.copy(x = p.x + 10, use = Use.NONE) else p }
        val d = localize(spoiled)
        assertTrue(d.residuals[0].dx > 9.9, "контрольная точка показывает ошибку")
        assertTrue(d.rmsPlan!! < 0.05, "испорченная точка не влияет на результат")
        assertFailsWith<LocalizationException> { localize(pairs.map { it.copy(use = Use.HEIGHT) }) }
        assertFailsWith<LocalizationException> { localize(listOf(pairs[0], pairs[0].copy(name = "dup"))) }
    }

    @Test
    fun csvParsing() {
        val text = "name;B;L;h;x;y;H;use\nR1;55,1;37,2;150,5;100;200;145;plan\n\nR2;55.2;37.3;151;101;201;146;\n"
        val p = Csv.parsePairs(text)
        assertEquals(2, p.size)
        assertEquals(55.1, p[0].lat)
        assertEquals(Use.PLAN, p[0].use)
        assertEquals(Use.BOTH, p[1].use)
        assertTrue(p.all { it.sigmaPlan == null && it.sigmaHeight == null })
        val s = Csv.parsePairs("name;B;L;h;x;y;H;use;sigma_plan;sigma_height\nR1;55;37;150;100;200;145;;0,005;\nR2;55;37;150;1;2;3;;;0.04\n")
        assertEquals(0.005, s[0].sigmaPlan)
        assertEquals(null, s[0].sigmaHeight)
        assertEquals(0.04, s[1].sigmaHeight)
        val w = Csv.parseWgsPoints("name,B,L,h\nT1,55.5,37.5,140\n")
        assertEquals(37.5, w.single().second.lon)
        assertFailsWith<IllegalArgumentException> { Csv.parsePairs("name;B;L\nR1;1;2\n") }
        assertEquals("-0.0010", (-0.001).fixed(4))
        assertEquals("12.3457", 12.34567.fixed(4))
        assertEquals("0.0000", (-0.00001).fixed(4))
    }
}
