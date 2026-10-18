package ru.mathdatum.localization

import kotlinx.serialization.Serializable
import kotlin.math.abs
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/*
 * Сетки высот геоида / аномалий высоты — как mathdatum/geoid.py (те же формулы, совпадение до 1e-12 м).
 *  GGF — Trimble Grid Factory (основной формат полевого ПО Trimble), little-endian; раскладка восстановлена
 *        по файлам (описание — в mathdatum/geoid.py): 0 int16 версия, 2 "TNL GRID FILE\0", 16 имя (32 байта),
 *        48 6×Double latMin, latMax, lonMin, lonMax, dlat, dlon; 96 2×Int rows, cols; 120 Double NODATA (0 — нет);
 *        128 Double масштаб; 136 10 байт флагов (смысл неизвестен; иные, чем у известных файлов, — замечание в
 *        [GeoidGrid.notes]); 146 rows·cols Float (или Short — по размеру) с СЕВЕРА на юг; хвост 2×Double min/max.
 *  GTX — бинарный big-endian: lat0, lon0, dlat, dlon (Double), rows, cols (Int), затем rows·cols Float
 *        по строкам с юга на север, внутри — с запада на восток; NODATA −88.8888.
 *  ISG — International Service for the Geoid (1.0 / 2.0), текст: begin_of_head … end_of_head, значения
 *        с севера на юг, с запада на восток. GeoTIFF читает только Python-эталон.
 * N(B, L) — высота геоида над эллипсоидом, H = h − N. Интерполяция bilinear (4 узла) или bicubic
 * (свёртка Кейса, a = −0.5, 16 узлов). Вне сетки, NODATA, бикубическая в крайней ячейке — GeoidException.
 */

class GeoidException(message: String) : IllegalArgumentException(message)

/** Ссылка на сетку в датуме: имя файла, SHA-256 содержимого, интерполяция. Сама сетка не хранится. */
@Serializable
data class GeoidRef(val file: String, val sha256: String, val interpolation: String = "bilinear")

/**
 * Регулярная сетка: узел (j, i) — широта lat0 + j·dlat, долгота lon0 + i·dlon; [values] по строкам,
 * строка 0 — южная; NODATA — NaN. [sha256] — сумма исходного файла.
 */
