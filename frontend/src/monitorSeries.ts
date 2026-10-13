import type { SessionMessage } from "./types";

export interface HopSeries {
  hop: number;
  label: string;
  values: (number | null)[];
}

export interface MonitorSeries {
  times: number[];
  hops: HopSeries[];
}

export const MAX_POINTS = 300;
const MIN_INTERVAL_S = 1;

export function emptySeries(): MonitorSeries {
  return { times: [], hops: [] };
}

/** Add one point per answering hop (its last RTT) at time `t` (unix seconds). */
export function appendSample(series: MonitorSeries, msg: SessionMessage, t: number): MonitorSeries {
  const lastTime = series.times.at(-1);
  if (lastTime !== undefined && t - lastTime < MIN_INTERVAL_S) return series;
  const previous = new Map(series.hops.map((h) => [h.hop, h]));
  const hops: HopSeries[] = msg.hops
    .filter((h) => h.ip !== null)
    .map((h) => {
      const history = previous.get(h.hop)?.values ?? new Array<number | null>(series.times.length).fill(null);
      return { hop: h.hop, label: `${h.hop}: ${h.hostname ?? h.ip}`, values: [...history, h.last_ms] };
    });
  for (const old of series.hops) {
    if (!hops.some((h) => h.hop === old.hop)) hops.push({ ...old, values: [...old.values, null] });
  }
  hops.sort((a, b) => a.hop - b.hop);
  const times = [...series.times, t];
  const drop = Math.max(0, times.length - MAX_POINTS);
  return { times: times.slice(drop), hops: hops.map((h) => ({ ...h, values: h.values.slice(drop) })) };
}
