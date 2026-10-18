# mathdatum-kmp — локализация ГНСС на Kotlin Multiplatform

Модуль `:localization` реализует ту же локализацию, что Python-эталон `mathdatum/` в корне
репозитория: те же формулы, тот же формат CSV и JSON. Датум, сохранённый в Python, читается в
Kotlin, и наоборот.

| Платформа | Цель | Что получается |
|---|---|---|
| Android | `androidTarget` | `localization-release.aar` |
| iOS | `iosArm64`, `iosSimulatorArm64`, `iosX64` | фреймворк `MathDatum` (собирается на macOS) |
| Web | `js` (браузер и Node) | библиотека + веб-приложение `:webApp` |
| Desktop | `jvm("desktop")` | `localization-desktop.jar` |

## Запустить веб-приложение

Готовая сборка лежит в `web-dist/`: откройте `web-dist/index.html` в браузере, сервер не нужен.

На странице можно:
- вставить или открыть CSV с парами точек и рассчитать локализацию;
- посмотреть невязки (большие, больше 3 СКО, подсвечиваются);
- скачать датум в JSON и скопировать строку PROJ;
- пересчитать точки WGS → местная и обратно (кнопка «Обратно ←» проверяет пересчёт туда и обратно).

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
  точек, флаги `use`, разбор CSV.

Эталонные данные генерирует `python tools/gen_kotlin_reference.py`, запускать из корня репозитория.

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
```

Из Swift после подключения `MathDatum.framework` вызывается то же самое:

```swift
let datum = LocalizationKt.localize(pairs: pairs, lat0: nil, lon0: nil, ellipsoid: "+ellps=WGS84")
let p = datum.toLocal(p: WgsPoint(lat: 55.08, lon: 39.34, h: 230.9))
```

## Модель

1. **Рабочая проекция** — поперечный Меркатор (ряды Крюгера 6-го порядка, как `+proj=tmerc` в PROJ)
   на WGS-84 с центром в среднем по точкам.
2. **План** — подобие относительно центроида: `[x, y] = [tx, ty] + [[a, −b], [b, a]]·([N, E] − [Nc, Ec])`.
3. **Высота** — плоскость `H = h + c0 + c1·(N − Nc) + c2·(E − Ec)`.

Обе подгонки — линейный МНК в замкнутой форме, без итераций.

**Если точек мало, модель упрощается:**
- 1 точка в плане — только сдвиг;
- 1–2 точки по высоте или точки на одной линии — только сдвиг по высоте.

**Ошибки.** Совпадающие точки или отсутствие точек для плана дают `LocalizationException`.
