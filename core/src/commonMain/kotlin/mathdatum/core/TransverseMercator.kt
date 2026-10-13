package mathdatum.core

import kotlin.math.asin
import kotlin.math.asinh
import kotlin.math.atan
import kotlin.math.atan2
import kotlin.math.atanh
import kotlin.math.cos
import kotlin.math.cosh
import kotlin.math.hypot
import kotlin.math.sin
import kotlin.math.sinh
import kotlin.math.tan
import kotlin.math.tanh

/** Результат проекции в геодезическом порядке осей: X — на север, Y — на восток (с учётом x_0/y_0). */
data class Projected(val north: Double, val east: Double)

/**
 * Поперечный Меркатор, ряды Крюгера по n до 6-го порядка (Karney 2011).
 * Сверка с PROJ (etmerc): ≤ 1e-8 м на ±10° от ЦМ. Параметры: широта начала, ЦМ (рад), k0, ложные восток/север.
 * Параметр [falseEasting] = x_0 PROJ (восток), [falseNorthing] = y_0 PROJ (север).
 * ЦМ может быть любым (±90°, > 180°): долгота нормализуется.
 */
class TransverseMercator(
    val ellipsoid: Ellipsoid,
    val lat0: Double,
    override val lon0: Double,
    val k0: Double,
    override val falseEasting: Double,
    override val falseNorthing: Double,
) : MapProjection {
    override val methodCode: Int get() = MapProjection.TM

    private val alpha: DoubleArray
    private val beta: DoubleArray
    private val bigA: Double
    private val xi0: Double

    init {
        val n = ellipsoid.n
        val n2 = n * n; val n3 = n2 * n; val n4 = n3 * n; val n5 = n4 * n; val n6 = n5 * n
        alpha = doubleArrayOf(
            n / 2 - 2.0 / 3 * n2 + 5.0 / 16 * n3 + 41.0 / 180 * n4 - 127.0 / 288 * n5 + 7891.0 / 37800 * n6,
            13.0 / 48 * n2 - 3.0 / 5 * n3 + 557.0 / 1440 * n4 + 281.0 / 630 * n5 - 1983433.0 / 1935360 * n6,
            61.0 / 240 * n3 - 103.0 / 140 * n4 + 15061.0 / 26880 * n5 + 167603.0 / 181440 * n6,
            49561.0 / 161280 * n4 - 179.0 / 168 * n5 + 6601661.0 / 7257600 * n6,
            34729.0 / 80640 * n5 - 3418889.0 / 1995840 * n6,
            212378941.0 / 319334400 * n6,
        )
        beta = doubleArrayOf(
            n / 2 - 2.0 / 3 * n2 + 37.0 / 96 * n3 - 1.0 / 360 * n4 - 81.0 / 512 * n5 + 96199.0 / 604800 * n6,
            1.0 / 48 * n2 + 1.0 / 15 * n3 - 437.0 / 1440 * n4 + 46.0 / 105 * n5 - 1118711.0 / 3870720 * n6,
            17.0 / 480 * n3 - 37.0 / 840 * n4 - 209.0 / 4480 * n5 + 5569.0 / 90720 * n6,
            4397.0 / 161280 * n4 - 11.0 / 504 * n5 - 830251.0 / 7257600 * n6,
            4583.0 / 161280 * n5 - 108847.0 / 3991680 * n6,
            20648693.0 / 638668800 * n6,
        )
        bigA = ellipsoid.a / (1 + n) * (1 + n2 / 4 + n4 / 64 + n6 / 256)
        val chi0 = conformalLat(lat0)
        xi0 = chi0 + (0 until 6).sumOf { alpha[it] * sin(2.0 * (it + 1) * chi0) }
    }

    private fun conformalLat(lat: Double): Double {
        val s = sin(lat).coerceIn(-1.0, 1.0)
        return atan(sinh(atanh(s) - ellipsoid.e * atanh(ellipsoid.e * s)))
    }

    override fun forward(lat: Double, lon: Double): Projected {
        val lam = Geodesy.normLon(lon - lon0)
        val t = tan(conformalLat(lat))
        val xi1 = atan2(t, cos(lam))
        val eta1 = asinh(sin(lam) / hypot(t, cos(lam)))
        var xi = xi1
        var eta = eta1
        for (j in 1..6) {
            xi += alpha[j - 1] * sin(2.0 * j * xi1) * cosh(2.0 * j * eta1)
            eta += alpha[j - 1] * cos(2.0 * j * xi1) * sinh(2.0 * j * eta1)
        }
        return Projected(
            north = falseNorthing + k0 * bigA * (xi - xi0),
            east = falseEasting + k0 * bigA * eta,
        )
    }

    /** Возвращает (lat, lon) в радианах; lon нормализована в (−π, π]. */
    override fun inverse(north: Double, east: Double): Pair<Double, Double> {
        val xi = (north - falseNorthing) / (k0 * bigA) + xi0
        val eta = (east - falseEasting) / (k0 * bigA)
        var xi1 = xi
        var eta1 = eta
        for (j in 1..6) {
            xi1 -= beta[j - 1] * sin(2.0 * j * xi) * cosh(2.0 * j * eta)
            eta1 -= beta[j - 1] * cos(2.0 * j * xi) * sinh(2.0 * j * eta)
        }
        val chi = asin((sin(xi1) / cosh(eta1)).coerceIn(-1.0, 1.0))
        val lam = atan2(sinh(eta1), cos(xi1))
        val sc = sin(chi).coerceIn(-1.0, 1.0)
        val e = ellipsoid.e
        var phi = chi
        for (i in 0 until 20) {
            val next = asin(tanh(atanh(sc) + e * atanh(e * sin(phi))).coerceIn(-1.0, 1.0))
            val done = kotlin.math.abs(next - phi) < 1e-16
            phi = next
            if (done) break
        }
        return phi to Geodesy.normLon(lon0 + lam)
    }
}

/**
 * TM South Orientated (EPSG 9808): оси направлены на запад и на юг. Поля результата: north — южное, east — западное
 * смещение, то есть W = 2·FE − E, S = 2·FN − N относительно обычной TM с теми же параметрами.
 */
class TransverseMercatorSouthOriented(private val tm: TransverseMercator) : MapProjection {
    override val methodCode: Int get() = MapProjection.TM_SOUTH_ORIENTED
    override val lon0: Double get() = tm.lon0
    override val falseEasting: Double get() = tm.falseEasting
    override val falseNorthing: Double get() = tm.falseNorthing
    val base: TransverseMercator get() = tm

    override fun forward(lat: Double, lon: Double): Projected {
        val p = tm.forward(lat, lon)
        return Projected(2 * tm.falseNorthing - p.north, 2 * tm.falseEasting - p.east)
    }

    override fun inverse(north: Double, east: Double) = tm.inverse(2 * tm.falseNorthing - north, 2 * tm.falseEasting - east)
}
