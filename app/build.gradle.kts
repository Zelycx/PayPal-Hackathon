plugins {
    alias(libs.plugins.android.application)
}

android {
    namespace = "com.example.paypalhackathon"
    buildFeatures {
        buildConfig = true
    }

    compileSdk {
        version = release(37) {
            minorApiLevel = 1
        }
    }

    defaultConfig {
        applicationId = "com.example.paypalhackathon"
        minSdk = 24
        targetSdk = 36
        versionCode = 1
        versionName = "1.0"

        val backendUrl = providers.gradleProperty("PAYPAL_BACKEND_URL")
            .getOrElse("http://10.0.2.2:8000")
        buildConfigField("String", "BACKEND_BASE_URL", "\"$backendUrl\"")

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        debug {
            manifestPlaceholders["allowCleartextTraffic"] = "true"
        }
        release {
            isMinifyEnabled = false
            manifestPlaceholders["allowCleartextTraffic"] = "false"
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.appcompat)
    implementation(libs.material)
    implementation(libs.androidx.activity)
    implementation(libs.androidx.constraintlayout)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
}
