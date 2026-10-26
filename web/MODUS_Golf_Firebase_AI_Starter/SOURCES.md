# Sources and attribution

Reviewed October 22, 2026. Current uploaded code takes priority over older project papers and public upstream examples.

## Supplied implementation

`MODUS-Golf-main (1).zip`, SHA256 `d5f72b90f815f48ca962459a264ce80b8a1274e0abd1ada74f74f172e66c430e`. The reference folder contains byte-identical copies of selected team files. The team repository remains unchanged. Source license/attribution needs to be retained for any upstream-derived code; the source ZIP contains no root LICENSE file. No external app source was copied into the new core modules.

User-confirmed update: the sound sensor broke, has been temporarily removed, and is planned to return after replacement. Current operation uses the camera-trigger path. This direct hardware update supersedes older installed-sensor descriptions.

## Official tooling documentation

- Firebase Studio migration and sunset: https://firebase.google.com/docs/studio/migrating-project
- Firebase Studio current overview: https://firebase.google.com/docs/studio
- Firebase integration in Google AI Studio: https://firebase.google.com/docs/ai-assistance/ai-studio-integration
- Google AI Studio Build: https://ai.google.dev/gemini-api/docs/aistudio-build-mode
- Firebase Hosting setup: https://firebase.google.com/docs/hosting/quickstart
- Firestore query authorization: https://firebase.google.com/docs/firestore/security/rules-query

The current migration notice says new Firebase Studio workspace creation and signup stopped June 22, 2026, with final sunset March 22, 2027. Core Firebase services continue. Google AI Studio's Firebase integration can set up Authentication and Firestore; enabling it is a deliberate project/location choice. Its publish action may use Cloud Run. This package does not claim to provision these services.

## Previously inspected app references

OpenFlight web UI is the closest technical reference; OpenFlight's Expo and Kotlin Multiplatform companion apps are useful navigation and reconnection references. PiTrac is useful for status and history organization. Study their exact versions and licenses before porting code. Their public feature or accuracy claims are not MODUS results.
