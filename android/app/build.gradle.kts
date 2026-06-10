plugins {
    id("com.android.application")
    kotlin("android")
    kotlin("plugin.serialization")
}

android {
    namespace = "com.aitutor.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.aitutor.app"
        minSdk = 29          // Android 10; covers the Z Flip 5 (Android 13+)
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0"
        ndk { abiFilters += "arm64-v8a" }  // the phone is arm64 only
    }

    // Phase 2: enable the llama.cpp native build. Left disabled so the Phase-1
    // stub app builds without the NDK / llama.cpp checkout.
    // externalNativeBuild {
    //     cmake { path = file("src/main/cpp/CMakeLists.txt") }
    // }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation("com.aitutor:core")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.webkit:webkit:1.11.0")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.7.3")
}

// Single-source the front-end: copy the web SPA and the grader prompts into
// assets at build time instead of forking them.
val copyAssets by tasks.registering(Copy::class) {
    from("../../server/aitutor_server/static") { into("www") }
    from("../../server/aitutor_server/gemini/prompts") { into("prompts") }
    into(layout.projectDirectory.dir("src/main/assets"))
}
tasks.named("preBuild") { dependsOn(copyAssets) }
