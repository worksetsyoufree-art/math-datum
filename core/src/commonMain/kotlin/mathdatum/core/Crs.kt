package mathdatum.core

/** Прямоугольник применимости СК, градусы. */
data class GeoBounds(val minLat: Double, val maxLat: Double, val minLon: Double, val maxLon: Double) {
    fun contains(p: Geodetic) = p.latDeg in minLat..maxLat && p.lonDeg in minLon..maxLon
}

/**
 * Описание СК: эллипсоид + (опц.) Гельмерт WGS84 → местная + TM.
 * Это «справочная» часть без калибровки (ГСКО/ВСКО/геоид — отдельный слой, см. docs/PLAN.md).
 */
class CrsDef(
    val id: String,
    val name: String,
    val ellipsoid: Ellipsoid,
    val helmert: Helmert?,       // направление WGS84 → местная
    val tm: TransverseMercator,
    val bounds: GeoBounds? = null,
    val epsg: Int? = null,
    val region: String? = null,
) {
    /** WGS84 (геодезические, рад) → (север, восток, высота над эллипсоидом СК). */
    fun fromWgs84(p: Geodetic): Triple<Double, Double, Double> {
        var c = Geodesy.toCart(Ellipsoid.WGS84, p)
        helmert?.let { c = it.forward(c) }
        val g = Geodesy.fromCart(ellipsoid, c)
        val pr = tm.forward(g.lat, g.lon)
        return Triple(pr.north, pr.east, g.h)
    }

    fun toWgs84(north: Double, east: Double, h: Double): Geodetic {
        val (lat, lon) = tm.inverse(north, east)
        var c = Geodesy.toCart(ellipsoid, Geodetic(lat, lon, h))
        helmert?.let { c = it.inverse(c) }
        return Geodesy.fromCart(Ellipsoid.WGS84, c)
    }

    /** Попадает ли точка в зону применимости: bounds, иначе ЦМ ± [halfWidthDeg]. */
    fun inZone(p: Geodetic, halfWidthDeg: Double = 3.5): Boolean {
        bounds?.let { return it.contains(p) }
        val d = Geodesy.normLon(p.lon - tm.lon0) / DEG
        return kotlin.math.abs(d) <= halfWidthDeg
    }
}
