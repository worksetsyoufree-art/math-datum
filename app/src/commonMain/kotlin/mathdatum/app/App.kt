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
import androidx.compose.runtime.LaunchedEffect
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
import mathdatum.core.CrsDef
import mathdatum.core.HelmertDirection
import mathdatum.core.MatchStatus
import mathdatum.core.Reliability

/**
 * Корень приложения. [initial] — готовый контроллер (тесты, скриншоты); иначе справочник EPSG грузится из ресурсов.
 */
@Composable
fun App(initial: GeorefController? = null) {
    var controller by remember { mutableStateOf(initial) }
    var loadNote by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) {
        if (controller == null) {
            controller = try {
                GeorefController(loadEpsgCatalog(), DemoData.surface())
            } catch (e: Throwable) {
                loadNote = "Не удалось загрузить справочник EPSG (${e.message}). Работает урезанный демо-справочник."
                GeorefController(Catalog.demo(), DemoData.surface())
            }
        }
    }
    MaterialTheme {
        Surface(Modifier.fillMaxSize()) {
            val c = controller
            if (c == null) Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("Загрузка справочника систем координат…") }
            else Main(c, loadNote)
        }
    }
}

@Composable
private fun Main(c: GeorefController, loadNote: String?) {
    val pick = rememberTextFilePicker { name, text -> c.open(name, text) }
    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Привязка чертежа", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f))
            OutlinedButton(onClick = { c.openSurface(DemoData.surface()) }, modifier = Modifier.heightIn(min = 48.dp)) { Text("Демо") }
            Button(onClick = pick, modifier = Modifier.heightIn(min = 48.dp)) { Text("Открыть файл…") }
        }
        SurfaceSummary(c)
        loadNote?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        c.message?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
        c.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        TabRow(selectedTabIndex = c.mode.ordinal) {
            Mode.entries.forEach { m ->
                Tab(selected = c.mode == m, onClick = { c.mode = m }, modifier = Modifier.heightIn(min = 48.dp)) { Text(m.title) }
            }
        }
        Box(Modifier.weight(1f).fillMaxWidth()) {
            when (c.mode) {
                Mode.AUTO -> AutoScreen(c)
                Mode.PICK -> PickScreen(c)
                Mode.POINTS -> PointsScreen(c)
                Mode.CHECK -> CheckScreen(c)
            }
        }
        StatusBar(c)
    }
}

private fun String.num(): Double? = trim().replace(',', '.').toDoubleOrNull()

