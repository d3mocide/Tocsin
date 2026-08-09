# data/

Checked-in reference data, not code -- see `docs/design/master-prompt.md` §9 and §12.

- `same_event_codes.yaml` -- SAME/EAS event code -> name and dispatch tier
  (§4). Covers the full Tier A list from the design doc plus a broad set of
  Tier B/C codes; confirm against the current NWS event code list before
  relying on it operationally.
- `same_to_cap.yaml` -- SAME event code -> CAP `event` field text, used by
  `fusion`'s correlation key (§5). Verify against live CAP payloads.
- `fips.csv` -- FIPS -> county/state. **Seeded with only the Portland, OR
  WFO (PQR) area** (the counties covered by KIG98/KEC91, per the open item
  in §12), not the full national FIPS list. Extend this file with the
  counties relevant to your deployment, or replace it with the full
  Census Bureau county list, before relying on templated county names
  outside the Pacific Northwest.
- `nwr_stations_or.yaml` -- NWR transmitter callsign -> site name, frequency,
  status, WFO, power, and coordinates for every station covering Oregon, per
  the §12 open item on verifying local transmitter frequencies. Name/
  frequency/status/WFO are from <https://www.weather.gov/nwr/stations?State=OR>;
  power/coordinates are from a third-party aggregator (see the file's header
  comment) since no NWS page publishing them was reachable while authoring
  this file, and two stations (WZ2522, WZ2559) have no coordinates at all --
  treat lat/lon as approximate and `null` as "unconfirmed," not "no
  transmitter." `api`'s `/reference` endpoint serves this file and adds a
  `distance_km` per station when `TOCSIN_LATITUDE`/`TOCSIN_LONGITUDE` are
  set (see `services/api/README.md`). Narrows down what to expect at a given
  antenna location; doesn't replace the empirical waterfall confirmation the
  open item calls for.
