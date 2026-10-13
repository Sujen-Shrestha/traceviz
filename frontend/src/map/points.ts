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

export interface MapCluster {
  hops: number[];
  lon: number;
  lat: number;
  x: number;
  y: number;
  label: string;
  title: string;
  approximate: boolean;
}

/** "7–10, 14–15" style hop list. */
export function formatHops(hops: number[]): string {
  const sorted = [...hops].sort((a, b) => a - b);
  const runs: string[] = [];
  let start = sorted[0];
  for (let i = 1; i <= sorted.length; i++) {
    if (i < sorted.length && sorted[i] === sorted[i - 1] + 1) continue;
    const end = sorted[i - 1];
    runs.push(start === end ? `${start}` : `${start}–${end}`);
    start = sorted[i];
  }
  return runs.join(", ");
}

/** Merge points that would overlap on screen (closer than `minDistance` projected pixels). */
export function clusterPoints(
  points: MapPoint[],
  project: (lonLat: [number, number]) => [number, number] | null,
  minDistance = 24,
): MapCluster[] {
  const clusters: (Omit<MapCluster, "label"> & { places: string[] })[] = [];
  for (const p of points) {
    const xy = project([p.lon, p.lat]);
    if (!xy) continue;
    const line = `Hop ${p.hops.join(", ")}: ${p.label}${p.approximate ? " (approximate)" : ""}`;
    const near = clusters.find((c) => Math.hypot(c.x - xy[0], c.y - xy[1]) < minDistance);
    if (near) {
      near.hops.push(...p.hops);
      if (!near.places.includes(p.label)) near.places.push(p.label);
      near.approximate ||= p.approximate;
      near.title += `\n${line}`;
      continue;
    }
    clusters.push({ hops: [...p.hops], lon: p.lon, lat: p.lat, x: xy[0], y: xy[1],
      places: [p.label], approximate: p.approximate, title: line });
  }
  return clusters.map(({ places, ...c }) => ({
    ...c,
    label: `${formatHops(c.hops)} ${places[0]}${places.length > 1 ? ` +${places.length - 1}` : ""}`,
  }));
}