@Composable
private fun SurfaceSummary(c: GeorefController) {
    val s = c.surface; val b = s.bounds
    Column {
        Text(s.name, style = MaterialTheme.typography.titleSmall)
        Text(
            "Вершин: ${s.vertices.size} · X ${fmt(b.minX)} … ${fmt(b.maxX)} · Y ${fmt(b.minY)} … ${fmt(b.maxY)}",
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun StatusBar(c: GeorefController) {
    val a = c.applied
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            if (a == null) Text(if (c.error != null) "Привязка не задана" else "Привязка ещё не задана")
            else {
                Text("Привязка: ${a.description}", style = MaterialTheme.typography.titleSmall)
                a.rmsM?.let { Text("Среднее отклонение по точкам: ${fmt(it * 1000)} мм") }
                c.surfaceCenterWgs84()?.let { Text("Центр чертежа: ${fmt6(it.latDeg)}, ${fmt6(it.lonDeg)}", style = MaterialTheme.typography.bodySmall) }
                a.warnings.forEach { Text("Внимание: $it", color = MaterialTheme.colorScheme.error) }
                a.crs?.let { crs -> if (crs.helmert != null && !crs.helmertDirectionConfirmed || crs.source?.startsWith("user") == true && crs.helmert != null) DirectionPanel(c, crs) }
            }
            var saved by remember { mutableStateOf<String?>(null) }
            // «Готово» не блокируем из-за предупреждений (в духе «не отключать кнопки»)
            Button(onClick = { saved = c.export() }, modifier = Modifier.heightIn(min = 48.dp), enabled = a != null) { Text("Сохранить привязку") }
            saved?.let { Text("Файл привязки сформирован: ${it.length} символов", style = MaterialTheme.typography.bodySmall) }
        }
    }
}

/** Направление параметров перехода у пользовательской СК: подсказка по высоте и ручной выбор. */
@Composable
private fun DirectionPanel(c: GeorefController, crs: CrsDef) {
    val ev = c.directionEvidence(crs)
    val amb = c.directionAmbiguityMeters(crs)
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text("Направление параметров перехода в WGS84", style = MaterialTheme.typography.titleSmall)
        if (amb != null) Text("Две трактовки дают положение с расхождением около ${fmt(amb)} м.")
        if (ev != null) {
            val s = ev.suggested
            Text(
                "Сдвиг высоты при переводе в WGS84: ${fmt(ev.dhIfWgs84ToLocal)} м, если параметры заданы «WGS84 → местная»; " +
                    "${fmt(ev.dhIfLocalToWgs84)} м, если «местная → WGS84». " +
                    when (s) {
                        HelmertDirection.WGS84_TO_LOCAL -> "У настоящих систем высота меняется на единицы метров, поэтому вероятнее «WGS84 → местная»."
                        HelmertDirection.LOCAL_TO_WGS84 -> "У настоящих систем высота меняется на единицы метров, поэтому вероятнее «местная → WGS84»."
                        null -> "Однозначно решить по высоте нельзя: сверьте по известной точке."
                    },
                style = MaterialTheme.typography.bodySmall,
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            HelmertDirection.entries.forEach { d ->
                val label = if (d == HelmertDirection.WGS84_TO_LOCAL) "WGS84 → местная" else "местная → WGS84"
                val on = crs.helmertDirection == d
                OutlinedButton(onClick = { c.setHelmertDirection(crs, d) }, modifier = Modifier.heightIn(min = 48.dp)) {
                    Text(label + if (on) " (выбрано)" else "")
                }
            }
        }
    }
}

@Composable
private fun CrsNote(crs: CrsDef) {
    GeorefController.datumNote(crs)?.let { Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall) }
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
                    cand.crs.region?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                    val status = when (cand.status) { MatchStatus.MATCH -> "подходит"; MatchStatus.NEAR -> "рядом"; MatchStatus.FAR -> "далеко" }
                    Text("$status · ${GeorefController.unitName(cand.unitToMeters)} · ${GeorefController.axesName(cand.swapXY)}")
                    cand.distanceToAnchorM?.let { Text("До вашей метки: ${fmt(it)} м") }
                    if (cand.reliability == Reliability.INDIRECT) Text("Выбрано по косвенным признакам, надёжность низкая")
                    CrsNote(cand.crs)
                    Button(onClick = { c.apply(cand) }, modifier = Modifier.heightIn(min = 48.dp)) { Text("Применить") }
                }
            }
        }
    }
}

