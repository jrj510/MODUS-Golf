# Synthetic fixtures only

Every CSV row, shot, clock value, flight point and status in this folder is synthetic. These are not test results from a real Pi. Use them only in an explicitly labeled demo adapter. Never upload them to real golfer collections.

The CSV uses the exact current header. The range paths were generated with the supplied Pi ball-flight model solely to exercise the renderer; they do not validate the model. HLA is separately reported, while the sample trajectories use assumed direction. The final row has an assumed launch. A missing club-speed example is included. Camera telemetry is null rather than invented. known_hardware.json describes a known configuration, not a current health reading.

`demo_shots.json` contains the canonical normalized form of these 12 rows. Every record is explicitly synthetic. Its timestamp is null because the source shape does not provide a precise impact time. The CSV importer defaults ordinary imports to unknown until a person confirms real-shot provenance; the demo adapter must additionally mark these fixture rows synthetic even if it reuses that importer.

`demo_profiles.json` includes one populated profile and one empty profile for interface states. `demo_sessions.json` uses the same deterministic session ID as the shot records. These are local demo shapes; their extra context fields are not a deployed Firestore profile schema. None of these files should be seeded into a real user's collections.
# November 19 CSV compatibility fixture

`pi_csv_34_synthetic.csv` has the actual 34-column header from the pinned producer in `../pi-csv-34.json`, with two **invented test rows**. Values are not real hardware measurements. It exercises zero direction, missing accepted club speed, hidden/check/model values, quoted commas and quotes. Tests use an explicit original-session filename in their import context and preserve the default unconfirmed record kind. Never upload this fixture as a physical session.
