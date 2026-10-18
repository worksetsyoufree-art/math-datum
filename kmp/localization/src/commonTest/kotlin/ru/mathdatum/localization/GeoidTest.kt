package ru.mathdatum.localization

import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Сетки геоида и модели высот geoid / geoid_plane — сверка с Python-эталоном (GeoidReferenceData.kt). */
class GeoidTest {

    private fun bytes(hex: String) = ByteArray(hex.length / 2) { hex.substring(2 * it, 2 * it + 2).toInt(16).toByte() }

    private val grids: Map<String, GeoidGrid> by lazy { GEOID_FILES.associate { it.name to GeoidGrid.parse(bytes(it.hex), it.name) } }

    @Test
    fun readersMatchPython() {
        for (f in GEOID_FILES) {
            val g = grids.getValue(f.name)
            assertEquals(f.sha256, g.sha256, "${f.name} sha256")
            assertEquals(f.sha256, Sha256.hex(bytes(f.hex)))
            assertEquals(f.rows, g.rows, f.name)
            assertEquals(f.cols, g.cols, f.name)
            assertEquals(f.lat0, g.lat0, f.name)
            assertEquals(f.lon0, g.lon0, f.name)
            assertEquals(f.dlat, g.dlat, f.name)
            assertEquals(f.dlon, g.dlon, f.name)
            assertEquals(f.nodata, g.values.count { it.isNaN() }, "${f.name} NODATA")
            assertTrue(g.notes.isEmpty(), "${f.name}: ${g.notes}")
        }
        assertEquals(setOf("ggf", "gtx", "isg"), grids.values.map { it.format }.toSet())
    }

    @Test
    fun sha256KnownVectors() {
        assertEquals("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", Sha256.hex(ByteArray(0)))
        assertEquals("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad", Sha256.hex("abc".encodeToByteArray()))
        assertEquals(
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
            Sha256.hex("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq".encodeToByteArray()),
        )
    }

    @Test
    fun valuesMatchPython() {
        for (c in GEOID_VALUES) {
            val g = grids.getValue(c.file)
            val what = "${c.file} ${c.lat},${c.lon} ${c.interpolation}"
            if (c.expected.isNaN()) {
                assertFailsWith<GeoidException>(what) { g.value(c.lat, c.lon, c.interpolation) }
            } else {
                near(c.expected, g.value(c.lat, c.lon, c.interpolation), 1e-12, what)
            }
        }
    }

    @Test
    fun formatsAgree() {
        val ggf = grids.getValue("RU-MOW_truth.ggf")
        val gtx = grids.getValue("RU-MOW_truth.gtx")
        val isg = grids.getValue("RU-MOW_truth.isg")
        for (k in ggf.values.indices) {
            assertEquals(gtx.values[k], ggf.values[k])
            near(gtx.values[k], isg.values[k], 1e-6, "isg #$k")
        }
    }

