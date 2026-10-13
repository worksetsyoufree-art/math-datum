package mathdatum.app

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import mathdatum.core.Anchor
import mathdatum.core.Candidate
import mathdatum.core.Catalog
import mathdatum.core.ControlPair
import mathdatum.core.CrsDef
import mathdatum.core.CrsGeoref
import mathdatum.core.DatumFinder
import mathdatum.core.FindDatumOptions
import mathdatum.core.Geodetic
import mathdatum.core.Georef
import mathdatum.core.GeorefJson
import mathdatum.core.HeightMode
import mathdatum.core.Localization
import mathdatum.core.LocalizationOptions
import mathdatum.core.LocalizationResult
import mathdatum.core.LocalizationWarning
import mathdatum.core.SurfaceBounds
import mathdatum.core.SurfacePoint
import mathdatum.core.SurfaceUnits
import mathdatum.core.SurfaceVertices

enum class Mode(val title: String) { AUTO("Авто"), PICK("Выбрать СК"), POINTS("По точкам"), CHECK("Проверка") }

/** Чертёж, который открыт в просмотрщике. */
class SurfaceInfo(val name: String, val vertices: SurfaceVertices, val bounds: SurfaceBounds, val insunits: Int? = null)

class PairRow(val id: Int, val x: Double, val y: Double, val lat: Double, val lon: Double, val enabled: Boolean = true)

enum class Level(val label: String) { GOOD("хорошо"), WARN("внимание"), BAD("плохо") }

class PairStatus(val row: PairRow, val residualM: Double?, val level: Level?)

/** Привязка, которую сейчас видит пользователь: что получилось и насколько ей можно верить. */
class Applied(val georef: Georef, val description: String, val warnings: List<String>, val rmsM: Double? = null)

/**
 * Логика экранов «Привязка чертежа» без UI: четыре режима, одна текущая привязка.
 * Тексты — без терминов «датум», «Гельмерт», «локализация» (см. dxf-georef-todo, этап 6).
 */
class GeorefController(val catalog: Catalog, val surface: SurfaceInfo) {
    var mode by mutableStateOf(Mode.AUTO)
    var anchor by mutableStateOf<Anchor?>(null)
    var candidates by mutableStateOf<List<Candidate>>(emptyList())
    var autoRan by mutableStateOf(false)
    var query by mutableStateOf("")
    var pickSwap by mutableStateOf(false)
    var pickUnit by mutableStateOf(1.0)
    var pairs by mutableStateOf<List<PairRow>>(emptyList())
    var applied by mutableStateOf<Applied?>(null)
    var error by mutableStateOf<String?>(null)
    var fitHeightPlane by mutableStateOf(false)
    private var nextId = 1

    // ——— Авто ———
    fun setAnchor(lat: Double, lon: Double) {
        anchor = Anchor(Geodetic.ofDegrees(lat, lon), "метка")
        error = null
    }

    fun clearAnchor() { anchor = null }

    fun runAuto() {
        val units = SurfaceUnits.candidates(surface.bounds, surface.insunits)
        candidates = DatumFinder.find(surface.bounds, anchor, catalog, FindDatumOptions(unitFactors = units))
        autoRan = true
        error = null
    }

    fun apply(c: Candidate) {
        applied = Applied(
            c.toGeoref(), "${c.crs.name}, ${axesName(c.swapXY)}, единица ${unitName(c.unitToMeters)}",
            warnings = buildList {
                if (c.status == mathdatum.core.MatchStatus.NEAR) add("Чертёж рядом с вашими метками, но не точно на них.")
                if (anchor == null) add("Нет меток: система выбрана по косвенным признакам, проверьте на экране «Проверка».")
            },
        )
    }

    // ——— Выбрать СК ———
    fun filteredCatalog(): List<CrsDef> {
        val q = query.trim().lowercase()
        return if (q.isEmpty()) catalog.entries else catalog.entries.filter { it.name.lowercase().contains(q) || it.id.lowercase().contains(q) }
    }

    fun pick(crs: CrsDef) {
        applied = Applied(CrsGeoref(crs, pickSwap, pickUnit), "${crs.name}, ${axesName(pickSwap)}, единица ${unitName(pickUnit)}", emptyList())
    }

