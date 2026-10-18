package ru.mathdatum.localization

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.sin
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/** Экспорт датума — сверка текстов с Python-эталоном (ExportReferenceData.kt). */
class ExportTest {

    private fun bytes(hex: String) = ByteArray(hex.length / 2) { hex.substring(2 * it, 2 * it + 2).toInt(16).toByte() }

    private fun datumOf(c: ExportCase): LocalizationDatum {
        val grid = c.grid?.let { n -> GeoidGrid.parse(bytes(GEOID_FILES.first { it.name == n }.hex), n) }
        return LocalizationDatum.fromJson(c.datumJson, geoid = grid)
    }

    private val number = Regex("-?\\d+(\\.\\d+)?([eE][-+]?\\d+)?")

    /**
     * Тексты совпадают; числа — до 1e-13 относительно (atan2, hypot, sin могут отличаться в последнем бите
     * между libm Python, JVM и JS). Возвращает число чисел, совпавших не побитно.
     */
    private fun sameText(expected: String, actual: String, what: String): Int {
        val e = number.findAll(expected).toList()
        val a = number.findAll(actual).toList()
        assertEquals(number.replace(expected, "#"), number.replace(actual, "#"), "$what: текст без чисел")
        assertEquals(e.size, a.size, "$what: число чисел")
        var inexact = 0
        e.zip(a).forEach { (x, y) ->
            if (x.value != y.value) {
                inexact++
                val u = x.value.toDouble(); val v = y.value.toDouble()
                assertTrue(abs(u - v) <= 1e-13 * max(abs(u), abs(v)), "$what: ${x.value} ≠ ${y.value}")
            }
        }
        return inexact
    }

    @Test
    fun textsMatchPython() {
        var inexact = 0; var total = 0
        for (c in EXPORT_CASES) {
            val d = datumOf(c)
            for ((f, text) in c.texts) {
                val r = Export.export(d, f, name = c.crsName, timestamp = "2026-10-18T12:00:00")
                inexact += sameText(text, r.text, "${c.name} $f")
                total += number.findAll(text).count()
                val w = c.warnings.getValue(f)
                assertEquals(w.size, r.warnings.size, "${c.name} $f: предупреждения ${r.warnings}")
                w.zip(r.warnings).forEach { (x, y) -> sameText(x, y, "${c.name} $f: предупреждение") }
            }
        }
        assertTrue(total > 2000 && inexact * 20 < total, "побитно не совпало $inexact из $total чисел")
    }

    @Test
    fun checkPointsMatchPython() {
        for (c in EXPORT_CASES) {
            val d = datumOf(c)
            for ((exp, act) in listOf(c.checks to Export.checkPoints(d), c.checksFlipped to Export.checkPoints(d, -1))) {
                assertEquals(exp.size, act.size, c.name)
                exp.zip(act).forEach { (e, p) ->
                    near(e[0], p.lat, 1e-11, "${c.name} ${p.name} B")
                    near(e[1], p.lon, 1e-11, "${c.name} ${p.name} L")
                    near(e[2], p.x, 1e-6, "${c.name} ${p.name} x")
                    near(e[3], p.y, 1e-6, "${c.name} ${p.name} y")
                }
            }
        }
    }

    @Test
    fun jxlManualExample() {
        // Ручной расчёт (как tests/test_export.py): TM k = 1.000078·1.00002, FN = 10000 + 1.00002·19000,
        // FE = 20000 + 1.00002·100500, поворот +30″ вокруг (10000, 20000), наклоны c/1.00002.
        val m = 1.00002; val th = 30.0 / 3600 * PI / 180
        val d = LocalizationDatum(lat0 = 55.0, lon0 = 38.0, nc = 1000.0, ec = -500.0, a = m * cos(th), b = m * sin(th),
            tx = 10000.0, ty = 20000.0, c0 = -14.2, c1 = 2e-5, c2 = -3e-5, k0 = 1.000078, x0 = 20000.0, y0 = 100000.0,
            gnssDatum = "WGS-84")
        val p = Export.jxlParameters(d)
        near(1.00009800156, p.scale, 1e-14, "scale")
        near(29000.38, p.falseNorthing, 1e-9, "FN")
        near(120502.01, p.falseEasting, 1e-9, "FE")
        near(30.0 / 3600, p.rotationDeg, 1e-15, "rotation")
        near(1.99996000080e-5, p.slopeNorth, 1e-16, "slopeN")
        near(-2.99994000120e-5, p.slopeEast, 1e-16, "slopeE")
        val xml = Export.toJxl(d).text
        assertTrue("<Type>PlaneAdjustment</Type>" in xml && "<ScaleFactor>1</ScaleFactor>" in xml && "<TranslationNorth>0</TranslationNorth>" in xml)
        assertTrue("<Type>InclinedPlane</Type>" in xml && "<ConstantAdjustment>-14.2</ConstantAdjustment>" in xml)
    }

    @Test
    fun numbersLikePythonRepr() {
        val cases = listOf(0.0 to "0", 1.0 to "1", 20000.0 to "20000", 1e-5 to "1e-05", 1e-4 to "0.0001",
            55.06991640959999 to "55.06991640959999", 1e16 to "1e+16", -2.5e-7 to "-2.5e-07", 1e15 to "1000000000000000.0",
            0.1 to "0.1", 123.456 to "123.456", 6.123e22 to "6.123e+22", -1.5e-300 to "-1.5e-300", 1.0 / 298.257223563 to "0.0033528106647474805",
            3.893347517381845e-06 to "3.893347517381845e-06", 1234567890123456.7 to "1234567890123456.8")
        for ((v, s) in cases) assertEquals(s, Export.fnum(v), "fnum($v)")
    }

    @Test
    fun closedAndUnknownFormats() {
        val d = LocalizationDatum.fromJson(EXPORT_CASES.first().datumJson)
        for (f in Export.CLOSED.keys) {
            val e = assertFailsWith<ExportException> { Export.export(d, f) }
            assertTrue("docs/export.md" in e.message!!, e.message)
        }
        assertFailsWith<ExportException> { Export.export(d, "dxf") }
        assertEquals(d.toProjPipeline() + "\n", Export.export(d, "proj").text)
    }
}
