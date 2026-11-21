# Physical-iPhone Google sign-in investigation — 2026-11-03

## Evidence and current conclusion

The owner reported that the **same previously failing new Google account successfully signed in on the physical iPhone before the diagnostic build was installed**. Do not attribute that success to this patch. The exact failed hostname and underlying cause are still unconfirmed. A transient network/DNS problem is consistent with the messages, but is not a confirmed root cause.

The confirmed code defect is loss of diagnostic information: authentication plugin 8.5.2's `handleFailedSignIn` sent only a localized description and an optional Firebase error code across the bridge, discarding the nested NSError and failing URL. Google and Firebase failures used the same handler. The UI then displayed only the description.

## Traced flow

1. Account → Continue with Google → `src/native-firebase.ts` → native `FirebaseAuthentication.signInWithGoogle`.
2. `GoogleAuthProviderHandler.swift` invokes GoogleSignIn. The SDK performs browser authorization, token exchange and, if needed, Google's own user-info request. Google's consent notification alone does not establish completion of these operations.
3. The plugin constructs a Google credential and calls `Auth.auth().signIn(with:)`. Firebase creates a user when appropriate; the app does not separately create another Firebase account.
4. The native auth listener updates React account state. Firestore history/profile listeners start afterward. Foreground upload is separately gated by an authenticated account and explicitly linked real sessions.
5. Golfer creation is an explicit **Add golfer** action. Sign-in does not write a parent user document, create a golfer, or overwrite existing profiles. Repeated sign-ins therefore do not create duplicate golfer profiles. The existing manual `addDocument` action is not a new automatic/idempotent profile bootstrap; retry safety for ambiguous manual-write failures remains separate work.

No localhost/emulator authentication endpoint, remote UI server, custom sign-in API, or automatic Firestore initialization write was found. `skipNativeAuth` remains false. Firebase plist identifiers, URL scheme, scene callbacks, signing and SDK versions are preserved.

## Changes

- `src/auth-diagnostics.ts`: allowlisted error metadata, distinct Google/Firebase messages, DNS hostname when supplied, actionable network guidance and readable Firebase account errors.
- `src/native-firebase.ts`: wraps existing sign-in calls with sanitized diagnostics; preserves native account persistence and existing auth methods.
- `scripts/AuthDiagnostics.swift`: bounded NSError chain extraction, domains/codes and **hostname only**; current authenticated boolean; Debug native logs. No userInfo dump, URL query, email, password or token.
- `scripts/patch-auth.swift`: idempotent patch limited to installed authentication **8.5.2**. Labels Google SDK and Firebase credential-exchange stages and transports sanitized native errors. Refuses an unexpected package version/source layout.
- `scripts/patch-auth.mjs`: runs the Swift patch on macOS; shared Windows React development remains supported.
- `scripts/prepare-mac.mjs`: reapplies the patch before native preparation.
- `package.json`, `package-lock.json`: installation hook and `preios:sync` hook; no dependency version change.
- `capacitor.config.ts`: disables generic Capacitor bridge logging, which can expose OAuth return data. Sanitized native `[MODUS Auth]` Debug logs remain available.
- `tests/auth-diagnostics.test.mjs`: verifies error staging, hostname extraction/absence, prefixed Firebase codes and credential redaction.
- This investigation document.
- Root `APP_READINESS.md`, `TEST_RESULTS.md`, and `MAC_BUILD_CHECKLIST.md`: updated physical-build and owner-reported sign-in evidence.

Generated outputs updated by build/sync: `dist/`, `ios/App/App/public/`, `ios/App/App/capacitor.config.json`; the two native authentication package source files under `node_modules/` are patched reproducibly. Capacitor also regenerates its managed SPM manifest. No `.pbxproj`, signing, Firebase plist, rules, backend or registration changes were made for this investigation.

## Verification

- 22 mobile tests passed, including offline cold start, saved-shot persistence and account isolation.
- TypeScript and production Vite build passed.
- Native nested-error test passed: correct failing hostname extracted; sensitive URL path/query and descriptions excluded.
- Signed Debug physical-iOS build: `BUILD SUCCEEDED` (existing signing settings).
- Updated diagnostic build installed over the existing app and launched on the connected iPhone 16 Pro. No uninstall or data reset.
- Physical new-account Google sign-in: owner-confirmed success on the previous build. Existing-account physical sign-in was reported working in the request.
- Updated-build physical sign-out/sign-in: captured native events `google-sign-in-start` → `firebase-credential-exchange-start` → `firebase-returning-user-authenticated`, with `authenticated: true` and no errors.
- Owner confirmed sign-out, sign-in, force quit/reopen and persisted authentication on the updated build. The owner also said “it all works now”; profile creation/retention was not separately described, so it is not recorded as an independently verified profile test.
- No failed device request was captured yet; exact hostname remains unknown.
- Profile creation/retention, an additional never-before-used Google account on the updated build, email/password regression and offline device acceptance remain manual checks. Unit tests and a successful build do not establish those outcomes.

## Rebuild and device checklist

```sh
cd web/mobile
npm run ios:prepare
npm run ios:open
```

In Xcode select **App** and the connected physical **iPhone**, then **⌘R**. Do not uninstall the app or reset its data. No Firebase Console configuration change is required by this patch. Avoid changing project, API keys, OAuth clients, DNS configuration or ATS speculatively.

1. Check Account after launch: the successful account should still be signed in.
2. If no golfer exists, add one once. If one exists, keep it. Record its name.
3. Sign out and back in with the same Google account; verify the same golfer appears without another copy.
4. Force quit and reopen; check that the account and golfer remain.
5. With Wi-Fi and cellular off, open Practice and verify saved local shots remain accessible. Restore internet afterward.
6. Test an existing account, email/password and a completely new Google account when available. Do not delete accounts to manufacture a new-user test.
7. On recurrence, record the on-screen error and only `[MODUS Auth]` Xcode console lines. These distinguish Google SDK failure from Firebase credential exchange and include the nested error domain/code and hostname when iOS supplies it. Never share raw OAuth callbacks or full bridge output.

Official flow reference: https://firebase.google.com/docs/auth/ios/google-signin
Error handling reference: https://firebase.google.com/docs/auth/ios/errors
