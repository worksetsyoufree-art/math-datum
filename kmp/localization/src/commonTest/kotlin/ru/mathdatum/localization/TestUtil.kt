package ru.mathdatum.localization

import kotlin.math.abs
import kotlin.math.max
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/* Общие проверки для сверки с Python-эталоном (LocalizationTest, GeoidTest). */

internal fun near(expected: Double, actual: Double, tol: Double, what: String) =
    assertTrue(abs(expected - actual) <= tol, "$what: ожидалось $expected, получено $actual (допуск $tol)")

/** NaN в эталоне — величина не определена (null); иначе допуск tol·max(1, |ожидаемое|). */
internal fun nearOrNull(expected: Double, actual: Double?, tol: Double, what: String) {
    if (expected.isNaN()) {
        assertTrue(actual == null, "$what: ожидалось null, получено $actual")
    } else {
        assertTrue(actual != null, "$what: ожидалось $expected, получено null")
        near(expected, actual, tol * max(1.0, abs(expected)), what)
    }
}

/** Сверка диагностики надёжности с Python-эталоном. */
internal fun checkDiag(what: String, d: LocalizationDatum, diag: DoubleArray, resid: List<DoubleArray>) {
    nearOrNull(diag[0], d.redundancyPlan?.toDouble(), 0.0, "$what redundancyPlan")
    nearOrNull(diag[1], d.redundancyHeight?.toDouble(), 0.0, "$what redundancyHeight")
    nearOrNull(diag[2], d.s0Plan, 1e-6, "$what s0Plan")
    nearOrNull(diag[3], d.s0Height, 1e-6, "$what s0Height")
    assertEquals(resid.size, d.residuals.size)
    resid.forEachIndexed { i, e ->
        val r = d.residuals[i]
        val w = "$what ${r.name}"
        nearOrNull(e[0], r.qvvPlan, 1e-8, "$w qvvPlan")
        nearOrNull(e[1], r.qvvHeight, 1e-8, "$w qvvHeight")
        nearOrNull(e[2], r.wx, 1e-4, "$w wx")
        nearOrNull(e[3], r.wy, 1e-4, "$w wy")
        nearOrNull(e[4], r.wH, 1e-4, "$w wH")
        nearOrNull(e[5], r.looDx, 1e-6, "$w looDx")
        nearOrNull(e[6], r.looDy, 1e-6, "$w looDy")
        nearOrNull(e[7], r.looDH, 1e-6, "$w looDH")
        nearOrNull(e[8], r.pPlan, 1e-12, "$w pPlan")
        nearOrNull(e[9], r.pHeight, 1e-12, "$w pHeight")
        near(e[10], r.dx, 1e-6, "$w dx")
        near(e[11], r.dy, 1e-6, "$w dy")
        near(e[12], r.dH, 1e-6, "$w dH")
    }
}

/** Параметры датума против эталона (те же допуски, что по регионам). */
internal fun checkParams(what: String, d: LocalizationDatum, e: DoubleArray) {
    near(e[0], d.lat0, 1e-12, "$what lat0")
    near(e[1], d.lon0, 1e-12, "$what lon0")
    near(e[2], d.nc, 1e-5, "$what Nc")
    near(e[3], d.ec, 1e-5, "$what Ec")
    near(e[4], d.a, 1e-10, "$what a")
    near(e[5], d.b, 1e-10, "$what b")
    near(e[6], d.tx, 1e-6, "$what tx")
    near(e[7], d.ty, 1e-6, "$what ty")
    near(e[8], d.c0, 1e-6, "$what c0")
    near(e[9], d.c1, 1e-10, "$what c1")
    near(e[10], d.c2, 1e-10, "$what c2")
    near(e[11], d.rmsPlan!!, 1e-6, "$what rmsPlan")
    nearOrNull(e[12], d.rmsHeight, 1e-6, "$what rmsHeight")
}

internal fun checkQuality(what: String, d: LocalizationDatum, pts: List<DoubleArray>, expected: List<DoubleArray>) {
    pts.forEachIndexed { i, p ->
        val q = d.quality(WgsPoint(p[0], p[1], p[2]))
        val qp = d.quality(WgsPoint(p[0], p[1], p[2]), posterior = true)
        val e = expected[i]
        nearOrNull(e[0], q.outside, 1e-6, "$what #$i outside")
        nearOrNull(e[1], q.mPlan, 1e-7, "$what #$i mPlan")
        nearOrNull(e[2], q.mHeight, 1e-7, "$what #$i mH")
        nearOrNull(e[3], qp.mPlan, 1e-7, "$what #$i mPlan апост.")
        nearOrNull(e[4], qp.mHeight, 1e-7, "$what #$i mH апост.")
    }
}
