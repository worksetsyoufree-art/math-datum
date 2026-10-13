package mathdatum.core

import kotlin.math.cos
import kotlin.math.sin
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Horn3DTest {
    private fun rotation(ax: Double, ay: Double, az: Double): DoubleArray {
        val cx = cos(ax); val sx = sin(ax); val cy = cos(ay); val sy = sin(ay); val cz = cos(az); val sz = sin(az)
        // R = Rz · Ry · Rx
        return doubleArrayOf(
            cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx,
            sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx,
            -sy, cy * sx, cy * cx,
        )
    }

    private val pts = listOf(
        Vec3(0.0, 0.0, 0.0), Vec3(100.0, 0.0, 5.0), Vec3(0.0, 80.0, 12.0), Vec3(90.0, 70.0, -3.0),
        Vec3(40.0, 30.0, 20.0), Vec3(-30.0, 60.0, 8.0),
    )

    @Test
    fun hornRecoversKnownTransformExactly() {
        val truth = Similarity3D(1.0003, rotation(0.05, -0.08, 2.1), Vec3(1500.0, -200.0, 35.0))
        val q = pts.map { truth.apply(it) }
        val s = assertNotNull(Horn.solve(pts, q))
        assertEquals(truth.scale, s.scale, 1e-12)
        for (i in 0 until 9) assertEquals(truth.r[i], s.r[i], 1e-12)
        pts.forEach { val m = s.apply(it); val e = truth.apply(it); assertEquals(e.x, m.x, 1e-9); assertEquals(e.z, m.z, 1e-9) }
        val back = s.applyInverse(q[3]); assertEquals(pts[3].x, back.x, 1e-9); assertEquals(pts[3].y, back.y, 1e-9)
        val fixed = assertNotNull(Horn.solve(pts, pts.map { Similarity3D(1.0, truth.r, truth.t).apply(it) }, fixScale = true))
        assertEquals(1.0, fixed.scale, 0.0)
    }

    @Test
    fun degenerateInputsReturnNull() {
        val line = listOf(Vec3(0.0, 0.0, 0.0), Vec3(1.0, 1.0, 1.0), Vec3(2.0, 2.0, 2.0), Vec3(5.0, 5.0, 5.0))
        assertNull(Horn.solve(line, line))
        assertNull(Horn.solve(pts.take(2), pts.take(2)))
        assertNull(Horn.solve(List(4) { Vec3(1.0, 2.0, 3.0) }, List(4) { Vec3(1.0, 2.0, 3.0) }))
    }

    @Test
    fun localize3DOnTiltedSurface() {
        val plane = LocalPlane(55.7 * DEG, 37.6 * DEG)
        val truth = Similarity3D(1.0, rotation(0.03, -0.02, 0.9), Vec3(120.0, -80.0, 4.0))
        val h0 = 150.0
        val pairs = pts.map { s ->
            val v = truth.apply(s)
            ControlPair(SurfacePoint(s.x, s.y, s.z), plane.fromPlane(v.x, v.y, v.z + h0))
        }
        val r = Localization.localize3D(pairs)
        assertIs<LocalizationResult3D.Ok>(r)
        assertTrue(r.rmsM < 1e-6, "rms=${r.rmsM}")
        // плоский 2D-вариант тут неточен (наклон ≈ 2°, 3° по осям)
        val flat = Localization.localize(pairs)
        assertIs<LocalizationResult.Ok>(flat)
        assertTrue(flat.rmsM > 0.05, "flat rms=${flat.rmsM}")

        val chk = Vec3(33.0, 44.0, 6.0)
        val w = r.georef.toWgs84(chk.x, chk.y, chk.z)
        val exp = truth.apply(chk).let { plane.fromPlane(it.x, it.y, it.z + h0) }
        assertEquals(exp.h, w.h, 1e-6); assertEquals(exp.lat, w.lat, 1e-12)
        val s = r.georef.fromWgs84(w)
        assertEquals(chk.x, s.x, 1e-6); assertEquals(chk.z, s.z, 1e-6)

        val again = GeorefJson.decode(GeorefJson.encode(r.georef))
        assertIs<LocalizedGeoref3D>(again)
        assertEquals(w.h, again.toWgs84(chk.x, chk.y, chk.z).h, 1e-9)
    }

    @Test
    fun localize3DReportsProblemsExplicitly() {
        val g = { x: Double, y: Double, z: Double -> ControlPair(SurfacePoint(x, y, z), Geodetic.ofDegrees(55.7 + y * 1e-5, 37.6 + x * 1e-5, z)) }
        assertIs<LocalizationResult3D.Failed>(Localization.localize3D(listOf(g(0.0, 0.0, 0.0), g(1.0, 1.0, 1.0))))
        assertIs<LocalizationResult3D.Failed>(Localization.localize3D(listOf(g(0.0, 0.0, 0.0), g(1.0, 0.0, 0.0), ControlPair(SurfacePoint(0.0, 1.0), Geodetic.ofDegrees(55.7, 37.6)))))
        assertIs<LocalizationResult3D.Failed>(Localization.localize3D(listOf(g(0.0, 0.0, 0.0), g(10.0, 10.0, 1.0), g(20.0, 20.0, 2.0))))
    }
}