    // ——— По точкам ———
    fun addPair(x: Double, y: Double, lat: Double, lon: Double) {
        pairs = pairs + PairRow(nextId++, x, y, lat, lon)
        recomputePoints()
    }

    fun togglePair(id: Int) {
        pairs = pairs.map { if (it.id == id) PairRow(it.id, it.x, it.y, it.lat, it.lon, !it.enabled) else it }
        recomputePoints()
    }

    fun removePair(id: Int) { pairs = pairs.filter { it.id != id }; recomputePoints() }

    var lastResult by mutableStateOf<LocalizationResult.Ok?>(null)

    /** Пересчёт привязки по включённым парам; «Готово» не блокируем, только предупреждаем. */
    fun recomputePoints() {
        val on = pairs.filter { it.enabled }
        val cp = on.map { ControlPair(SurfacePoint(it.x, it.y), Geodetic.ofDegrees(it.lat, it.lon)) }
        val opts = LocalizationOptions(allowSinglePair = true, heightMode = if (fitHeightPlane) HeightMode.PLANE else HeightMode.OFFSET)
        when (val r = if (cp.isEmpty()) null else Localization.localize(cp, opts)) {
            null -> { lastResult = null; applied = null; error = null }
            is LocalizationResult.Failed -> { lastResult = null; applied = null; error = r.reason }
            is LocalizationResult.Ok -> {
                lastResult = r; error = null
                applied = Applied(r.georef, "По ${on.size} ${pointsWord(on.size)}", describe(r), r.rmsM)
            }
        }
    }

    fun pairStatuses(): List<PairStatus> {
        val r = lastResult
        val on = pairs.filter { it.enabled }
        return pairs.map { row ->
            val i = on.indexOfFirst { it.id == row.id }
            val d = if (r != null && i >= 0 && on.size >= 3) r.residuals[i].distance else null
            PairStatus(row, d, d?.let { levelOf(it) })
        }
    }

    // ——— Проверка / сохранение ———
    fun toSurface(lat: Double, lon: Double): SurfacePoint? = applied?.georef?.fromWgs84(Geodetic.ofDegrees(lat, lon))

    fun export(): String? = applied?.georef?.let { GeorefJson.encode(it) }

    companion object {
        fun levelOf(m: Double) = when {
            m <= 0.02 -> Level.GOOD
            m <= 0.10 -> Level.WARN
            else -> Level.BAD
        }

        fun axesName(swap: Boolean) = if (swap) "X — восток, Y — север" else "X — север, Y — восток"

        fun pointsWord(n: Int) = when {
            n % 10 == 1 && n % 100 != 11 -> "точке"
            else -> "точкам"
        }

        fun unitName(f: Double) = when (f) {
            1.0 -> "метры"; 0.001 -> "миллиметры"; 0.01 -> "сантиметры"; 1000.0 -> "километры"; 0.3048 -> "футы"; else -> "×$f м"
        }

        fun describe(r: LocalizationResult.Ok): List<String> = r.warnings.mapNotNull {
            when (it) {
                LocalizationWarning.SINGLE_PAIR_TRANSLATION_ONLY -> "Одна точка: учтён только сдвиг, поворот и масштаб не определены."
                LocalizationWarning.NO_REDUNDANCY -> "Две точки: ошибку проверить нельзя. Добавьте третью."
                LocalizationWarning.DUPLICATE_POINTS -> "Есть совпадающие точки."
                LocalizationWarning.SCALE_NOT_ONE -> "Масштаб чертежа заметно отличается от 1. Проверьте единицы и точки."
                LocalizationWarning.RMS_ABOVE_TOLERANCE -> "Невязки выше нормы. Проверьте точки с красной пометкой."
                LocalizationWarning.OUTLIER_SUSPECTED -> r.suspectedOutlier?.let { i -> "Точка ${i + 1} похожа на ошибочную: попробуйте её отключить." }
                LocalizationWarning.HEIGHT_PLANE_FALLBACK -> "Для высоты по плоскости точек мало или они на одной линии: применён общий сдвиг."
                LocalizationWarning.NO_HEIGHTS -> null
            }
        }
    }
}
