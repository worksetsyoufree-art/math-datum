package ru.mathdatum.localization

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlin.time.Clock
import kotlin.time.ExperimentalTime
import kotlin.uuid.ExperimentalUuidApi
import kotlin.uuid.Uuid

/*
 * Метаданные датума и контрольная сумма исходных данных — как mathdatum/meta.py.
 * Каноническая запись (вход SHA-256) одинакова в Python и Kotlin:
 *   mathdatum inputs v1
 *   gnss_datum="WGS-84"          — поля LocalizeInputs по порядку (null — не задано)
 *   pair="R1";55.05…;…;"both";null;null   — name;B;L;h;x;y;H;use;sigma_plan;sigma_height
 * Числа — как repr(float) в Python ([Export.pyRepr]), строки — в кавычках с экранированием \ " и
 * управляющих символов (\u00XX); строки разделены \n, в конце \n; UTF-8.
 */

/** Версия библиотеки (общая с Python-эталоном). */
const val MATHDATUM_VERSION = "0.9.0"
const val MATHDATUM_LIBRARY = "mathdatum (Kotlin) $MATHDATUM_VERSION"

/** Метаданные датума; все поля необязательны (null — не указано). */
@Serializable
data class DatumMeta(
    /** Объект / наименование. */
    @SerialName("object") val objectName: String? = null,
    val organization: String? = null,
    /** Исполнитель. */
    val author: String? = null,
    /** Дата и время расчёта, UTC, ISO 8601: 2026-10-18T12:00:00Z. */
    @SerialName("computed_at") val computedAt: String? = null,
    @SerialName("library_version") val libraryVersion: String? = null,
    /** UUID датума; ревизия 1, 2, …; UUID предыдущей ревизии. */
    @SerialName("datum_id") val datumId: String? = null,
    val revision: Int? = null,
    @SerialName("previous_id") val previousId: String? = null,
    /** Источник каталога пунктов. */
    @SerialName("catalog_source") val catalogSource: String? = null,
    /** Система ГНСС, оборудование, базовая станция. */
    @SerialName("gnss_equipment") val gnssEquipment: String? = null,
    val note: String? = null,
    /** SHA-256 канонической записи пар и параметров. */
    @SerialName("inputs_sha256") val inputsSha256: String? = null,
) {
    /**
     * Метаданные следующей ревизии: описательные поля наследуются (кроме примечания), revision + 1,
     * previousId — UUID этой ревизии; id, время и сумма назначаются при расчёте.
     */
    fun nextRevision(): DatumMeta {
        val id = datumId ?: throw IllegalArgumentException("У предыдущего датума нет идентификатора (datum_id): ревизию не связать.")
        return DatumMeta(
            objectName = objectName, organization = organization, author = author, catalogSource = catalogSource,
            gnssEquipment = gnssEquipment, revision = (revision ?: 1) + 1, previousId = id,
        )
    }
}

/** Параметры localize, от которых зависит результат (с парами — вход контрольной суммы); null — по умолчанию. */
@Serializable
data class LocalizeInputs(
    @SerialName("gnss_datum") val gnssDatum: String = "WGS-84",
    @SerialName("sigma_plan") val sigmaPlan: Double = 0.02,
    @SerialName("sigma_height") val sigmaHeight: Double = 0.03,
    @SerialName("w_limit") val wLimit: Double = 3.29,
    @SerialName("max_scale_ppm") val maxScalePpm: Double = 200.0,
    @SerialName("max_rotation_deg") val maxRotationDeg: Double = 3.0,
    /** Запрошенная модель высоты. */
    @SerialName("height_model") val heightModel: String = "plane",
    @SerialName("geoid_sha256") val geoidSha256: String? = null,
    @SerialName("geoid_interpolation") val geoidInterpolation: String? = null,
    val lat0: Double? = null,
    val lon0: Double? = null,
    val ellipsoid: String? = null,
    val k0: Double = 1.0,
    val x0: Double = 0.0,
    val y0: Double = 0.0,
)

object DatumChecksum {
    private const val HEADER = "mathdatum inputs v1"

    private fun jstr(s: String) = buildString {
        append('"')
        for (ch in s) when {
            ch == '"' || ch == '\\' -> append('\\').append(ch)
            ch.code < 0x20 -> append("\\u").append(ch.code.toString(16).padStart(4, '0'))
            else -> append(ch)
        }
        append('"')
    }

    private fun v(x: Double?) = if (x == null) "null" else Export.pyRepr(x)
    private fun v(s: String?) = if (s == null) "null" else jstr(s)

    /** Каноническая запись пар и параметров (вход SHA-256). */
    fun canonical(pairs: List<LocalizationPair>, i: LocalizeInputs): String = buildString {
        append(HEADER).append('\n')
        listOf(
            "gnss_datum" to v(i.gnssDatum), "sigma_plan" to v(i.sigmaPlan), "sigma_height" to v(i.sigmaHeight),
            "w_limit" to v(i.wLimit), "max_scale_ppm" to v(i.maxScalePpm), "max_rotation_deg" to v(i.maxRotationDeg),
            "height_model" to v(i.heightModel), "geoid_sha256" to v(i.geoidSha256),
            "geoid_interpolation" to v(i.geoidInterpolation), "lat0" to v(i.lat0), "lon0" to v(i.lon0),
            "ellipsoid" to v(i.ellipsoid), "k0" to v(i.k0), "x0" to v(i.x0), "y0" to v(i.y0),
        ).forEach { (k, s) -> append(k).append('=').append(s).append('\n') }
        for (p in pairs) {
            append("pair=").append(
                listOf(jstr(p.name), v(p.lat), v(p.lon), v(p.h), v(p.x), v(p.y), v(p.height), jstr(useName(p.use)),
                    v(p.sigmaPlan), v(p.sigmaHeight)).joinToString(";"),
            ).append('\n')
        }
    }

    /** SHA-256 (hex) канонической записи. */
    fun of(pairs: List<LocalizationPair>, inputs: LocalizeInputs): String = Sha256.hex(canonical(pairs, inputs).encodeToByteArray())

    internal fun useName(u: Use) = when (u) {
        Use.BOTH -> "both"
        Use.PLAN -> "plan"
        Use.HEIGHT -> "height"
        Use.NONE -> "none"
    }

    /** Текущее время UTC, ISO 8601 с точностью до секунды. */
    @OptIn(ExperimentalTime::class)
    fun nowUtc(): String = Clock.System.now().toString().take(19) + "Z"

    @OptIn(ExperimentalUuidApi::class)
    fun newId(): String = Uuid.random().toString()
}