@Composable
private fun PickScreen(c: GeorefController) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        OutlinedTextField(c.query, { c.query = it }, label = { Text("Поиск: название, код EPSG, регион") }, modifier = Modifier.fillMaxWidth(), singleLine = true)
        Text("Оси:", style = MaterialTheme.typography.labelMedium)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf<Pair<Boolean?, String>>(null to "как в системе", false to "X — север", true to "X — восток").forEach { (v, label) ->
                OutlinedButton(onClick = { c.pickSwap = v }, modifier = Modifier.heightIn(min = 48.dp)) { Text(label + if (c.pickSwap == v) " (выбрано)" else "") }
            }
        }
        Text("Единицы чертежа:", style = MaterialTheme.typography.labelMedium)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf<Pair<Double?, String>>(null to "как в системе", 1.0 to "метры", 0.001 to "мм", 0.01 to "см", 1000.0 to "км").forEach { (v, label) ->
                OutlinedButton(onClick = { c.pickUnit = v }, modifier = Modifier.heightIn(min = 48.dp)) { Text(label + if (c.pickUnit == v) " (выбрано)" else "") }
            }
        }
        Text("Найдено: ${c.matchCount()}${if (c.matchCount() > 200) " (показаны первые 200)" else ""}" +
            if (c.catalog.unsupported.isNotEmpty()) " · ещё ${c.catalog.unsupported.size} систем пока не поддерживаются" else "",
            style = MaterialTheme.typography.bodySmall)
        LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            items(c.filteredCatalog(), key = { it.id }) { crs ->
                Card(Modifier.fillMaxWidth()) {
                    Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Column(Modifier.weight(1f)) {
                            Text((if (crs.source?.startsWith("user") == true) "Моя СК · " else "") + crs.name, style = MaterialTheme.typography.titleSmall)
                            Text(listOfNotNull(crs.id.takeIf { crs.epsg != null }, crs.region).joinToString(" · "), style = MaterialTheme.typography.bodySmall)
                            CrsNote(crs)
                        }
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
        Text("Оси: X и Y как в чертеже (X — восток, Y — север для обычного CAD).", style = MaterialTheme.typography.bodySmall)
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
    val center = c.surfaceCenterWgs84()
    var lat by remember(c.applied, c.surface) { mutableStateOf(center?.let { fmt6(it.latDeg) } ?: DemoData.DEMO_LAT.toString()) }
    var lon by remember(c.applied, c.surface) { mutableStateOf(center?.let { fmt6(it.lonDeg) } ?: DemoData.DEMO_LON.toString()) }
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
                if (la != null && lo != null) Text("Карта: https://www.openstreetmap.org/?mlat=${fmt6(la)}&mlon=${fmt6(lo)}#map=17/${fmt6(la)}/${fmt6(lo)}", style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

/** Превью вершин и габаритов; метка и точки привязки поверх. Ось Y вверх. */
@Composable
private fun SurfacePreview(c: GeorefController, modifier: Modifier, mark: Pair<Double, Double>? = null) {
    val b = c.surface.bounds
    val v = c.surface.vertices
    // у справочных СК (X — север) картинка рисуется как есть: по горизонтали Y, по вертикали X, если применённая привязка так задана
    val swapped = (c.applied?.georef as? mathdatum.core.CrsGeoref)?.let { !it.swapXY } ?: false
    Canvas(modifier.background(Color(0xFFF3F3F3))) {
        val pad = 12f
        val w = size.width - 2 * pad; val h = size.height - 2 * pad
        val minH = if (swapped) b.minY else b.minX; val maxH = if (swapped) b.maxY else b.maxX
        val minV = if (swapped) b.minX else b.minY; val maxV = if (swapped) b.maxX else b.maxY
        val sx = maxH - minH; val sy = maxV - minV
        val k = minOf(w / (if (sx > 0) sx else 1.0), h / (if (sy > 0) sy else 1.0)).toFloat()
        fun px(x: Double, y: Double) = pad + (((if (swapped) y else x) - minH) * k).toFloat()
        fun py(x: Double, y: Double) = size.height - pad - (((if (swapped) x else y) - minV) * k).toFloat()
        val step = maxOf(1, v.size / 1500)
        for (i in 0 until v.size step step) {
            if (v.x[i] in b.minX..b.maxX && v.y[i] in b.minY..b.maxY) drawCircle(Color(0xFF607D8B), 1.5f, Offset(px(v.x[i], v.y[i]), py(v.x[i], v.y[i])))
        }
        c.pairs.forEach { drawCircle(if (it.enabled) Color(0xFF1565C0) else Color.Gray, 6f, Offset(px(it.x, it.y), py(it.x, it.y))) }
        mark?.let { (mx, my) -> drawCircle(Color(0xFFC62828), 8f, Offset(px(mx, my), py(mx, my))) }
    }
}

private fun fmt6(v: Double): String = (kotlin.math.round(v * 1_000_000) / 1_000_000).toString()

private fun fmt(v: Double): String {
    val r = kotlin.math.round(v * 100) / 100
    return r.toString().removeSuffix(".0")
}
