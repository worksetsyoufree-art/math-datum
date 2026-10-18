package ru.mathdatum.localization

import kotlin.math.abs
import kotlin.math.pow
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Метаданные, контрольная сумма и HTML-отчёт — сверка с Python-эталоном (ReportReferenceData.kt). */
class ReportTest {

    private fun bytes(hex: String) = ByteArray(hex.length / 2) { hex.substring(2 * it, 2 * it + 2).toInt(16).toByte() }

    private fun datumOf(c: ReportCase): LocalizationDatum {
        val grid = c.grid?.let { n -> GeoidGrid.parse(bytes(GEOID_FILES.first { it.name == n }.hex), n) }
        return LocalizationDatum.fromJson(c.datumJson, geoid = grid)
    }

    private val leaf = Regex("<(td|span|text)\\b[^>]*?data-k=\"([^\"]*)\"[^>]*>([^<]*)")
    private val number = Regex("-?\\d+(\\.(\\d+))?")

    private fun values(html: String) = leaf.findAll(html).map { it.groupValues[2] to it.groupValues[3] }.toList()

    /** Тексты совпадают; числа с фиксированными знаками — до единицы последнего знака (округление на границе). */
    private fun sameValue(key: String, e: String, a: String) {
        if (e == a) return
        val me = number.matchEntire(e)
        val ma = number.matchEntire(a)
        assertTrue(me != null && ma != null, "$key: «$e» ≠ «$a»")
        val digits = me.groups[2]?.value?.length ?: 0
        assertTrue(abs(e.toDouble() - a.toDouble()) <= 1.01 * 10.0.pow(-digits), "$key: $e ≠ $a")
    }

    @Test
    fun checksumMatchesPython() {
        for (c in REPORT_CASES) {
            val d = datumOf(c)
            assertEquals(c.checksum, d.checksum(), c.name)
            if (c.checksum != null) {
                assertEquals(true, d.verifyChecksum(), c.name)
                assertEquals(c.checksum, d.meta!!.inputsSha256, c.name)
            } else {
                assertNull(d.verifyChecksum(), c.name)
                assertNull(d.meta, c.name)
            }
        }
        // Тот же расчёт в Kotlin даёт ту же сумму, что Python.
        val pairs = datumOf(REPORT_CASES[0]).pairs!!
        val d = localize(pairs)
        assertEquals(PY_DEFAULT_CHECKSUM, d.meta!!.inputsSha256)
        assertEquals(PY_DEFAULT_CHECKSUM, d.checksum())
    }

    @Test
    fun checksumChangesWithPairsAndParameters() {
        val pairs = datumOf(REPORT_CASES[0]).pairs!!
        val base = localize(pairs).meta!!.inputsSha256
        val moved = pairs.mapIndexed { i, p -> if (i == 2) p.copy(x = p.x + 0.001) else p }
        assertNotEquals(base, localize(moved).meta!!.inputsSha256)
        assertNotEquals(base, localize(pairs.mapIndexed { i, p -> if (i == 0) p.copy(use = Use.PLAN) else p }).meta!!.inputsSha256)
        assertNotEquals(base, localize(pairs, sigmaPlan = 0.021).meta!!.inputsSha256)
        assertNotEquals(base, localize(pairs.mapIndexed { i, p -> if (i == 0) p.copy(name = "R1 ") else p }).meta!!.inputsSha256)
        // Подмена пары в сохранённом датуме обнаруживается.
        val d = localize(pairs)
        val forged = d.copy(pairs = moved)
        assertEquals(false, forged.verifyChecksum())
        assertEquals(false, LocalizationDatum.fromJson(forged.toJson()).verifyChecksum())
        assertEquals("mismatch", Report.checksumStatus(forged).first)
        assertTrue("НЕ СОВПАДАЕТ" in Report.html(forged, generatedAt = REPORT_TIME))
    }

    @Test
    fun metadataAndRevisions() {
        val pairs = datumOf(REPORT_CASES[0]).pairs!!
        val d1 = localize(pairs, meta = DatumMeta(objectName = "Объект", author = "Иванов", note = "первый"))
        val m1 = d1.meta!!
        assertEquals(1, m1.revision)
        assertNull(m1.previousId)
        assertTrue(Regex("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}").matches(m1.datumId!!), m1.datumId)
        assertTrue(Regex("\\d{4}-\\d\\d-\\d\\dT\\d\\d:\\d\\d:\\d\\dZ").matches(m1.computedAt!!), m1.computedAt)
        assertEquals(MATHDATUM_LIBRARY, m1.libraryVersion)
        val d2 = localize(pairs, meta = m1.nextRevision().copy(note = "второй"))
        val m2 = d2.meta!!
        assertEquals(2, m2.revision)
        assertEquals(m1.datumId, m2.previousId)
        assertNotEquals(m1.datumId, m2.datumId)
        assertEquals("Объект", m2.objectName)
        assertEquals("Иванов", m2.author)
        assertEquals("второй", m2.note)
        assertEquals(m1.inputsSha256, m2.inputsSha256)
        assertFailsWith<IllegalArgumentException> { DatumMeta().nextRevision() }
        // JSON: туда и обратно; повторный расчёт по сохранённым данным сохраняет UUID и даёт те же параметры.
        val back = LocalizationDatum.fromJson(d2.toJson())
        assertEquals(d2, back)
        val re = back.relocalize()
        assertEquals(m2, re.meta)
        assertEquals(d2.a, re.a); assertEquals(d2.tx, re.tx); assertEquals(d2.c0, re.c0)
    }