class GeoidGrid(
    val lat0: Double, val lon0: Double, val dlat: Double, val dlon: Double,
    val rows: Int, val cols: Int, val values: DoubleArray,
    val name: String = "grid", val sha256: String = "", val format: String = "",
    /** Замечания читателя (например, неизвестные флаги GGF). */
    val notes: List<String> = emptyList(),
) {
    /** Число шагов на 360° для глобальной по долготе сетки, иначе 0. */
    val period: Int

    init {
        if (rows < 2 || cols < 2) throw GeoidException("$name: сетка должна быть не меньше 2×2 узлов")
        if (values.size != rows * cols) throw GeoidException("$name: значений ${values.size}, ожидалось $rows×$cols")
        if (!(dlat > 0 && dlon > 0)) throw GeoidException("$name: шаг сетки должен быть > 0")
        val p = (360.0 / dlon).roundToInt()
        period = if (abs(p * dlon - 360.0) < 1e-6 && cols >= p) p else 0
    }

    val lat1: Double get() = lat0 + (rows - 1) * dlat
    val lon1: Double get() = lon0 + (cols - 1) * dlon

    fun node(j: Int, i: Int): Double = values[j * cols + i]

    fun describe(): String {
        val nodata = values.count { it.isNaN() }
        val ok = values.filter { !it.isNaN() }
        return "$name ($format): $rows×$cols узлов, B ${g(lat0)}…${g(lat1)}°, L ${g(lon0)}…${g(lon1)}°, " +
            "шаг ${g(dlat * 60)}′×${g(dlon * 60)}′" + (if (period != 0) ", глобальная по долготе" else "") +
            (if (nodata > 0) ", NODATA: $nodata" else "") +
            (if (ok.isEmpty()) "" else "; N ${ok.min().fixed(3)}…${ok.max().fixed(3)} м") +
            notes.joinToString("") { "\n  внимание: $it" }
    }

    private fun outside(lat: Double, lon: Double) = GeoidException(
        "Точка B = ${lat.fixed(8)}, L = ${lon.fixed(8)} вне сетки геоида $name " +
            "(B ${g(lat0)}…${g(lat1)}°, L ${g(lon0)}…${g(lon1)}°).",
    )

    /** Дробные индексы (y, x) узла; ошибка, если точка вне сетки. */
    private fun index(lat: Double, lon: Double): Pair<Double, Double> {
        var y = (lat - lat0) / dlat
        if (!(y.isFinite() && y >= -EDGE_EPS && y <= rows - 1 + EDGE_EPS)) throw outside(lat, lon)
        y = min(max(y, 0.0), rows - 1.0)
        var t = lon - lon0
        if (period != 0) {
            t -= 360.0 * floor(t / 360.0)
            return y to t / dlon
        }
        for (shift in doubleArrayOf(0.0, 360.0, -360.0)) {
            val x = (t + shift) / dlon
            if (x >= -EDGE_EPS && x <= cols - 1 + EDGE_EPS) return y to min(max(x, 0.0), cols - 1.0)
        }
        throw outside(lat, lon)
    }

    private fun col(i: Int) = if (period != 0) ((i % period) + period) % period else i

    private fun at(j: Int, i: Int, lat: Double, lon: Double): Double {
        val v = values[j * cols + col(i)]
        if (v.isNaN()) throw GeoidException(
            "Точка B = ${lat.fixed(8)}, L = ${lon.fixed(8)}: в ячейке сетки геоида $name нет данных (NODATA).",
        )
        return v
    }

    /** N(B, L), м. [interpolation] — "bilinear" или "bicubic". */
    fun value(lat: Double, lon: Double, interpolation: String = "bilinear"): Double {
        val (y, x) = index(lat, lon)
        when (interpolation) {
            "bilinear" -> {
                val j0 = min(floor(y).toInt(), rows - 2)
                val i0 = if (period != 0) floor(x).toInt() else min(floor(x).toInt(), cols - 2)
                val fy = y - j0
                val fx = x - i0
                val v00 = at(j0, i0, lat, lon)
                val v10 = at(j0, i0 + 1, lat, lon)
                val v01 = at(j0 + 1, i0, lat, lon)
                val v11 = at(j0 + 1, i0 + 1, lat, lon)
                return (1 - fx) * ((1 - fy) * v00 + fy * v01) + fx * ((1 - fy) * v10 + fy * v11)
            }
            "bicubic" -> {
                var j0 = floor(y).toInt()
                var i0 = floor(x).toInt()
                if (j0 == rows - 1) j0 -= 1
                if (period == 0 && i0 == cols - 1) i0 -= 1
                if (j0 < 1 || j0 + 2 > rows - 1 || (period == 0 && (i0 < 1 || i0 + 2 > cols - 1))) {
                    throw GeoidException(
                        "Точка B = ${lat.fixed(8)}, L = ${lon.fixed(8)} в крайней ячейке сетки геоида $name: " +
                            "для бикубической интерполяции нужна окрестность 4×4 узла.",
                    )
                }
                val wy = keys(y - j0)
                val wx = keys(x - i0)
                var s = 0.0
                for (a in 0 until 4) {
                    var r = 0.0
                    for (b in 0 until 4) r += wx[b] * at(j0 - 1 + a, i0 - 1 + b, lat, lon)
                    s += wy[a] * r
                }
                return s
            }
            else -> throw GeoidException("Интерполяция «$interpolation»: ожидается bilinear или bicubic.")
        }
    }

    companion object {
        const val GTX_NODATA = -88.8888
        val INTERPOLATIONS = listOf("bilinear", "bicubic")
        private const val EDGE_EPS = 1e-9

        /** Веса свёртки Кейса (a = −0.5) для узлов −1, 0, 1, 2. */
        private fun keys(t: Double): DoubleArray {
            val t2 = t * t
            val t3 = t * t * t
            return doubleArrayOf((-t3 + 2 * t2 - t) / 2, (3 * t3 - 5 * t2 + 2) / 2, (-3 * t3 + 4 * t2 + t) / 2, (t3 - t2) / 2)
        }

        /** Читает сетку из содержимого файла: .gtx или .isg (по расширению, иначе по содержимому). */
        fun parse(bytes: ByteArray, name: String): GeoidGrid {
            val ext = name.substringAfterLast('.', "").lowercase()
            val sha = Sha256.hex(bytes)
            val head = bytes.copyOfRange(0, min(bytes.size, 4096)).decodeToString()
            val ggf = bytes.size >= 16 && bytes.copyOfRange(2, 16).contentEquals(GGF_SIGNATURE)
            return when {
                ext == "ggf" || ggf -> parseGgf(bytes, name, sha)
                ext == "gtx" -> parseGtx(bytes, name, sha)
                ext == "isg" || "begin_of_head" in head -> parseIsg(bytes.decodeToString(), name, sha)
                ext == "tif" || ext == "tiff" -> throw GeoidException(
                    "$name: GeoTIFF здесь не читается — переведите сетку в GTX или ISG (python -m mathdatum geoid … -o сетка.gtx).",
                )
                else -> parseGtx(bytes, name, sha)
            }
        }

        private val GGF_SIGNATURE = "TNL GRID FILE\u0000".encodeToByteArray()
        private const val GGF_HEADER = 146
        private val GGF_KNOWN_FLAGS = byteArrayOf(2, 0, -128, 0, 2, 8, 2, 1, 0, 0)

        private fun leLong(b: ByteArray, o: Int): Long {
            var v = 0L
            for (k in 7 downTo 0) v = (v shl 8) or (b[o + k].toLong() and 0xFF)
            return v
        }

        private fun leInt(b: ByteArray, o: Int): Int {
            var v = 0
            for (k in 3 downTo 0) v = (v shl 8) or (b[o + k].toInt() and 0xFF)
            return v
        }

        private fun leDouble(b: ByteArray, o: Int) = Double.fromBits(leLong(b, o))

        private fun parseGgf(b: ByteArray, name: String, sha: String): GeoidGrid {
            if (b.size < GGF_HEADER || !b.copyOfRange(2, 16).contentEquals(GGF_SIGNATURE)) {
                throw GeoidException("$name: не GGF (нет подписи «TNL GRID FILE» в заголовке)")
            }
            val latMin = leDouble(b, 48)
            val latMax = leDouble(b, 56)
            var lonMin = leDouble(b, 64)
            val lonMax = leDouble(b, 72)
            val dlat = leDouble(b, 80)
            val dlon = leDouble(b, 88)
            val rows = leInt(b, 96)
            val cols = leInt(b, 100)
            val nodata = leDouble(b, 120)
            val scale = leDouble(b, 128)
            val flags = b.copyOfRange(136, 146)
            if (rows < 2 || cols < 2) throw GeoidException("$name: GGF $rows×$cols — сетка должна быть не меньше 2×2")
            val n = rows.toLong() * cols
            val rest = (b.size - GGF_HEADER).toLong()
            val size = when (rest) {
                4 * n, 4 * n + 16 -> 4
                2 * n, 2 * n + 16 -> 2
                else -> throw GeoidException("$name: размер GGF ${b.size} байт не соответствует сетке $rows×$cols")
            }
            if (!(dlat > 0 && dlon > 0) || abs((latMax - latMin) / dlat - (rows - 1)) > 1e-3 ||
                abs((lonMax - lonMin) / dlon - (cols - 1)) > 1e-3
            ) throw GeoidException("$name: охват и шаг заголовка GGF не соответствуют $rows×$cols узлам")
            val notes = mutableListOf<String>()
            if (!flags.contentEquals(GGF_KNOWN_FLAGS)) {
                notes += "флаги GGF ${hex(flags)} отличаются от известных (${hex(GGF_KNOWN_FLAGS)}) — " +
                    "проверьте значения сетки по контрольным пунктам"
            }
            val k = if (scale != 0.0 && scale.isFinite()) scale else 1.0
            val v = DoubleArray(rows * cols)
            for (r in 0 until rows) for (c in 0 until cols) {
                val o = GGF_HEADER + size * (r * cols + c)
                val x = if (size == 4) Float.fromBits(leInt(b, o)).toDouble()
                else ((b[o].toInt() and 0xFF) or (b[o + 1].toInt() shl 8)).toShort().toDouble()
                val bad = !x.isFinite() || (nodata != 0.0 && abs(x - nodata) <= 1e-6 * max(1.0, abs(nodata)))
                v[(rows - 1 - r) * cols + c] = if (bad) Double.NaN else x * k   // строки файла — с севера
            }
            if (lonMin >= 180.0) lonMin -= 360.0
            return GeoidGrid(latMin, lonMin, dlat, dlon, rows, cols, v, name, sha, "ggf", notes)
        }

        private fun hex(b: ByteArray) = b.joinToString(" ") { (it.toInt() and 0xFF).toString(16).padStart(2, '0') }

        private fun parseGtx(b: ByteArray, name: String, sha: String): GeoidGrid {
            if (b.size < 40) throw GeoidException("$name: файл GTX короче заголовка (40 байт)")
            fun long(o: Int): Long {
                var v = 0L
                for (k in 0 until 8) v = (v shl 8) or (b[o + k].toLong() and 0xFF)
                return v
            }
            fun int(o: Int): Int {
                var v = 0
                for (k in 0 until 4) v = (v shl 8) or (b[o + k].toInt() and 0xFF)
                return v
            }
            val lat0 = Double.fromBits(long(0))
            var lon0 = Double.fromBits(long(8))
            val dlat = Double.fromBits(long(16))
            val dlon = Double.fromBits(long(24))
            val rows = int(32)
            val cols = int(36)
            if (rows < 2 || cols < 2 || b.size.toLong() != 40L + 4L * rows * cols) {
                throw GeoidException("$name: заголовок GTX ($rows×$cols) не соответствует размеру файла ${b.size} байт")
            }
            val v = DoubleArray(rows * cols) {
                val x = Float.fromBits(int(40 + 4 * it)).toDouble()
                if (abs(x - GTX_NODATA) < 1e-4) Double.NaN else x
            }
            if (lon0 >= 180.0) lon0 -= 360.0
            return GeoidGrid(lat0, lon0, dlat, dlon, rows, cols, v, name, sha, "gtx")
        }

        /** Число или угол ISG: 45.5 | 45°30'00" | -10°00'00". */
        private fun isgNumber(s0: String): Double {
            val s = s0.trim()
            if ('°' !in s) return s.toDouble()
            val sign = if (s.startsWith("-")) -1.0 else 1.0
            val r = s.trimStart('+', '-')
            val deg = r.substringBefore('°')
            val rest = r.substringAfter('°')
            val mins = rest.substringBefore('\'', rest)
            val secs = if ('\'' in rest) rest.substringAfter('\'').replace("\"", "").trim() else ""
            return sign * (deg.toDouble() + (mins.trim().ifEmpty { "0" }.toDouble()) / 60 + (secs.ifEmpty { "0" }.toDouble()) / 3600)
        }

        private fun parseIsg(text: String, name: String, sha: String): GeoidGrid {
            val lines = text.lines()
            val b = lines.indexOfFirst { it.trim().lowercase().startsWith("begin_of_head") }
            val e = lines.indexOfFirst { it.trim().lowercase().startsWith("end_of_head") }
            if (b < 0 || e < 0) throw GeoidException("$name: нет заголовка ISG (begin_of_head … end_of_head)")
            val head = mutableMapOf<String, String>()
            for (ln in lines.subList(b + 1, e)) {
                val pos = listOf(ln.indexOf(':'), ln.indexOf('=')).filter { it >= 0 }.minOrNull() ?: continue
                head[ln.substring(0, pos).trim().lowercase()] = ln.substring(pos + 1).trim()
            }
            fun num(key: String): Double {
                val v = head[key]?.takeIf { it.isNotEmpty() } ?: throw GeoidException("$name: в заголовке ISG нет «$key»")
                return try {
                    isgNumber(v)
                } catch (ex: NumberFormatException) {
                    throw GeoidException("$name: «$key» = '$v' — не число")
                }
            }
            val order = (head["data ordering"] ?: "N-to-S, W-to-E").replace(" ", "").lowercase()
            if (order != "n-to-s,w-to-e" && order != "") {
                throw GeoidException("$name: порядок данных «${head["data ordering"]}» не поддерживается (нужен N-to-S, W-to-E)")
            }
            val ctype = (head["coord type"] ?: "geodetic").lowercase()
            if (ctype != "geodetic" && ctype != "") throw GeoidException("$name: координаты «${head["coord type"]}» — поддерживаются только геодезические")
            val units = (head["data units"]?.takeIf { it.isNotEmpty() } ?: head["units"]?.takeIf { it.isNotEmpty() } ?: "meters").lowercase()
            if (units !in listOf("meters", "metres", "m")) throw GeoidException("$name: единицы «$units» — поддерживаются только метры")
            val rows = num("nrows").toInt()
            val cols = num("ncols").toInt()
            val dlat = num("delta lat")
            val dlon = num("delta lon")
            var latMin = num("lat min")
            var lonMin = num("lon min")
            var latMax = num("lat max")
            var lonMax = num("lon max")
            val nodata = if (head["nodata"].isNullOrEmpty()) null else num("nodata")
            if ((head["node offset"] ?: "no").trim().lowercase() in listOf("yes", "1", "true")) {
                latMin += dlat / 2; lonMin += dlon / 2; latMax -= dlat / 2; lonMax -= dlon / 2
            }
            if (abs((latMax - latMin) / dlat - (rows - 1)) > 1e-3 || abs((lonMax - lonMin) / dlon - (cols - 1)) > 1e-3) {
                throw GeoidException("$name: охват и шаг заголовка ISG не соответствуют nrows = $rows, ncols = $cols")
            }
            val vals = ArrayList<String>(rows * cols)
            for (ln in lines.subList(e + 1, lines.size)) ln.split(' ', '\t', '\r').filterTo(vals) { it.isNotEmpty() }
            if (vals.size != rows * cols) {
                throw GeoidException("$name: в ISG ${vals.size} значений, ожидалось $rows×$cols = ${rows * cols}")
            }
            val v = DoubleArray(rows * cols)
            for (j in 0 until rows) for (i in 0 until cols) {
                val x = vals[(rows - 1 - j) * cols + i].toDoubleOrNull() ?: throw GeoidException("$name: «${vals[(rows - 1 - j) * cols + i]}» — не число")
                v[j * cols + i] = if (nodata != null && abs(x - nodata) <= 1e-6 * max(1.0, abs(nodata))) Double.NaN else x
            }
            return GeoidGrid(latMin, lonMin, dlat, dlon, rows, cols, v, name, sha, "isg")
        }
    }
}

