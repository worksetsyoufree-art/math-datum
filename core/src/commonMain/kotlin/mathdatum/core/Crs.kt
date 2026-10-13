package mathdatum.core

/** Прямоугольник применимости СК, градусы. */
data class GeoBounds(val minLat: Double, val maxLat: Double, val minLon: Double, val maxLon: Double) {
    /** Зона через линию смены дат: minLon > maxLon. */
    private val wraps get() = minLon > maxLon

    fun contains(p: Geodetic): Boolean {
        val lon = p.lonDeg
        val inLon = if (wraps) lon >= minLon || lon <= maxLon else lon in minLon..maxLon
        return p.latDeg in minLat..maxLat && inLon
    }
}

/** В какую сторону заданы параметры Гельмерта у СК. У EPSG — «местная → WGS84», у справочника приложения — «WGS84 → местная». */
enum class HelmertDirection { WGS84_TO_LOCAL, LOCAL_TO_WGS84 }

/**
 * Описание СК: эллипсоид + (опц.) Гельмерт + проекция.
 * Это «справочная» часть без калибровки (ГСКО/ВСКО/геоид — отдельный слой, см. docs/PLAN.md).
 *
 * [firstAxisIsEast] — порядок осей СК (false: X — север, Y — восток, как в справочнике; true: X — восток, Y — север).
 * [unitToMeters] — единица осей СК (метр = 1, фут = 0,3048, американский фут = 1200/3937).
 */
class CrsDef(
    val id: String,
    val name: String,
    val ellipsoid: Ellipsoid,
    val helmert: Helmert?,
    val projection: MapProjection,
    val bounds: GeoBounds? = null,
    val epsg: Int? = null,
    val region: String? = null,
    val source: String? = null,
    val helmertDirection: HelmertDirection = HelmertDirection.WGS84_TO_LOCAL,
    val firstAxisIsEast: Boolean = false,
    val unitToMeters: Double = 1.0,
    /** false — направление Гельмерта не подтверждено источником (см. [helmertAmbiguityMeters]). */
    val helmertDirectionConfirmed: Boolean = true,
) {
    private fun toLocalCart(c: Vec3): Vec3 = helmert?.let {
        if (helmertDirection == HelmertDirection.WGS84_TO_LOCAL) it.forward(c) else it.inverse(c)
    } ?: c

    private fun toWgsCart(c: Vec3): Vec3 = helmert?.let {
        if (helmertDirection == HelmertDirection.WGS84_TO_LOCAL) it.inverse(c) else it.forward(c)
    } ?: c

    /** WGS84 (геодезические, рад) → (север, восток, высота над эллипсоидом СК), метры, геодезический порядок осей. */
    fun fromWgs84(p: Geodetic): Triple<Double, Double, Double> {
        val g = Geodesy.fromCart(ellipsoid, toLocalCart(Geodesy.toCart(Ellipsoid.WGS84, p)))
        val pr = projection.forward(g.lat, g.lon)
        return Triple(pr.north, pr.east, g.h)
    }

    fun toWgs84(north: Double, east: Double, h: Double): Geodetic {
        val (lat, lon) = projection.inverse(north, east)
        return Geodesy.fromCart(Ellipsoid.WGS84, toWgsCart(Geodesy.toCart(ellipsoid, Geodetic(lat, lon, h))))
    }

    /** Попадает ли точка в зону применимости: bounds, иначе ЦМ ± [halfWidthDeg]. */
    fun inZone(p: Geodetic, halfWidthDeg: Double = 3.5): Boolean {
        bounds?.let { return it.contains(p) }
        val d = Geodesy.normLon(p.lon - projection.lon0) / DEG
        return kotlin.math.abs(d) <= halfWidthDeg
    }

    /** Копия с другим направлением Гельмерта (для проверки обеих трактовок). */
    fun withHelmertDirection(dir: HelmertDirection, confirmed: Boolean = helmertDirectionConfirmed) = CrsDef(
        id, name, ellipsoid, helmert, projection, bounds, epsg, region, source, dir, firstAxisIsEast, unitToMeters, confirmed,
    )

    /**
     * Насколько расходятся две трактовки направления Гельмерта в точке (метры по поверхности WGS84).
     * 0, если Гельмерта нет. Большое значение — повод просить пользователя сверить по известной точке.
     */
    fun helmertAmbiguityMeters(at: Geodetic): Double {
        if (helmert == null) return 0.0
        val a = withHelmertDirection(HelmertDirection.WGS84_TO_LOCAL)
        val b = withHelmertDirection(HelmertDirection.LOCAL_TO_WGS84)
        val (n, e, h) = a.fromWgs84(at)
        return Geodesy.haversine(a.toWgs84(n, e, h), b.toWgs84(n, e, h))
    }
}
