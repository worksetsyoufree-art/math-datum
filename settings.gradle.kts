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
include(":app")
// Следующие модули — см. docs/PLAN.md (блоки 6–7):
// include(":catalog")  // справочник СК + загрузка
