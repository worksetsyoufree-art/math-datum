package ru.mathdatum.localization

import kotlin.math.abs
import kotlin.math.pow
import kotlin.math.round

/*
 * CSV в том же формате, что у Python-эталона (mathdatum/io.py).
 * Первая строка — заголовок; разделитель «;» или «,» определяется по заголовку.
 * Пары:   name;B;L;h;x;y;H[;use][;sigma_plan][;sigma_height]     Точки WGS: name;B;L;h     Местные точки: name;x;y;H
 * sigma_plan, sigma_height — необязательные априорные СКО точки, м; пусто — глобальная σ.
 * Пересчёт между системами: name;B;L;h | name;X;Y;Z | name;x;y;H ([parseColumns]).
 */
object Csv {
    fun parsePairs(text: String): List<LocalizationPair> = rows(text).mapIndexed { i, (r, line) ->
        try {
            LocalizationPair(
                name = r["name"]?.takeIf { it.isNotEmpty() } ?: "P${i + 1}",
                lat = num(r, "B"), lon = num(r, "L"), h = num(r, "h"),
                x = num(r, "x"), y = num(r, "y"), height = num(r, "H"),
                use = r["use"]?.takeIf { it.isNotEmpty() }?.let(Use::parse) ?: Use.BOTH,
                sigmaPlan = r["sigma_plan"]?.takeIf { it.isNotEmpty() }?.let { num(r, "sigma_plan") },
                sigmaHeight = r["sigma_height"]?.takeIf { it.isNotEmpty() }?.let { num(r, "sigma_height") },
            )
        } catch (e: IllegalArgumentException) {
            throw IllegalArgumentException("Строка $line: ${e.message}")
        }
    }

    fun parseWgsPoints(text: String): List<Pair<String, WgsPoint>> = rows(text).mapIndexed { i, (r, line) ->
        try {
            (r["name"]?.takeIf { it.isNotEmpty() } ?: "P${i + 1}") to WgsPoint(num(r, "B"), num(r, "L"), num(r, "h"))
        } catch (e: IllegalArgumentException) {
            throw IllegalArgumentException("Строка $line: ${e.message}")
        }
    }

    fun parseLocalPoints(text: String): List<Pair<String, LocalPoint>> = rows(text).mapIndexed { i, (r, line) ->
        try {
            (r["name"]?.takeIf { it.isNotEmpty() } ?: "P${i + 1}") to LocalPoint(num(r, "x"), num(r, "y"), num(r, "H"))
        } catch (e: IllegalArgumentException) {
            throw IllegalArgumentException("Строка $line: ${e.message}")
        }
    }

    /** Произвольные числовые столбцы [columns] (например X;Y;Z) → (name, значения). */
    fun parseColumns(text: String, columns: List<String>): List<Pair<String, DoubleArray>> = rows(text).mapIndexed { i, (r, line) ->
        try {
            (r["name"]?.takeIf { it.isNotEmpty() } ?: "P${i + 1}") to DoubleArray(columns.size) { num(r, columns[it]) }
        } catch (e: IllegalArgumentException) {
            throw IllegalArgumentException("Строка $line: ${e.message}")
        }
    }

    /** name и столбцы [columns] с [digits] знаками после точки. */
    fun formatColumns(points: List<Pair<String, DoubleArray>>, columns: List<String>, digits: List<Int>): String =
        "name;${columns.joinToString(";")}\n" + points.joinToString("") { (n, v) ->
            n + v.indices.joinToString("") { ";" + v[it].fixed(digits[it]) } + "\n"
        }

    fun formatWgs(points: List<Pair<String, WgsPoint>>): String =
        "name;B;L;h\n" + points.joinToString("") { (n, p) -> "$n;${p.lat.fixed(10)};${p.lon.fixed(10)};${p.h.fixed(4)}\n" }

    fun formatLocal(points: List<Pair<String, LocalPoint>>): String =
        "name;x;y;H\n" + points.joinToString("") { (n, p) -> "$n;${p.x.fixed(4)};${p.y.fixed(4)};${p.height.fixed(4)}\n" }

    /** Строка таблицы: значения по именам столбцов; при разделителе «;» допускается десятичная запятая. */
    private class Row(val values: Map<String, String>, val commaDecimal: Boolean) {
        operator fun get(key: String) = values[key]
    }

