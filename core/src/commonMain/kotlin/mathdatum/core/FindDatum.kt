package mathdatum.core

import kotlin.math.abs
import kotlin.math.exp
import kotlin.math.hypot

/** Габариты вершин поверхности в её локальных координатах (единицы чертежа). */
data class SurfaceBounds(val minX: Double, val maxX: Double, val minY: Double, val maxY: Double) {
    val centerX get() = (minX + maxX) / 2
    val centerY get() = (minY + maxY) / 2
    val diagonal get() = hypot(maxX - minX, maxY - minY)
}

/** Опорная информация: позиция GPS, центр меток или известный регион. */
data class Anchor(val position: Geodetic, val label: String = "")

enum class MatchStatus { MATCH, NEAR, FAR }
enum class Reliability { ANCHORED, INDIRECT }

data class Candidate(
    val crs: CrsDef,
    val swapXY: Boolean,
    val unitToMeters: Double,
    val center: Geodetic,
    val distanceToAnchorM: Double?,   // null без anchor
    val inZone: Boolean,
    val status: MatchStatus,
    val reliability: Reliability,
    val score: Double,                // 0..1
) {
    fun toGeoref(): Georef = CrsGeoref(crs, swapXY, unitToMeters)
}

data class FindDatumOptions(
    val matchM: Double = 2_000.0,      // «совпал»: центр чертежа ближе к anchor
    val nearM: Double = 50_000.0,      // «рядом»: иначе «не подходит»
    val unitFactors: List<Double> = listOf(1.0, 0.001, 0.01, 1000.0), // м, мм, см, км
    val topN: Int = 5,
    val zoneHalfWidthEastM: Double = 600_000.0, // грубый отсев по Y без anchor
)

object DatumFinder {
    /**
     * Перебор: СК × (X/Y местами) × единицы. Без anchor — только правдоподобие по косвенным признакам
     * (reliability = INDIRECT), с anchor — по расстоянию до него.
     * Прототип: предфильтр по восточной координате (быстрый отсев зоны по x_0/ЦМ) до полного преобразования.
     */
    fun find(
        bounds: SurfaceBounds, anchor: Anchor?, catalog: Catalog, opts: FindDatumOptions = FindDatumOptions(),
    ): List<Candidate> {
        val out = ArrayList<Candidate>()
        for (crs in catalog.entries) for (swap in listOf(false, true)) for (unit in (opts.unitFactors + crs.unitToMeters).distinct()) {
            val (a, b) = bounds.centerX to bounds.centerY
            val north = (if (swap) b else a) * unit
            val east = (if (swap) a else b) * unit
            // грубый отсев: восточная координата должна быть в полосе зоны вокруг x_0
            if (crs.projection is TransverseMercator && abs(east - crs.projection.falseEasting) > opts.zoneHalfWidthEastM) continue
            if (abs(north) > 1.1e7) continue
            val center = crs.toWgs84(north, east, 0.0)
            if (center.latDeg !in -90.0..90.0) continue
            val inZone = crs.inZone(center)
            val d = anchor?.let { Geodesy.haversine(center, it.position) }
            val status = when {
                d == null -> MatchStatus.NEAR // без anchor «совпал» утверждать нельзя
                d <= opts.matchM -> MatchStatus.MATCH
                d <= opts.nearM -> MatchStatus.NEAR
                else -> MatchStatus.FAR
            }
            if (status == MatchStatus.FAR) continue
            val score = when {
                d == null -> if (inZone) 0.3 else 0.1
                else -> exp(-d / opts.matchM).let { if (inZone) it else it * 0.5 }
            }
            out += Candidate(
                crs, swap, unit, center, d, inZone, status,
                if (anchor == null) Reliability.INDIRECT else Reliability.ANCHORED, score,
            )
        }
        return out.sortedByDescending { it.score }.take(opts.topN)
    }
}
