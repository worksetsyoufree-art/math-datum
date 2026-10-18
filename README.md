# math-datum

Локализация ГНСС (пары точек WGS-84 ↔ местная система → датум → пересчёты), а также наборы точек
и эталонные результаты для её проверки.

## Локализация

```
pip install -r requirements.txt

python -m mathdatum localize examples/pairs.csv -o datum.json      # расчёт датума + отчёт по невязкам
python -m mathdatum to-local datum.json examples/wgs_points.csv -o local.csv   # B L h → x y H
python -m mathdatum to-wgs   datum.json local.csv -o wgs.csv                   # x y H → B L h
python -m mathdatum proj datum.json                                 # строка PROJ для QGIS / cs2cs
```

Формат пар (`examples/pairs.csv`): `name;B;L;h;x;y;H;use`. B, L — градусы WGS-84, h — высота ГНСС
(эллипсоидальная), x — север, y — восток, H — местная высота. `use`: `both` (по умолчанию), `plan`,
`height` или `none` — точка не участвует в расчёте, но для неё печатается ошибка (контроль).

Из Python:

```python
from mathdatum import Pair, localize, LocalizationDatum
d = localize([Pair("R1", 55.05, 39.27, 215.5, -200498.03, 3258049.82, 209.38), ...])
x, y, H = d.to_local(B, L, h)
B, L, h = d.to_wgs(x, y, H)
d.save("datum.json"); d = LocalizationDatum.load("datum.json")
```

Модель (`mathdatum/localization.py`):
1. Рабочая проекция — поперечный Меркатор на WGS-84 с центром в среднем по точкам.
2. План — подобие (сдвиг, разворот, масштаб) относительно центроида точек.
3. Высота — наклонная плоскость `H = h + c0 + c1·dN + c2·dE`.

Обе подгонки — линейный МНК в замкнутой форме. Если точек мало, модель упрощается: 1 точка в плане
даёт только сдвиг; 1–2 точки по высоте или точки на одной линии дают только сдвиг по высоте.

Тесты: `pip install pytest && python -m pytest tests` (176 тестов, включая 83 региона из `data/geodetic`).

## Kotlin Multiplatform

`kmp/` — та же локализация на Kotlin для Android, iOS, Web и Desktop, с тестами против
Python-эталона. Готовое веб-приложение: откройте `kmp/web-dist/index.html` в браузере.
Подробности — в `kmp/README.md`.

## Данные

- `data/nist_l2/` — эталонные МНК-подгонки NIST (прямая, плоскость, окружность, сфера, цилиндр, конус).
- `data/synthetic/` — машиностроение: МНК-плоскость, плоскостность по минимальной зоне, система датумов 3-2-1, совмещение с номинальной моделью.
- `data/geodetic/` — геодезия по 83 субъектам РФ: 7 параметров СК-42 → ПЗ-90.11 (ГОСТ 32453-2017), локализация ГНСС в местной системе.

Описание форматов: `data/README.md`, `data/geodetic/README.md`.

```
pip install -r requirements.txt
python tools/verify_cases.py      # NIST + synthetic
python tools/verify_geodetic.py   # регионы РФ
```

## Проверка сторонних реализаций

- `tools/kotlin_check/` — прогон локализации gsimath (Kotlin/JVM) на `data/geodetic`: `tools/kotlin_check/run.sh <gsimath.jar> <model.jar>`.
- `results/gsimath-0.5.5/REPORT.md` — результаты для gsimath-desktop 0.5.5 / model 1.2.54.
