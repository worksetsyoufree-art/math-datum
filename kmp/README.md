# mathdatum-kmp — локализация ГНСС на Kotlin Multiplatform

Модуль `:localization` реализует ту же локализацию и те же пересчёты между государственными
системами координат (ГОСТ 32453-2017), что Python-эталон `mathdatum/` в корне репозитория: те же
формулы, тот же формат CSV и JSON. Датум, сохранённый в Python, читается в Kotlin, и наоборот.

| Платформа | Цель | Что получается |
|---|---|---|
| Android | `androidTarget` | `localization-release.aar` |
| iOS | `iosArm64`, `iosSimulatorArm64`, `iosX64` | фреймворк `MathDatum` (собирается на macOS) |
| Web | `js` (браузер и Node) | библиотека + веб-приложение `:webApp` |
| Desktop | `jvm("desktop")` | `localization-desktop.jar` |

## Запустить веб-приложение

Готовая сборка лежит в `web-dist/`: откройте `web-dist/index.html` в браузере, сервер не нужен.

На странице можно:
- выбрать модель высоты (плоскость, геоид, геоид + плоскость) и загрузить сетку геоида (.ggf Trimble, .gtx, .isg) —
  файл читается в браузере и никуда не отправляется; датум с геоидом при загрузке требует ту же сетку (SHA-256);
- выбрать систему ГНСС-координат пар (WGS-84 по умолчанию, ПЗ-90.11, ГСК-2011, ITRF-2008, СК-42…) — рабочая
  проекция строится на её эллипсоиде;
- вставить или открыть CSV с парами точек и рассчитать локализацию; необязательные столбцы
  `sigma_plan;sigma_height` задают σ точки (вес `p = σ0²/σ²`), использованные σ видны в таблице;
- посмотреть невязки, нормированные поправки |w| (подсвечиваются |w| > 3.29 — вероятные грубые ошибки),
  ошибки «без точки» (leave-one-out), избыточность и предупреждения датума;
- скачать датум в JSON и скопировать строку PROJ;
- пересчитать точки ГНСС → местная и обратно (кнопка «Обратно ←» проверяет пересчёт туда и обратно);
  если точки ГНСС в другой системе, чем датум, её выбирают в списке — пересчёт по 7 параметрам ГОСТ.
  Точки вне выпуклой оболочки опорных пунктов перечисляются под результатом; флажок «столбцы качества»
  добавляет `outside_m;m_plan;m_H`;
- пересчитать точки между системами (СК-42, СК-95, ГСК-2011, ПЗ-90.x, WGS-84, ITRF-2008) в форматах
  BLH, XYZ и Гаусс–Крюгер 6° (раздел 4); путь по параметрам ГОСТ показывается под результатом.

Пересобрать:

```
./gradlew :webApp:jsBrowserDistribution          # → webApp/build/dist/js/productionExecutable/
./gradlew :webApp:jsBrowserDevelopmentRun        # dev-сервер с автообновлением
```

## Сборка и тесты

Нужны JDK 17+ и Android SDK. Путь к SDK задаётся в `local.properties` (`sdk.dir=...`) или в `ANDROID_HOME`.

```
./gradlew :localization:desktopTest              # тесты на JVM
./gradlew :localization:jsNodeTest               # тесты на JS (Node)
./gradlew :localization:testDebugUnitTest        # тесты на Android (JVM)
./gradlew :localization:iosSimulatorArm64Test    # тесты на iOS-симуляторе (только macOS)
./gradlew :localization:assemble                 # все артефакты
```

**iOS на других ОС.** Код под iOS компилируется и на Linux. Фреймворк и тесты на симуляторе
собираются только на macOS с Xcode; на других ОС эти задачи пропускаются.

Тесты (`commonTest`) сверяют результат с Python-эталоном:
- поперечный Меркатор против PROJ — 72 точки на трёх эллипсоидах, до 4.5° от осевого меридиана;
- локализация и пересчёты по всем 83 регионам из `data/geodetic`;
- пересчёт туда и обратно, JSON (в том числе датум из Python), упрощение модели при малом числе
  точек, флаги `use`, разбор CSV;
