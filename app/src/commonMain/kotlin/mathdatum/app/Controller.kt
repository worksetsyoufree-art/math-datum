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
import mathdatum.core.DatumStatus
import mathdatum.core.FindDatumOptions
import mathdatum.core.Geodetic
import mathdatum.core.Georef
import mathdatum.core.GeorefJson
import mathdatum.core.GsiDatumJson
import mathdatum.core.HeightMode
import mathdatum.core.HelmertDirection
import mathdatum.core.HelmertDirectionEvidence
import mathdatum.core.Json
import mathdatum.core.Localization
import mathdatum.core.LocalizationOptions
import mathdatum.core.LocalizationResult
import mathdatum.core.LocalizationWarning
import mathdatum.core.MatchStatus
import mathdatum.core.SurfaceAnalysis
import mathdatum.core.SurfaceBounds
import mathdatum.core.SurfaceParseException
import mathdatum.core.SurfacePoint
import mathdatum.core.SurfaceUnits
import mathdatum.core.SurfaceV1
import mathdatum.core.SurfaceVertices

enum class Mode(val title: String) { AUTO("Авто"), PICK("Выбрать СК"), POINTS("По точкам"), CHECK("Проверка") }

/** Чертёж, который открыт в просмотрщике. */
class SurfaceInfo(
    val name: String,
    val vertices: SurfaceVertices,
    val bounds: SurfaceBounds,
    val insunits: Int? = null,
    /** Число вершин, отброшенных как мусор при расчёте габаритов. */
    val junkVertices: Int = 0,
)

class PairRow(val id: Int, val x: Double, val y: Double, val lat: Double, val lon: Double, val enabled: Boolean = true)

enum class Level(val label: String) { GOOD("хорошо"), WARN("внимание"), BAD("плохо") }

class PairStatus(val row: PairRow, val residualM: Double?, val level: Level?)

/** Привязка, которую сейчас видит пользователь: что получилось и насколько ей можно верить. */
class Applied(val georef: Georef, val description: String, val warnings: List<String>, val rmsM: Double? = null, val crs: CrsDef? = null)

/** Результат разбора файла, выбранного пользователем. */
sealed interface Opened {
    class Surface(val info: SurfaceInfo) : Opened
    class Datum(val crs: CrsDef) : Opened
    class Failed(val message: String) : Opened
}

/**
 * Логика экранов «Привязка чертежа» без UI: четыре режима, одна текущая привязка.
 * Тексты — без терминов «датум», «Гельмерт», «локализация» (см. dxf-georef-todo, этап 6).
 */
class GeorefController(catalog: Catalog, surface: SurfaceInfo) {
    var catalog by mutableStateOf(catalog)
        private set
    var surface by mutableStateOf(surface)
        private set
    /** СК, добавленные пользователем (файлы datum.json): показываются первыми. */
    var userCrs by mutableStateOf<List<CrsDef>>(emptyList())
        private set

    var mode by mutableStateOf(Mode.AUTO)
    var anchor by mutableStateOf<Anchor?>(null)
    var candidates by mutableStateOf<List<Candidate>>(emptyList())
    var autoRan by mutableStateOf(false)
    var query by mutableStateOf("")
    /** null — как в самой СК (порядок осей и единицы EPSG). */
    var pickSwap by mutableStateOf<Boolean?>(null)
    var pickUnit by mutableStateOf<Double?>(null)
    var pairs by mutableStateOf<List<PairRow>>(emptyList())
    var applied by mutableStateOf<Applied?>(null)
    var error by mutableStateOf<String?>(null)
    var message by mutableStateOf<String?>(null)
    var fitHeightPlane by mutableStateOf(false)
    private var nextId = 1

    // ——— Открытие файлов ———
    /** Определяет тип файла по содержимому: чертёж SURFACE_V1 или описание СК (datum.json). */
    fun parseFile(name: String, text: String): Opened {
        val t = text.trimStart('﻿', ' ', '\n', '\r', '\t')
        return try {
            when {
                t.startsWith("SURFACE_V1") -> {
                    val mesh = SurfaceV1.parse(t)
                    val rb = SurfaceAnalysis.robustBounds(mesh.points) ?: return Opened.Failed("В файле нет вершин с корректными координатами")
                    Opened.Surface(SurfaceInfo(mesh.title.ifBlank { name }, mesh.points, rb.bounds, junkVertices = rb.dropped))
                }
                t.startsWith("{") && t.contains("\"csCode\"") -> Opened.Datum(GsiDatumJson.decode(t))
                else -> Opened.Failed("Неизвестный формат файла «$name». Поддерживаются чертёж SURFACE_V1 и описание системы координат (.json)")
            }
        } catch (e: SurfaceParseException) {
            Opened.Failed("Не удалось прочитать чертёж: ${e.message}")
        } catch (e: Json.ParseException) {
            Opened.Failed("Не удалось прочитать описание системы координат: ${e.message}")
        }
    }