    @Test
    fun edgesNodataAndErrors() {
        val g = grids.getValue("RU-MOW_truth.ggf")
        near(g.node(g.rows - 1, 0), g.value(g.lat1, g.lon0), 1e-12, "СЗ узел")
        near(g.node(0, g.cols - 1), g.value(g.lat0, g.lon1), 1e-12, "ЮВ узел")
        assertFailsWith<GeoidException> { g.value(g.lat1 + 1e-6, g.lon0) }
        assertFailsWith<GeoidException> { g.value(55.1, g.lon1 + 0.001) }    // не переходит на соседнюю строку
        assertFailsWith<GeoidException> { g.value(Double.NaN, 39.2) }
        assertFailsWith<GeoidException> { g.value(g.lat0 + 0.5 * g.dlat, g.lon0 + 5 * g.dlon, "bicubic") }
        assertFailsWith<GeoidException> { g.value(55.1, 39.3, "nearest") }
        for (name in listOf("nodata.ggf", "nodata.gtx", "nodata.isg")) {
            val n = grids.getValue(name)
            assertTrue(n.node(3, 4).isNaN())
            val e = assertFailsWith<GeoidException> { n.value(55.6, 38.8) }
            assertTrue("NODATA" in e.message!!)
            assertTrue(n.value(55.4, 38.6).isFinite())
        }
        // Повреждённые файлы.
        val raw = bytes(GEOID_FILES.first { it.name == "RU-MOW_truth.ggf" }.hex)
        assertFailsWith<GeoidException> { GeoidGrid.parse(raw.copyOf(raw.size - 20), "cut.ggf") }
        assertFailsWith<GeoidException> { GeoidGrid.parse(ByteArray(200), "x.ggf") }
        val gtxRaw = bytes(GEOID_FILES.first { it.name == "RU-MOW_truth.gtx" }.hex)
        assertFailsWith<GeoidException> { GeoidGrid.parse(gtxRaw, "x.tif") }     // GeoTIFF — только в Python
        assertEquals("ggf", GeoidGrid.parse(raw, "grid.bin").format)
        // Неизвестные флаги GGF — читается, с замечанием.
        val other = raw.copyOf().also { it[136] = 7 }
        val g2 = GeoidGrid.parse(other, "flags.ggf")
        assertTrue(g2.notes.isNotEmpty() && "внимание" in g2.describe())
        assertTrue(g2.values.contentEquals(g.values))
        // Без хвоста min/max.
        assertTrue(GeoidGrid.parse(raw.copyOf(raw.size - 16), "short.ggf").values.contentEquals(g.values))
    }

    @Test
    fun globalWrap() {
        val rows = 19
        val cols = 36
        val v = DoubleArray(rows * cols) { k ->
            val lat = -90.0 + 10 * (k / cols)
            val lon = -180.0 + 10 * (k % cols)
            20 * cos(lat * kotlin.math.PI / 180) * sin(lon * kotlin.math.PI / 180) + 5
        }
        val g = GeoidGrid(-90.0, -180.0, 10.0, 10.0, rows, cols, v, "global")
        assertEquals(36, g.period)
        near(g.value(45.0, 175.0), g.value(45.0, -185.0), 1e-12, "wrap −185")
        near(g.value(45.0, 175.0), g.value(45.0, 535.0), 1e-12, "wrap 535")
        near((g.value(45.0, 170.0) + g.value(45.0, 180.0)) / 2, g.value(45.0, 175.0), 1e-12, "антимеридиан")
        assertTrue(g.value(45.0, 179.0, "bicubic").isFinite())
    }

    @Test
    fun localizationMatchesPython() {
        for (c in GEOID_LOC_CASES) {
            val g = grids.getValue(c.file)
            val d = localize(c.pairs, gnssDatum = "PZ-90.11", heightModel = c.model, geoid = g, geoidInterpolation = c.interpolation)
            assertEquals(c.heightModel, d.heightModel, c.name)
            assertEquals(GeoidRef(c.file, g.sha256, c.interpolation), d.geoid, c.name)
            checkParams(c.name, d, c.expected)
            checkDiag(c.name, d, c.diag, c.residDiag)
            assertEquals(c.warnings, d.warnings.map { it.code }, "${c.name} warnings")
            val ex = suggestExclusions(c.pairs, gnssDatum = "PZ-90.11", heightModel = c.model, geoid = g, geoidInterpolation = c.interpolation)
            assertEquals(c.exclusions, ex.map { "${it.name}:${it.part}" }, "${c.name} exclusions")
            c.check.forEachIndexed { i, p ->
                val w = WgsPoint(p[0], p[1], p[2])
                val l = d.toLocal(w)
                near(c.local[i][0], l.x, 1e-6, "${c.name} #$i x")
                near(c.local[i][1], l.y, 1e-6, "${c.name} #$i y")
                near(c.local[i][2], l.height, 1e-6, "${c.name} #$i H")
                val b = d.toWgs(LocalPoint(c.local[i][0], c.local[i][1], c.local[i][2]))
                near(c.back[i][0], b.lat, 1e-10, "${c.name} #$i B")
                near(c.back[i][1], b.lon, 1e-10, "${c.name} #$i L")
                near(c.back[i][2], b.h, 1e-6, "${c.name} #$i h")
                // Туда и обратно.
                val r = d.toWgs(l)
                near(w.h, r.h, 1e-6, "${c.name} #$i туда-обратно h")
                near(w.lat, r.lat, 1e-11, "${c.name} #$i туда-обратно B")
            }
            checkQuality(c.name, d, c.check, c.quality)
        }
    }

