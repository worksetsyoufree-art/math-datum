package mathdatum.core

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.asin
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.sin
import kotlin.math.sqrt

const val DEG = PI / 180.0
const val ARCSEC = PI / (180.0 * 3600.0)

data class Vec3(val x: Double, val y: Double, val z: Double)

/** Геодезические координаты, радианы, высота над эллипсоидом в метрах. */
data class Geodetic(val lat: Double, val lon: Double, val h: Double) {
    val latDeg get() = lat / DEG
    val lonDeg get() = lon / DEG

    companion object {
        fun ofDegrees(latDeg: Double, lonDeg: Double, h: Double = 0.0) = Geodetic(latDeg * DEG, lonDeg * DEG, h)
    }
}

object Geodesy {
    fun toCart(e: Ellipsoid, p: Geodetic): Vec3 {
        val sl = sin(p.lat)
        val cl = cos(p.lat)
        val n = e.a / sqrt(1.0 - e.e2 * sl * sl)
        return Vec3(
            (n + p.h) * cl * cos(p.lon),
            (n + p.h) * cl * sin(p.lon),
            (n * (1.0 - e.e2) + p.h) * sl,
        )
    }

    /** Долгота через atan2; на оси Земли — ±90° и h = |z| − b; высота без потери точности у полюса. */
    fun fromCart(e: Ellipsoid, v: Vec3): Geodetic {
        val p = hypot(v.x, v.y)
        if (p < 1e-9) {
            return Geodetic(if (v.z >= 0) PI / 2 else -PI / 2, 0.0, abs(v.z) - e.b)
        }
        val lon = atan2(v.y, v.x)
        var lat = atan2(v.z, p * (1.0 - e.e2))
        for (i in 0 until 12) {
            val sl = sin(lat)
            val n = e.a / sqrt(1.0 - e.e2 * sl * sl)
            val next = atan2(v.z + e.e2 * n * sl, p)
            val done = abs(next - lat) < 1e-15
            lat = next
            if (done) break
        }
        val sl = sin(lat)
        val cl = cos(lat)
        val n = e.a / sqrt(1.0 - e.e2 * sl * sl)
        val h = if (abs(lat) < PI / 4) p / cl - n else v.z / sl - n * (1.0 - e.e2)
        return Geodetic(lat, lon, h)
    }

    /** Нормализация долготы в (−π, π]. */
    fun normLon(lon: Double): Double = atan2(sin(lon), cos(lon))

    /** Расстояние по большому кругу на сфере WGS84-радиуса, м. Для оценок «далеко/рядом», не для измерений. */
    fun haversine(a: Geodetic, b: Geodetic): Double {
        val dLat = b.lat - a.lat
        val dLon = b.lon - a.lon
        val s = sin(dLat / 2).let { it * it } + cos(a.lat) * cos(b.lat) * sin(dLon / 2).let { it * it }
        return 2 * 6371008.8 * asin(sqrt(s.coerceIn(0.0, 1.0)))
    }
}
