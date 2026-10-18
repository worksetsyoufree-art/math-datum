# Экспорт датума локализации

```
python -m mathdatum export datum.json --format wkt2|projjson|jxl|landxml|proj [-o файл] [--name Имя] [--geoid-file имя]
```

Датум = рабочая TM (lat0, lon0, k0, x0, y0 на эллипсоиде `gnss_datum`) + подобие в плане
(`x = tx + a·dN − b·dE`, `y = ty + b·dN + a·dE`, dN, dE — от центроида Nc, Ec) + модель высоты
(`H = h [− N_геоид] + c0 + c1·dN + c2·dE`). Ограничения и оценки погрешности по объекту (по оболочке опорных
пунктов) печатаются в stderr; в Kotlin — `Export.export(d, format)` → `ExportResult(text, warnings)`, в вебе —
кнопки «Экспорт» в разделе 2.

## Что сделано и насколько точно

| Формат | Как выражена модель | Точность |
|---|---|---|
| **WKT2** (ISO 19162:2019) | план — `DERIVEDPROJCRS`: базовая TM (EPSG 9807) + `DERIVINGCONVERSION` «Similarity transformation» (EPSG 9621: точка начала, масштаб, разворот); высота — `COMPOUNDCRS` с `BOUNDCRS` вертикальной системы к ГНСС-системе 3D, преобразование `METHOD["PROJ-based operation method: …"]` (tmerc → affine z → inv tmerc → vgridshift) | pyproj: 83 региона, < 1e-8 м (x, y, H) и обратно; от EPSG:4979 — то же |
| **PROJJSON** | то же в JSON (схема PROJ 0.7) | то же |
| **Trimble JobXML** (схема 6.30) | TM с `Scale = k0·M`, `FalseNorthing = tx + M·(x0 − Nc)`, `FalseEasting = ty + M·(y0 − Ec)` (масштаб подобия сворачивается точно); `HorizontalAdjustment` PlaneAdjustment: центр (tx, ty), сдвиг 0, масштаб 1, `Rotation` = θ; `VerticalAdjustment` InclinedPlane / GeoidModelAndInclinedPlane: центр (tx, ty), наклоны c1/M, c2/M, `ConstantAdjustment` c0, `GeoidName` без .ggf; датум — 7 параметров по нулям, эллипсоид системы ГНСС | по формулам Trimble Access Calculations Reference (в нашем прочтении) — < 1e-6 м; схема 6.30 — валидна. Неоднозначности — ниже |
| **LandXML 1.2** | `CoordinateSystem` без параметров (их в 1.2 нет), WKT2 — в `ogcWktCode` | точно только для ПО, отдающего строку в PROJ |
| **proj** | строка PROJ-пайплайна (как `proj`) | точно |

**Почему подобие не сворачивается в проекцию.** Масштаб M сворачивается в TM точно (k0·M и ложные смещения).
Разворот — нет: у TM нет параметра поворота сетки, «TM + rotation» в EPSG нет, а косая Меркатора (Хотин, omerc)
даже при α → 0 — другая конформная проекция (масштаб постоянен на апосфере, а не вдоль меридиана). Поэтому:
если разворот на объекте даёт < 0.1 мм (`2·M·R·sin(|θ|/2)`, R — наибольшее расстояние от центроида до вершин
оболочки), WKT2/PROJJSON пишут обычный `PROJCRS` (с предупреждением и оценкой), иначе — `DERIVEDPROJCRS`.
Оси экспорта — восток (y), север (x): подобие EPSG 9621 действует на порядок осей базовой системы (PROJ берёт
восток, север), перестановка осей сделала бы его отражением.

**Высота в WKT2.** Метод EPSG от эллипсоидальной высоты к местной для наклонной плоскости нет («Vertical Offset and
Slope», EPSG 1046, — между двумя вертикальными системами, и PROJ не строит его к географической 3D). Поэтому
вертикальная часть — `PROJ-based operation method` (ПО на PROJ ≥ 6: QGIS, GDAL, pyproj); план — стандартный.
Сетка геоида — ссылкой `vgridshift +grids=…` (PROJ читает GTX и GeoTIFF). GGF и ISG PROJ не читает: в файл
пишется имя `.gtx` и предупреждение — переведите `python -m mathdatum geoid region.ggf -o region.gtx` (узлы те
же, float32). PROJ интерполирует билинейно; если датум бикубический — предупреждение с разницей на объекте.

## Trimble JobXML: определения и неоднозначности

Источник формул — Trimble Access Calculations Reference Guide (Rev. D, 2024, с. 6–8): «N′E′ — projected grid
coordinates, NEcontrol — local control»; `N′ = aN + bE + ΔN`, `E′ = −bN + aE + ΔE`, `a = k·cos φ`, `b = k·sin φ`;
наклоны — «height shift per unit distance» по координатам, «derived from the WGS-84 data set».
Отсюда разворот JobXML φ = θ = atan2(b, a) (положительный — по часовой стрелке: дирекционные углы растут). Но:

