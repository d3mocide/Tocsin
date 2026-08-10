import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { el } from "../dom";
import { apiSource, isActive, rfSource, tierOf } from "../format";
import type { Store } from "../store";
import type { Alert } from "../types";
import { NWS_ZONES } from "./zone_data";

const FIPS_TO_ZONES: Record<string, string[]> = {
  "041051": ["ORZ111", "ORZ112", "ORZ113"], // Multnomah, OR
  "041067": ["ORZ109", "ORZ110"],           // Washington, OR
  "041005": ["ORZ113", "ORZ123"],           // Clackamas, OR
  "041009": ["ORZ108"],                     // Columbia, OR
  "041071": ["ORZ110", "ORZ114"],           // Yamhill, OR
  "041047": ["ORZ115", "ORZ124"],           // Marion, OR
  "041053": ["ORZ114"],                     // Polk, OR
  "53011":  ["WAZ205", "WAZ206", "WAZ207"], // Clark, WA
  "53015":  ["WAZ204"],                     // Cowlitz, WA
  "53059":  ["WAZ208", "WAZ209"],           // Skamania, WA
};

export class MapView {
  private readonly container: HTMLElement;
  private readonly store: Store;
  private map: L.Map | null = null;
  private zoneGroup: L.LayerGroup | null = null;
  private stationGroup: L.LayerGroup | null = null;
  private radarLayer: L.TileLayer | null = null;
  private showRadar = false;
  private tileStatus = "Live";

  constructor(container: HTMLElement, store: Store) {
    this.container = container;
    this.store = store;
  }

  render(): void {
    if (!this.map) {
      this.initMap();
    }
    this.updateLayers();
  }

  private initMap(): void {
    this.container.innerHTML = "";

    const checkbox = el("input", {
      class: "map-checkbox",
      attrs: { type: "checkbox", id: "map-radar-toggle" },
    }) as HTMLInputElement;

    checkbox.addEventListener("change", () => {
      this.showRadar = checkbox.checked;
      this.toggleRadar();
    });

    const controls = el(
      "div",
      { class: "map-controls-bar" },
      el(
        "label",
        { class: "map-toggle-label", attrs: { for: "map-radar-toggle" } },
        checkbox,
        el("span", { text: " NEXRAD Radar Overlay" })
      ),
      el("div", { class: "map-status-pill", text: `Tiles: ${this.tileStatus}` })
    );

    const mapDiv = el("div", { class: "map-canvas", attrs: { id: "leaflet-map-canvas" } });
    this.container.appendChild(controls);
    this.container.appendChild(mapDiv);

    // Default center on Portland Metro
    this.map = L.map(mapDiv, {
      center: [45.52, -122.67],
      zoom: 9,
      zoomControl: true,
      attributionControl: false,
    });

    // Dark Carto tiles
    const tileUrl = "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png";
    const tiles = L.tileLayer(tileUrl, {
      maxZoom: 18,
      subdomains: "abcd",
    });

    tiles.on("tileerror", () => {
      this.tileStatus = "Offline (Vector Mode)";
      const statusEl = this.container.querySelector(".map-status-pill");
      if (statusEl) statusEl.textContent = `Tiles: ${this.tileStatus}`;
    });

    tiles.addTo(this.map);

    this.zoneGroup = L.layerGroup().addTo(this.map);
    this.stationGroup = L.layerGroup().addTo(this.map);

    setTimeout(() => this.map?.invalidateSize(), 200);
  }

  public invalidateSize(): void {
    if (this.map) {
      setTimeout(() => this.map?.invalidateSize(), 100);
    }
  }

  private toggleRadar(): void {
    if (!this.map) return;
    if (this.showRadar) {
      if (!this.radarLayer) {
        // Iowa State IEM WMS Radar Overlay
        this.radarLayer = L.tileLayer(
          "https://mesonet.agron.iastate.edu/cache/tile.py/1.0.0/nexrad-n0q-900913/{z}/{x}/{y}.png",
          { opacity: 0.5, maxZoom: 18 }
        );
      }
      this.radarLayer.addTo(this.map);
    } else if (this.radarLayer) {
      this.map.removeLayer(this.radarLayer);
    }
  }

