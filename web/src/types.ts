// Mirrors services/api's response shapes (service/frontend boundary --
// duplicated knowledge, not a shared schema package, same posture every
// Python service in this repo takes toward its Redis/ZMQ neighbors).

export type AlertState = "RF_ONLY" | "API_ONLY" | "CONFIRMED";

/** `same_decoder`'s SAME header fields, as fusion carries them on an
 * alert's RF source. Every field here was previously fetched by the UI
 * and discarded -- `tier` in particular decides whether the alert reaches
 * the mesh at all (design doc §4/§7). */
export interface SameEvent {
  site: string;
  channel: string;
  received_at: string;
  event_code: string;
  event_name: string;
  tier: string;
  fips_codes: string[];
  originator: string;
  callsign: string;
  purge_minutes: number;
  raw_header: string;
}

/** `nws_poller`'s CAP fields. This is the entire content of hybrid mode:
 * without it an API_ONLY alert renders as a badge and nothing else. */
export interface CapAlert {
  id: string;
  event: string;
  headline: string | null;
  status: string;
  message_type: string;
  category: string;
  severity: string;
  certainty: string;
  urgency: string;
  area_desc: string;
  sent: string;
  effective: string | null;
  onset: string | null;
  expires: string | null;
  ends: string | null;
  same_codes: string[];
  ugc_codes: string[];
  vtec: string | null;
}

export interface AlertSource {
  kind: "RF" | "API";
  event?: SameEvent;
  alert?: CapAlert;
}

export interface Alert {
  id: string;
  state: AlertState;
  confidence: number;
  event_name: string;
  fips_codes: string[];
  first_seen: string;
  last_updated: string;
  sources: AlertSource[];
}

export interface HealthSample {
  site: string;
  channel: string;
  sampled_at: string;
  rms: number;
  power: number;
  dead: boolean;
}

export interface HealthHistoryPoint {
  site: string;
  channel: string;
  bucket: string;
  rms: number;
  power: number;
  dead: boolean;
}

export interface SpectrumSnapshot {
  site: string;
  timestamp_ns: number;
  bin_frequencies_hz: number[];
  bin_power_db: number[];
}

export interface DispatchSummary {
  sent: number;
  skipped: number;
  by_reason: Record<string, number>;
  since_seconds: number;
}

export interface Stats {
  counts: Partial<Record<AlertState, number>>;
  total: number;
  divergence_rate: number;
  dispatch: DispatchSummary;
}

export type ServiceStatus = "up" | "down" | "unexpected";

export interface ServiceRow {
  service: string;
  status: ServiceStatus;
  expected: boolean;
  updated_at: string | null;
  age_seconds: number | null;
  detail: Record<string, unknown>;
}

export interface SystemInfo {
  mode: string | null;
  icecast_public_url: string | null;
  icecast_port: number | null;
  captures_available: boolean;
}

export interface StreamRow {
  mount: string;
  site: string | null;
  channel: string | null;
  /** `null` means live_audio's heartbeat doesn't know about this mount --
   * distinct from `false`, which means it knows the feeder died. */
  feeder_alive: boolean | null;
  url: string;
  on_air: boolean;
  listeners: number | null;
  stream_name: string | null;
}

export interface StreamsResponse {
  icecast_reachable: boolean;
  streams: StreamRow[];
}

export interface Transcript {
  raw_header: string;
  timestamp_ns: number;
  site: string;
  channel: string;
  event_code: string;
  tier: string;
  fips_codes: string[];
  /** Empty whenever `passed_guard` is false -- stt_worker drops the text
   * of a transcript that looks hallucinated rather than passing it on. */
  text: string;
  passed_guard: boolean;
  guard_reason: string | null;
  wav_path: string | null;
}

export interface Dispatch {
  dispatched_at: string;
  stage: string;
  alert_id: string | null;
  site: string | null;
  channel: string | null;
  event_code: string;
  tier: string;
  fips_codes: string[];
  raw_header: string;
  sent: boolean;
  reason: string;
}

export interface CountyEntry {
  county: string;
  state: string;
}

export interface EventCodeEntry {
  name: string;
  tier: string | null;
}

/** One NWR transmitter, from `data/nwr_stations_or.yaml` via `GET
 * /reference`. `distance_km` is `null` unless the operator has set
 * `TOCSIN_LATITUDE`/`TOCSIN_LONGITUDE` *and* this station has its own
 * coordinates -- two of them (Carney Butte, Enterprise) don't yet. */
export interface NwrStation {
  name: string;
  frequency_mhz: number;
  status: string;
  wfo: string;
  power_watts: number | null;
  lat: number | null;
  lon: number | null;
  distance_km: number | null;
  distance_miles?: number | null;
}

export interface Reference {
  event_codes: Record<string, EventCodeEntry>;
  counties: Record<string, CountyEntry>;
  stations: Record<string, NwrStation>;
}
