// Mirrors services/api's response shapes (service/frontend boundary --
// duplicated knowledge, not a shared schema package, same posture every
// Python service in this repo takes toward its Redis/ZMQ neighbors).

export type AlertState = "RF_ONLY" | "API_ONLY" | "CONFIRMED";

export interface AlertSource {
  kind: "RF" | "API";
  event?: Record<string, unknown>;
  alert?: Record<string, unknown>;
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

export interface SpectrumSnapshot {
  site: string;
  timestamp_ns: number;
  bin_frequencies_hz: number[];
  bin_power_db: number[];
}

export interface Stats {
  counts: Partial<Record<AlertState, number>>;
  total: number;
  divergence_rate: number;
}
