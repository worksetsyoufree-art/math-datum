package mathdatum.core

/**
 * Минимальный JSON без зависимостей. Значения: Map<String, Any?>, List<Any?>, String, Double, Boolean, null.
 * Числа читаются как Double; целые читаются через [asInt].
 */
object Json {
    class ParseException(message: String) : Exception(message)

    fun parse(text: String): Any? {
        val p = Parser(text)
        p.ws()
        val v = p.value()
        p.ws()
        if (p.i != text.length) throw ParseException("Лишние символы в позиции ${p.i}")
        return v
    }

    fun write(value: Any?, indent: Boolean = false): String = StringBuilder().also { write(it, value, if (indent) 0 else -1) }.toString()

    private fun write(sb: StringBuilder, v: Any?, level: Int) {
        val nl: (Int) -> Unit = { l -> if (level >= 0) { sb.append('\n'); repeat(l * 2) { sb.append(' ') } } }
        when (v) {
            null -> sb.append("null")
            is Boolean -> sb.append(v)
            is Int -> sb.append(v)
            is Long -> sb.append(v)
            is Double -> {
                require(v.isFinite()) { "NaN/Infinity нельзя записать в JSON" }
                sb.append(v)
            }
            is String -> quote(sb, v)
            is Map<*, *> -> {
                sb.append('{')
                var first = true
                for ((k, x) in v) {
                    if (!first) sb.append(',')
                    first = false
                    if (level >= 0) nl(level + 1)
                    quote(sb, k as String); sb.append(':'); if (level >= 0) sb.append(' ')
                    write(sb, x, if (level >= 0) level + 1 else -1)
                }
                if (!first && level >= 0) nl(level)
                sb.append('}')
            }
            is List<*> -> {
                sb.append('[')
                var first = true
                for (x in v) {
                    if (!first) sb.append(',')
                    first = false
                    if (level >= 0) nl(level + 1)
                    write(sb, x, if (level >= 0) level + 1 else -1)
                }
                if (!first && level >= 0) nl(level)
                sb.append(']')
            }
            else -> throw IllegalArgumentException("Неподдерживаемый тип ${v::class}")
        }
    }

    private fun quote(sb: StringBuilder, s: String) {
        sb.append('"')
        for (c in s) when (c) {
            '"' -> sb.append("\\\""); '\\' -> sb.append("\\\\")
            '\n' -> sb.append("\\n"); '\r' -> sb.append("\\r"); '\t' -> sb.append("\\t")
            else -> if (c < ' ') sb.append("\\u").append(c.code.toString(16).padStart(4, '0')) else sb.append(c)
        }
        sb.append('"')
    }

    private class Parser(val s: String) {
        var i = 0
        fun ws() { while (i < s.length && s[i].isWhitespace()) i++ }
        fun value(): Any? {
            if (i >= s.length) throw ParseException("Неожиданный конец")
            return when (val c = s[i]) {
                '{' -> obj()
                '[' -> arr()
                '"' -> str()
                't' -> lit("true", true)
                'f' -> lit("false", false)
                'n' -> lit("null", null)
                else -> if (c == '-' || c.isDigit()) num() else throw ParseException("Неожиданный символ '$c' в позиции $i")
            }
        }
        fun lit(w: String, v: Any?): Any? {
            if (!s.startsWith(w, i)) throw ParseException("Ожидалось $w в позиции $i")
            i += w.length; return v
        }
        fun num(): Double {
            val st = i
            while (i < s.length && (s[i].isDigit() || s[i] in "+-.eE")) i++
            return s.substring(st, i).toDoubleOrNull() ?: throw ParseException("Неверное число в позиции $st")
        }
        fun str(): String {
            i++
            val sb = StringBuilder()
            while (true) {
                if (i >= s.length) throw ParseException("Строка не закрыта")
                val c = s[i++]
                when (c) {
                    '"' -> return sb.toString()
                    '\\' -> {
                        if (i >= s.length) throw ParseException("Строка не закрыта")
                        when (val e = s[i++]) {
                            'n' -> sb.append('\n'); 'r' -> sb.append('\r'); 't' -> sb.append('\t')
                            'b' -> sb.append('\b'); 'f' -> sb.append('\u000C')
                            'u' -> {
                                if (i + 4 > s.length) throw ParseException("Неверный \\u")
                                sb.append(s.substring(i, i + 4).toInt(16).toChar()); i += 4
                            }
                            '"', '\\', '/' -> sb.append(e)
                            else -> throw ParseException("Неверный escape \\$e")
                        }
                    }
                    else -> sb.append(c)
                }
            }
        }
        fun arr(): List<Any?> {
            i++; ws()
            val r = ArrayList<Any?>()
            if (s.getOrNull(i) == ']') { i++; return r }
            while (true) {
                ws(); r += value(); ws()
                when (s.getOrNull(i++)) { ',' -> continue; ']' -> return r; else -> throw ParseException("Ожидалось , или ] в позиции ${i - 1}") }
            }
        }
        fun obj(): Map<String, Any?> {
            i++; ws()
            val r = LinkedHashMap<String, Any?>()
            if (s.getOrNull(i) == '}') { i++; return r }
            while (true) {
                ws()
                if (s.getOrNull(i) != '"') throw ParseException("Ожидался ключ в позиции $i")
                val k = str(); ws()
                if (s.getOrNull(i++) != ':') throw ParseException("Ожидалось : в позиции ${i - 1}")
                ws(); r[k] = value(); ws()
                when (s.getOrNull(i++)) { ',' -> continue; '}' -> return r; else -> throw ParseException("Ожидалось , или } в позиции ${i - 1}") }
            }
        }
    }
}

// Хелперы чтения для разбора форматов
@Suppress("UNCHECKED_CAST")
internal fun Any?.asMap(what: String): Map<String, Any?> = this as? Map<String, Any?> ?: throw Json.ParseException("$what: ожидался объект")
@Suppress("UNCHECKED_CAST")
internal fun Any?.asList(what: String): List<Any?> = this as? List<Any?> ?: throw Json.ParseException("$what: ожидался массив")
internal fun Any?.asDouble(what: String): Double = this as? Double ?: throw Json.ParseException("$what: ожидалось число")
internal fun Any?.asInt(what: String): Int = asDouble(what).let { d -> if (d == kotlin.math.floor(d)) d.toInt() else throw Json.ParseException("$what: ожидалось целое") }
internal fun Any?.asString(what: String): String = this as? String ?: throw Json.ParseException("$what: ожидалась строка")
