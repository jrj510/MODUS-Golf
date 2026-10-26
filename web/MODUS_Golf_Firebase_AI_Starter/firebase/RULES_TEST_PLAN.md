# Required emulator checks before deployment

No emulator result is claimed in this starter. The AI builder must implement these tests using the current Firebase rules testing tools and run them against the proposed rules and backend.

| Scenario | Expected result |
|---|---|
| Signed-out request reads any golfer, shot, session, device or credential | Denied |
| Account A reads account B's profiles, shots, sessions or summaries | Denied |
| Account A creates own profile with valid name and server timestamps | Allowed |
| Profile has blank/overlong name, unknown fields, or client-forged timestamps | Denied |
| Own profile rename preserves creation timestamp and uses new server update timestamp | Allowed |
| Profile rename attempts to change created_at or add role/owner/admin fields | Denied |
| Browser directly creates, edits or deletes any shot/session/summary | Denied |
| Browser directly creates, transfers or lists devices | Denied |
| Browser gets own device registration by ID | Allowed only for registered owner |
| Browser reads device credential material | Denied, including for owner |
| Backend import omits auth or spoofs a body owner UID | Rejected by backend |
| Backend receives a device token owned by another account | Rejected by backend |
| Repeated import of same bytes/device/filename/profile | Same IDs; no duplicate shots |
| Imported source session is later assigned to another profile | Rejected |
| A previous row changes while a new row is appended | Explicit conflict; no partial overwrite |
| Late shot revision or duplicate function invocation arrives | No duplicate shot or double-counted aggregate |

Do not use permissive rules as a workaround when a test fails. Backend tests remain necessary even if all rule tests pass because Admin SDK bypasses these rules.
