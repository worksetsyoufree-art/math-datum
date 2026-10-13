package mathdatum.core

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.ln
import kotlin.math.pow
import kotlin.math.sign
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.math.tan

/**
 * Lambert Conformal Conic (EPSG 9801 — 1SP, 9802 — 2SP), ellipsoidal, формулы EPSG Guidance Note 7-2.
 * Создаётся фабриками [oneParallel] и [twoParallel]; [lon0] — долгота начала (естественного или ложного).
 */
class LambertConformalConic private constructor(
    private val ellipsoid: Ellipsoid,
    override val methodCode: Int,
    override val lon0: Double,
    override val falseEasting: Double,
    override val falseNorthing: Double,
    private val n: Double,
    private val bigF: Double,
    private val rF: Double,
    private val scale: Double,
    private val params: Map<String, Any?>,
) : MapProjection {

    /** Параметры в формате справочника (градусы, метры). */
    fun toParams(): Map<String, Any?> = params

    private val a = ellipsoid.a
    private val e = ellipsoid.e

    /** t(φ) = tan(π/4 − φ/2) / ((1 − e sinφ)/(1 + e sinφ))^(e/2) */
    private fun t(lat: Double): Double {
        val s = sin(lat)
        return tan(PI / 4 - lat / 2) / ((1 - e * s) / (1 + e * s)).pow(e / 2)
    }

    override fun forward(lat: Double, lon: Double): Projected {
        val tt = t(lat)
        val r = if (tt.isFinite()) a * scale * bigF * tt.pow(n) else if (n > 0) 0.0 else Double.POSITIVE_INFINITY
        val theta = n * Geodesy.normLon(lon - lon0)
        return Projected(
            north = falseNorthing + rF - r * cos(theta),
            east = falseEasting + r * sin(theta),
        )
    }

    override fun inverse(north: Double, east: Double): Pair<Double, Double> {
        val dE = east - falseEasting
        val dN = rF - (north - falseNorthing)
        val sg = sign(n)
        val r = sg * hypot(dE, dN)
        val theta = atan2(sg * dE, sg * dN)
        val tt = (r / (a * scale * bigF)).pow(1 / n)
        var phi = PI / 2 - 2 * atan(tt)
        for (i in 0 until 30) {
            val s = sin(phi)
            val next = PI / 2 - 2 * atan(tt * ((1 - e * s) / (1 + e * s)).pow(e / 2))
            val done = abs(next - phi) < 1e-15
            phi = next
            if (done) break
        }
        if (r == 0.0) phi = sg * PI / 2
        return phi to Geodesy.normLon(lon0 + theta / n)
    }

    companion object {
        private fun m(el: Ellipsoid, lat: Double): Double {
            val s = sin(lat)
            return cos(lat) / sqrt(1 - el.e2 * s * s)
        }

        private fun tOf(el: Ellipsoid, lat: Double): Double {
            val s = sin(lat)
            return tan(PI / 4 - lat / 2) / ((1 - el.e * s) / (1 + el.e * s)).pow(el.e / 2)
        }

        /** 1SP: широта естественного начала [lat0], масштаб [k0] на ней. */
        fun oneParallel(el: Ellipsoid, lat0: Double, lon0: Double, k0: Double, fe: Double, fn: Double): LambertConformalConic {
            val n = sin(lat0)
            val t0 = tOf(el, lat0)
            val f = m(el, lat0) / (n * t0.pow(n))
            val rF = el.a * f * t0.pow(n) * k0
            return LambertConformalConic(
                el, MapProjection.LCC_1SP, lon0, fe, fn, n, f, rF, k0,
                linkedMapOf("method" to MapProjection.LCC_1SP.toDouble(), "lat0" to lat0 / DEG, "lon0" to lon0 / DEG, "k0" to k0, "x0" to fe, "y0" to fn),
            )
        }

        /** 2SP: широта ложного начала [latF], стандартные параллели [lat1], [lat2]. */
        fun twoParallel(
            el: Ellipsoid, latF: Double, lonF: Double, lat1: Double, lat2: Double, eF: Double, nF: Double,
        ): LambertConformalConic {
            val m1 = m(el, lat1); val m2 = m(el, lat2)
            val t1 = tOf(el, lat1); val t2 = tOf(el, lat2)
            val n = if (abs(lat1 - lat2) < 1e-12) sin(lat1) else (ln(m1) - ln(m2)) / (ln(t1) - ln(t2))
            val f = m1 / (n * t1.pow(n))
            val rF = el.a * f * tOf(el, latF).pow(n)
            return LambertConformalConic(
                el, MapProjection.LCC_2SP, lonF, eF, nF, n, f, rF, 1.0,
                linkedMapOf(
                    "method" to MapProjection.LCC_2SP.toDouble(), "latF" to latF / DEG, "lonF" to lonF / DEG,
                    "lat1" to lat1 / DEG, "lat2" to lat2 / DEG, "eF" to eF, "nF" to nF,
                ),
            )
        }
    }
}

