package mathdatum.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class SurfaceTest {
    private fun cloud(n: Int, ox: Double, oy: Double, span: Double): Pair<DoubleArray, DoubleArray> {
        val xs = DoubleArray(n) { ox + span * ((it * 7919) % 1000) / 1000.0 }
        val ys = DoubleArray(n) { oy + span * ((it * 104729) % 1000) / 1000.0 }
        return xs to ys
    }

    @Test
    fun strayVerticesAreDropped() {
        val (x, y) = cloud(2000, 413_000.0, 6_178_800.0, 800.0)
        x[5] = 0.0; y[5] = 0.0           // нулевая точка чертежа
        x[77] = 1e9; y[77] = -1e9        // мусор
        y[200] = Double.NaN
        val r = SurfaceAnalysis.robustBounds(SurfaceVertices(x, y))
        assertNotNull(r)
        assertEquals(3, r.dropped)
        assertTrue(r.bounds.minX >= 413_000.0 && r.bounds.maxX <= 413_800.0)
        assertTrue(r.bounds.minY >= 6_178_800.0 && r.bounds.maxY <= 6_179_600.0)
    }

    @Test
    fun wideRealSurfaceKeepsItsTails() {
        // плотное ядро (95 %) + длинный разреженный хвост (5 %): хвост настоящий, отбрасывать нельзя
        val n = 2000
        val x = DoubleArray(n) { if (it % 20 == 0) 460_000.0 + (it % 17) * 700.0 else 461_000.0 + (it % 100) * 5.0 }
        val y = DoubleArray(n) { if (it % 20 == 0) 2_240_000.0 + (it % 13) * 1500.0 else 2_257_000.0 + (it % 90) * 5.0 }
        val r = assertNotNull(SurfaceAnalysis.robustBounds(SurfaceVertices(x, y)))
        assertEquals(0, r.dropped)
        assertEquals(x.min(), r.bounds.minX); assertEquals(y.max(), r.bounds.maxY)
    }

    @Test
    fun boundsOfSmallOrDegenerateInput() {
        assertNull(SurfaceAnalysis.robustBounds(SurfaceVertices(DoubleArray(0), DoubleArray(0))))
        assertNull(SurfaceAnalysis.robustBounds(SurfaceVertices(doubleArrayOf(Double.NaN), doubleArrayOf(1.0))))
        val one = SurfaceAnalysis.robustBounds(SurfaceVertices(doubleArrayOf(5.0), doubleArrayOf(7.0)))
        assertNotNull(one); assertEquals(1, one.used); assertEquals(0.0, one.bounds.diagonal)
        val same = SurfaceAnalysis.robustBounds(SurfaceVertices(DoubleArray(10) { 3.0 }, DoubleArray(10) { 4.0 }))
        assertNotNull(same); assertEquals(0, same.dropped)
    }

    @Test
    fun unitsFromInsunitsAndSize() {
        val metres = SurfaceBounds(0.0, 800.0, 0.0, 600.0)
        assertEquals(1.0, SurfaceUnits.candidates(metres).first())
        val mm = SurfaceBounds(0.0, 800_000.0, 0.0, 600_000.0)
        assertEquals(0.001, SurfaceUnits.candidates(mm).first())
        assertEquals(0.01, SurfaceUnits.candidates(mm, insunits = 5).first())  // $INSUNITS=cm имеет приоритет
        assertEquals(0.3048, SurfaceUnits.candidates(metres, insunits = 2).first())
        assertEquals(SurfaceUnits.candidates(metres).toSet(), setOf(1.0, 0.001, 0.01, 1000.0)) // ничего не теряем
        assertEquals(1.0, SurfaceUnits.candidates(metres, insunits = 0).first())
    }
}