    private fun rows(text: String): List<Pair<Row, Int>> {
        val lines = text.removePrefix("\uFEFF").lines().mapIndexed { i, s -> s to i + 1 }.filter { it.first.isNotBlank() }
        if (lines.isEmpty()) return emptyList()
        val head = lines.first().first
        val delimiter = if (head.count { it == ';' } >= head.count { it == ',' }) ';' else ','
        val cols = head.split(delimiter).map { it.trim() }
        return lines.drop(1).map { (s, n) ->
            val v = s.split(delimiter).map { it.trim() }
            Row(cols.indices.associate { cols[it] to v.getOrElse(it) { "" } }, delimiter == ';') to n
        }
    }

    private fun num(r: Row, key: String): Double {
        val s = r[key] ?: throw IllegalArgumentException("нет столбца «$key»")
        val t = s.replace(" ", "").let { if (r.commaDecimal) it.replace(',', '.') else it }
        return t.toDoubleOrNull() ?: throw IllegalArgumentException("«$key» = «$s» — не число")
    }
}

/** Число с фиксированным количеством знаков после точки (одинаково на всех платформах). */
fun Double.fixed(digits: Int): String {
    if (isNaN() || isInfinite()) return toString()
    val p = 10.0.pow(digits)
    val r = round(abs(this) * p)
    val sign = if (this < 0 && r != 0.0) "-" else ""
    val intPart = (r / p).toLong()
    val frac = (r - intPart * p).toLong()
    return if (digits == 0) "$sign$intPart" else "$sign$intPart." + frac.toString().padStart(digits, '0')
}

/** Текстовый отчёт о локализации. */
fun LocalizationDatum.report(): String = buildString {
    gnssSystem?.takeIf { it != "WGS-84" }?.let { Datums.system(it) }?.let {
        appendLine("ГНСС:   ${it.name}, рабочая проекция на эллипсоиде ${it.ellipsoid.name} ($ellipsoid)")
    }
    appendLine("План:   модель $planModel; масштаб ${scale.fixed(9)} (${signed(scalePpm, 2)} ppm), разворот ${signed(rotationArcsec, 2)}″")
    appendLine("Высота: модель $heightModel; c0 = ${signed(c0, 4)} м, наклон N ${signed(c1 * 1e6, 2)} мм/км, E ${signed(c2 * 1e6, 2)} мм/км")
    appendLine("СКО:    план ${rmsPlan?.fixed(4) ?: "—"} м, высота ${rmsHeight?.fixed(4) ?: "—"} м")
    if (redundancyPlan != null) {
        appendLine(
            "Избыточность: план $redundancyPlan, высота ${redundancyHeight ?: "—"}; СКО ед. веса (на координату): " +
                "план ${f4(s0Plan)} м (априори ${f4(sigma0Plan)}), высота ${f4(s0Height)} м (априори ${f4(sigma0Height)})",
        )
    }
    appendLine()
    val w = weighted
    appendLine(
        "точка".padEnd(12) + "use".padEnd(8) + "dx, м".padStart(10) + "dy, м".padStart(10) + "dH, м".padStart(10) +
            (if (w) "σ план".padStart(9) + "σ выс".padStart(8) else "") +
            "|w|план".padStart(9) + "|w|выс".padStart(8) + "LOO план".padStart(10) + "LOO dH".padStart(9),
    )
    for (r in residuals) {
        append(r.name.padEnd(12) + r.use.name.lowercase().padEnd(8))
        append(r.dx.fixed(4).padStart(10) + r.dy.fixed(4).padStart(10) + r.dH.fixed(4).padStart(10))
        if (w) append(f4(r.sigmaPlan).padStart(9) + f4(r.sigmaHeight).padStart(8))
        append((r.wPlan?.fixed(2) ?: "—").padStart(9) + (r.wH?.let { kotlin.math.abs(it).fixed(2) } ?: "—").padStart(8))
        append(f4(r.looPlan).padStart(10) + f4(r.looDH).padStart(9))
        appendLine((if (r.suspect) "  !" else "") + (if (r.use == Use.NONE) "  (контроль)" else ""))
    }
    if (redundancyPlan != null) {
        appendLine(
            "|w| — нормированная поправка (тест Баарда, порог $wLimit, «!» — подозрение); " +
                "LOO — ошибка прогноза без точки, м; «—» — нельзя проверить." +
                (if (w) " σ — априорная СКО точки, м (вес p = σ0² / σ²)." else ""),
        )
    }
    if (warnings.isNotEmpty()) {
        appendLine()
        appendLine("Предупреждения:")
        for (x in warnings) appendLine("  - ${x.message}")
    }
}

private fun f4(v: Double?) = v?.fixed(4) ?: "—"

internal fun signed(v: Double, d: Int) = (if (v >= 0) "+" else "") + v.fixed(d)
