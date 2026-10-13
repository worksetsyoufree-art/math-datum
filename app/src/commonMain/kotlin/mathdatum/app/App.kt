package mathdatum.app

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import mathdatum.core.Catalog
import mathdatum.core.MatchStatus

@Composable
fun App(controller: GeorefController = remember { GeorefController(Catalog.demo(), DemoData.surface()) }) {
    MaterialTheme {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Привязка чертежа", style = MaterialTheme.typography.headlineSmall)
                Text(controller.surface.name, style = MaterialTheme.typography.bodyMedium)
                TabRow(selectedTabIndex = controller.mode.ordinal) {
                    Mode.entries.forEach { m ->
                        Tab(selected = controller.mode == m, onClick = { controller.mode = m }, modifier = Modifier.heightIn(min = 48.dp)) { Text(m.title) }
                    }
                }
                Box(Modifier.weight(1f).fillMaxWidth()) {
                    when (controller.mode) {
                        Mode.AUTO -> AutoScreen(controller)
                        Mode.PICK -> PickScreen(controller)
                        Mode.POINTS -> PointsScreen(controller)
                        Mode.CHECK -> CheckScreen(controller)
                    }
                }
                StatusBar(controller)
            }
        }
    }
}

private fun String.num(): Double? = trim().replace(',', '.').toDoubleOrNull()

@Composable
private fun StatusBar(c: GeorefController) {
    val a = c.applied
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            if (a == null) Text(c.error ?: "Привязка ещё не задана", color = if (c.error != null) MaterialTheme.colorScheme.error else Color.Unspecified)
            else {
                Text("Привязка: ${a.description}", style = MaterialTheme.typography.titleSmall)
                a.rmsM?.let { Text("Среднее отклонение по точкам: ${fmt(it * 1000)} мм") }
                a.warnings.forEach { Text("Внимание: $it", color = MaterialTheme.colorScheme.error) }
            }
            var saved by remember { mutableStateOf<String?>(null) }
            // «Готово» не блокируем из-за предупреждений (в духе «не отключать кнопки»)
            Button(onClick = { saved = c.export() }, modifier = Modifier.heightIn(min = 48.dp), enabled = a != null) { Text("Сохранить привязку") }
            saved?.let { Text("Файл привязки сформирован: ${it.length} символов", style = MaterialTheme.typography.bodySmall) }
        }
    }
}

@Composable
private fun AutoScreen(c: GeorefController) {
    var lat by remember { mutableStateOf("") }
    var lon by remember { mutableStateOf("") }
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Где вы или метки? Это помогает выбрать систему координат.")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(lat, { lat = it }, label = { Text("Широта") }, modifier = Modifier.weight(1f), singleLine = true)
            OutlinedTextField(lon, { lon = it }, label = { Text("Долгота") }, modifier = Modifier.weight(1f), singleLine = true)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = { lat = DemoData.DEMO_LAT.toString(); lon = DemoData.DEMO_LON.toString() }, modifier = Modifier.heightIn(min = 48.dp)) { Text("Подставить демо-метку") }
            Button(onClick = {
                val la = lat.num(); val lo = lon.num()
                if (la != null && lo != null) c.setAnchor(la, lo) else c.clearAnchor()
                c.runAuto()
            }, modifier = Modifier.heightIn(min = 48.dp)) { Text("Подобрать") }
        }
        if (c.autoRan && c.candidates.isEmpty()) Text("Подходящих систем не найдено. Попробуйте «По точкам».")
        c.candidates.forEach { cand ->
            Card(Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(cand.crs.name, style = MaterialTheme.typography.titleSmall)
                    val status = when (cand.status) { MatchStatus.MATCH -> "подходит"; MatchStatus.NEAR -> "рядом"; MatchStatus.FAR -> "далеко" }
                    Text("$status · ${GeorefController.unitName(cand.unitToMeters)}· ${GeorefController.axesName(cand.swapXY)}")
                    cand.distanceToAnchorM?.let { Text("До вашей метки: ${fmt(it)} м") }
                    if (cand.reliability == mathdatum.core.Reliability.INDIRECT) Text("Выбрано по косвенным признакам, надёжность низкая")
                    Button(onClick = { c.apply(cand) }, modifier = Modifier.heightIn(min = 48.dp)) { Text("Применить") }
                }
            }
        }
    }
}

@Composable
private fun PickScreen(c: GeorefController) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(c.query, { c.query = it }, label = { Text("Поиск системы") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(c.pickSwap, { c.pickSwap = it }); Text("X — восток, Y — север (как в CAD)")
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(1.0, 0.001, 0.01, 1000.0).forEach { u ->
                OutlinedButton(onClick = { c.pickUnit = u }, modifier = Modifier.heightIn(min = 48.dp)) {
                    Text(GeorefController.unitName(u) + if (c.pickUnit == u) " (выбрано)" else "")
                }
            }
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(c.filteredCatalog(), key = { it.id }) { crs ->
                Card(Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(crs.name, Modifier.weight(1f))
                        Button(onClick = { c.pick(crs) }, modifier = Modifier.heightIn(min = 48.dp)) { Text("Выбрать") }
                    }
                }
            }
        }
    }
}

