package mathdatum.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/** Реальные файлы пользователя (участок «Траншея» в Московской области) из desktopTest/resources. */
class RealFilesTest {
    private fun res(name: String) = RealFilesTest::class.java.getResourceAsStream("/$name")!!.readBytes().decodeToString()

    @Test
    fun trenchSurfaceParsesCompletely() {
        val m = SurfaceV1.parse(res("trench.surface.txt"))
        assertEquals("ACAD-Траншея с раскрытием для полигона", m.title)
        assertEquals(1546, m.points.size); assertEquals(2246, m.triangleCount)
        val h = assertNotNull(m.hints, "служебные точки должны распознаваться: центр, min, max, near")
        assertEquals(453677.068, h.min.x, 1e-9); assertEquals(2259093.783, h.max.y, 1e-9)
        val rb = assertNotNull(SurfaceAnalysis.robustBounds(m.points))
        assertEquals(0, rb.dropped)
        assertEquals(h.min.x, rb.bounds.minX, 1e-9); assertEquals(h.max.y, rb.bounds.maxY, 1e-9)
    }

    @Test
    fun datumAndSurfaceFindEachOtherWithHeightEvidence() {
        val mesh = SurfaceV1.parse(res("trench.surface.txt"))
        val crs = GsiDatumJson.decode(res("mggt-msk50-zone2.datum.json"))
        val b = SurfaceAnalysis.robustBounds(mesh.points)!!.bounds
        // X — север, Y — восток, метры: «подбор» должен вернуть именно эту СК без переопределения осей
        val ev = assertNotNull(crs.checkHelmertDirection(b.centerX, b.centerY, mesh.service.first().z))
        assertEquals(HelmertDirection.WGS84_TO_LOCAL, ev.suggested)
        val resolved = crs.withHelmertDirection(ev.suggested!!, confirmed = true)
        val where = resolved.toWgs84(b.centerX, b.centerY, 125.0)
        assertTrue(where.latDeg in 55.6..55.8 && where.lonDeg in 38.4..38.7, "${where.latDeg}, ${where.lonDeg}")
        val found = DatumFinder.find(b, Anchor(where), Catalog(listOf(resolved) + Catalog.demo().entries))
        val top = found.first()
        assertEquals(resolved.id, top.crs.id)
        assertEquals(false, top.swapXY); assertEquals(1.0, top.unitToMeters)
        assertEquals(MatchStatus.MATCH, top.status)
    }
}