- надёжность: избыточность, `q_vv`, нормированные поправки, leave-one-out, СКО прогноза, экстраполяция,
  предупреждения и `suggestExclusions` — по 83 регионам и 16 особым случаям (грубые ошибки в плане,
  по высоте и на контрольной точке, 1–3 точки, вырождение без точки, перепутанные оси, масштаб);
- веса точек: параметры, `p`, `q_vv`, `w`, leave-one-out во взвешенном случае (5 случаев: разные σ,
  равные σ, большая σ у грубой ошибки, малая σ, 4 точки), `Σ p·q_vv = r`, разбор столбцов σ;
- пересчёты между системами (`DatumsTest`): BLH ↔ XYZ на 5 эллипсоидах, XYZ по всем 56 парам систем и
  туда-обратно (< 1e-8 м), контрольный пример ГОСТ (все три шага), Гаусс–Крюгер (в том числе принудительная
  зона) и свой поперечный Меркатор, задачи `helmert_7p` 83 регионов, локализация с `gnssDatum`
  (ПЗ-90.11, СК-42, ГСК-2011) и пересчёт точек из другой системы, датум из Python с `gnss_datum`;
- сетки геоида (`GeoidTest`): чтение GGF, GTX, ISG (заголовок, SHA-256, NODATA), 476 значений билинейной и
  бикубической интерполяции и ошибок (вне сетки, NODATA, край) — до 1e-12 м; 9 случаев локализации с моделями
  `geoid` / `geoid_plane` (параметры, диагностика, leave-one-out, предупреждения, пересчёты туда и обратно);
  датум из Python со ссылкой на сетку, проверка SHA-256, переход через 180°.

Эталонные данные генерирует `python tools/gen_kotlin_reference.py`, запускать из корня репозитория
(`ReferenceData.kt`, `DatumReferenceData.kt`, `GeoidReferenceData.kt`; тестовые сетки — `tests/data/geoid`). Python-эталон сам сверен с PROJ в `tests/`.

## API

```kotlin
import ru.mathdatum.localization.*

val pairs = Csv.parsePairs(csvText)              // или список LocalizationPair(...)
val datum = localize(pairs)                      // LocalizationDatum
println(datum.report())                          // параметры и невязки

val local = datum.toLocal(WgsPoint(lat = 55.08, lon = 39.34, h = 230.9))   // → LocalPoint(x, y, height)
val wgs = datum.toWgs(LocalPoint(x = -196396.5, y = 3263150.3, height = 224.8))

val json = datum.toJson()                        // сохранить
val restored = LocalizationDatum.fromJson(json)  // загрузить (в том числе датум из Python)
val proj = datum.toProjPipeline()                // строка PROJ для QGIS / cs2cs

val grid = GeoidGrid.parse(bytes, "region.ggf")  // содержимое файла сетки (.ggf, .gtx, .isg)
localize(pairs, gnssDatum = "PZ-90.11", heightModel = "geoid_plane", geoid = grid, geoidInterpolation = "bilinear")
LocalizationDatum.fromJson(json, geoid = grid)   // датум со ссылкой на сетку: та же SHA-256, иначе GeoidException
localize(pairs, gnssDatum = "PZ-90.11")          // ГНСС-координаты в ПЗ-90.11: проекция на эллипсоиде ПЗ-90
datum.toLocal(WgsPoint(55.08, 39.34, 230.9), datum = "WGS-84")   // точка в другой системе — пересчёт по ГОСТ
datum.warnings                                   // List<DatumWarning(code, message, point)>
datum.residuals[0].wPlan; datum.residuals[0].looDH   // |w| и ошибка без точки (null — нельзя проверить)
datum.residuals[0].sigmaPlan; datum.residuals[0].pPlan // использованная σ точки и её вес
localize(pairs.map { it.copy(sigmaPlan = 0.01) })     // свои σ точек (взвешенный МНК)
datum.quality(WgsPoint(55.08, 39.34, 230.9))     // PointQuality(outside, mPlan, mHeight)
datum.covariancePlan(posterior = true)           // σ²·Q для (tx, ty, a, b)
suggestExclusions(pairs)                         // [Exclusion("R4", "plan", 3.87)] — только предложение
```

Пересчёты между системами (ГОСТ 32453-2017):

