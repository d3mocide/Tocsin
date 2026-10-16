// Dev-only (imported behind import.meta.env.DEV): scrub time of day, sky and
// alarm level to preview every backdrop without waiting for the weather.
import { sunPosition } from "./daylight";
import { setScene, type Alarm, type Sky } from "./scene";
import { refreshSky, setTimeOverride } from "./sky_clock";

const SKIES: Sky[] = ["clear", "cloudy", "fog", "rain", "snow", "storm", "wind"];
const ALARMS: Alarm[] = ["calm", "watch", "warning"];

const clockText = (h: number) =>
  `${String(Math.floor(h)).padStart(2, "0")}:${String(Math.round((h % 1) * 60)).padStart(2, "0")}`;

// Presets follow the sun (sunrise, solar noon, sunset, antipodal midnight) so
// they land correctly whatever timezone this browser is in.
function presets(): [string, number][] {
  const now = new Date();
  const lon = -now.getTimezoneOffset() / 4;
  const elev = (h: number) =>
    sunPosition(new Date(now.getFullYear(), now.getMonth(), now.getDate(), Math.floor(h), Math.round((h % 1) * 60)), 40, lon);
  let rise = 6;
  let set = 18;
  let noon = 12;
  let best = -90;
  for (let h = 0; h < 24; h += 0.05) {
    const a = elev(h);
    const b = elev(h + 0.05);
    if (a.elevation < 0 && b.elevation >= 0) rise = h;
    if (a.elevation >= 0 && b.elevation < 0) set = h;
    if (a.elevation > best) {
      best = a.elevation;
      noon = h;
    }
  }
  return [["Night", (noon + 12) % 24], ["Dawn", rise], ["Day", noon], ["Dusk", set]];
}

export function mountDevPanel(): void {
  const box = document.createElement("div");
  box.style.cssText =
    "position:fixed;left:12px;bottom:12px;z-index:9999;padding:10px 12px;border-radius:12px;" +
    "background:rgb(0 0 0 / 78%);border:1px solid rgb(255 255 255 / 18%);color:#eef1fb;" +
    "font:12px ui-monospace,monospace;display:grid;gap:6px;width:250px";
  const row = (...kids: Node[]) => {
    const r = document.createElement("div");
    r.style.cssText = "display:flex;gap:6px;align-items:center;flex-wrap:wrap";
    r.append(...kids);
    return r;
  };
  const button = (label: string, onClick: () => void) => {
    const b = document.createElement("button");
    b.textContent = label;
    b.style.cssText = "font:inherit;padding:2px 8px;border-radius:6px;cursor:pointer";
    b.addEventListener("click", onClick);
    return b;
  };
  const select = (options: string[], onChange: (v: string) => void) => {
    const s = document.createElement("select");
    s.style.cssText = "font:inherit";
    for (const o of options) s.add(new Option(o));
    s.addEventListener("change", () => onChange(s.value));
    return s;
  };

  const readout = document.createElement("div");
  const slider = document.createElement("input");
  slider.type = "range";
  slider.min = "0";
  slider.max = "24";
  slider.step = "0.05";
  slider.style.width = "100%";

  const show = () => {
    const now = new Date();
    const h = Number(slider.value);
    const when = new Date(now.getFullYear(), now.getMonth(), now.getDate(), Math.floor(h), Math.round((h % 1) * 60));
    setTimeOverride(when);
    refreshSky();
    const sun = sunPosition(when, 40, -when.getTimezoneOffset() / 4);
    readout.textContent = `sky time ${clockText(h)}  sun ${sun.elevation.toFixed(1)}° ${sun.morning ? "AM" : "PM"}`;
  };
  const live = () => {
    setTimeOverride(null);
    refreshSky();
    const n = new Date();
    slider.value = String(n.getHours() + n.getMinutes() / 60);
    readout.textContent = "sky time: live";
  };
  slider.addEventListener("input", show);

  const skyPick = select(SKIES, (v) => setScene({ sky: v as Sky }));
  const alarmPick = select(ALARMS, (v) => setScene({ alarm: v as Alarm }));
  box.append(
    readout,
    slider,
    row(...presets().map(([name, h]) => button(name, () => { slider.value = String(h); show(); })), button("Live", live)),
    row(document.createTextNode("sky"), skyPick, document.createTextNode("alarm"), alarmPick),
  );
  document.body.append(box);
  live();
}
