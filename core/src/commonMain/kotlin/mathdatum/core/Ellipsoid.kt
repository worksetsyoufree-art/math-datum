package mathdatum.core

import kotlin.math.sqrt

/** Эллипсоид вращения. Производные величины считаются один раз. */
class Ellipsoid(val name: String, val a: Double, val invF: Double) {
    val f: Double = 1.0 / invF
    val e2: Double = f * (2.0 - f)
    val e: Double = sqrt(e2)
    val b: Double = a * (1.0 - f)
    val n: Double = f / (2.0 - f)

    companion object {
        val WGS84 = Ellipsoid("WGS84", 6378137.0, 298.257223563)
        val GRS80 = Ellipsoid("GRS80", 6378137.0, 298.257222101)
        val KRASSOVSKY = Ellipsoid("Krassovsky 1940", 6378245.0, 298.3)
        val BESSEL = Ellipsoid("Bessel 1841", 6377397.155, 299.1528128)
        val GSK2011 = Ellipsoid("GSK-2011", 6378136.5, 298.2564151)
        val PZ90_11 = Ellipsoid("PZ-90.11", 6378136.0, 298.25784)
    }
}
