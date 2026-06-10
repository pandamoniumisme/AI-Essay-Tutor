# AI Essay Tutor — Android (on-device)

Fully on-device essay grading for a Samsung Z Flip 5 (8 GB). No network: essays
never leave the phone. Inference runs **Qwen3.5-2B** (multimodal, Apache 2.0)
via llama.cpp — one model does OCR + picture description (vision) and grading
(text-only). Design: `/root/.claude/plans/is-there-a-qwen-proud-octopus.md`.

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
recommends a model (`core/ModelAdvisor`): **< 12 GB-class → Qwen3.5-2B**,
otherwise **Qwen3.5-4B**. The cutoff is 11 GiB of reported `totalMem` (a 12 GB
phone reports ~11.x GiB because some RAM is reserved). The recommendation
appears in the setup banner (and drives which GGUF the Phase-4 downloader
fetches). The Z Flip 5's 8 GB lands on 2B. `ModelAdvisor` is unit-tested.

## Status

- **Phase 1 (stub inference): code complete.** `StubInference` returns canned
  responses so the full capture → review → annotated-results flow + camera
  capture + bridge can be validated on the phone with **zero model**. Build the
  app in Android Studio and run.
- **Phase 2+ (real model): skeletoned.** `LlamaInference` + `LlamaJni` +
  `src/main/cpp/` show the integration; the native build is disabled
  (`externalNativeBuild` commented out) until llama.cpp is vendored.

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
Gemini fallback are the safety nets.
