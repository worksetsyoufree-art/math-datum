pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "math-datum"
include(":core")
// Следующие модули — см. docs/PLAN.md (блоки 6–7):
// include(":catalog")  // справочник СК + загрузка
// include(":app")      // Compose Multiplatform UI: android / desktop / web
