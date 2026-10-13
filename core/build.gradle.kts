plugins {
    alias(libs.plugins.kotlinMultiplatform)
    alias(libs.plugins.androidLibrary)
}

kotlin {

    jvm("desktop")
    androidTarget()
    js(IR) {
        browser()
        nodejs() // тесты в CI без браузера
    }

    sourceSets {
        commonMain.dependencies {
            // Намеренно без зависимостей: ядро — чистый Kotlin (kotlin.math)
        }
        commonTest.dependencies {
            implementation(kotlin("test"))
        }
    }
}

android {
    namespace = "mathdatum.core"
    compileSdk = 35
    defaultConfig { minSdk = 24 }
}
