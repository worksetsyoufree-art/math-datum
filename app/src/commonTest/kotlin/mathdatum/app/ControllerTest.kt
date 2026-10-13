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
}
