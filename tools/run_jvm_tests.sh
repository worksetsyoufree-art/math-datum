#!/usr/bin/env bash
# Сборка и прогон тестов ядра на JVM без Gradle (автономный kotlinc). Нужен KOTLINC_HOME (распакованный kotlin-compiler zip).
# Использование: KOTLINC_HOME=/path/to/kotlinc tools/run_jvm_tests.sh [ClassName ...]
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${KOTLINC_HOME:?задайте KOTLINC_HOME}"
OUT="${OUT:-$(mktemp -d)}"
STUB="$OUT/stub"; mkdir -p "$STUB"
cat > "$STUB/Stub.kt" <<'KT'
package kotlin.test
@Target(AnnotationTarget.FUNCTION) @Retention(AnnotationRetention.RUNTIME) annotation class Test
KT
cat > "$STUB/Runner.kt" <<'KT'
fun main(args: Array<String>) {
    var fail = 0; var ok = 0
    for (cn in args) {
        val c = Class.forName(cn); val inst = c.getDeclaredConstructor().newInstance()
        for (m in c.declaredMethods.filter { it.annotations.any { a -> a.annotationClass.simpleName == "Test" } }.sortedBy { it.name }) {
            try { m.isAccessible = true; m.invoke(inst); ok++; println("PASS ${c.simpleName}.${m.name}") }
            catch (e: java.lang.reflect.InvocationTargetException) { fail++; println("FAIL ${c.simpleName}.${m.name}: ${e.targetException.message}") }
        }
    }
    println("ok=$ok fail=$fail"); if (fail > 0) System.exit(1)
}
KT
L="$KOTLINC_HOME/lib"
"$KOTLINC_HOME/bin/kotlinc" -nowarn -d "$OUT/main.jar" "$ROOT/core/src/commonMain/kotlin" 2>&1 | grep -v '^Picked' || true
"$KOTLINC_HOME/bin/kotlinc" -nowarn -Xallow-kotlin-package -cp "$OUT/main.jar:$L/kotlin-test.jar" -d "$OUT/test.jar" "$STUB/Stub.kt" "$STUB/Runner.kt" "$ROOT/core/src/commonTest/kotlin" 2>&1 | grep -v '^Picked' || true
CLASSES=("$@")
if [ ${#CLASSES[@]} -eq 0 ]; then
  mapfile -t CLASSES < <(cd "$ROOT/core/src/commonTest/kotlin" && grep -rl '@Test' . | sed 's|^\./||; s|\.kt$||; s|/|.|g')
fi
java -cp "$OUT/main.jar:$OUT/test.jar:$L/kotlin-stdlib.jar:$L/kotlin-test.jar" RunnerKt "${CLASSES[@]}" 2>&1 | grep -v '^Picked'