    @Test
    fun jsonWithGeoidReference() {
        val g = grids.getValue("RU-MOW_truth.ggf")
        assertFailsWith<GeoidException> { LocalizationDatum.fromJson(PY_GEOID_DATUM_JSON) }
        assertFailsWith<GeoidException> { LocalizationDatum.fromJson(PY_GEOID_DATUM_JSON, grids.getValue("RU-MOW_truth.gtx")) }
        val noGrid = LocalizationDatum.fromJson(PY_GEOID_DATUM_JSON, requireGeoid = false)
        assertNull(noGrid.geoidGrid)
        assertFailsWith<GeoidException> { noGrid.toLocal(WgsPoint(55.09, 39.3, 200.0)) }
        val d = LocalizationDatum.fromJson(PY_GEOID_DATUM_JSON, g)
        assertEquals("geoid_plane", d.heightModel)
        assertEquals(GeoidRef("RU-MOW_truth.ggf", g.sha256, "bilinear"), d.geoid)
        PY_GEOID_DATUM_CHECK.forEachIndexed { i, p ->
            val l = d.toLocal(WgsPoint(p[0], p[1], p[2]))
            near(PY_GEOID_DATUM_LOCAL[i][2], l.height, 1e-8, "Python-датум #$i H")
            near(PY_GEOID_DATUM_LOCAL[i][0], l.x, 1e-7, "Python-датум #$i x")
        }
        // Сохранение и чтение в Kotlin; ссылка на сетку сохраняется, сама сетка — нет.
        val json = d.toJson()
        assertTrue("\"sha256\": \"${g.sha256}\"" in json && "\"interpolation\": \"bilinear\"" in json)
        assertEquals(d.copy(geoidGrid = null), LocalizationDatum.fromJson(json, requireGeoid = false))
        assertTrue("+proj=vgridshift +grids=RU-MOW_truth.ggf +multiplier=-1" in d.toProjPipeline())
        // Старый JSON — без геоида; сетка к нему — ошибка.
        val old = LocalizationDatum.fromJson(PY_DATUM_JSON)
        assertNull(old.geoid)
        assertEquals(0.0, old.geoidHeight(55.0, 39.0))
        assertFailsWith<GeoidException> { LocalizationDatum.fromJson(PY_DATUM_JSON, g) }
        assertFailsWith<GeoidException> { old.withGeoid(g) }
    }

    @Test
    fun argumentAndOutsideErrors() {
        val c = GEOID_LOC_CASES.first { it.name == "truth_geoid" }
        val g = grids.getValue(c.file)
        val pairs = c.pairs
        assertFailsWith<LocalizationException> { localize(pairs, heightModel = "geoid") }
        assertFailsWith<LocalizationException> { localize(pairs, geoid = g) }
        assertFailsWith<LocalizationException> { localize(pairs, heightModel = "quasi", geoid = g) }
        assertFailsWith<LocalizationException> { localize(pairs, heightModel = "geoid", geoid = g, geoidInterpolation = "cubic") }
        val far = LocalizationPair("FAR", 56.5, 39.3, 200.0, 0.0, 0.0, 0.0, Use.NONE)
        assertFailsWith<GeoidException> { localize(pairs + far, gnssDatum = "PZ-90.11", heightModel = "geoid", geoid = g) }
        val d = localize(pairs, gnssDatum = "PZ-90.11", heightModel = "geoid_plane", geoid = g)
        assertFailsWith<GeoidException> { d.toLocal(WgsPoint(56.5, 39.3, 200.0)) }
        assertFailsWith<GeoidException> { d.toWgs(LocalPoint(d.tx + 200_000, d.ty, 150.0)) }
        // По умолчанию — прежняя модель plane без геоида.
        val plain = localize(pairs, gnssDatum = "PZ-90.11")
        assertEquals("plane", plain.heightModel)
        assertNull(plain.geoid)
        assertTrue(abs(plain.c0) > 1.0)
    }
}