    fun open(name: String, text: String) {
        when (val r = parseFile(name, text)) {
            is Opened.Surface -> openSurface(r.info)
            is Opened.Datum -> addUserCrs(r.crs)
            is Opened.Failed -> { error = r.message; message = null }
        }
    }

    fun openSurface(info: SurfaceInfo) {
        surface = info
        candidates = emptyList(); autoRan = false; applied = null; lastResult = null; pairs = emptyList(); error = null
        message = "Открыт чертёж «${info.name}»" + if (info.junkVertices > 0) " (${info.junkVertices} лишних вершин не учтены в габаритах)" else ""
    }

    fun addUserCrs(crs: CrsDef) {
        userCrs = listOf(crs) + userCrs.filter { it.id != crs.id }
        error = null
        message = "Добавлена система «${crs.name}»"
        mode = Mode.PICK
    }

    private fun allCatalog(): Catalog = Catalog(userCrs + catalog.entries, catalog.unsupported, catalog.version, catalog.source)

    // ——— Авто ———
    fun setAnchor(lat: Double, lon: Double) {
        anchor = Anchor(Geodetic.ofDegrees(lat, lon), "метка")
        error = null
    }

    fun clearAnchor() { anchor = null }

    fun runAuto() {
        val units = SurfaceUnits.candidates(surface.bounds, surface.insunits)
        candidates = DatumFinder.find(surface.bounds, anchor, allCatalog(), FindDatumOptions(unitFactors = units, topN = 6))
        autoRan = true
        error = null
    }

    fun apply(c: Candidate) {
        val crs = c.crs
        applied = Applied(
            c.toGeoref(), "${crs.name}, ${axesName(c.swapXY)}, единица ${unitName(c.unitToMeters)}",
            warnings = buildList {
                if (c.status == MatchStatus.NEAR) add("Чертёж рядом с вашими метками, но не точно на них.")
                if (anchor == null) add("Нет меток: система выбрана по косвенным признакам, проверьте на экране «Проверка».")
                addAll(crsWarnings(crs, c.swapXY, c.unitToMeters, directionEvidence(crs, c.swapXY, c.unitToMeters)))
            },
            crs = crs,
        )
    }

    // ——— Выбрать СК ———
    private fun tokens(c: CrsDef): List<String> =
        (c.name + " " + c.id + " " + (c.region ?: "")).lowercase().split(Regex("[^\\p{L}\\p{N}]+")).filter { it.isNotEmpty() }

    private fun matches(q: String): List<CrsDef> {
        val words = q.trim().lowercase().split(' ').filter { it.isNotEmpty() }
        val all = userCrs + catalog.entries
        if (words.isEmpty()) return all
        val scored = ArrayList<Pair<Int, CrsDef>>()
        for (c in all) {
            val hay = (c.name + " " + c.id + " " + (c.region ?: "")).lowercase()
            if (!words.all { hay.contains(it) }) continue
            val tk = tokens(c)
            // целое слово весомее подстроки; пользовательские СК выше
            var score = words.count { w -> tk.contains(w) || w.split('-', '/').all { part -> part.isEmpty() || tk.contains(part) } } * 10
            if (c.source?.startsWith("user") == true) score += 5
            scored += score to c
        }
        return scored.sortedWith(compareByDescending<Pair<Int, CrsDef>> { it.first }.thenBy { it.second.name.length }).map { it.second }
    }

    fun filteredCatalog(limit: Int = 200): List<CrsDef> = matches(query).take(limit)

    fun matchCount(): Int = matches(query).size

    fun pick(crs: CrsDef) {
        val swap = pickSwap ?: crs.firstAxisIsEast
        val unit = pickUnit ?: crs.unitToMeters
        applied = Applied(
            CrsGeoref(crs, swap, unit), "${crs.name}, ${axesName(swap)}, единица ${unitName(unit)}",
            crsWarnings(crs, swap, unit, directionEvidence(crs, swap, unit)), crs = crs,
        )
    }

