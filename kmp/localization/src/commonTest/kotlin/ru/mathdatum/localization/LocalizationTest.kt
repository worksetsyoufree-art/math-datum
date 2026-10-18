package ru.mathdatum.localization

import kotlin.math.abs
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** Сверка с Python-эталоном (ReferenceData.kt генерируется tools/gen_kotlin_reference.py). */
class LocalizationTest {

    private fun near(expected: Double, actual: Double, tol: Double, what: String) =
        assertTrue(abs(expected - actual) <= tol, "$what: ожидалось $expected, получено $actual (допуск $tol)")

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
            val e = r.expected
            near(e[0], d.lat0, 1e-12, "${r.iso} lat0")
            near(e[1], d.lon0, 1e-12, "${r.iso} lon0")
            near(e[2], d.nc, 1e-5, "${r.iso} Nc")
            near(e[3], d.ec, 1e-5, "${r.iso} Ec")
            near(e[4], d.a, 1e-10, "${r.iso} a")
            near(e[5], d.b, 1e-10, "${r.iso} b")
            near(e[6], d.tx, 1e-6, "${r.iso} tx")
            near(e[7], d.ty, 1e-6, "${r.iso} ty")
            near(e[8], d.c0, 1e-6, "${r.iso} c0")
            near(e[9], d.c1, 1e-10, "${r.iso} c1")
            near(e[10], d.c2, 1e-10, "${r.iso} c2")
            near(e[11], d.rmsPlan!!, 1e-6, "${r.iso} rmsPlan")
            near(e[12], d.rmsHeight!!, 1e-6, "${r.iso} rmsHeight")
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
        val w = Csv.parseWgsPoints("name,B,L,h\nT1,55.5,37.5,140\n")
        assertEquals(37.5, w.single().second.lon)
        assertFailsWith<IllegalArgumentException> { Csv.parsePairs("name;B;L\nR1;1;2\n") }
        assertEquals("-0.0010", (-0.001).fixed(4))
        assertEquals("12.3457", 12.34567.fixed(4))
        assertEquals("0.0000", (-0.00001).fixed(4))
    }
}
