# MODUS Golf for iPhone

From the repository root, the phone app lives in `web/mobile/`, shared React code in `web/src/`, the CSV parser and schema in `web/MODUS_Golf_Firebase_AI_Starter/`, and the physical monitor interface in `camera/kiosk.py`.

## Run the app

Use Node 24 or newer. From `web/mobile`, run `npm ci`, `npm test`, `npm run build`, and `npm run ios:check`. Use `npm run dev` for a browser preview. Direct monitor access uses Capacitor in the installed app. On the configured Mac, sync with `npm run ios:sync`, open with `npm run ios:open`, and run the App scheme. See [the Mac checklist](MAC_BUILD_CHECKLIST.md) for fresh native setup.

## Practice with a monitor

Start practice on the kiosk, join the monitor Wi-Fi on the iPhone, allow local-network access and connect in the **Monitor** tab. Use the private address shown by the monitor (commonly `http://10.42.0.1:8000`). The app reads readiness from `/state` and measurements from `/session.csv`. Keep the app open to capture. Copy shots before starting the next kiosk session. Both 14-column and 34-column CSVs are supported.

Select **Enable phone controls** in Monitor to change the club, lighting or camera zoom when supported, or sleep and wake the monitor. With the updated kiosk, **Show on monitor screen** can open Dashboard, Camera or Range. The phone confirms page changes through the physical browser's acknowledgement. The touchscreen remains available, including its Back button. Controls start off when entering Monitor or reconnecting. Local practice and saved history work offline.

## Cloud history

In **Monitor**, confirm that the session contains physical shots. Sign in, select a golfer and explicitly link the session in **Account**. Keep the app open with internet access for upload and a receipt. For this existing Firebase project (`modus-golf-ea469`), `ingestLegacyShots` in `us-central1` verifies the signed-in account and checks golfer ownership before writing. The Pi has no cloud role. Previously rejected 34-column records from the original validator get a fresh attempt. Local shots remain available while offline.