1. В документе есть опечатка (`φ = tan⁻¹(a/b)`), формула с центром (`OriginNorth/East`) не выписана, образца
   JXL с калибровкой и парами точек в открытом доступе нет. **Знак разворота подтверждён только чтением
   документации.** Чтобы неоднозначность не затронула масштаб и сдвиг, они свёрнуты в TM (масштаб корректировки 1,
   сдвиг 0, центр — неподвижная точка). Если знак окажется обратным, ошибка в плане `2·R·sin|θ|` — export
   печатает её и контрольные точки (B, L → x, y, а также x′, y′ при обратном знаке): одной точки на контроллере
   достаточно, чтобы убедиться. Для RU-MOW (θ = −434.55″, R ≈ 5.7 км) — до 24 м, поэтому проверка обязательна.
2. Наклон высот пишется в сетке до горизонтальной корректировки («derived from the WGS-84 data set»). Если Trimble
   берёт координаты после неё, ошибка высоты `|c|·2R·sin(|θ|/2)` — печатается, если ≥ 0.5 мм.
3. Интерполяция GGF у Trimble не документирована; Trimble читает только GGF.
4. Преобразование датума нулевое, эллипсоид — системы ГНСС датума: координаты ГНСС на контроллере должны быть в той же
   системе, что при расчёте (базовая станция в ПЗ-90.11 и т. п.).

Проверка в `tests/test_export.py`: ручной пример (k = 1.000078·1.00002 = 1.00009800156, FN = 29000.38,
FE = 120502.01, поворот +30″, наклоны 1.9999600008e-5 и −2.9999400012e-5; точка dN = 100 → x = 10100.00199894,
y = 20000.01454470), повтор формул Trimble по 11 регионам (< 1e-6 м), схема 6.30 (скачивается во время теста, без
сети — skip).

## Отвергнутые форматы

| Формат | Причина |
|---|---|
| Trimble .cal, .dc, .csd | закрытые двоичные / записи без описания |
| Topcon / Sokkia .gc3, .tp3 (Magnet) | закрытые |
| Carlson SurvCE / SurvPC .loc | описания нет (по форумам — XML или двоичный в разных версиях) |
| Leica HeXML / Captivate | схема с параметрами локализации не опубликована |
| Emlid Flow | экспорта локализации нет; импортирует DC/Cal (Trimble) и JSON BEV (Австрия) |
| проект gsimath | формат не описан; к тому же модель другая (стереографическая проекция B0, L0, FE, FN, k0) — TM + подобие в неё точно не переводится |

`export … --format cal|dc|gc3|tp3|loc|hexml|gsimath|csd` — ошибка со ссылкой сюда, байты не угадываются.

## Что нужно для поддержки закрытых форматов

Общее для всех: на один и тот же участок (4–6 пар точек) — файл формата **и** отчёт программы с параметрами
(проекция, сдвиги, разворот с указанием направления, масштаб, наклоны, константа, геоид), плюс 2–3 точки с
координатами ГНСС и местными, пересчитанными самой программой. Лучше 3 варианта: без разворота, с заметным разворотом
(> 1′), с геоидом; и версия программы.

- **Trimble .cal / .dc / .jxl** — то же задание из Trimble Access или TBC в трёх видах: `.cal` (или `.dc`), **JobXML
  с `CalibrationPointPairs`** и отчёт «GPS Calibration report». JXL с калибровкой и парами точек сразу снимает
  неоднозначность знака разворота и системы наклона в нашем экспорте JobXML.
- **Topcon .gc3 / .tp3** — файлы Magnet Field / Magnet Office с локализацией и экран (или отчёт) параметров;
  если есть — документация Topcon по формату (часто под NDA — тогда только по образцам).
- **Carlson .loc** — файлы SurvCE / SurvPC (с указанием версии) с локализацией и отчёт (Localization report).
- **Leica** — экспорт системы координат из Captivate / Infinity (HeXML или .dbx) с локализацией (OneStep / TwoStep)
  и протокол параметров; схема HeXML, если Leica её предоставит.
- **gsimath** — файл проекта с сохранённой локализацией (`LocalizationViewModel.onSave`) и описание сериализации
  (классы модели проекта из `model.jar`); плюс решение, переводить ли наш датум в их стереографическую модель
  (только приближённо — с оценкой погрешности по объекту) или добавить в gsimath TM + подобие.

## Источники

- ISO 19162:2019 / OGC 18-010r7 (WKT2): https://docs.ogc.org/is/18-010r7/18-010r7.html
- PROJJSON: https://proj.org/specifications/projjson.html ; IOGP Guidance Note 7-2 (EPSG 9621, 9807, 1046)
- Trimble JobXML schema 6.30: http://www.trimble.com/schema/JobXML/6_2/JobXMLSchema-6.30.xsd
- Trimble Access Calculations Reference Guide: https://help.fieldsystems.trimble.com/trimble-access/latest/en/pdfs/access-calculations-reference.pdf
- Trimble stylesheet «GPS Calibration report.xsl» (имена полей корректировок): https://help.fieldsystems.trimble.com/trimble-access-downloads/Stylesheets/GeneralSurvey/GPS%20Calibration%20report.xsl
- LandXML 1.2: http://www.landxml.org/schema/LandXML-1.2/LandXML-1.2.xsd
- Emlid Flow, локализация: https://docs.emlid.com/emlid-flow/preparing-projects/cs-setup/localization/
