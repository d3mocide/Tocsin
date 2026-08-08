import type {
  Alert,
  Dispatch,
  HealthHistoryPoint,
  HealthSample,
  Reference,
  ServiceRow,
  SpectrumSnapshot,
  Stats,
  StreamsResponse,
  SystemInfo,
  Transcript,
} from "./types";

// Same-origin, unprefixed by default -- the production build is served
// by the `api` container itself (see services/api/app.py's static mount),
// so its own routes are already same-origin. Override for `npm run dev`
// via a .env.local with VITE_API_BASE_URL=http://localhost:8000.
const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(`${path} -> HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchAlerts(limit = 100): Promise<Alert[]> {
  return getJson<Alert[]>(`/alerts?limit=${limit}`);
}

export function fetchHealth(): Promise<HealthSample[]> {
  return getJson<HealthSample[]>("/health");
}

export function fetchHealthHistory(sinceSeconds = 3600, buckets = 60): Promise<HealthHistoryPoint[]> {
  return getJson<HealthHistoryPoint[]>(`/health/history?since_seconds=${sinceSeconds}&buckets=${buckets}`);
}

export function fetchSpectrumSites(): Promise<string[]> {
  return getJson<string[]>("/spectrum");
}

export function fetchSpectrum(site: string): Promise<SpectrumSnapshot> {
  return getJson<SpectrumSnapshot>(`/spectrum/${encodeURIComponent(site)}`);
}

export function fetchStats(): Promise<Stats> {
  return getJson<Stats>("/stats");
}

export function fetchServices(): Promise<ServiceRow[]> {
  return getJson<ServiceRow[]>("/services");
}

export function fetchSystem(): Promise<SystemInfo> {
  return getJson<SystemInfo>("/system");
}

export function fetchStreams(): Promise<StreamsResponse> {
  return getJson<StreamsResponse>("/streams");
}

export function fetchReference(): Promise<Reference> {
  return getJson<Reference>("/reference");
}

export function fetchTranscripts(limit = 100, rawHeader?: string): Promise<Transcript[]> {
  const suffix = rawHeader ? `&raw_header=${encodeURIComponent(rawHeader)}` : "";
  return getJson<Transcript[]>(`/transcripts?limit=${limit}${suffix}`);
}

export function fetchDispatches(limit = 100, rawHeader?: string): Promise<Dispatch[]> {
  const suffix = rawHeader ? `&raw_header=${encodeURIComponent(rawHeader)}` : "";
  return getJson<Dispatch[]>(`/dispatches?limit=${limit}${suffix}`);
}

export function captureUrl(name: string): string {
  return `${API_BASE_URL}/captures/${encodeURIComponent(name)}`;
}

export interface EventHandlers {
  onAlert?: (alert: Alert) => void;
  onHealth?: (sample: HealthSample) => void;
  onTranscript?: (transcript: Transcript) => void;
  onDispatch?: (dispatch: Dispatch) => void;
  onStatusChange?: (connected: boolean) => void;
}

/**
 * Live feed over SSE (design doc §10 milestone 8). One connection now
 * carries every named event type rather than alerts alone, which is what
 * let the polling timers for health go away -- a stream the browser is
 * already holding open costs less than a `setInterval` re-fetching state
 * that usually hasn't changed, and a channel going dead reaches the
 * screen when it happens instead of up to five seconds later.
 *
 * Named events need `addEventListener`; `onmessage` only fires for
 * unnamed ones. `EventSource` reconnects on its own -- `onStatusChange`
 * just surfaces that it's happening.
 */
export function subscribeToEvents(handlers: EventHandlers): () => void {
  const source = new EventSource(`${API_BASE_URL}/events`);

  source.onopen = () => handlers.onStatusChange?.(true);
  source.onerror = () => handlers.onStatusChange?.(false);

  const bind = <T>(name: string, handler: ((item: T) => void) | undefined) => {
    if (!handler) return;
    source.addEventListener(name, (event) => {
      try {
        handler(JSON.parse((event as MessageEvent<string>).data) as T);
      } catch (err) {
        console.error(`malformed ${name} event`, err);
      }
    });
  };

  bind("alert", handlers.onAlert);
  bind("health", handlers.onHealth);
  bind("transcript", handlers.onTranscript);
  bind("dispatch", handlers.onDispatch);

  return () => source.close();
}
