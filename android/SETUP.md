# Android APK — Setup & Build Guide

How to build the AI Essay Tutor Android app and install it on your phone
(e.g. the Samsung Z Flip 5). For the architecture and module layout, see
[`README.md`](README.md).

> **What you'll get today:** the **Phase-1 stub** APK — the full app (capture →
> transcription review → annotated results), camera capture, and the RAM-based
> model recommendation, with **placeholder (canned) grading**. The real
> on-device model (llama.cpp + Qwen3.5) is a separate step — see
> [Phase 2](#phase-2-enable-the-real-on-device-model) at the end.

---

## 1. Prerequisites

| Need | Version | Notes |
|---|---|---|
| **JDK** | 17+ | Android Studio bundles one; or `sudo apt install openjdk-17-jdk`. |
| **Android Studio** | latest (Koala/Ladybug+) | Easiest path — bundles Gradle + SDK manager. |
| **Android SDK Platform** | API 35 | `compileSdk = 35`. Installed via Android Studio's SDK Manager. |
| **A phone** | Android 10+ (`minSdk 29`) | The Z Flip 5 (Android 13/14) is fine. |
| Android NDK | r27+ | **Only for Phase 2** (native model). Not needed for the stub. |

You do **not** need Python, Node, or the web server to build the app — the
build copies the web UI into the app automatically.

---

## 2. Get the code

```bash
git clone <your-repo-url> AI-Essay-Tutor
cd AI-Essay-Tutor
git checkout android/on-device
```

The Android project is the `android/` directory.

---

## 3. Build — Option A: Android Studio (recommended)

1. **Open** Android Studio → *Open* → select the `android/` folder (not the repo
   root). Let it finish "Gradle sync".
   - If it asks about the Gradle wrapper, accept generating one, or let it use
     its bundled Gradle. It writes `android/local.properties` with your SDK
     path automatically.
   - If prompted, install **SDK Platform 35** and **Build-Tools** via the
     notification / SDK Manager.
2. Wait for sync to finish (first time downloads AGP + dependencies).
3. **Run** ▶ with your phone connected (see [§5](#5-install-on-your-phone)), or
   build an APK without installing: *Build → Build App Bundle(s) / APK(s) →
   Build APK(s)*.
4. The APK lands at:
   ```
   android/app/build/outputs/apk/debug/app-debug.apk
   ```

---

## 4. Build — Option B: command line

Requires the Android command-line SDK installed and `ANDROID_HOME` (or
`ANDROID_SDK_ROOT`) set.

```bash
cd android

# 1. Tell Gradle where the SDK is (Android Studio does this for you).
echo "sdk.dir=$ANDROID_HOME" > local.properties

# 2. Make sure SDK Platform 35 + build-tools are installed:
sdkmanager "platforms;android-35" "build-tools;35.0.0"

# 3. Generate the Gradle wrapper once (needs a local `gradle` on PATH), then build.
gradle wrapper --gradle-version 8.14.3
./gradlew :app:assembleDebug
```

Output: `android/app/build/outputs/apk/debug/app-debug.apk`.

> The `core` module (pure logic + unit tests) builds with no SDK at all:
> `cd android/core && gradle test`.

---

## 4b. Build — Option C: download from CI (no toolchain at all)

Every push to `android/on-device` runs the **Android** GitHub Actions workflow,
which builds the debug APK on a runner and uploads it as an artifact:

1. GitHub → **Actions** → latest **Android** run → **Artifacts** →
   **`app-debug-apk`**.
2. Unzip it to get `app-debug.apk`, then jump to [§5](#5-install-on-your-phone).

You can also trigger it manually via *Actions → Android → Run workflow*.

## 5. Install on your phone

1. **Enable Developer options:** Settings → *About phone* → tap **Build number**
   7 times.
2. **Enable USB debugging:** Settings → *Developer options* → **USB debugging**.
3. Connect the phone by USB, accept the "Allow USB debugging?" prompt, then:
   ```bash
   adb install -r android/app/build/outputs/apk/debug/app-debug.apk
   ```

**No cable?** Copy `app-debug.apk` to the phone (Drive/email/USB storage), tap it
in a file manager, and allow "install from unknown sources" when prompted.

---

## 6. First run (what to expect)

- The app opens the web UI full-screen in a WebView.
- The top banner shows the RAM check, e.g.
  `device 8 GB · recommended Qwen3.5-2B (~2 GB) · model not downloaded`.
- **Capture** lets you shoot/upload question + essay pages (the camera button
  uses the system camera).
- **Transcribe** and **Grade** return **placeholder** text/scores in this build
  (stub), so you can exercise the whole flow — including the annotated redline
  view — without a model.

This confirms the UI, camera capture, the native bridge, and the RAM
recommendation all work on your device.

---

## 7. Phase 2: enable the real on-device model

The Kotlin/JNI/download-manager side of this is already wired (see
`README.md`'s Status section). What's actually left, summarized (full detail
in [`README.md`](README.md#enable-the-real-model-phase-2)):

1. Install the NDK (Android Studio → SDK Manager → SDK Tools → **NDK**).
2. Vendor llama.cpp as a submodule under `app/src/main/cpp/llama.cpp` (a recent
   commit — Qwen3.5 needs newer ops + `libmtmd` vision support; still landing
   on HEAD as of mid-2026, confirm current status). `externalNativeBuild`
   turns on automatically once this checkout exists — no build file edits
   needed. A GitHub Actions job (`build-apk-native`, manually triggered) does
   the equivalent checkout in CI.
3. Fill in real, verified Hugging Face URLs + sha256 in `ModelRepo.kt` (candidate
   repos are noted in its doc-comment, but unverified — confirm the exact
   filenames yourself).
4. Build, then iterate on the `mtmd`/grammar API in `cpp/llama_jni.cpp` against
   whatever commit you pinned — it's version-sensitive and needs real
   on-device verification.

> Before investing in Phase 2, run the **Phase 0 desktop quality gate**
> (Qwen3.5-2B vs real handwriting samples) — small models can summarise instead
> of transcribe. See `README.md`.

---

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| `SDK location not found` | Create `android/local.properties` with `sdk.dir=/path/to/Android/sdk` (Android Studio does this automatically). |
| `Failed to find Build Tools` / `platform 35` | Install via SDK Manager, or `sdkmanager "platforms;android-35" "build-tools;35.0.0"`. |
| Gradle sync wants a different JDK | Set Android Studio → Settings → *Build Tools → Gradle → Gradle JDK* to 17. |
| `INSTALL_FAILED_USER_RESTRICTED` (Samsung) | In *Developer options*, also enable **Install via USB** / disable MIUI/OneUI install blocks. |
| Blank screen on launch | Ensure **Android System WebView** is installed/updated (Play Store). |
| Camera button does nothing | Grant the camera permission to the system camera app when prompted; the WebView uses the OS file/camera chooser. |
