import fs from "node:fs";
import path from "node:path";
import type { Plugin } from "vite";

function parseStationsYaml(content: string): Record<string, any> {
  const stations: Record<string, any> = {};
  let currentCallsign: string | null = null;
  for (const line of content.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    if (line.match(/^[A-Z0-9_-]+:\s*$/)) {
      currentCallsign = line.split(":")[0].trim();
      stations[currentCallsign] = {};
    } else if (currentCallsign && line.startsWith("  ")) {
      const parts = trimmed.split(":");
      if (parts.length >= 2) {
        const key = parts[0].trim();
        const valStr = parts.slice(1).join(":").trim();
        let val: any = valStr;
        if (valStr === "null") val = null;
        else if (!isNaN(Number(valStr))) val = Number(valStr);
        stations[currentCallsign][key] = val;
      }
    }
  }
  return stations;
}

/**
 * Vite plugin that serves mock data for UI development when no backend API is running.
 * Provides realistic alerts, health metrics, spectrum snapshots, services, and live SSE event streams.
 */
export function mockApiPlugin(): Plugin {
  return {
    name: "tocsin-mock-api",
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);
        const reqPath = url.pathname;

        // Skip non-API routes or requests handled by static files
        if (!reqPath.startsWith("/alerts") &&
            !reqPath.startsWith("/health") &&
            !reqPath.startsWith("/spectrum") &&
            !reqPath.startsWith("/stats") &&
            !reqPath.startsWith("/services") &&
            !reqPath.startsWith("/system") &&
            !reqPath.startsWith("/streams") &&
            !reqPath.startsWith("/reference") &&
            !reqPath.startsWith("/transcripts") &&
            !reqPath.startsWith("/dispatches") &&
            !reqPath.startsWith("/events") &&
            !reqPath.startsWith("/captures")) {
          return next();
        }

        // SSE live event stream
        if (reqPath === "/events") {
          res.writeHead(200, {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            Connection: "keep-alive",
          });
          res.write("event: open\ndata: {}\n\n");

          const interval = setInterval(() => {
            const mockHealth = {
              site: "PDX",
              channel: "WX5",
              sampled_at: new Date().toISOString(),
              rms: 0.12 + Math.random() * 0.05,
              power: -45.0 + Math.random() * 2,
              dead: false,
            };
            res.write(`event: health\ndata: ${JSON.stringify(mockHealth)}\n\n`);
          }, 3000);

          req.on("close", () => clearInterval(interval));
          return;
        }

        res.setHeader("Content-Type", "application/json");

        if (reqPath === "/system") {
          return res.end(JSON.stringify({
            mode: "hybrid",
            icecast_public_url: null,
            icecast_port: 8000,
            captures_available: true,
            // Downtown Portland, so the forecast, map marker and sky have a location to work with.
            latitude: 45.5152,
            longitude: -122.6784,
          }));
        }

        if (reqPath === "/reference") {
          const cwd = process.cwd();
          const stationsDir = path.resolve(cwd, "../data/nwr_stations");
          const fallbackYaml = path.resolve(cwd, "../data/nwr_stations.yaml");
          const legacyYaml = path.resolve(cwd, "../data/nwr_stations_or.yaml");
          let stations: Record<string, any> = {};

          try {
            if (fs.existsSync(stationsDir) && fs.statSync(stationsDir).isDirectory()) {
              const files = fs.readdirSync(stationsDir).filter((f) => f.endsWith(".yaml"));
              for (const f of files) {
                const text = fs.readFileSync(path.join(stationsDir, f), "utf-8");
                Object.assign(stations, parseStationsYaml(text));
              }
            }
            if (Object.keys(stations).length === 0) {
              const fileToRead = fs.existsSync(fallbackYaml) ? fallbackYaml : fs.existsSync(legacyYaml) ? legacyYaml : null;
              if (fileToRead) {
                const text = fs.readFileSync(fileToRead, "utf-8");
                stations = parseStationsYaml(text);
              }
            }
          } catch (e) {
            console.error("mock-plugin: failed to load stations", e);
          }

          const opLat = 45.385313;
          const opLon = -122.756285;
          for (const s of Object.values(stations)) {
            if (s.lat != null && s.lon != null) {
              const R = 6371;
              const dLat = (s.lat - opLat) * Math.PI / 180;
              const dLon = (s.lon - opLon) * Math.PI / 180;
              const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
                        Math.cos(opLat * Math.PI / 180) * Math.cos(s.lat * Math.PI / 180) *
                        Math.sin(dLon/2) * Math.sin(dLon/2);
              const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
              s.distance_km = Math.round(R * c * 10) / 10;
              s.distance_miles = Math.round(s.distance_km * 0.621371 * 10) / 10;
            } else {
              s.distance_km = null;
              s.distance_miles = null;
            }
          }

          return res.end(JSON.stringify({
            event_codes: {
              TOR: { name: "Tornado Warning", tier: "A" },
              SVR: { name: "Severe Thunderstorm Warning", tier: "A" },
              FFW: { name: "Flash Flood Warning", tier: "A" },
              HWW: { name: "High Wind Warning", tier: "B" },
              FLA: { name: "Flood Watch", tier: "B" },
              AQA: { name: "Air Quality Alert", tier: "B" },
              RWT: { name: "Required Weekly Test", tier: "C" },
            },
            counties: {
              "41051": { county: "Multnomah", state: "OR" },
              "41005": { county: "Clackamas", state: "OR" },
              "41067": { county: "Washington", state: "OR" },
              "053011": { county: "Clark", state: "WA" },
            },
            stations,
          }));
        }

        if (reqPath === "/stats") {
          return res.end(JSON.stringify({
            counts: { CONFIRMED: 1, RF_ONLY: 1, API_ONLY: 2 },
            total: 4,
            divergence_rate: 0.75,
            dispatch: { sent: 3, skipped: 1, by_reason: { duplicate: 1 }, since_seconds: 86400 },
          }));
        }

        if (reqPath === "/services") {
          const now = new Date().toISOString();
          return res.end(JSON.stringify([
            { service: "sdr-rx", status: "up", expected: true, updated_at: now, age_seconds: 2, detail: { devices: 1 } },
            { service: "same-decoder", status: "up", expected: true, updated_at: now, age_seconds: 3, detail: {} },
            { service: "live-audio", status: "up", expected: true, updated_at: now, age_seconds: 2, detail: {} },
            { service: "segment-capture", status: "up", expected: true, updated_at: now, age_seconds: 1, detail: {} },
            { service: "stt-worker", status: "up", expected: true, updated_at: now, age_seconds: 1, detail: { model: "ggml-base.en.bin", chain: "local,remote" } },
            { service: "fusion", status: "up", expected: true, updated_at: now, age_seconds: 2, detail: {} },
            { service: "dispatcher", status: "up", expected: true, updated_at: now, age_seconds: 3, detail: {} },
            { service: "api", status: "up", expected: true, updated_at: now, age_seconds: 1, detail: {} },
            { service: "nws-poller", status: "up", expected: true, updated_at: now, age_seconds: 15, detail: { last_success: now } },
          ]));
        }

        if (reqPath === "/streams") {
          return res.end(JSON.stringify({
            icecast_reachable: true,
            streams: [
              { mount: "/pdx-wx5.ogg", site: "PDX", channel: "WX5", feeder_alive: true, url: "#mock-wx5", on_air: true, listeners: 1, stream_name: "Tocsin PDX WX5" },
              { mount: "/pdx-wx6.ogg", site: "PDX", channel: "WX6", feeder_alive: true, url: "#mock-wx6", on_air: true, listeners: 0, stream_name: "Tocsin PDX WX6" },
              { mount: "/pdx-wx7.ogg", site: "PDX", channel: "WX7", feeder_alive: true, url: "#mock-wx7", on_air: true, listeners: 2, stream_name: "Tocsin PDX WX7" },
            ],
          }));
        }

        if (reqPath === "/health") {
          return res.end(JSON.stringify([
            { site: "PDX", channel: "WX5", sampled_at: new Date().toISOString(), rms: 0.15, power: -42.0, dead: false },
            { site: "PDX", channel: "WX6", sampled_at: new Date().toISOString(), rms: 0.12, power: -46.0, dead: false },
            { site: "PDX", channel: "WX7", sampled_at: new Date().toISOString(), rms: 0.09, power: -52.0, dead: false },
          ]));
        }

        if (reqPath === "/health/history") {
          const points = [];
          const now = Date.now();
          for (let i = 20; i >= 0; i--) {
            const time = new Date(now - i * 60 * 1000).toISOString();
            points.push(
              { site: "PDX", channel: "WX5", bucket: time, rms: 0.14 + Math.sin(i / 2) * 0.02, power: -42.0, dead: false },
              { site: "PDX", channel: "WX6", bucket: time, rms: 0.11 + Math.cos(i / 2) * 0.02, power: -46.0, dead: false },
              { site: "PDX", channel: "WX7", bucket: time, rms: 0.08 + Math.sin(i / 3) * 0.01, power: -52.0, dead: false }
            );
          }
          return res.end(JSON.stringify(points));
        }

        if (reqPath.startsWith("/spectrum")) {
          if (reqPath === "/spectrum") {
            return res.end(JSON.stringify(["PDX"]));
          }
          // Synthetic 48-bin spectrum
          const bin_power_db = new Array(48).fill(0).map((_, idx) => {
            if (idx === 0 || idx === 7 || idx === 14) return -30.0 + (Math.random() * 4 - 2);
            return -95.0 + (Math.random() * 6 - 3);
          });
          const bin_frequencies_hz = new Array(48).fill(0).map((_, idx) => 162.400 + idx * 0.025);
          return res.end(JSON.stringify({
            site: "PDX",
            timestamp_ns: Date.now() * 1_000_000,
            bin_frequencies_hz,
            bin_power_db,
          }));
        }

        if (reqPath.startsWith("/alerts")) {
          // An atmospheric-river storm: a scenario that actually happens in the Pacific Northwest.
          const minutesAgo = (m: number) => new Date(Date.now() - m * 60 * 1000).toISOString();
          const minutesAhead = (m: number) => new Date(Date.now() + m * 60 * 1000).toISOString();
          const mockAlerts = [
            {
              id: "urn:oid:2.49.0.1.840.0.mock.ffw.001",
              state: "CONFIRMED",
              confidence: 1.0,
              event_name: "Flash Flood Warning",
              fips_codes: ["041051", "041005"],
              first_seen: minutesAgo(6),
              last_updated: minutesAgo(5),
              sources: [
                {
                  kind: "RF",
                  event: {
                    site: "PDX",
                    channel: "WX5",
                    received_at: minutesAgo(6),
                    event_code: "FFW",
                    event_name: "Flash Flood Warning",
                    tier: "A",
                    fips_codes: ["041051", "041005"],
                    originator: "WXR",
                    callsign: "KIG98",
                    purge_minutes: 90,
                    raw_header: "ZCZC-WXR-FFW-041051-041005+0130-2891025-KIG98/NWR-",
                  },
                },
                {
                  kind: "API",
                  alert: {
                    id: "urn:oid:2.49.0.1.840.0.mock.ffw.001",
                    event: "Flash Flood Warning",
                    headline: "Flash Flood Warning in effect until 1:30 PM PDT for Multnomah and Clackamas Counties",
                    status: "Actual",
                    message_type: "Alert",
                    category: "Met",
                    severity: "Severe",
                    certainty: "Likely",
                    urgency: "Immediate",
                    area_desc: "Multnomah, OR; Clackamas, OR",
                    sent: minutesAgo(6),
                    effective: minutesAgo(6),
                    onset: minutesAgo(6),
                    expires: minutesAhead(84),
                    ends: minutesAhead(84),
                    same_codes: ["041051", "041005"],
                    ugc_codes: ["ORC005"],
                    // Storm-based polygon over southeast Portland and northern Clackamas County.
                    geometry: {
                      type: "Polygon",
                      coordinates: [[[-122.62, 45.33], [-122.36, 45.36], [-122.3, 45.52], [-122.55, 45.58], [-122.7, 45.46], [-122.62, 45.33]]],
                    },
                    vtec: "/O.NEW.KPQR.FF.W.0007.261016T1725Z-261016T2030Z/",
                  },
                },
              ],
            },
            {
              id: "urn:oid:2.49.0.1.840.0.mock.hww.002",
              state: "RF_ONLY",
              confidence: 0.85,
              event_name: "High Wind Warning",
              fips_codes: ["041067"],
              first_seen: minutesAgo(22),
              last_updated: minutesAgo(22),
              sources: [
                {
                  kind: "RF",
                  event: {
                    site: "PDX",
                    channel: "WX5",
                    received_at: minutesAgo(22),
                    event_code: "HWW",
                    event_name: "High Wind Warning",
                    tier: "B",
                    fips_codes: ["041067"],
                    originator: "WXR",
                    callsign: "KIG98",
                    purge_minutes: 120,
                    raw_header: "ZCZC-WXR-HWW-041067+0200-2891008-KIG98/NWR-",
                  },
                },
              ],
            },
            {
              id: "urn:oid:2.49.0.1.840.0.mock.fla.003",
              state: "API_ONLY",
              confidence: 0.7,
              event_name: "Flood Watch",
              fips_codes: ["041051", "041005", "041067"],
              first_seen: minutesAgo(180),
              last_updated: minutesAgo(180),
              sources: [
                {
                  kind: "API",
                  alert: {
                    id: "urn:oid:2.49.0.1.840.0.mock.fla.003",
                    event: "Flood Watch",
                    headline: "Flood Watch in effect through Saturday morning for the Portland Metro area",
                    status: "Actual",
                    message_type: "Alert",
                    category: "Met",
                    severity: "Moderate",
                    certainty: "Possible",
                    urgency: "Future",
                    area_desc: "Multnomah, OR; Clackamas, OR; Washington, OR",
                    sent: minutesAgo(180),
                    effective: minutesAgo(180),
                    onset: minutesAgo(180),
                    expires: minutesAhead(26 * 60),
                    ends: minutesAhead(26 * 60),
                    same_codes: ["041051", "041005", "041067"],
                    ugc_codes: ["ORZ006"],
                    vtec: null,
                  },
                },
              ],
            },
          ];
          return res.end(JSON.stringify(mockAlerts));
        }

        if (reqPath.startsWith("/transcripts")) {
          return res.end(JSON.stringify([
            {
              raw_header: "ZCZC-WXR-FFW-041051-041005+0130-2891025-KIG98/NWR-",
              timestamp_ns: Date.now() * 1_000_000,
              site: "PDX",
              channel: "WX5",
              event_code: "FFW",
              tier: "A",
              fips_codes: ["041051", "041005"],
              text: "The National Weather Service in Portland has issued a Flash Flood Warning for Multnomah and Clackamas County until 1:30 PM PDT. Heavy rain is causing flooding of streams and low-lying roads. Turn around, don't drown.",
              passed_guard: true,
              guard_reason: null,
              wav_path: "mock_capture_ffw.wav",
            },
          ]));
        }

        if (reqPath.startsWith("/dispatches")) {
          return res.end(JSON.stringify([
            {
              dispatched_at: new Date(Date.now() - 4 * 60 * 1000).toISOString(),
              stage: "stage_1",
              alert_id: "urn:oid:2.49.0.1.840.0.mock.ffw.001",
              site: "PDX",
              channel: "WX5",
              event_code: "FFW",
              tier: "A",
              fips_codes: ["041051", "041005"],
              raw_header: "ZCZC-WXR-FFW-041051-041005+0130-2891025-KIG98/NWR-",
              sent: true,
              reason: "sent over serial mesh",
            },
          ]));
        }

        next();
      });
    },
  };
}
