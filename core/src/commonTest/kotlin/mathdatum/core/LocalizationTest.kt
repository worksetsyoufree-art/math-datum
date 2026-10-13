package mathdatum.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

class LocalizationTest {
    /** «Истина»: СК с ЦМ рядом с участком (как МСК), чертёж — CAD, x = восток, y = север, начало сдвинуто. */
    private val truth = CrsDef(
        id = "t", name = "truth", ellipsoid = Ellipsoid.WGS84, helmert = null,
        tm = TransverseMercator(Ellipsoid.WGS84, 0.0, 37.5 * DEG, 1.0, 1_500_000.0, 0.0),
    )
    private val e0 = 1_500_000.0 + 5_000.0 // участок рядом с ЦМ, как в МСК; при 20 км от ЦМ подобие даёт ≈7 мм (предел модели)
    private val n0 = 6_180_000.0

    private fun pair(dx: Double, dy: Double, z: Double = Double.NaN) =
        ControlPair(SurfacePoint(dx, dy, z), truth.toWgs84(n0 + dy, e0 + dx, 0.0))

    private val grid = listOf(
        -4800.0 to -4200.0, 4900.0 to -4700.0, 4100.0 to 4800.0, -4600.0 to 4300.0,
        100.0 to 200.0, 2500.0 to -300.0, -2700.0 to 1900.0, 300.0 to -3900.0,
    )

    @Test
    fun eightPointsOn10kmGiveMillimetres() {
        val r = Localization.localize(grid.map { pair(it.first, it.second) })
        assertIs<LocalizationResult.Ok>(r)
        assertTrue(r.rmsM < 0.004, "rms=${r.rmsM}")
        assertTrue(r.residuals.all { it.distance < 0.008 })
        assertNull(r.suspectedOutlier)
        // контрольная точка не участвовала в подгонке
        val check = pair(1234.5, -2345.6)
        val s = r.georef.fromWgs84(check.wgs84)
        assertEquals(1234.5, s.x, 0.005); assertEquals(-2345.6, s.y, 0.005)
        val w = r.georef.toWgs84(1234.5, -2345.6)
        assertTrue(Geodesy.haversine(w, check.wgs84) < 0.01)
    }

    @Test
    fun rotationOfDrawingIsRecovered() {
        // чертёж повёрнут на 30° относительно истины
        val th = 30.0 * DEG
        val rotated = grid.map { (x, y) ->
            val p = pair(x, y)
            ControlPair(SurfacePoint(x * kotlin.math.cos(th) - y * kotlin.math.sin(th), x * kotlin.math.sin(th) + y * kotlin.math.cos(th)), p.wgs84)
        }
        val r = Localization.localize(rotated)
        assertIs<LocalizationResult.Ok>(r)
        assertTrue(r.rmsM < 0.004)
        // + сближение меридианов между ЦМ истины (37,5°) и центром участка (≈0,07°)
        assertEquals(-th, r.similarity.rotation, 0.005)
    }

    @Test
    fun degenerateCasesAreExplicitNotNaN() {
        assertIs<LocalizationResult.Failed>(Localization.localize(emptyList()))
        assertIs<LocalizationResult.Failed>(Localization.localize(listOf(pair(0.0, 0.0))))
        val same = Localization.localize(listOf(pair(5.0, 5.0), pair(5.0, 5.0), pair(5.0, 5.0)))
        assertIs<LocalizationResult.Failed>(same)
        val one = Localization.localize(listOf(pair(10.0, 20.0)), LocalizationOptions(allowSinglePair = true))
        assertIs<LocalizationResult.Ok>(one)
        assertTrue(LocalizationWarning.SINGLE_PAIR_TRANSLATION_ONLY in one.warnings)
        assertTrue(one.rmsM < 1e-6)
        val two = Localization.localize(listOf(pair(0.0, 0.0), pair(1000.0, 500.0)))
        assertIs<LocalizationResult.Ok>(two)
        assertTrue(LocalizationWarning.NO_REDUNDANCY in two.warnings)
    }