    /** Переключает трактовку направления параметров у пользовательской СК и пересчитывает текущую привязку. */
    fun setHelmertDirection(crs: CrsDef, direction: HelmertDirection) {
        val fixed = crs.withHelmertDirection(direction, confirmed = true)
        userCrs = userCrs.map { if (it.id == crs.id) fixed else it }
        val cur = applied
        if (cur?.crs?.id == crs.id) {
            val g = cur.georef as? CrsGeoref
            pickSwap = g?.swapXY; pickUnit = g?.unitToMeters
            pick(fixed)
        }
    }

    /** Подсказка по направлению параметров: сдвиг высоты в центре чертежа при обеих трактовках. */
    fun directionEvidence(crs: CrsDef, swap: Boolean = pickSwap ?: crs.firstAxisIsEast, unit: Double = pickUnit ?: crs.unitToMeters): HelmertDirectionEvidence? {
        if (crs.helmert == null) return null
        val b = surface.bounds
        val (n, e) = if (swap) b.centerY to b.centerX else b.centerX to b.centerY
        val h = zMedian()
        return crs.checkHelmertDirection(n * unit, e * unit, h * unit)
    }

    fun directionAmbiguityMeters(crs: CrsDef): Double? {
        if (crs.helmert == null) return null
        val g = CrsGeoref(crs, pickSwap ?: crs.firstAxisIsEast, pickUnit ?: crs.unitToMeters)
        val c = g.toWgs84(surface.bounds.centerX, surface.bounds.centerY, zMedian())
        return crs.helmertAmbiguityMeters(c)
    }

    private fun zMedian(): Double {
        val z = surface.vertices.z ?: return 0.0
        if (z.isEmpty()) return 0.0
        val s = z.copyOf().also { it.sort() }
        return s[s.size / 2]
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

    /** Центр чертежа в WGS84 при текущей привязке (для проверки и подсказок). */
    fun surfaceCenterWgs84(): Geodetic? = applied?.georef?.toWgs84(surface.bounds.centerX, surface.bounds.centerY, zMedian())

    fun export(): String? = applied?.georef?.let { GeorefJson.encode(it) }

    companion object {
        fun levelOf(m: Double) = when {
            m <= 0.02 -> Level.GOOD
            m <= 0.10 -> Level.WARN
            else -> Level.BAD
        }

        fun pointsWord(n: Int) = when {
            n % 10 == 1 && n % 100 != 11 -> "точке"
            else -> "точкам"
        }

        fun unitName(f: Double) = when {
            f == 1.0 -> "метры"; f == 0.001 -> "миллиметры"; f == 0.01 -> "сантиметры"; f == 1000.0 -> "километры"
            kotlin.math.abs(f - 0.3048) < 1e-9 -> "футы"; kotlin.math.abs(f - 1200.0 / 3937.0) < 1e-9 -> "американские футы"
            else -> "×$f м"
        }

        fun axesName(swap: Boolean) = if (swap) "X — восток, Y — север" else "X — север, Y — восток"

        /** Что пользователю нужно знать о точности перехода СК → WGS84. */
        fun datumNote(crs: CrsDef): String? = when (crs.datumStatus) {
            DatumStatus.EXACT, DatumStatus.HELMERT -> null
            DatumStatus.HELMERT_PARTIAL ->
                "Параметры перехода в WGS84 из реестра относятся к другой части территории: возможна ошибка до десятков метров."
            DatumStatus.APPROX_GRID ->
                "Для этой системы в реестре есть только сеточный переход в WGS84 (не поддерживается): возможна ошибка до сотен метров."
            DatumStatus.APPROX_UNKNOWN ->
                "Перехода в WGS84 для этой системы в реестре нет: положение на карте может отличаться на десятки–сотни метров."
        }

        fun crsWarnings(crs: CrsDef, swap: Boolean, unit: Double, evidence: HelmertDirectionEvidence? = null): List<String> = buildList {
            datumNote(crs)?.let { add(it) }
            if (crs.helmert != null && !crs.helmertDirectionConfirmed) {
                add(
                    when (evidence?.suggested) {
                        crs.helmertDirection -> "Направление параметров перехода определено по сдвигу высоты, но источником не подтверждено: сверьте положение по известной точке (экран «Проверка»)."
                        null -> "Направление параметров перехода не подтверждено источником и по высоте однозначно не определяется: проверьте положение по известной точке (экран «Проверка»)."
                        else -> "По сдвигу высоты вероятнее другое направление параметров перехода: переключите его ниже или проверьте положение по известной точке."
                    },
                )
            }
            if (swap != crs.firstAxisIsEast || kotlin.math.abs(unit - crs.unitToMeters) > 1e-12) {
                add("Порядок осей или единицы изменены относительно самой системы.")
            }
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
