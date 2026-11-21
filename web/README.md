# MODUS Golf for iPhone

The iPhone app in `web/mobile/` is the supported MODUS Golf app. Capacitor bundles its React interface into the installed app. Golfers can open Practice offline, connect to the monitor over MODUS Wi-Fi, and use the physical touchscreen or opt in to phone controls. With internet access, the app can upload a confirmed session linked to a signed-in golfer.

## Build and run in Xcode

Use Node 24 LTS and Xcode 26 or newer. From the **repository root** on a Mac, run:

```sh
cd web/mobile
npm ci
npm run ios:prepare
npm run ios:open
```

Preparation tests and builds the mobile interface, generates or reuses the Capacitor iOS project, and syncs it using Swift Package Manager. For a fresh checkout, complete the App target’s two resource memberships, linker flag and signing setup. The configured build Mac can reuse its existing native project. In Xcode select the **App** scheme and **iPhone 18 Pro** simulator or a connected iPhone, then press **⌘R**. [Mac build checklist](mobile/MAC_BUILD_CHECKLIST.md)

For later UI edits in the same mobile directory, run `npm run build` followed by `npm run ios:sync`, then run **App** again in Xcode.

## Develop on Windows or Mac

From the repository root, run the following to install the mobile dependencies, test the shared code and phone app, and build the bundled interface:

```sh
cd web
npm ci
npm test
npm run build
```

Use `npm run dev` in that directory for a local mobile UI preview. The installed iPhone app provides the native monitor connection and Google sign-in. The browser preview is a development tool.

From `web/`, run `npm run test:firebase` with Java 21 or newer on your PATH. It starts the Auth and Firestore emulators for `demo-modus-golf`, runs sign-in and access-rule tests, and shuts both emulators down. To test cloud upload and replay as well, follow the [ingestion test instructions](MODUS_Golf_Firebase_AI_Starter/firebase/README.md).

## Work on the monitor connection

The iPhone polls the kiosk’s readiness at `/state` and copies shots from `/session.csv`. The Pi runs its existing capture and touchscreen software. To check a change on hardware, start practice on the monitor, join MODUS Wi-Fi on the phone, and open **Monitor** in the app. [Monitor controls and cloud history](mobile/README.md)

| Component | Repository path |
|---|---|
| Mobile app, Capacitor configuration and tests | `web/mobile/` |
| Shared shot views, bag, metrics and styling | `web/src/` |
| CSV parser, shot schema and authenticated upload function | `web/MODUS_Golf_Firebase_AI_Starter/` |
| Physical monitor and touchscreen | `camera/kiosk.py` |

The mobile app uses the existing Firebase project `modus-golf-ea469` and Apple bundle ID `com.modusgolf.app`. Xcode installs the app. Local practice requires neither Firebase sign-in nor an internet connection.