```kotlin
Datums.transformBlh(GeodeticPoint(55.752, 37.6175, 150.0), "СК-42", "WGS-84")   // через ПЗ-90.11
Datums.transformXyz(Xyz(x, y, z), "ITRF-2008", "PZ-90.11", epoch = 2005.0, velocity = Xyz(vx, vy, vz), targetEpoch = 2013.9)
Datums.findPath("SK-42", "WGS-84")               // [Step(А.1, прямой), Step(Г.1, обратный)]
Datums.blhToXyz(p, Ellipsoid.KRASSOVSKY); Datums.xyzToBlh(xyz, Datums.system("PZ-90.11").ellipsoid.ellipsoid)
GaussKruger.forward(55.752, 37.6175, Ellipsoid.KRASSOVSKY)       // PlanePoint(x, y), y с номером зоны
GaussKruger.inverse(x, y, Ellipsoid.KRASSOVSKY)                   // зона — по первым цифрам y
TmProjection(Ellipsoid.KRASSOVSKY, lon0 = 38.48333, x0 = -5712900.566, y0 = 1250000.0).forward(lat, lon)
```

Формулы — как в Python-эталоне (см. README в корне): 7 параметров ГОСТ с малыми углами (поворот системы
координат), точное обращение, кратчайшая цепочка по графу параметров, линейный перенос эпохи по скорости
пункта перед шагами с эпохой параметров (А.5, Б.1, Д.1).

Из Swift после подключения `MathDatum.framework` вызывается то же самое:

```swift
let datum = LocalizationKt.localize(pairs: pairs, lat0: nil, lon0: nil, ellipsoid: "+ellps=WGS84")
let p = datum.toLocal(p: WgsPoint(lat: 55.08, lon: 39.34, h: 230.9))
```

## Модель

1. **Рабочая проекция** — поперечный Меркатор (ряды Крюгера 6-го порядка, как `+proj=tmerc` в PROJ)
   на эллипсоиде системы ГНСС-измерений (`gnssDatum`, по умолчанию WGS-84) с центром в среднем по точкам;
   координаты в другую систему не переводятся (обоснование — в README в корне).
2. **План** — подобие относительно (взвешенного) центроида: `[x, y] = [tx, ty] + [[a, −b], [b, a]]·([N, E] − [Nc, Ec])`.
3. **Высота** — плоскость `H = h + c0 + c1·(N − Nc) + c2·(E − Ec)` (`heightModel = "plane"`, по умолчанию),
   `geoid` — `H = h − N(B, L) + c0` или `geoid_plane` — `H = h − N(B, L) + c0 + c1·(N − Nc) + c2·(E − Ec)`;
   N — сетка `GeoidGrid` (GGF, GTX, ISG; GeoTIFF — только в Python). Вне сетки, NODATA, нет сетки или другая
   SHA-256 — `GeoidException`. Подробности — в README в корне.

Обе подгонки — взвешенный линейный МНК в замкнутой форме, без итераций. Вес точки `p = σ0² / σi²`:
σi — `LocalizationPair.sigmaPlan` / `sigmaHeight` (столбцы CSV `sigma_plan` / `sigma_height`, суммарная
СКО каталога и ГНСС), без неё `p = 1`; σ0 — `sigmaPlan` / `sigmaHeight` у `localize`.

**Если точек мало, модель упрощается:**
- 1 точка в плане — только сдвиг;
- 1–2 точки по высоте или точки на одной линии — только сдвиг по высоте.

**Надёжность** — как в Python-эталоне (см. README в корне): избыточность `2n − 4` / `n − 3`,
`Q = (AᵀPA)⁻¹`, `q_vv = 1/p − aᵀQa`, нормированные поправки `w = v / (σ0·√q_vv)` с σ0 = 0.02 / 0.03 м
и порогом 3.29, ошибка без точки (пересчёт датума без неё, `= v / (p·q_vv)`), `s0 = √(vᵀPv/r)`,
ковариации `σ²·Q`, СКО прогноза `σ·√(aᵀQa)`, расстояние до выпуклой оболочки опорных пунктов,
проверки масштаба (200 ppm) и разворота (3°: сближение меридианов в МСК достигает 1–1.5°).
Параметры — у `localize(sigmaPlan, sigmaHeight, wLimit, maxScalePpm, maxRotationDeg)`.

**Ошибки.** Совпадающие точки или отсутствие точек для плана дают `LocalizationException`.
