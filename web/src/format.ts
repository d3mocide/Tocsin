import type { Alert, AlertSource, CapAlert, Reference, SameEvent } from "./types";

/** Derived presentation logic shared by every view. Kept out of the views
 * themselves because most of it answers questions the API deliberately
 * doesn't answer server-side -- expiry, RF/API latency, county names --
 * all of which are computable from data already on the wire. */

export function rfSource(alert: Alert): SameEvent | null {
  const source = alert.sources.find((s: AlertSource) => s.kind === "RF");
  return source?.event ?? null;
}

export function apiSource(alert: Alert): CapAlert | null {
  const source = alert.sources.find((s: AlertSource) => s.kind === "API");
  return source?.alert ?? null;
}

export function tierOf(alert: Alert, reference: Reference | null): string | null {
  const rf = rfSource(alert);
  if (rf?.tier) return rf.tier;
  // An API_ONLY alert has no SAME header and so no tier of its own. The
  // CAP event name maps back to a code only via data/same_to_cap.yaml,
  // which isn't loaded here -- so fall back to matching the event name
  // against the reference table rather than showing nothing.
  if (!reference) return null;
  const match = Object.values(reference.event_codes).find((entry) => entry.name === alert.event_name);
  return match?.tier ?? null;
}

/**
 * When this alert stops being in effect, or `null` if nothing on it says.
 *
 * Two independent sources of truth, deliberately preferring CAP's own
 * `expires` over the SAME purge time: SAME's purge is a duration from the
 * *decode* time (fusion stands `received_at` in for SAME's issue time --
 * see its correlator), so it drifts by however long the message sat
 * before it was decoded, while CAP carries a real absolute timestamp.
 */
export function expiresAt(alert: Alert): Date | null {
  const cap = apiSource(alert);
  const capExpiry = cap?.expires ?? cap?.ends ?? null;
  if (capExpiry) {
    const parsed = new Date(capExpiry);
    if (!Number.isNaN(parsed.getTime())) return parsed;
  }
  const rf = rfSource(alert);
  if (rf?.received_at && typeof rf.purge_minutes === "number") {
    const received = new Date(rf.received_at);
    if (!Number.isNaN(received.getTime())) {
      return new Date(received.getTime() + rf.purge_minutes * 60_000);
    }
  }
  return null;
}

export function isActive(alert: Alert, now: Date = new Date()): boolean {
  const expiry = expiresAt(alert);
  // No expiry information at all counts as active rather than expired:
  // dropping an alert out of the live list because its provenance was
  // thin is the wrong way to be wrong.
  return expiry === null || expiry.getTime() > now.getTime();
}

/**
 * Seconds between the RF decode and the CAP issue for a CONFIRMED alert,
 * negative when the radio got there first (the usual and desirable case).
 *
 * This is the number the whole dual-path architecture exists to produce
 * and nothing in the system computed it before -- design doc §5 treats
 * RF-vs-API agreement as the system's health metric, and this is that
 * agreement measured in seconds rather than counted in states.
 */
export function rfApiLatencySeconds(alert: Alert): number | null {
  const rf = rfSource(alert);
  const cap = apiSource(alert);
  if (!rf?.received_at || !cap?.sent) return null;
  const rfTime = new Date(rf.received_at).getTime();
  const capTime = new Date(cap.sent).getTime();
  if (Number.isNaN(rfTime) || Number.isNaN(capTime)) return null;
  return (rfTime - capTime) / 1000;
}

/** SAME's 6-digit PSSCCC: `P` is the county-subdivision digit, `SSCCC` is
 * the plain 5-digit FIPS that data/fips.csv keys on. Mirrors
 * dispatcher.fips.FipsTable.lookup -- same table, same granularity. */
export function countyName(fipsCode: string, reference: Reference | null): string {
  const entry = reference?.counties[fipsCode.slice(-5)];
  return entry ? `${entry.county}, ${entry.state}` : fipsCode;
}

export function countyNames(fipsCodes: string[], reference: Reference | null): string {
  if (fipsCodes.length === 0) return "—";
  return fipsCodes.map((code) => countyName(code, reference)).join(" · ");
}

const RELATIVE_UNITS: [limitSeconds: number, divisor: number, unit: Intl.RelativeTimeFormatUnit][] = [
  [60, 1, "second"],
  [3600, 60, "minute"],
  [86_400, 3600, "hour"],
  [604_800, 86_400, "day"],
];

const relativeFormatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const deltaSeconds = (then - now.getTime()) / 1000;
  const magnitude = Math.abs(deltaSeconds);
  for (const [limit, divisor, unit] of RELATIVE_UNITS) {
    if (magnitude < limit) return relativeFormatter.format(Math.round(deltaSeconds / divisor), unit);
  }
  return relativeFormatter.format(Math.round(deltaSeconds / 604_800), "week");
}

export function absoluteTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleString();
}

export function durationSeconds(seconds: number): string {
  const magnitude = Math.abs(Math.round(seconds));
  if (magnitude < 60) return `${magnitude}s`;
  if (magnitude < 3600) return `${Math.round(magnitude / 60)}m`;
  return `${(magnitude / 3600).toFixed(1)}h`;
}

/** The last path segment of a capture's absolute container path -- what
 * `GET /captures/{name}` takes. It refuses anything but a basename, so
 * sending the full path would just 404. */
export function captureName(wavPath: string | null): string | null {
  if (!wavPath) return null;
  const name = wavPath.split("/").pop();
  return name || null;
}

export function serviceLabel(service: string): string {
  return service.replace(/_/g, "-");
}
