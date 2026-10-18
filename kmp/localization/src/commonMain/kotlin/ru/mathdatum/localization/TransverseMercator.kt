package ru.mathdatum.localization

import kotlin.math.PI
import kotlin.math.asin
import kotlin.math.asinh
import kotlin.math.atan
import kotlin.math.atan2
import kotlin.math.atanh
import kotlin.math.cos
import kotlin.math.cosh
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sinh
import kotlin.math.sqrt
import kotlin.math.tan

/** Эллипсоид: большая полуось [a] (м) и сжатие [f]. */
data class Ellipsoid(val a: Double, val f: Double) {
    val e: Double get() = sqrt(f * (2 - f))

    /** Запись в синтаксисе PROJ, совместимая с Python-эталоном. */
    fun toProj(): String = KNOWN.entries.firstOrNull { it.value == this }?.let { "+ellps=${it.key}" }
        ?: "+a=$a +rf=${1 / f}"

    companion object {
        val WGS84 = Ellipsoid(6378137.0, 1 / 298.257223563)
        val GRS80 = Ellipsoid(6378137.0, 1 / 298.257222101)
        val KRASSOVSKY = Ellipsoid(6378245.0, 1 / 298.3)
        val PZ90 = Ellipsoid(6378136.0, 1 / 298.25784)
        val GSK2011 = Ellipsoid(6378136.5, 1 / 298.2564151)

        private val KNOWN = mapOf("WGS84" to WGS84, "GRS80" to GRS80, "krass" to KRASSOVSKY)

        /** Разбор строки PROJ: `+ellps=WGS84|GRS80|krass` или `+a=... +rf=...`. */
        fun fromProj(s: String): Ellipsoid {
            val kv = s.trim().split(Regex("\\s+")).filter { "=" in it }
                .associate { it.removePrefix("+").substringBefore("=") to it.substringAfter("=") }
            kv["ellps"]?.let { return KNOWN[it] ?: throw IllegalArgumentException("Неизвестный эллипсоид: $it") }
            val a = kv["a"]?.toDouble() ?: throw IllegalArgumentException("Нет параметра a в «$s»")
            val f = kv["rf"]?.let { 1 / it.toDouble() } ?: kv["f"]?.toDouble()
                ?: throw IllegalArgumentException("Нет параметра rf/f в «$s»")
            return Ellipsoid(a, f)
        }
    }
}

/**
 * Поперечный Меркатор (ряды Крюгера 6-го порядка, как `+proj=tmerc` в PROJ).
 * Масштаб k0 = 1, без ложных смещений; север отсчитывается от широты [lat0].
 * Точность — доли миллиметра в пределах тысяч километров от осевого меридиана.
 */
class TransverseMercator(val ellipsoid: Ellipsoid, val lat0: Double, val lon0: Double) {
    private val e = ellipsoid.e
    private val n = ellipsoid.f / (2 - ellipsoid.f)
    private val bigA: Double
    private val alpha: DoubleArray
    private val beta: DoubleArray
    private val northing0: Double

    init {
        val n2 = n * n; val n3 = n2 * n; val n4 = n3 * n; val n5 = n4 * n; val n6 = n5 * n
        bigA = ellipsoid.a / (1 + n) * (1 + n2 / 4 + n4 / 64 + n6 / 256)
        alpha = doubleArrayOf(
            n / 2 - 2 * n2 / 3 + 5 * n3 / 16 + 41 * n4 / 180 - 127 * n5 / 288 + 7891 * n6 / 37800,
            13 * n2 / 48 - 3 * n3 / 5 + 557 * n4 / 1440 + 281 * n5 / 630 - 1983433 * n6 / 1935360,
            61 * n3 / 240 - 103 * n4 / 140 + 15061 * n5 / 26880 + 167603 * n6 / 181440,
            49561 * n4 / 161280 - 179 * n5 / 168 + 6601661 * n6 / 7257600,
            34729 * n5 / 80640 - 3418889 * n6 / 1995840,
            212378941 * n6 / 319334400,
        )
        beta = doubleArrayOf(
            n / 2 - 2 * n2 / 3 + 37 * n3 / 96 - n4 / 360 - 81 * n5 / 512 + 96199 * n6 / 604800,
            n2 / 48 + n3 / 15 - 437 * n4 / 1440 + 46 * n5 / 105 - 1118711 * n6 / 3870720,
            17 * n3 / 480 - 37 * n4 / 840 - 209 * n5 / 4480 + 5569 * n6 / 90720,
            4397 * n4 / 161280 - 11 * n5 / 504 - 830251 * n6 / 7257600,
            4583 * n5 / 161280 - 108847 * n6 / 3991680,
            20648693 * n6 / 638668800,
        )
        northing0 = forwardRaw(lat0, lon0).first
    }

    /** Широта, долгота (градусы) → (север N, восток E), м. */
    fun forward(lat: Double, lon: Double): Pair<Double, Double> {
        val (n, e) = forwardRaw(lat, lon)
        return (n - northing0) to e
    }

    /** (север N, восток E), м → широта, долгота (градусы). */
    fun inverse(north: Double, east: Double): Pair<Double, Double> {
        val xi = (north + northing0) / bigA
        val eta = east / bigA
        var xiP = xi
        var etaP = eta
        for (j in 1..6) {
            val b = beta[j - 1]
            xiP -= b * sin(2 * j * xi) * cosh(2 * j * eta)
            etaP -= b * cos(2 * j * xi) * sinh(2 * j * eta)
        }
        val chi = asin(sin(xiP) / cosh(etaP))
        val dLon = atan2(sinh(etaP), cos(xiP))
        // Конформная широта → геодезическая (итерации сходятся за несколько шагов).
        var phi = chi
        repeat(15) {
            val es = e * sin(phi)
            phi = 2 * atan(tan(PI / 4 + chi / 2) * ((1 + es) / (1 - es)).pow(e / 2)) - PI / 2
        }
        return phi.toDegrees() to (lon0 + dLon.toDegrees())
    }

    private fun forwardRaw(lat: Double, lon: Double): Pair<Double, Double> {
        val phi = lat.toRadians()
        val lam = (lon - lon0).toRadians()
        val t = sinh(atanh(sin(phi)) - e * atanh(e * sin(phi)))
        val xiP = atan2(t, cos(lam))
        val etaP = asinh(sin(lam) / sqrt(t * t + cos(lam) * cos(lam)))
        var xi = xiP
        var eta = etaP
        for (j in 1..6) {
            val a = alpha[j - 1]
            xi += a * sin(2 * j * xiP) * cosh(2 * j * etaP)
            eta += a * cos(2 * j * xiP) * sinh(2 * j * etaP)
        }
        return bigA * xi to bigA * eta
    }
}

internal fun Double.toRadians() = this * PI / 180
internal fun Double.toDegrees() = this * 180 / PI
