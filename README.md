# math-datum

Наборы точек и эталонные результаты для построения датумов и локализации.

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
