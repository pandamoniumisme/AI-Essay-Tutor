# AI Essay Tutor — Android (on-device)

Fully on-device essay grading for a Samsung Z Flip 5 (8 GB). No network: essays
never leave the phone. Inference runs **Qwen3.5-2B** (multimodal, Apache 2.0)
via llama.cpp — one model does OCR + picture description (vision) and grading
(text-only). Design: `/root/.claude/plans/is-there-a-qwen-proud-octopus.md`.

**Building the APK?** See [SETUP.md](SETUP.md) for the step-by-step build +
install guide.

## How it reuses the web app

The whole front-end (`server/aitutor_server/static/`) is loaded in a `WebView`.
`js/api.js` detects `window.AndroidBridge` and routes `transcribe()`/`grade()`
to native code instead of HTTP — so **one SPA serves both** web and Android. The
build copies the SPA + grader prompts into `app/src/main/assets/` (no fork).

## Module layout

| Module | Builds without Android SDK? | What |
|---|---|---|
| **`core/`** | ✅ yes (plain JVM) | Ported platform-independent logic: prompts, grade JSON schema, JSON validation/clamping, language detection, data schemas. **Unit-tested here.** |
| **`app/`** | ❌ needs Android Studio + NDK | WebView host, JS bridge, inference (stub + llama.cpp), foreground service. |

`core` is a composite build (`includeBuild("core")`) so it compiles and tests on
a plain JVM — that's where the risky ported logic is verified.

## Model recommendation at setup

Before any download, setup reads the device's total RAM (`DeviceRam`) and
recommends a model (`core/ModelAdvisor`): **Qwen3.5-4B** when reported
`totalMem` ≥ **10.5 GiB**, otherwise **Qwen3.5-2B** (a "12 GB" phone reports
~10.9 GiB; an 8 GB phone ~7.4 GiB). The recommendation drives the default
download; the user can override it (Auto / 2B / 4B) in **Settings**.
`ModelAdvisor` is unit-tested.

## Status

The whole app is implemented in Kotlin and **CI-verified to compile** (the
`build-apk` workflow). What ships in the APK depends on whether the native
engine is compiled in:

- **Engine wiring — complete.** `LlamaInference` (download → load → vision OCR →
  grammar-constrained grade → validate), `ModelDownloader` (resumable + sha256),
  `InferenceService` (foreground service), the RAM-based model picker, and the
  JS bridge are all done. `Inference.create()` uses the real engine when the
  native lib is present and **falls back to `StubInference`** otherwise.
- **Native engine — bring-up scaffold, OFF by default.** `cpp/llama_jni.cpp` +
  `CMakeLists.txt` implement the llama.cpp text + `libmtmd` vision paths, but
  `externalNativeBuild` is commented out so the APK builds without the NDK. The
  default CI APK therefore ships the **stub fallback** (full UI + camera + RAM
  recommendation, placeholder grades).
- **Two things gate a real-grading APK:** (1) compile the native engine on a
  machine with the NDK + a device to iterate the `mtmd`/grammar API and the
  Qwen3.5 vision template; (2) fill in verified model URLs/checksums in
  `ModelRepo` (currently placeholders).

## Verify the core (no Android toolchain needed)

```bash
cd android/core && gradle test
```

## Build the app (Phase 1 stub)

Open `android/` in Android Studio (it provides the Gradle wrapper + SDK), or
with a local SDK:

```bash
cd android && gradle :app:assembleDebug   # requires ANDROID_HOME + SDK
```

`Inference.create()` returns `StubInference` — no model download, runs offline.

## Enable the real model (Phase 2)

1. Vendor llama.cpp (recent commit — Qwen3.5 Gated DeltaNet + `libmtmd` vision):
   `git submodule add https://github.com/ggml-org/llama.cpp android/app/src/main/cpp/llama.cpp`
2. Uncomment `externalNativeBuild` in `app/build.gradle.kts` and the
   `add_subdirectory`/`target_link_libraries` lines in `cpp/CMakeLists.txt`.
3. Implement the four stubs in `cpp/llama_jni.cpp`.
4. Switch `Inference.create()` to return `LlamaInference(context)`.
5. Add the model download manager (Phase 4) to fetch the Qwen3.5-2B Q4 GGUF +
   `mmproj` into `filesDir/models`.

## Known risk

Small models can "summarise instead of transcribe" handwriting. Run the
**Phase 0 desktop quality gate** (Qwen3.5-2B vs `samples/` ground truth) before
investing in the native layer. The transcription-review screen and an optional
Hugging Face online option are the safety nets.