/** Короткая запись числа для сообщений (до 4 знаков после точки, без хвостовых нулей). */
private fun g(v: Double): String {
    val s = v.fixed(4).trimEnd('0').trimEnd('.')
    return if (s == "-0") "0" else s
}

/** SHA-256 (FIPS 180-4) — контрольная сумма файла сетки, как hashlib.sha256 в Python. */
object Sha256 {
    private val K = intArrayOf(
        0x428a2f98, 0x71374491, -0x4a3f0431, -0x164a245b, 0x3956c25b, 0x59f111f1, -0x6dc07d5c, -0x54e3a12b,
        -0x27f85568, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, -0x7f214e02, -0x6423f959, -0x3e640e8c,
        -0x1b64963f, -0x1041b87a, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
        -0x67c1aeae, -0x57ce3993, -0x4ffcd838, -0x40a68039, -0x391ff40d, -0x2a586eb9, 0x06ca6351, 0x14292967,
        0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, -0x7e3d36d2, -0x6d8dd37b,
        -0x5d40175f, -0x57e599b5, -0x3db47490, -0x3893ae5d, -0x2e6d17e7, -0x2966f9dc, -0xbf1ca7b, 0x106aa070,
        0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, -0x7b3787ec, -0x7338fdf8, -0x6f410006, -0x5baf9315, -0x41065c09, -0x398e870e,
    )

