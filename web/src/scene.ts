/** What the ASCII backdrop should depict. Two independent inputs: the sky
 * (from the NWS forecast, hybrid mode only) and the alarm level (from live
 * alerts, works offgrid). */

export type Sky = "clear" | "cloudy" | "fog" | "rain" | "snow" | "storm" | "wind";
export type Alarm = "calm" | "watch" | "warning";

export interface Scene {
  sky: Sky;
  alarm: Alarm;
}

const scene: Scene = { sky: "clear", alarm: "calm" };
const listeners = new Set<(s: Scene) => void>();

export function currentScene(): Readonly<Scene> {
  return scene;
}

export function onScene(fn: (s: Scene) => void): void {
  listeners.add(fn);
}

export function setScene(patch: Partial<Scene>): void {
  const next = { ...scene, ...patch };
  if (next.sky === scene.sky && next.alarm === scene.alarm) return;
  Object.assign(scene, next);
  for (const fn of listeners) fn(scene);
}

export function skyFromForecast(shortForecast: string | undefined): Sky {
  const text = (shortForecast ?? "").toLowerCase();
  if (/thunder|t-storm|tornado/.test(text)) return "storm";
  if (/snow|flurr|sleet|blizzard|freezing/.test(text)) return "snow";
  if (/rain|shower|drizzle/.test(text)) return "rain";
  if (/fog|haze|smoke|mist/.test(text)) return "fog";
  if (/wind|breezy|gust/.test(text)) return "wind";
  if (/cloud|overcast/.test(text)) return "cloudy";
  return "clear";
}

export interface WeatherNow {
  temp: number;
  unit: string;
  short: string;
  wind: string;
  place: string | null;
}

let weatherNow: WeatherNow | null = null;

export function getWeatherNow(): WeatherNow | null {
  return weatherNow;
}

export function setWeatherNow(next: WeatherNow): void {
  weatherNow = next;
}
