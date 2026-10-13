package mathdatum.app

import mathdatum.core.SurfaceAnalysis
import mathdatum.core.SurfaceVertices

/** Демо-чертёж: участок ~800 × 600 м в Москве, система UTM 37N, CAD-оси, метры, плюс «мусорная» точка в нуле. */
object DemoData {
    fun surface(): SurfaceInfo {
        val xs = ArrayList<Double>(); val ys = ArrayList<Double>()
        for (i in 0..40) for (j in 0..30) {
            xs += 413_000.0 + i * 20.0 + (j % 3) * 1.5
            ys += 6_178_800.0 + j * 20.0 + (i % 4) * 1.2
        }
        xs += 0.0; ys += 0.0
        val v = SurfaceVertices(xs.toDoubleArray(), ys.toDoubleArray())
        val b = SurfaceAnalysis.robustBounds(v)!!.bounds
        return SurfaceInfo("Демо: участок в Москве", v, b)
    }

    const val DEMO_LAT = 55.7487
    const val DEMO_LON = 37.6183
}
