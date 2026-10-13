package mathdatum.core

import kotlin.math.sqrt

/** Эллипсоид вращения. Производные величины считаются один раз. */
class Ellipsoid(val name: String, val a: Double, val invF: Double, val id: String? = null) {
    val f: Double = 1.0 / invF
    val e2: Double = f * (2.0 - f)
    val e: Double = sqrt(e2)
    val b: Double = a * (1.0 - f)
    val n: Double = f / (2.0 - f)

    companion object {
        val WGS84 = Ellipsoid("WGS84", 6378137.0, 298.257223563, "WGS84")
        val GRS80 = Ellipsoid("GRS80", 6378137.0, 298.257222101, "GRS80")
        val KRASSOVSKY = Ellipsoid("Krassovsky 1940", 6378245.0, 298.3, "KRASSOVSKY")
        val BESSEL = Ellipsoid("Bessel 1841", 6377397.155, 299.1528128, "BESSEL")
        val GSK2011 = Ellipsoid("GSK-2011", 6378136.5, 298.2564151, "GSK2011")
        val PZ90_11 = Ellipsoid("PZ-90.11", 6378136.0, 298.25784, "PZ90_11")

        val known: List<Ellipsoid> get() = listOf(WGS84, GRS80, KRASSOVSKY, BESSEL, GSK2011, PZ90_11)
        fun byId(id: String): Ellipsoid? = known.firstOrNull { it.id == id }
    }
}
