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

/**
 * Merge points that would overlap on screen (closer than `minDistance` projected pixels) into
 * clusters, joining each point to the nearest cluster in range. `route` lists cluster indexes in
 * hop order (repeats collapsed), so arcs follow the real path even when it returns to a cluster.
 */
export function clusterRoute(
  points: MapPoint[],
  project: (lonLat: [number, number]) => [number, number] | null,
  minDistance = 24,
): { clusters: MapCluster[]; route: number[] } {
  const clusters: (Omit<MapCluster, "label"> & { places: string[] })[] = [];
  const route: number[] = [];
  for (const p of points) {
    const xy = project([p.lon, p.lat]);
    if (!xy) continue;
    const line = `Hop ${p.hops.join(", ")}: ${p.label}${p.approximate ? " (approximate)" : ""}`;
    let nearest = -1;
    let nearestDistance = minDistance;
    clusters.forEach((c, i) => {
      const d = Math.hypot(c.x - xy[0], c.y - xy[1]);
      if (d < nearestDistance) {
        nearest = i;
        nearestDistance = d;
      }
    });
    if (nearest >= 0) {
      const c = clusters[nearest];
      c.hops.push(...p.hops);
      if (!c.places.includes(p.label)) c.places.push(p.label);
      c.approximate ||= p.approximate;
      c.title += `\n${line}`;
    } else {
      nearest = clusters.length;
      clusters.push({ hops: [...p.hops], lon: p.lon, lat: p.lat, x: xy[0], y: xy[1],
        places: [p.label], approximate: p.approximate, title: line });
    }
    if (route.at(-1) !== nearest) route.push(nearest);
  }
  return {
    clusters: clusters.map(({ places, ...c }) => ({
      ...c,
      label: `${formatHops(c.hops)} ${places[0]}${places.length > 1 ? ` +${places.length - 1}` : ""}`,
    })),
    route,
  };
}

export interface ZoomBox {
  width: number;
  height: number;
  padding: number;
  maxScale?: number;
}

/** Zoom transform (scale k, translate x/y) that frames the given projected points. */
export function fitTransform(points: [number, number][], box: ZoomBox): { k: number; x: number; y: number } {
  if (points.length === 0) return { k: 1, x: 0, y: 0 };
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const minSpan = 60; // a lone point (or a tight cluster) still shows its surroundings
  const w = Math.max(maxX - minX, minSpan);
  const h = Math.max(maxY - minY, minSpan);
  const fit = Math.min((box.width - 2 * box.padding) / w, (box.height - 2 * box.padding) / h);
  const k = Math.min(Math.max(fit, 1), box.maxScale ?? 40);
  if (k === 1) return { k: 1, x: 0, y: 0 };
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  return { k, x: box.width / 2 - k * cx, y: box.height / 2 - k * cy };
}

/** Map units per screen pixel, so markers/labels keep a constant on-screen size. */
export function markerScale(viewBoxWidth: number, renderedWidthPx: number): number {
  if (renderedWidthPx <= 0) return 1;
  return Math.min(Math.max(viewBoxWidth / renderedWidthPx, 0.25), 4);
}
