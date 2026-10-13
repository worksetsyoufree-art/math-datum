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

    /**
     * Участок в ~85 км от ЦМ базовой СК, истина = база + малая поправка (сдвиг 2,5/1,5 м и поворот ≈ 4″).
     * Чистое подобие ограничено градиентом масштаба проекции; калибровка поверх базы держит миллиметры.
     */
    @Test
    fun calibrationOverKnownCrsBeatsPureSimilarityFarFromCm() {
        val crs = Catalog.sk42Gk(7)                          // ЦМ 39°
        val base = CrsGeoref(crs, swapXY = true)             // x — восток, y — север (CAD), метры
        val centre = Geodetic.ofDegrees(55.7, 37.6)
        val (n0, e0, _) = crs.fromWgs84(centre)
        val plane = LocalPlane(centre.lat, centre.lon)
        val corr = Similarity2D(1.0 + 3e-6, 2e-5, 2.5, 1.5)
        val truthOf = { x: Double, y: Double ->
            val w = base.toWgs84(x, y, 0.0)   // h после Гельмерта ≠ 0; горизонталь зависит от h, держим согласованно
            val (e, n) = plane.toPlane(w)
            val (e2, n2) = corr.apply(e, n)
            plane.fromPlane(e2, n2, w.h)
        }
        val pairs = grid.map { (dx, dy) -> ControlPair(SurfacePoint(e0 + dx, n0 + dy), truthOf(e0 + dx, n0 + dy)) }

        val cal = Localization.calibrate(base, pairs)
        assertIs<LocalizationResult.Ok>(cal)
        assertTrue(cal.rmsM < 0.0005, "calibrated rms=${cal.rmsM}")
        val check = truthOf(e0 + 1234.5, n0 - 2345.6)
        val back = cal.georef.fromWgs84(check)
        assertEquals(e0 + 1234.5, back.x, 0.001); assertEquals(n0 - 2345.6, back.y, 0.001)
        assertTrue(Geodesy.haversine(cal.georef.toWgs84(e0 + 1234.5, n0 - 2345.6), check) < 0.002)

        val pure = Localization.localize(pairs)
        assertIs<LocalizationResult.Ok>(pure)
        assertTrue(pure.rmsM > 10 * cal.rmsM, "pure=${pure.rmsM} cal=${cal.rmsM}")
    }

    @Test
    fun calibratedGeorefSurvivesJsonAndHasHeightPlane() {
        val crs = Catalog.sk42Gk(7)
        val base = CrsGeoref(crs, swapXY = true)
        val centre = Geodetic.ofDegrees(55.7, 37.6)
        val (n0, e0, _) = crs.fromWgs84(centre)
        val pairs = grid.map { (dx, dy) ->
            val x = e0 + dx; val y = n0 + dy; val z = 120.0 + dx * 0.002
            val w = base.toWgs84(x, y, z)
            ControlPair(SurfacePoint(x, y, z), Geodetic(w.lat, w.lon, w.h + 0.3 + 5e-5 * dx - 1e-4 * dy))
        }
        val r = Localization.calibrate(base, pairs, LocalizationOptions(heightMode = HeightMode.PLANE))
        assertIs<LocalizationResult.Ok>(r)
        assertTrue(r.heightRmsM!! < 1e-6, "h rms=${r.heightRmsM}")
        val again = GeorefJson.decode(GeorefJson.encode(r.georef))
        assertIs<CalibratedGeoref>(again)
        val w1 = r.georef.toWgs84(e0 + 50.0, n0 + 60.0, 130.0); val w2 = again.toWgs84(e0 + 50.0, n0 + 60.0, 130.0)
        assertEquals(w1.h, w2.h, 1e-9); assertEquals(w1.lat, w2.lat, 1e-14)
        val s = r.georef.fromWgs84(w1)
        assertEquals(e0 + 50.0, s.x, 1e-4); assertEquals(130.0, s.z, 1e-4)
    }

    @Test
    fun calibrationErrorsAreExplicit() {
        val base = CrsGeoref(Catalog.utm(37))
        assertIs<LocalizationResult.Failed>(Localization.calibrate(base, emptyList()))
        assertIs<LocalizationResult.Failed>(Localization.calibrate(base, listOf(pair(0.0, 0.0))))
    }
}
