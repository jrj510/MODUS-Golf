# Using the launch monitor from the iPhone

Start practice on the physical monitor. On the iPhone, join MODUS Wi-Fi, open **Monitor** in the installed app, allow Local Network access and connect to the kiosk. The usual address is `http://10.42.0.1:8000`. Use the address shown by your monitor if it differs. Practice, capture and local History work with cellular data off and without signing in.

| Route | What the phone uses it for |
|---|---|
| `GET /state` | Poll readiness, supported settings and acknowledgement of a requested screen change. |
| `GET /session.csv` | Copy the current session into local History. The phone uses the original filename from the download header to identify the session. A header-only export can mean the first shot is still pending. |
| `POST /club`, `/light`, `/view`, `/sleep`, `/wake` | Change a supported setting after the golfer enables phone controls in Monitor. |
| `POST /display/main`, `/display/camera`, `/display/range` | Request a page on the physical screen. The kiosk browser acknowledges it. The touchscreen remains available. |

The parser accepts the complete legacy 14-column and current 34-column CSV layouts by header name. The 20 extra values are saved as diagnostics. Copy shots before starting the next kiosk session. Kiosk `shot` and `rev` are process counters. The phone uses the monitor identity, original filename and shot sequence to recognize repeated reads. [CSV contract](SOURCE_MAP.md)

For cloud history, confirm the session contains physical shots, sign in and explicitly link the session to the intended golfer in **Account**. With internet access and the app open, the phone uploads eligible shots and records the returned receipts. Shots stay available in local History.

The kiosk also serves its touchscreen pages at `/` and `/range`, a local availability check at `/ping`, and recent in-memory flights at `/history`. The phone reads captured measurements from the CSV. See the [mobile guide](../../mobile/README.md) for the field workflow.