    fun hex(data: ByteArray): String {
        val h = intArrayOf(0x6a09e667, -0x4498517b, 0x3c6ef372, -0x5ab00ac6, 0x510e527f, -0x64fa9774, 0x1f83d9ab, 0x5be0cd19)
        val bitLen = data.size.toLong() * 8
        val padLen = ((data.size + 9 + 63) / 64) * 64
        val msg = data.copyOf(padLen)
        msg[data.size] = 0x80.toByte()
        for (k in 0 until 8) msg[padLen - 1 - k] = (bitLen ushr (8 * k)).toByte()
        val w = IntArray(64)
        for (chunk in 0 until padLen / 64) {
            for (t in 0 until 16) {
                val o = chunk * 64 + 4 * t
                w[t] = (msg[o].toInt() and 0xFF shl 24) or (msg[o + 1].toInt() and 0xFF shl 16) or
                    (msg[o + 2].toInt() and 0xFF shl 8) or (msg[o + 3].toInt() and 0xFF)
            }
            for (t in 16 until 64) {
                val s0 = w[t - 15].rotateRight(7) xor w[t - 15].rotateRight(18) xor (w[t - 15] ushr 3)
                val s1 = w[t - 2].rotateRight(17) xor w[t - 2].rotateRight(19) xor (w[t - 2] ushr 10)
                w[t] = w[t - 16] + s0 + w[t - 7] + s1
            }
            var a = h[0]; var b = h[1]; var c = h[2]; var d = h[3]
            var e = h[4]; var f = h[5]; var g = h[6]; var hh = h[7]
            for (t in 0 until 64) {
                val s1 = e.rotateRight(6) xor e.rotateRight(11) xor e.rotateRight(25)
                val ch = (e and f) xor (e.inv() and g)
                val t1 = hh + s1 + ch + K[t] + w[t]
                val s0 = a.rotateRight(2) xor a.rotateRight(13) xor a.rotateRight(22)
                val maj = (a and b) xor (a and c) xor (b and c)
                val t2 = s0 + maj
                hh = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2
            }
            h[0] += a; h[1] += b; h[2] += c; h[3] += d; h[4] += e; h[5] += f; h[6] += g; h[7] += hh
        }
        return h.joinToString("") { it.toUInt().toString(16).padStart(8, '0') }
    }
}