  private updateLayers(): void {
    if (!this.map || !this.zoneGroup || !this.stationGroup) return;

    this.zoneGroup.clearLayers();
    this.stationGroup.clearLayers();

    const alertsMap = this.store.state.alerts;
    const alerts: Alert[] = alertsMap ? Array.from(alertsMap.values()) : [];
    const reference = this.store.state.reference;
    const stations = reference?.stations ?? {};

    // Map active alerts by UGC codes or mapped FIPS codes
    const activeZoneAlerts: Record<string, { count: number; highestTier: string; titles: string[] }> = {};

    for (const alert of alerts) {
      if (!isActive(alert)) continue;

      const tier = tierOf(alert, reference);
      const cap = apiSource(alert);
      const rf = rfSource(alert);

      const ugcCodes = cap?.ugc_codes ?? [];
      const sameCodes = alert.fips_codes ?? rf?.fips_codes ?? cap?.same_codes ?? [];

      const targetZones = new Set<string>();
      for (const code of ugcCodes) targetZones.add(code);
      for (const fips of sameCodes) {
        const mapped = FIPS_TO_ZONES[fips];
        if (mapped) {
          for (const z of mapped) targetZones.add(z);
        }
      }

      for (const code of targetZones) {
        if (!activeZoneAlerts[code]) {
          activeZoneAlerts[code] = { count: 0, highestTier: "NONE", titles: [] };
        }
        activeZoneAlerts[code].count += 1;
        if (!activeZoneAlerts[code].titles.includes(alert.event_name)) {
          activeZoneAlerts[code].titles.push(alert.event_name);
        }

        if (tier === "A" || activeZoneAlerts[code].highestTier === "A") {
          activeZoneAlerts[code].highestTier = "A";
        } else if (tier === "B" || activeZoneAlerts[code].highestTier === "B") {
          activeZoneAlerts[code].highestTier = "B";
        } else if (tier === "C" && activeZoneAlerts[code].highestTier !== "A" && activeZoneAlerts[code].highestTier !== "B") {
          activeZoneAlerts[code].highestTier = "C";
        }
      }
    }

    // 1. Draw Active Weather Advisory / Watch / Warning Areas ONLY
    let activePolygonCount = 0;
    for (const [code, geo] of Object.entries(NWS_ZONES)) {
      const alertState = activeZoneAlerts[code];
      if (!alertState) continue; // Skip quiet zones -- do NOT render empty NWS zone boxes!

      activePolygonCount += 1;

      let color = "#ef4444";
      let fillColor = "#ef4444";
      let fillOpacity = 0.40;
      let weight = 2.5;

      if (alertState.highestTier === "A") {
        color = "#ef4444";
        fillColor = "#ef4444";
        fillOpacity = 0.42;
        weight = 2.5;
      } else if (alertState.highestTier === "B") {
        color = "#f97316";
        fillColor = "#f97316";
        fillOpacity = 0.35;
        weight = 2.0;
      } else if (alertState.highestTier === "C") {
        color = "#eab308";
        fillColor = "#eab308";
        fillOpacity = 0.30;
        weight = 2.0;
      }

      const polygon = L.polygon(geo.polygon as [number, number][], {
        color,
        fillColor,
        fillOpacity,
        weight,
      });

      const popupContent = `
        <div class="map-popup">
          <div class="map-popup-title">⚠️ ${alertState.titles.join(", ")}</div>
          <div class="map-popup-sub">
            <b>Zone:</b> ${code} (${geo.name})<br/>
            <b>Severity:</b> <span class="badge badge-tier-${alertState.highestTier.toLowerCase()}">Tier ${alertState.highestTier}</span>
          </div>
        </div>
      `;

      polygon.bindPopup(popupContent);
      polygon.bindTooltip(`⚠️ ${alertState.titles.join(", ")} (${geo.name})`, { sticky: true });
      this.zoneGroup.addLayer(polygon);
    }

    // Update map status pill
    const statusEl = this.container.querySelector(".map-status-pill");
    if (statusEl) {
      statusEl.textContent = `Active Advisories: ${activePolygonCount} | Tiles: ${this.tileStatus}`;
    }

    // Determine active receiver channels from store
    const activeStreams = this.store.state.streams?.streams ?? [];
    const activeHealth = Array.from(this.store.state.health.values());
    const activeSites = new Set<string>();

    for (const s of activeStreams) {
      if (s.on_air || s.feeder_alive) {
        if (s.site) activeSites.add(s.site.toUpperCase());
      }
    }
    for (const h of activeHealth) {
      if (!h.dead && h.site) {
        activeSites.add(h.site.toUpperCase());
      }
    }

    // 2. Draw NWR Radio Transmitters
    for (const [callsign, station] of Object.entries(stations)) {
      if (station.lat === null || station.lon === null) continue;

      const distMiles = station.distance_miles ?? (station.distance_km !== null ? station.distance_km * 0.621371 : null);
      if (distMiles !== null && distMiles > 150) continue;

      const isNormal = station.status.toUpperCase() === "NORMAL";
      // Gate active pulse ring to stations actively monitored by the receiver site
      const isMonitored = isNormal && (
        (distMiles !== null && distMiles <= 15) ||
        activeSites.has(callsign.toUpperCase()) ||
        activeSites.has(station.name.toUpperCase())
      );

      const statusClass = isNormal
        ? (isMonitored ? "tower-icon-active" : "tower-icon-normal")
        : "tower-icon-abnormal";
      const markerColor = isNormal ? (isMonitored ? "#22c55e" : "#16a34a") : "#ef4444";

      const towerIcon = L.divIcon({
        className: "custom-tower-marker-container",
        html: `
          <div class="tower-marker ${statusClass}">
            ${isMonitored ? '<div class="tower-pulse"></div>' : ""}
            <div class="tower-dot"></div>
          </div>
        `,
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      });

      const marker = L.marker([station.lat, station.lon], { icon: towerIcon });

      const distStr = station.distance_km !== null ? `${station.distance_km.toFixed(1)} km away` : "";

      const popupHtml = `
        <div class="map-popup">
          <div class="map-popup-title">📻 ${station.name} (${callsign}) ${isMonitored ? '<span class="badge badge-tier-a" style="font-size:0.65rem;margin-left:0.3rem;">📡 MONITORED</span>' : ""}</div>
          <div class="map-popup-sub">
            <b>${station.frequency_mhz.toFixed(3)} MHz</b> · WFO ${station.wfo}<br/>
            Power: ${station.power_watts ?? 0}W · Status: <span style="color:${markerColor}">${station.status}</span><br/>
            ${distStr ? `<b>${distStr}</b>` : ""}
          </div>
        </div>
      `;

      marker.bindPopup(popupHtml);
      marker.bindTooltip(`📻 NWR ${callsign} (${station.name})${isMonitored ? " [Monitored]" : ""}`, { direction: "top" });
      this.stationGroup.addLayer(marker);
    }
  }
}
