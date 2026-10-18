#!/usr/bin/env bash
# Проверка локализации gsimath на датасетах data/geodetic.
# Использование: tools/kotlin_check/run.sh <gsimath-desktop.jar> <model.jar> [out_dir]
# Нужны: JDK 17+, python3 с numpy. Зависимости Kotlin скачиваются с Maven Central.
set -euo pipefail

GSIMATH=$(realpath "$1")
MODEL=$(realpath "$2")
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
OUT=${3:-$ROOT/results/local}
WORK=$(mktemp -d)
LIB=$HERE/lib
mkdir -p "$LIB" "$OUT"

M=https://repo1.maven.org/maven2
for p in \
  org/jetbrains/kotlin/kotlin-stdlib/2.0.21/kotlin-stdlib-2.0.21.jar \
  org/jetbrains/kotlin/kotlin-reflect/2.0.21/kotlin-reflect-2.0.21.jar \
  org/jetbrains/kotlinx/multik-core-jvm/0.2.1/multik-core-jvm-0.2.1.jar \
  org/jetbrains/kotlinx/multik-kotlin-jvm/0.2.1/multik-kotlin-jvm-0.2.1.jar \
  org/jetbrains/kotlinx/kotlinx-serialization-core-jvm/1.7.3/kotlinx-serialization-core-jvm-1.7.3.jar \
  org/jetbrains/kotlinx/kotlinx-coroutines-core-jvm/1.9.0/kotlinx-coroutines-core-jvm-1.9.0.jar ; do
  [ -f "$LIB/$(basename "$p")" ] || curl -sSfL -o "$LIB/$(basename "$p")" "$M/$p"
done
CP="$GSIMATH:$MODEL:$(ls "$LIB"/*.jar | tr '\n' ':')"

python3 "$HERE/export_sites.py" "$WORK/sites.txt" "$WORK/sites_ne.txt"
javac -nowarn -d "$WORK/build" -cp "$CP" "$HERE/LocalizationCheck.java" "$HERE/GskoCheck.java"

for n in 1 2 3 4 6; do
  java -cp "$WORK/build:$CP" LocalizationCheck "$WORK/sites.txt" "$n" > "$WORK/out_$n.txt"
  python3 "$HERE/compare.py" "$WORK/out_$n.txt" "$OUT/site_${n}pts.csv" | tee "$OUT/summary_${n}pts.txt"
done
java -cp "$WORK/build:$CP" GskoCheck "$WORK/sites_ne.txt" > "$OUT/solver_isolated_raw.txt"
echo "Результаты: $OUT"
