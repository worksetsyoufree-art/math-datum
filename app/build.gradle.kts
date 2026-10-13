plugins {
    alias(libs.plugins.kotlinMultiplatform)
    alias(libs.plugins.androidApplication)
    alias(libs.plugins.composeMultiplatform)
    alias(libs.plugins.composeCompiler)
}

kotlin {
    jvm("desktop")
    androidTarget()
    js(IR) {
        browser()
        binaries.executable()
    }

    sourceSets {
        commonMain.dependencies {
            implementation(project(":core"))
            implementation(compose.runtime)
            implementation(compose.foundation)
            implementation(compose.material3)
            implementation(compose.ui)
            implementation(compose.components.resources)
        }
        commonTest.dependencies {
            implementation(kotlin("test"))
        }
        androidMain.dependencies {
            implementation(libs.androidx.activity.compose)
        }
        val desktopMain by getting {
            dependencies {
                implementation(compose.desktop.currentOs)
            }
        }
    }
}

android {
    namespace = "mathdatum.app"
    compileSdk = 35
    defaultConfig {
        applicationId = "mathdatum.app"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "0.1"
    }
}

compose.resources {
    packageOfResClass = "mathdatum.app.res"
    generateResClass = always
}

compose.desktop {
    application {
        mainClass = "mathdatum.app.MainKt"
    }
}
