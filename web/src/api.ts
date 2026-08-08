import type { Alert, HealthSample, SpectrumSnapshot, Stats } from "./types";

// Same-origin /api by default (production nginx proxies it -- see
// Dockerfile/nginx.conf); override for `npm run dev` via a .env.local
// with VITE_API_BASE_URL=http://localhost:8000.
const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "/api";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(`${path} -> HTTP ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchAlerts(limit = 50): Promise<Alert[]> {
  return getJson<Alert[]>(`/alerts?limit=${limit}`);
}

export function fetchHealth(): Promise<HealthSample[]> {
  return getJson<HealthSample[]>("/health");
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

/**
 * Live alert feed over SSE (design doc §10 milestone 8). `onAlert` fires
 * for every event; `onStatusChange` reports connection state so the UI
 * can show "live" vs "reconnecting" -- EventSource retries automatically
 * on its own, this just surfaces that it's happening.
 */
export function subscribeToAlerts(
  onAlert: (alert: Alert) => void,
  onStatusChange: (connected: boolean) => void,
): () => void {
  const source = new EventSource(`${API_BASE_URL}/alerts/stream`);

  source.onopen = () => onStatusChange(true);
  source.onerror = () => onStatusChange(false);
  source.onmessage = (event: MessageEvent<string>) => {
    onAlert(JSON.parse(event.data) as Alert);
  };

  return () => source.close();
}
