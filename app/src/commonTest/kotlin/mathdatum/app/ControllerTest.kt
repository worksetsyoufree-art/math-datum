package mathdatum.app

import mathdatum.core.Catalog
import mathdatum.core.Geodetic
import mathdatum.core.Geodesy
import mathdatum.core.SurfaceBounds
import mathdatum.core.SurfaceVertices
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ControllerTest {
    private val moscow = Geodetic.ofDegrees(55.75, 37.62)

    // Чертёж UTM 37N в миллиметрах, CAD (x — восток, y — север)
    private fun surface() = SurfaceInfo(
        "demo",
        SurfaceVertices(doubleArrayOf(413_000_000.0, 413_800_000.0), doubleArrayOf(6_178_800_000.0, 6_179_400_000.0)),
        SurfaceBounds(413_000_000.0, 413_800_000.0, 6_178_800_000.0, 6_179_400_000.0),
    )

    @Test
    fun autoFindsAndAppliesRightSystem() {
        val c = GeorefController(Catalog.demo(), surface())
        c.setAnchor(moscow.latDeg, moscow.lonDeg)
        c.runAuto()
        assertTrue(c.autoRan && c.candidates.isNotEmpty())
        c.apply(c.candidates.first())
        val a = assertNotNull(c.applied)
        assertTrue(a.description.contains("UTM 37") && a.description.contains("миллиметры") && a.description.contains("X — восток"))
        val mid = a.georef.toWgs84(413_400_000.0, 6_179_100_000.0)
        assertTrue(Geodesy.haversine(mid, moscow) < 2_000)
        assertTrue(c.export()!!.contains("\"format\""))
    }

    @Test
    fun withoutMarksWarnsAboutIndirectChoice() {
        val c = GeorefController(Catalog.demo(), surface())
        c.runAuto()
        c.apply(c.candidates.first())
        assertTrue(c.applied!!.warnings.any { it.contains("косвенным") })
    }

    @Test
    fun pickFiltersAndApplies() {
        val c = GeorefController(Catalog.demo(), surface())
        c.query = "utm 36"
        assertEquals(listOf("demo:utm36"), c.filteredCatalog().map { it.id })
        c.pickUnit = 0.001; c.pickSwap = true
        c.pick(c.filteredCatalog().first())
        assertTrue(c.applied!!.description.contains("X — восток, Y — север"))
    }

    @Test
    fun pointsFlowWarnsButNeverBlocks() {
        val c = GeorefController(Catalog.demo(), surface())
        assertNull(c.applied)
        c.addPair(0.0, 0.0, 55.75, 37.62)
        assertNotNull(c.applied)                                   // одна точка: можно, с предупреждением
        assertTrue(c.applied!!.warnings.any { it.contains("Одна точка") })
        c.addPair(1000.0, 0.0, 55.75, 37.6346)
        assertTrue(c.applied!!.warnings.any { it.contains("Две точки") })
        c.addPair(0.0, 1000.0, 55.759, 37.62)
        c.addPair(1000.0, 1000.0, 55.759, 37.6346)
        val st = c.pairStatuses()
        assertEquals(4, st.size)
        assertTrue(st.all { it.level != null })
        c.addPair(500.0, 500.0, 55.80, 37.70)                      // грубая ошибка
        assertTrue(c.pairStatuses().any { it.level == Level.BAD })
        val bad = c.pairStatuses().first { it.level == Level.BAD }.row.id
        c.togglePair(bad)
        assertTrue(c.pairStatuses().first { it.row.id == bad }.level == null)
        c.removePair(bad)
        assertEquals(4, c.pairs.size)
    }

    @Test
    fun duplicateOnlyPointsGiveReadableError() {
        val c = GeorefController(Catalog.demo(), surface())
        c.addPair(5.0, 5.0, 55.75, 37.62); c.addPair(5.0, 5.0, 55.75, 37.62)
        assertNull(c.applied)
        assertNotNull(c.error)
    }

    @Test
    fun levelsAreNotOnlyColors() {
        assertEquals(Level.GOOD, GeorefController.levelOf(0.005))
        assertEquals(Level.WARN, GeorefController.levelOf(0.05))
        assertEquals(Level.BAD, GeorefController.levelOf(1.0))
        assertTrue(Level.entries.all { it.label.isNotBlank() })
    }

    private val miniSurface = "SURFACE_V1\nloaded file name: Мини surfaceId: 0 dxf\n3\n1\n" +
        "10 20 5\n0 0 0\n20 40 10\n10 20 5\n0 0 0\n20 40 10\n10 20 5\n0 1 2\n"

    private val miniDatum = """{"azimuth":"North","orientation":"NE","csCode":"Тест_СК",
        "ellipsoidOriginal":{"paramA":6378137.0,"param1f":298.257223563},
        "ellipsoid":{"type":"K","paramA":6378245.0,"param1f":298.3},
        "projection":{"type":"x.ProjectionTM","longitudeCenter":38.4833333333,"eastShift":2250000.0,"northShift":-5712900.566},
        "parameters7":{"d_x":118.754,"d_y":61.782,"d_z":93.237,"r_x":2.40896,"r_y":3.47502,"r_z":-1.29688,"k":-6.5177}}"""

    @Test
    fun filesAreRecognisedByContent() {
        val c = GeorefController(Catalog.demo(), surface())
        assertTrue(c.parseFile("a.txt", miniSurface) is Opened.Surface)
        assertTrue(c.parseFile("a.json", miniDatum) is Opened.Datum)
        assertTrue(c.parseFile("a.json", "\uFEFF" + miniDatum) is Opened.Datum)
        val bad = c.parseFile("x.bin", "hello") as Opened.Failed
        assertTrue(bad.message.contains("Неизвестный формат"))
        assertTrue((c.parseFile("s.txt", miniSurface.replace("0 1 2", "0 1 9")) as Opened.Failed).message.contains("вне диапазона"))
        assertTrue((c.parseFile("d.json", miniDatum.replace("ProjectionTM", "ProjectionLCC")) as Opened.Failed).message.contains("не поддерживается"))
    }

    @Test
    fun openingSurfaceResetsStateAndUserCrsGoFirst() {
        val c = GeorefController(Catalog.demo(), surface())
        c.addPair(0.0, 0.0, 55.75, 37.62)
        c.open("mini.txt", miniSurface)
        assertEquals("Мини", c.surface.name)
        assertTrue(c.pairs.isEmpty() && c.applied == null && !c.autoRan)
        c.open("d.json", miniDatum)
        assertEquals("user:Тест_СК", c.filteredCatalog().first().id)
        assertEquals(Mode.PICK, c.mode)
        c.open("junk", "???")
        assertTrue(c.error!!.contains("Неизвестный формат"))
    }

    @Test
    fun pickUsesNativeAxesAndUnitsByDefault() {
        val c = GeorefController(Catalog.demo(), surface())
        c.open("d.json", miniDatum)
        val crs = c.userCrs.first()
        c.pick(crs)
        assertTrue(c.applied!!.description.contains("X — север") && c.applied!!.description.contains("метры"))
        // у пользовательской СК направление параметров не подтверждено → предупреждение
        assertTrue(c.applied!!.warnings.any { it.contains("не подтверждено") })
        c.pickSwap = true; c.pickUnit = 0.001
        c.pick(crs)
        assertTrue(c.applied!!.warnings.any { it.contains("изменены") })
    }

    @Test
    fun searchPrefersWholeWords() {
        val c = GeorefController(Catalog.demo(), surface())
        c.query = "zone 7"
        assertEquals("demo:sk42gk7", c.filteredCatalog().first().id)
        c.query = "UTM"
        assertTrue(c.matchCount() >= 3)
        c.query = "zzzz"
        assertEquals(0, c.matchCount())
    }

    @Test
    fun datumNotesExplainApproximation() {
        val demo = Catalog.demo().entries.first()
        assertEquals(null, GeorefController.datumNote(demo))
        val approx = CrsDefFixtures.withStatus(mathdatum.core.DatumStatus.APPROX_UNKNOWN)
        assertTrue(GeorefController.datumNote(approx)!!.contains("в реестре нет"))
        assertTrue(GeorefController.datumNote(CrsDefFixtures.withStatus(mathdatum.core.DatumStatus.HELMERT_PARTIAL))!!.contains("другой части"))
    }
}

private object CrsDefFixtures {
    fun withStatus(s: mathdatum.core.DatumStatus) = mathdatum.core.CrsDef(
        "t", "t", mathdatum.core.Ellipsoid.WGS84, null,
        mathdatum.core.TransverseMercator(mathdatum.core.Ellipsoid.WGS84, 0.0, 0.0, 1.0, 0.0, 0.0), datumStatus = s,
    )
}