    @Test
    fun jsonCompatibility() {
        // Датум Python с метаданными читается, поля совпадают.
        val py = datumOf(REPORT_CASES[0])
        val m = py.meta!!
        assertEquals("3f1c2a64-1d7e-4b8a-9a51-0c2d5e6f7a80", m.datumId)
        assertEquals("ЖК «Север» <script>alert(\"x\")</script> & корпус 3", m.objectName)
        assertEquals("Иванов И. И.", m.author)
        assertEquals("2026-10-18T11:00:00Z", m.computedAt)
        assertEquals(1, m.revision)
        assertEquals(10, py.pairs!!.size)
        assertEquals("WGS-84", py.inputs!!.gnssDatum)
        assertNull(py.inputs!!.lat0)
        val rev = datumOf(REPORT_CASES[1]).meta!!
        assertEquals(2, rev.revision)
        assertEquals(m.datumId, rev.previousId)
        // Старый JSON (без пар, параметров и метаданных) и датум примера из Python читаются.
        val old = datumOf(REPORT_CASES.first { it.checksum == null })
        assertNull(old.pairs); assertNull(old.inputs); assertNull(old.meta)
        assertNull(LocalizationDatum.fromJson(PY_DATUM_JSON).meta)
        // Неизвестные поля будущих версий пропускаются.
        val future = py.toJson().replaceFirst("{", "{\n  \"future_field\": {\"x\": 1},")
        assertEquals(py, LocalizationDatum.fromJson(future, requireGeoid = false))
    }

    @Test
    fun reportValuesMatchPython() {
        var total = 0
        for (c in REPORT_CASES) {
            val d = datumOf(c)
            val pairs = c.pairsCsv?.let { Csv.parsePairs(it) }
            val html = Report.html(d, pairs, generatedAt = REPORT_TIME)
            val kt = values(html)
            assertEquals(c.values.map { it.first }, kt.map { it.first }, "${c.name}: ключи data-k")
            c.values.zip(kt).forEach { (e, a) -> sameValue("${c.name} ${e.first}", e.second, a.second) }
            total += kt.size
            // Все точки — в таблицах и на схеме (если есть пары).
            val names = (pairs ?: d.pairs)?.map { it.name }
            if (names != null) {
                for ((i, n) in names.withIndex()) {
                    assertTrue("data-k=\"p$i.name\">${Report.esc(n)}<" in html, "${c.name}: $n в исходных данных")
                    assertTrue("data-k=\"svg.$i\">${Report.esc(n)}<" in html, "${c.name}: $n на схеме")
                }
                assertEquals(1, Regex("<svg ").findAll(html).count())
                assertEquals(1, Regex("</svg>").findAll(html).count())
            }
            assertTrue("ВНИМАНИЕ (Trimble JobXML)" in html && "data-k=\"chk0.x2\"" in html, c.name)
        }
        assertTrue(total > 500, "сверено величин: $total")
    }

    @Test
    fun userTextIsEscaped() {
        val pairs = datumOf(REPORT_CASES[0]).pairs!!.mapIndexed { i, p -> if (i == 0) p.copy(name = "<img src=x onerror=alert(1)>&\"") else p }
        val d = localize(pairs, meta = DatumMeta(objectName = "</style><script>alert(1)</script>", author = "<b>A</b>",
            note = "\"'><svg onload=alert(1)>"))
        val html = Report.html(d)
        assertFalse("<script" in html, "script")
        assertFalse("<img" in html, "img")
        assertFalse("<b>A</b>" in html)
        assertFalse("onload=alert" in html.replace("&lt;svg onload=alert", ""))
        assertTrue("&lt;img src=x onerror=alert(1)&gt;&amp;&quot;" in html)
        // В @page (CSS) объект — строкой с экранированными < >, без выхода из <style>.
        val style = html.substringAfter("<style>").substringBefore("</style>")
        assertFalse("<" in style, "< в CSS")
        assertTrue("\\3c /style\\3e " in style)
    }
}
