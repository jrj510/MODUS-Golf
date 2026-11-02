# MODUS Golf — MacBook to iPhone

Prepared 2026-11-02. The selected tools are **Capacitor CLI + Xcode + Swift Package Manager**. The application already uses React and native Capacitor Firebase plugins, so this route uses the supported native project generator and existing code.

## Transfer and prepare

1. Copy **`MODUS_Golf_Mac_Ready_2026-11-02.zip`** to the MacBook and extract it. Keep the extracted `mobile/`, `src/` and `MODUS_Golf_Firebase_AI_Starter/` folders together.
2. Install/open Xcode 26 or newer and finish its first-run components. Install Node 24 LTS. Run `swift --version`, `xcodebuild -version` and `node --version` in Terminal. If the selected developer tools are Command Line Tools rather than Xcode, select the installed Xcode under Xcode Settings → Locations → Command Line Tools.
   For **macOS Sequoia 15.6.1**, choose **Xcode 26.3** from [Apple Developer downloads](https://developer.apple.com/download/all/?q=Xcode%2026.3). Apple lists it as compatible with Sequoia 15.6 and later; no macOS 27 upgrade is required for this build toolchain. Check [Apple's Xcode compatibility table](https://developer.apple.com/xcode/system-requirements) when choosing another version.
3. In Terminal, enter the extracted `mobile/` directory. In the GitHub repository this is `web/mobile/`.

```bash
npm ci
npm run ios:prepare
npm run ios:open
```

The preparation command validates the registered Firebase configuration, checks the Mac toolchain, runs tests and builds the bundled UI. It generates/reuses the standard Capacitor iOS SPM project, syncs native plugins and runs a Swift resource configurator. An unexpected/custom native project layout stops preparation for inspection.

## Finish once in Xcode

The full instructions are in **`mobile/MAC_BUILD_CHECKLIST.md`**. Complete these explicit native steps:

1. Select the **App** target. Confirm bundle ID **`com.modusgolf.app`**, choose the owner's signing team and connect the iPhone by USB. Complete Apple's account, Trust and Developer Mode prompts directly.
2. Add the staged `ios/App/App/GoogleService-Info.plist` and `PrivacyInfo.xcprivacy` files to the **App** target, referencing them in place. Verify both appear exactly once in **Copy Bundle Resources**. Their presence on disk alone is insufficient.
3. In **Build Settings → All → Other Linker Flags**, retain existing values and `$(inherited)` and add **`-ObjC`** for Debug and Release if absent.
4. Let SPM resolve dependencies, select the connected iPhone and press **Run**. Keep the generated scene callback forwarding. The Google URL scheme and local-network settings are merged by the preparation script.

No Firebase project creation or new Apple registration is required. Reuse project `modus-golf-ea469`, Apple app `1:759125763752:ios:7e7aacf0f2e63d32dc449d`, and bundle ID `com.modusgolf.app`. The downloaded SDK plist and native email/password/Google integration are included.

## Confirm the first install

- With Wi-Fi and cellular off, cold-launch local practice. Add a synthetic shot, force quit and reopen; the saved record must survive.
- Enable only Wi-Fi, join MODUS and start the local connection. Copy a known physical shot from the existing Pi CSV. Disconnect and reopen; the saved metrics must remain. The Pi does not host the app or run new processing.
- With internet, test email/password and Google sign-in, cloud profile creation/history, sign-out and account switching.
- Test phone safe areas, portrait/landscape, keyboard and larger text, plus local-network denial/retry.

The first build/install requires the Mac and internet for dependency/signing setup. The installed UI and saved local shots are designed to open independently of both afterward. Receiving new Pi shots requires the local MODUS Wi-Fi link; that link needs no upstream internet.

## Exact limits of this package

This is a source/preparation package, **not a signed IPA or a verified native device build**. Native generation/configuration happens on the Mac; the Mac-only Swift configurator has not been executed or compiled on the Windows preparation host. Resource membership, linker settings, signing and device tests remain explicit steps.

Automatic upload of locally copied shots still requires account/profile pairing, a persistent upload queue and the trusted Firebase ingestion backend. Existing private cloud history can be read. Do not count a successful login/history read as a successful upload of new phone captures. The Pi archive/late-result fixes remain documented in the integration handoff.

The package contains client Firebase configuration, no service-account key or Apple signing credential. No backend, Firebase rules or Pi firmware changes were deployed by this preparation task. A free Apple Personal Team install requires periodic rebuilding/reinstallation; use the signing terms shown by Apple for your account.

## Validation and references

See `BUILD_VALIDATION.json` in the ZIP for the actual source-level checks performed on Windows. These are separate from native compilation and the device tests above. The source manifest lists the SHA-256 of each packaged file.

Primary references: [Capacitor SPM workflow](https://capacitorjs.com/docs/ios/spm), [iOS toolchain requirements](https://capacitorjs.com/docs/ios), [Capacitor 8.5 scene lifecycle](https://capacitorjs.com/docs/updating/8-5), [Firebase Auth plugin setup](https://capawesome.io/docs/sdks/capacitor/firebase/authentication/), [Filesystem privacy manifest](https://capacitorjs.com/docs/apis/filesystem).
