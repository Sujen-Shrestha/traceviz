import type { Hop } from "../types";

export interface MapPoint {
  hops: number[];
  lat: number;
  lon: number;
  label: string;
  approximate: boolean;
}

export function mapPoints(hops: Hop[]): MapPoint[] {
  const points: MapPoint[] = [];
  for (const h of hops) {
    const g = h.geo;
    if (!g || g.status !== "geo" || g.lat === null || g.lon === null) continue;
    const prev = points.at(-1);
    if (prev && prev.lat === g.lat && prev.lon === g.lon) {
      prev.hops.push(h.hop);
      prev.approximate ||= g.approximate;
      continue;
    }
    const label = [g.city, g.country].filter(Boolean).join(", ") || (g.country_name ?? "");
    points.push({ hops: [h.hop], lat: g.lat, lon: g.lon, label, approximate: g.approximate });
  }
  return points;
}
