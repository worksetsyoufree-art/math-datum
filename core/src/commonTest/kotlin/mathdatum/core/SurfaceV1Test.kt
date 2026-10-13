package mathdatum.core

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class SurfaceV1Test {
    private val ok = """SURFACE_V1
loaded file name: ACAD-Тест surfaceId: 0 dxf
4
2
10 20 5
0 0 0
20 40 10
12 22 6
0 0 0
20 40 10
12 22 6
10 20 5
0 1 2
1 2 3
"""

    // центр = среднее вершин (0+20+12+10)/4 = 10.5 ... строим так, чтобы служебные точки совпали с вычисленными
    private fun consistent(): String {
        val v = listOf(Triple(0.0, 0.0, 0.0), Triple(20.0, 40.0, 10.0), Triple(10.0, 20.0, 5.0), Triple(10.0, 20.0, 5.0))
        val mean = Triple(v.sumOf { it.first } / 4, v.sumOf { it.second } / 4, v.sumOf { it.third } / 4)
        val near = Triple(10.0, 20.0, 5.0)
        return "SURFACE_V1\nloaded file name: Тест surfaceId: 3 dxf\n4\n2\n" +
            "${mean.first} ${mean.second} ${mean.third}\n0 0 0\n20 40 10\n${near.first} ${near.second} ${near.third}\n" +
            v.joinToString("\n") { "${it.first} ${it.second} ${it.third}" } + "\n0 1 2\n1 2 3\n"
    }

    @Test
    fun parsesHeaderVerticesTrianglesAndHints() {
        val m = SurfaceV1.parse(consistent().replace("\n", "\r\n"))
        assertEquals("Тест", m.title)
        assertEquals(4, m.points.size); assertEquals(2, m.triangleCount)
        assertEquals(listOf(0, 1, 2, 1, 2, 3), m.triangles.toList())
        val h = assertNotNull(m.hints)
        assertEquals(0.0, h.min.x); assertEquals(40.0, h.max.y); assertEquals(10.0, h.mid.x); assertEquals(10.0, h.near.x)
        assertEquals(4, m.service.size)
    }

    @Test
    fun unclassifiableServicePointsAreKeptRaw() {
        val m = SurfaceV1.parse(ok)
        assertNull(m.hints)           // служебные точки в этом файле не сходятся с вершинами
        assertEquals(4, m.service.size)
        assertEquals(4, m.points.size)
    }

    @Test
    fun brokenFilesGiveLineNumbers() {
        val bad = { s: String -> assertFailsWith<SurfaceParseException> { SurfaceV1.parse(s) }.message!! }
        assertTrue(bad("NOT_A_SURFACE\n").contains("SURFACE_V1"))
        assertTrue(bad(consistent().replace("0 1 2", "0 1 9")).contains("вне диапазона"))
        assertTrue(bad(consistent().replace("20 40 10\n10", "20 40\n10")).contains("3 числа"))
        assertTrue(bad(consistent().replace("0 1 2", "0 x 2")).contains("не индекс"))
        assertTrue(bad(consistent().substringBeforeLast("1 2 3")).contains("Неожиданный конец"))
        assertTrue(bad("SURFACE_V1\nname\nabc\n1\n").contains("число вершин"))
        assertTrue(bad(consistent().replace("20 40 10\n10", "20 NaN 10\n10")).isNotEmpty())
    }
}