@Composable
private fun PointsScreen(c: GeorefController) {
    var x by remember { mutableStateOf("") }; var y by remember { mutableStateOf("") }
    var lat by remember { mutableStateOf("") }; var lon by remember { mutableStateOf("") }
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        SurfacePreview(c, Modifier.fillMaxWidth().height(180.dp))
        Text("Точка на чертеже и такая же точка в WGS84 (где вы стоите или откуда взяты координаты).")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(x, { x = it }, label = { Text("X чертежа") }, modifier = Modifier.weight(1f), singleLine = true)
            OutlinedTextField(y, { y = it }, label = { Text("Y чертежа") }, modifier = Modifier.weight(1f), singleLine = true)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(lat, { lat = it }, label = { Text("Широта") }, modifier = Modifier.weight(1f), singleLine = true)
            OutlinedTextField(lon, { lon = it }, label = { Text("Долгота") }, modifier = Modifier.weight(1f), singleLine = true)
        }
        Button(onClick = {
            val vx = x.num(); val vy = y.num(); val la = lat.num(); val lo = lon.num()
            if (vx != null && vy != null && la != null && lo != null) { c.addPair(vx, vy, la, lo); x = ""; y = ""; lat = ""; lon = "" }
        }, modifier = Modifier.heightIn(min = 48.dp)) { Text("Добавить точку") }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(c.fitHeightPlane, { c.fitHeightPlane = it; c.recomputePoints() }); Text("Высота по плоскости (нужно 3+ точек с высотой)")
        }
        c.pairStatuses().forEachIndexed { i, st ->
            Card(Modifier.fillMaxWidth()) {
                Row(Modifier.padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Checkbox(st.row.enabled, { c.togglePair(st.row.id) })
                    Column(Modifier.weight(1f)) {
                        Text("Точка ${i + 1}: (${fmt(st.row.x)}; ${fmt(st.row.y)}) ↔ (${fmt6(st.row.lat)}; ${fmt6(st.row.lon)})")
                        val level = st.level
                        // уровень передаётся и текстом, и цветом (доступность)
                        Text(
                            if (!st.row.enabled) "отключена" else if (level == null || st.residualM == null) "оценка со 3 точек" else "${level.label}: ${fmt(st.residualM * 1000)} мм",
                            color = when (level) { Level.GOOD -> Color(0xFF2E7D32); Level.WARN -> Color(0xFFB26A00); Level.BAD -> Color(0xFFC62828); null -> Color.Unspecified },
                        )
                    }
                    OutlinedButton(onClick = { c.removePair(st.row.id) }, modifier = Modifier.heightIn(min = 48.dp)) { Text("Удалить") }
                }
            }
        }
    }
}

@Composable
private fun CheckScreen(c: GeorefController) {
    var lat by remember { mutableStateOf(DemoData.DEMO_LAT.toString()) }
    var lon by remember { mutableStateOf(DemoData.DEMO_LON.toString()) }
    val la = lat.num(); val lo = lon.num()
    val mark = if (la != null && lo != null) c.toSurface(la, lo) else null
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        SurfacePreview(c, Modifier.fillMaxWidth().height(260.dp), mark = mark?.let { it.x to it.y })
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(lat, { lat = it }, label = { Text("Широта метки") }, modifier = Modifier.weight(1f), singleLine = true)
            OutlinedTextField(lon, { lon = it }, label = { Text("Долгота метки") }, modifier = Modifier.weight(1f), singleLine = true)
        }
        when {
            c.applied == null -> Text("Сначала задайте привязку на других экранах.")
            mark == null -> Text("Введите координаты метки.")
            else -> {
                val b = c.surface.bounds
                val inside = mark.x in b.minX..b.maxX && mark.y in b.minY..b.maxY
                Text("Метка на чертеже: X ${fmt(mark.x)}, Y ${fmt(mark.y)}")
                Text(if (inside) "Метка внутри чертежа." else "Метка вне чертежа. Если она должна быть внутри, проверьте единицы и порядок осей.")
            }
        }
    }
}

/** Превью вершин и габаритов; метка и точки привязки поверх. Ось Y вверх. */
@Composable
private fun SurfacePreview(c: GeorefController, modifier: Modifier, mark: Pair<Double, Double>? = null) {
    val b = c.surface.bounds
    val v = c.surface.vertices
    Canvas(modifier.background(Color(0xFFF3F3F3))) {
        val pad = 12f
        val w = size.width - 2 * pad; val h = size.height - 2 * pad
        val sx = b.maxX - b.minX; val sy = b.maxY - b.minY
        val k = minOf(w / (if (sx > 0) sx else 1.0), h / (if (sy > 0) sy else 1.0)).toFloat()
        fun px(x: Double) = pad + ((x - b.minX) * k).toFloat()
        fun py(y: Double) = size.height - pad - ((y - b.minY) * k).toFloat()
        val step = maxOf(1, v.size / 1500)
        for (i in 0 until v.size step step) {
            if (v.x[i] in b.minX..b.maxX && v.y[i] in b.minY..b.maxY) drawCircle(Color(0xFF607D8B), 1.5f, Offset(px(v.x[i]), py(v.y[i])))
        }
        c.pairs.forEach { drawCircle(if (it.enabled) Color(0xFF1565C0) else Color.Gray, 6f, Offset(px(it.x), py(it.y))) }
        mark?.let { (mx, my) -> drawCircle(Color(0xFFC62828), 8f, Offset(px(mx), py(my))) }
    }
}

private fun fmt6(v: Double) = (kotlin.math.round(v * 1_000_000) / 1_000_000).toString()

private fun fmt(v: Double): String {
    val r = kotlin.math.round(v * 100) / 100
    return r.toString().removeSuffix(".0")
}
