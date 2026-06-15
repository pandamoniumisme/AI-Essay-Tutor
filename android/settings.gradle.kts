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

rootProject.name = "ai-essay-tutor-android"

// Composite build: the platform-independent :core (prompts, schema, validation,
// lang detect) is its own JVM build so it compiles/tests without the Android SDK.
// Gradle substitutes the `com.aitutor:core` dependency for the included build.
includeBuild("core")

include(":app")
