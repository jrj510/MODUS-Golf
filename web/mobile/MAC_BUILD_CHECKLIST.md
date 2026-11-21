# Build MODUS Golf on a MacBook — selected route

Updated 2026-11-02: use Capacitor CLI, Xcode and Swift Package Manager on the MacBook. This is the selected route for the existing app. Shared development can remain on Windows; the MacBook performs the native build, signing and installation. The installed app does not depend on a running MacBook.

The native host is already configured and builds in the iPhone 18 Pro simulator. Reuse it. Resource membership, linker flags and signing are already present; the steps below also document recovery on another Mac. The corrected owner account `lbrowningsgc@gmail.com` was verified on 2026-11-03. Its project ID is the original `modus-golf-ea469`; all original registrations are reused.

On 2026-11-03 the signed Debug app also built, installed and launched on the physical iPhone 16 Pro. The owner confirmed Google sign-in for the previously failing new account before the diagnostic update. See [Google sign-in investigation](GOOGLE_SIGNIN_INVESTIGATION.md) for remaining physical checks. `npm ci`, `npm run ios:prepare` and `npm run ios:sync` apply the version-checked native auth diagnostic patch; use these scripts when rebuilding. Generic bridge logging is disabled to avoid exposing OAuth results.

## Before starting

1. Transfer and extract **`MODUS_Golf_Mac_Ready_2026-11-02.zip`**. Preserve its parent folders; `mobile/src` imports the shared parent `src` and contract files. For a GitHub checkout the equivalent folder is `web/mobile/`.
2. Use a Mac that supports **Xcode 26 or newer**, as required by Capacitor 8. Install a compatible Xcode and **Node 24 LTS** for this tested source package. Accept Apple's Xcode license directly if prompted. Open Xcode once to finish installing its components.
   On **macOS Sequoia 15.6.1**, use **Xcode 26.3**, which Apple lists as compatible with Sequoia 15.6+. Download that version from [Apple Developer downloads](https://developer.apple.com/download/all/?q=Xcode%2026.3) if the App Store offers a newer incompatible version. A macOS 27 upgrade is not required for this toolchain. See [Apple's compatibility table](https://developer.apple.com/xcode/system-requirements).
3. Confirm `swift --version`, `xcodebuild -version` and `node --version` work. If an AI performs native project/package changes, use the installed Firebase/Xcode skills and their toolchain/project checks. Do not text-edit `.pbxproj` files or use Ruby project-editing scripts.
4. Use your own Apple ID and signing team in Xcode. Connect your iPhone by USB. You perform Apple sign-in, any two-factor prompts, device Trust prompts and Developer Mode steps yourself.

## Prepare the Capacitor app

From the extracted source folder:

```bash
cd mobile
npm ci
npm run ios:prepare
npm run ios:open
```

The preparation command verifies macOS, Swift, Xcode 26+ and the iPhone SDK before native changes. It runs the journal tests and UI production build, then uses the installed Capacitor CLI's official workflow:

```bash
npx cap add ios --packagemanager SPM
npx cap sync ios
```

It reuses an existing standard SPM project and stops on an unexpected/incomplete layout. It also runs `scripts/configure-ios.swift` to merge the Google callback/local-network Info.plist entries and stage Firebase/privacy resources. Existing resource/plist changes are backed up under `.modus-backups/`. It does not alter signing or resource target membership, and it does not text-edit `.pbxproj`.

The SPM configuration in `capacitor.config.ts` includes the Google provider trait and authentication package symlink option. Keep the CLI-generated `CapApp-SPM/Package.swift` managed by `cap sync`; do not replace it with a custom xtool manifest.

## Complete native configuration in Xcode

1. Select the **App** application target. Set display name **MODUS Golf** and bundle identifier **`com.modusgolf.app`**.
2. Under Signing & Capabilities, select the owner's signing team and use the appropriate development signing/provisioning workflow. Device registration/provisioning is separate from Firebase registration.
3. **Add the two staged resources to the App target once.** In Finder open `ios/App/App/`. Drag `GoogleService-Info.plist` and `PrivacyInfo.xcprivacy` into the App group in Xcode, referencing them in place and selecting **App** target membership. Verify both appear exactly once under **App → Build Phases → Copy Bundle Resources**. Copying a file to the folder alone does not register it in the generated project. The Firebase plist must contain project `modus-golf-ea469`, bundle ID `com.modusgolf.app`, and app ID `1:759125763752:ios:7e7aacf0f2e63d32dc449d`.
4. The Swift configurator already merges this Google callback URL scheme into Info.plist; verify it under the target's URL Types:

   ```text
   com.googleusercontent.apps.759125763752-jleq4gprpelp2s2qs4ssabqu1l5kcc0b
   ```

5. Verify the merged local-network usage description and `NSAppTransportSecurity.NSAllowsLocalNetworking=true` in the actual App Info.plist. There is no blanket arbitrary-internet-load exception. The privacy manifest declares file-timestamp use for this Filesystem implementation; review additional declarations if the app's behavior changes.
6. **Preserve the generated Capacitor 8.5 scene lifecycle.** Its `SceneDelegate.swift` forwards URL/connection callbacks through `SceneDelegateProxy`, including the cold-start path. Test Google sign-in callbacks both with the app already running and after relaunch. Do not replace it with an older AppDelegate-only tutorial or add duplicate default Firebase initialization; the installed plugins configure Firebase when needed.
7. Let SPM resolve the native dependencies. Under **App → Build Settings → All → Other Linker Flags**, preserve existing values and add **`-ObjC`** for Debug and Release if absent; retain **`$(inherited)`**. Verify the native Firebase/Google SDK products resolve through the generated plugin package graph. If an AI performs additional Xcode dependency changes, use the Xcode skill's Swift setup workflow; do not edit the project file as raw text.
8. Select the connected iPhone as the run destination, then Build/Run. Complete the phone's development/trust prompts as requested by Apple.

## First device acceptance test

- Launch in Airplane Mode with both Wi-Fi and cellular disabled. The app opens local practice without waiting for sign-in. Add a synthetic test shot, force quit and reopen; it survives. It stays labeled synthetic.
- Re-enable only Wi-Fi and join MODUS. Start the local connection. The app reads the Pi's existing CSV; no app is hosted by the Pi. Turn on physical-shot confirmation only for a known physical-shot session.
- Disconnect from MODUS. Previously copied local shots remain available. Repeat after force quit. Confirm the Pi's existing capture behavior was unchanged.
- Restore internet. Test email/password account creation/sign-in, Google native sign-in, profile creation and private Firestore history. Switch accounts and sign out; another account's cloud data must disappear.
- Revisit the app while offline with a cached account. Local practice must still open. Cloud history must identify cached data honestly.
- Verify local-network denial/retry, Pi unavailable, empty CSV, partial download, missing metrics, zero launch angles and duplicate refreshes.
- Check all screens at the actual phone's size, including portrait, landscape, keyboard open, safe areas and larger text. The final browser viewport check on Windows was interrupted by a tool authorization-review timeout.
- Confirm real CSV paths remain unavailable rather than being invented. Synthetic fixture flight views may display their supplied paths.
- For a sync-enabled build, link a confirmed monitor session to a test golfer in Account. Reopen while offline, then restore internet and verify the same shot in Firebase history after the phone records a matching receipt. See the Cloud history section in README.md.

Production builds now load `VITE_ENABLE_CLOUD_SYNC=true` from `.env.production`. The service is deployed to the original project and has passed live service checks. The app must be open, signed in, and have an explicitly linked physical session to upload.

For later shared-source changes, rerun `npm run ios:prepare`, reopen Xcode and build/run again. The resource memberships and signing selections remain in the native project. Keep that project in source control if you want to preserve the one-time Xcode setup. The installed app is independent of the Mac while in use.

For free Personal Team testing, Apple states that device provisioning profiles expire seven days after issuance. Plan to re-sign/reinstall when needed; do not assume a development install will remain launchable indefinitely. See [Apple's account overview](https://developer.apple.com/help/account/basics/about-your-developer-account).

Primary references: [Capacitor iOS](https://capacitorjs.com/docs/ios), [SPM workflow](https://capacitorjs.com/docs/ios/spm), [native Firebase Auth plugin](https://capawesome.io/docs/sdks/capacitor/firebase/authentication/), [Firestore offline behavior](https://firebase.google.com/docs/firestore/manage-data/enable-offline).