    @Test
    fun grossErrorInOnePairIsFlagged() {
        val pairs = grid.mapIndexed { i, (x, y) -> if (i == 3) pair(x, y).let { ControlPair(SurfacePoint(x + 5.0, y - 4.0), it.wgs84) } else pair(x, y) }
        val r = Localization.localize(pairs)
        assertIs<LocalizationResult.Ok>(r)
        assertEquals(3, r.suspectedOutlier)
        assertTrue(LocalizationWarning.OUTLIER_SUSPECTED in r.warnings)
    }

    @Test
    fun resultDoesNotDependOnPairOrder() {
        val a = Localization.localize(grid.map { pair(it.first, it.second) })
        val b = Localization.localize(grid.reversed().map { pair(it.first, it.second) })
        assertIs<LocalizationResult.Ok>(a); assertIs<LocalizationResult.Ok>(b)
        assertEquals(a.rmsM, b.rmsM, 1e-9)
        assertEquals(a.similarity.scale, b.similarity.scale, 1e-12)
    }

    // высота истины: H_wgs = z + 0.5 + 1e-4·x − 2e-4·y (наклон ВСКО); у truth h = 0 по построению, добавим вручную
    private fun pairWithHeight(dx: Double, dy: Double): ControlPair {
        val z = 100.0 + dx * 0.001
        val hw = z + 0.5 + 1e-4 * dx - 2e-4 * dy
        val p = pair(dx, dy, z)
        return ControlPair(p.surface, Geodetic(p.wgs84.lat, p.wgs84.lon, hw))
    }

    @Test
    fun heightPlaneRecoversSlopeAndOffsetMode() {
        val pairs = grid.map { pairWithHeight(it.first, it.second) }
        val r = Localization.localize(pairs, LocalizationOptions(heightMode = HeightMode.PLANE))
        assertIs<LocalizationResult.Ok>(r)
        assertTrue(r.heightRmsM!! < 1e-6, "h rms=${r.heightRmsM}")
        assertTrue(LocalizationWarning.HEIGHT_PLANE_FALLBACK !in r.warnings)
        val c = pairWithHeight(777.0, -888.0)
        val w = r.georef.toWgs84(c.surface.x, c.surface.y, c.surface.z)
        assertEquals(c.wgs84.h, w.h, 1e-5)
        assertEquals(c.surface.z, r.georef.fromWgs84(c.wgs84).z, 1e-5)
        val off = Localization.localize(pairs)
        assertIs<LocalizationResult.Ok>(off)
        assertTrue(off.heightRmsM!! > 0.1) // сдвигом наклон не убрать
    }

    @Test
    fun heightPlaneFallsBackOnCollinearOrFewPoints() {
        val line = listOf(0.0 to 0.0, 100.0 to 50.0, 200.0 to 100.0, 300.0 to 150.0).map { pairWithHeight(it.first, it.second) }
        val r = Localization.localize(line, LocalizationOptions(heightMode = HeightMode.PLANE))
        assertIs<LocalizationResult.Ok>(r)
        assertTrue(LocalizationWarning.HEIGHT_PLANE_FALLBACK in r.warnings)
        assertTrue(!r.heightRmsM!!.isNaN())
        val two = Localization.localize(line.take(2), LocalizationOptions(heightMode = HeightMode.PLANE))
        assertIs<LocalizationResult.Ok>(two)
        assertTrue(LocalizationWarning.HEIGHT_PLANE_FALLBACK in two.warnings)
    }

    @Test
    fun noHeightsIsReported() {
        val r = Localization.localize(grid.map { pair(it.first, it.second) })
        assertIs<LocalizationResult.Ok>(r)
        assertTrue(LocalizationWarning.NO_HEIGHTS in r.warnings)
        assertNull(r.heightRmsM)
    }
}
