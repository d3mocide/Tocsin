import type { Plugin } from "vite";

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
        const path = url.pathname;

        // Skip non-API routes or requests handled by static files
        if (!path.startsWith("/alerts") &&
            !path.startsWith("/health") &&
            !path.startsWith("/spectrum") &&
            !path.startsWith("/stats") &&
            !path.startsWith("/services") &&
            !path.startsWith("/system") &&
            !path.startsWith("/streams") &&
            !path.startsWith("/reference") &&
            !path.startsWith("/transcripts") &&
            !path.startsWith("/dispatches") &&
            !path.startsWith("/events") &&
            !path.startsWith("/captures")) {
          return next();
        }

        // SSE live event stream
        if (path === "/events") {
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

        if (path === "/system") {
          return res.end(JSON.stringify({
            mode: "hybrid",
            icecast_public_url: null,
            icecast_port: 8000,
            captures_available: true,
          }));
        }

        if (path === "/reference") {
          return res.end(JSON.stringify({
            event_codes: {
              TOR: { name: "Tornado Warning", tier: "A" },
              SVR: { name: "Severe Thunderstorm Warning", tier: "A" },
              FFW: { name: "Flash Flood Warning", tier: "A" },
              AQA: { name: "Air Quality Alert", tier: "B" },
              RWT: { name: "Required Weekly Test", tier: "C" },
            },
            counties: {
              "041051": { county: "Multnomah", state: "OR" },
              "041005": { county: "Clackamas", state: "OR" },
              "041067": { county: "Washington", state: "OR" },
              "053011": { county: "Clark", state: "WA" },
            },
            stations: {
              "PDX - WX5": { name: "Portland (WX5)", frequency_mhz: 162.55, status: "operational", wfo: "PQR", power_watts: 1000, lat: 45.515, lon: -122.678, distance_km: 12.4 },
              "PDX - WX6": { name: "Portland (WX6)", frequency_mhz: 162.525, status: "operational", wfo: "PQR", power_watts: 1000, lat: 45.520, lon: -122.680, distance_km: 14.1 },
              "PDX - WX7": { name: "Portland (WX7)", frequency_mhz: 162.40, status: "operational", wfo: "PQR", power_watts: 1000, lat: 45.510, lon: -122.670, distance_km: 15.8 },
            },
          }));
        }

        if (path === "/stats") {
          return res.end(JSON.stringify({
            counts: { CONFIRMED: 1, RF_ONLY: 1, API_ONLY: 2 },
            total: 4,
            divergence_rate: 0.75,
            dispatch: { sent: 3, skipped: 1, by_reason: { duplicate: 1 }, since_seconds: 86400 },
          }));
        }

        if (path === "/services") {
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

        if (path === "/streams") {
          return res.end(JSON.stringify({
            icecast_reachable: true,
            streams: [
              { mount: "/pdx-wx5.ogg", site: "PDX", channel: "WX5", feeder_alive: true, url: "#mock-wx5", on_air: true, listeners: 1, stream_name: "Tocsin PDX WX5" },
              { mount: "/pdx-wx6.ogg", site: "PDX", channel: "WX6", feeder_alive: true, url: "#mock-wx6", on_air: true, listeners: 0, stream_name: "Tocsin PDX WX6" },
              { mount: "/pdx-wx7.ogg", site: "PDX", channel: "WX7", feeder_alive: true, url: "#mock-wx7", on_air: true, listeners: 2, stream_name: "Tocsin PDX WX7" },
            ],
          }));
        }

        if (path === "/health") {
          return res.end(JSON.stringify([
            { site: "PDX", channel: "WX5", sampled_at: new Date().toISOString(), rms: 0.15, power: -42.0, dead: false },
            { site: "PDX", channel: "WX6", sampled_at: new Date().toISOString(), rms: 0.12, power: -46.0, dead: false },
            { site: "PDX", channel: "WX7", sampled_at: new Date().toISOString(), rms: 0.09, power: -52.0, dead: false },
          ]));
        }

        if (path === "/health/history") {
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

        if (path.startsWith("/spectrum")) {
          if (path === "/spectrum") {
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

        if (path.startsWith("/alerts")) {
          const mockAlerts = [
            {
              id: "urn:oid:2.49.0.1.840.0.mock.tor.001",
              state: "CONFIRMED",
              confidence: 1.0,
              event_name: "Tornado Warning",
              fips_codes: ["041051", "041005"],
              first_seen: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
              last_updated: new Date(Date.now() - 4 * 60 * 1000).toISOString(),
              sources: [
                {
                  kind: "RF",
                  event: {
                    site: "PDX",
                    channel: "WX5",
                    received_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
                    event_code: "TOR",
                    event_name: "Tornado Warning",
                    tier: "A",
                    fips_codes: ["041051", "041005"],
                    originator: "WXR",
                    callsign: "KIG98",
                    purge_minutes: 45,
                    raw_header: "ZCZC-WXR-TOR-041051-041005+0045-2212130-KIG98/NWR-",
                  },
                },
                {
                  kind: "API",
                  alert: {
                    id: "urn:oid:2.49.0.1.840.0.mock.tor.001",
                    event: "Tornado Warning",
                    headline: "Tornado Warning issued August 09 at 2:25PM PDT until 3:10PM PDT by NWS Portland OR",
                    status: "Actual",
                    message_type: "Alert",
                    category: "Met",
                    severity: "Extreme",
                    certainty: "Observed",
                    urgency: "Immediate",
                    area_desc: "Multnomah, OR; Clackamas, OR",
                    sent: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
                    effective: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
                    onset: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
                    expires: new Date(Date.now() + 40 * 60 * 1000).toISOString(),
                    ends: new Date(Date.now() + 40 * 60 * 1000).toISOString(),
                    same_codes: ["041051", "041005"],
                    ugc_codes: ["ORZ006"],
                    vtec: "/O.NEW.KPQR.TO.W.0012.260809T2125Z-260809T2210Z/",
                  },
                },
              ],
            },
            {
              id: "urn:oid:2.49.0.1.840.0.mock.svr.002",
              state: "RF_ONLY",
              confidence: 0.85,
              event_name: "Severe Thunderstorm Warning",
              fips_codes: ["041051"],
              first_seen: new Date(Date.now() - 15 * 60 * 1000).toISOString(),
              last_updated: new Date(Date.now() - 15 * 60 * 1000).toISOString(),
              sources: [
                {
                  kind: "RF",
                  event: {
                    site: "PDX",
                    channel: "WX5",
                    received_at: new Date(Date.now() - 15 * 60 * 1000).toISOString(),
                    event_code: "SVR",
                    event_name: "Severe Thunderstorm Warning",
                    tier: "A",
                    fips_codes: ["041051"],
                    originator: "WXR",
                    callsign: "KIG98",
                    purge_minutes: 60,
                    raw_header: "ZCZC-WXR-SVR-041051+0100-2212115-KIG98/NWR-",
                  },
                },
              ],
            },
            {
              id: "urn:oid:2.49.0.1.840.0.mock.aqa.003",
              state: "API_ONLY",
              confidence: 0.7,
              event_name: "Air Quality Alert",
              fips_codes: ["041051", "041005"],
              first_seen: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
              last_updated: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
              sources: [
                {
                  kind: "API",
                  alert: {
                    id: "urn:oid:2.49.0.1.840.0.mock.aqa.003",
                    event: "Air Quality Alert",
                    headline: "Air Quality Alert in effect until 5:00PM PDT Monday for Portland Metro area",
                    status: "Actual",
                    message_type: "Alert",
                    category: "Env",
                    severity: "Moderate",
                    certainty: "Unknown",
                    urgency: "Unknown",
                    area_desc: "Multnomah, OR; Clackamas, OR",
                    sent: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
                    effective: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
                    onset: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
                    expires: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
                    ends: new Date(Date.now() + 24 * 3600 * 1000).toISOString(),
                    same_codes: ["041051", "041005"],
                    ugc_codes: ["ORZ006"],
                    vtec: null,
                  },
                },
              ],
            },
          ];
          return res.end(JSON.stringify(mockAlerts));
        }

        if (path.startsWith("/transcripts")) {
          return res.end(JSON.stringify([
            {
              raw_header: "ZCZC-WXR-TOR-041051-041005+0045-2212130-KIG98/NWR-",
              timestamp_ns: Date.now() * 1_000_000,
              site: "PDX",
              channel: "WX5",
              event_code: "TOR",
              tier: "A",
              fips_codes: ["041051", "041005"],
              text: "The National Weather Service in Portland has issued a Tornado Warning for Multnomah and Clackamas County until 3:10 PM PDT. Take cover immediately.",
              passed_guard: true,
              guard_reason: null,
              wav_path: "mock_capture_tor.wav",
            },
          ]));
        }

        if (path.startsWith("/dispatches")) {
          return res.end(JSON.stringify([
            {
              dispatched_at: new Date(Date.now() - 4 * 60 * 1000).toISOString(),
              stage: "stage_1",
              alert_id: "urn:oid:2.49.0.1.840.0.mock.tor.001",
              site: "PDX",
              channel: "WX5",
              event_code: "TOR",
              tier: "A",
              fips_codes: ["041051", "041005"],
              raw_header: "ZCZC-WXR-TOR-041051-041005+0045-2212130-KIG98/NWR-",
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
