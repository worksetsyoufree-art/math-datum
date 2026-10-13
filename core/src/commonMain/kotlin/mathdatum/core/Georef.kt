package mathdatum.core

/** Точка поверхности в её локальных координатах (единицы чертежа). */
data class SurfacePoint(val x: Double, val y: Double, val z: Double = Double.NaN)

/** Единый результат обоих путей (поиск СК и локализация): WGS84 ↔ координаты поверхности. */
interface Georef {
    fun toWgs84(x: Double, y: Double, z: Double = 0.0): Geodetic
    fun fromWgs84(p: Geodetic): SurfacePoint
}

/**
 * Поверхность лежит в СК из справочника.
 * [swapXY] = false: X поверхности — север, Y — восток (геодезический порядок, как в справочнике);
 * true: X — восток, Y — север (CAD). [unitToMeters]: 1.0 м, 0.001 мм, 0.01 см, 1000.0 км.
 */
class CrsGeoref(
    val crs: CrsDef,
    val swapXY: Boolean = false,
    val unitToMeters: Double = 1.0,
) : Georef {
    override fun toWgs84(x: Double, y: Double, z: Double): Geodetic {
        val (n, e) = if (swapXY) y to x else x to y
        val h = if (z.isNaN()) 0.0 else z
        return crs.toWgs84(n * unitToMeters, e * unitToMeters, h * unitToMeters)
    }

    override fun fromWgs84(p: Geodetic): SurfacePoint {
        val (n, e, h) = crs.fromWgs84(p)
        val (a, b) = if (swapXY) e to n else n to e
        return SurfacePoint(a / unitToMeters, b / unitToMeters, h / unitToMeters)
    }
}

/** Подобие 2D: q = a·p + t, где a = s·e^{iθ} (комплексное число (aRe, aIm)). */
class Similarity2D(val aRe: Double, val aIm: Double, val tx: Double, val ty: Double) {
    val scale get() = kotlin.math.hypot(aRe, aIm)
    val rotation get() = kotlin.math.atan2(aIm, aRe)

    fun apply(x: Double, y: Double) = (aRe * x - aIm * y + tx) to (aIm * x + aRe * y + ty)

    fun applyInverse(x: Double, y: Double): Pair<Double, Double> {
        val d = aRe * aRe + aIm * aIm
        val dx = x - tx
        val dy = y - ty
        return ((aRe * dx + aIm * dy) / d) to ((aRe * dy - aIm * dx) / d)
    }
}

/**
 * Локальная TM с ЦМ в центре участка (k0 = 1, WGS84): устойчивая точность на 50–100 км,
 * в отличие от глобальной проекции. Плоскость: (east, north) в метрах.
 */
class LocalPlane(val lat0: Double, val lon0: Double) {
    val tm = TransverseMercator(Ellipsoid.WGS84, lat0, lon0, 1.0, 0.0, 0.0)
    fun toPlane(p: Geodetic): Pair<Double, Double> = tm.forward(p.lat, p.lon).let { it.east to it.north }
    fun fromPlane(e: Double, n: Double, h: Double): Geodetic = tm.inverse(n, e).let { Geodetic(it.first, it.second, h) }
}

/** Привязка по точкам: поверхность(x, y) —подобие→ локальная плоскость (E, N) ↔ WGS84. */
class LocalizedGeoref(
    val plane: LocalPlane,
    val similarity: Similarity2D,
    val heightOffset: Double,
) : Georef {
    override fun toWgs84(x: Double, y: Double, z: Double): Geodetic {
        val (e, n) = similarity.apply(x, y)
        val h = (if (z.isNaN()) 0.0 else z) + heightOffset
        return plane.fromPlane(e, n, h)
    }

    override fun fromWgs84(p: Geodetic): SurfacePoint {
        val (e, n) = plane.toPlane(p)
        val (x, y) = similarity.applyInverse(e, n)
        return SurfacePoint(x, y, p.h - heightOffset)
    }
}
