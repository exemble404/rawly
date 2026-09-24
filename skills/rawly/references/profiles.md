# Shooting profiles

No saved-profile database is needed. Create as many JSON files as you need and pass
one to `process --profile`. With no profile, output does not add camera or location tags.
The bundled devices are illustrative metadata templates, not verified camera signatures.

```json
{
  "device": "apple_0",
  "city": null,
  "time": "current"
}
```

Use `presets devices` / `presets cities` to find exact IDs. `--search` filters labels
and IDs; city labels in the bundled catalog are Russian (for example `--search Москва`).

Create a device-only profile:
```text
rawly.py profile studio.json --device apple_0
```

Set a location and explicit local time:
```text
rawly.py profile studio.json --device apple_0 --city c_Россия_Москва --time fixed --datetime "2026:09:24 12:00:00" --timezone +03:00
```

`time` is `current`, `random48` or `fixed`. `datetime` is only used by `fixed`.
`timezone` is an explicit UTC offset. Without one, the tool uses the city's bundled
static offset or the machine's local offset. City offsets do not track daylight-saving
transitions; supply the correct offset when the capture time matters. GPS timestamps
are written in UTC. Camera exposure fields are synthesized within the template ranges.
A profile is an editing instruction, not proof of capture provenance.

To reuse device fields from a reference photo:
```text
rawly.py profile camera.json --from-photo reference.jpg
```
This copies camera fields only; it does not automatically copy GPS or the old date.
