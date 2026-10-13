package mathdatum.core

/**
 * Картографическая проекция на эллипсоиде СК. Результат прямой — (север, восток) в метрах с учётом ложных смещений;
 * порядок осей и единицы СК накладывает [CrsDef]. [methodCode] — код метода EPSG.
 */
interface MapProjection {
    val methodCode: Int
    val lon0: Double
    val falseEasting: Double
    val falseNorthing: Double
    fun forward(lat: Double, lon: Double): Projected

    /** (lat, lon) в радианах, lon нормализована в (−π, π]. */
    fun inverse(north: Double, east: Double): Pair<Double, Double>

    companion object {
        const val TM = 9807
        const val TM_SOUTH_ORIENTED = 9808
        const val LCC_1SP = 9801
        const val LCC_2SP = 9802
    }
}
