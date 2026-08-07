# data/

Checked-in reference data, not code -- see `docs/design-spec.md` §9 and §12.

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
