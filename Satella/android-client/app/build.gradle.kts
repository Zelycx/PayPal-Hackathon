plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.plugin.compose")
}

fun String.asBuildConfigString(): String = "\"${replace("\\", "\\\\").replace("\"", "\\\"")}\""

val emulatorUrl = providers.gradleProperty("ellieEmulatorUrl").orElse("http://10.0.2.2:8000").get()
val physicalDeviceUrl = providers.gradleProperty("elliePhysicalDeviceUrl").orElse("http://192.168.1.100:8000").get()
val developmentUserId = providers.gradleProperty("ellieDevUserId").orElse("ellie-android").get()

android {
    namespace = "com.satella.ellie"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.satella.ellie"
        minSdk = 26
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField("String", "EMULATOR_BASE_URL", emulatorUrl.asBuildConfigString())
        buildConfigField("String", "PHYSICAL_DEVICE_BASE_URL", physicalDeviceUrl.asBuildConfigString())
        buildConfigField("String", "DEVELOPMENT_USER_ID", developmentUserId.asBuildConfigString())
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    testOptions {
        unitTests.isIncludeAndroidResources = true
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2026.09.00")
    implementation(composeBom)
    implementation("androidx.activity:activity-compose:1.13.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.11.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.11.0")
    implementation("androidx.lifecycle:lifecycle-viewmodel-ktx:2.11.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    debugImplementation("androidx.compose.ui:ui-tooling")

    testImplementation("junit:junit:4.13.2")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation("org.json:json:20250517")
}
