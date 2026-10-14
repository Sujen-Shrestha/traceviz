import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import type { MonitorSeries } from "../monitorSeries";

const COLORS = ["#4cc9f0", "#f72585", "#b5e48c", "#ffd166", "#9b5de5", "#00f5d4", "#f15bb5", "#fee440", "#ff8c42", "#8ecae6"];

function toData(series: MonitorSeries): uPlot.AlignedData {
  return [series.times, ...series.hops.map((h) => h.values)] as uPlot.AlignedData;
}

export function LatencyChart({ series }: { series: MonitorSeries }) {
  const container = useRef<HTMLDivElement>(null);
  const plot = useRef<uPlot | null>(null);
  const hopKey = series.hops.map((h) => h.hop).join(",");

  useEffect(() => {
    if (!container.current) return;
    const options: uPlot.Options = {
      width: container.current.clientWidth || 900,
      height: 260,
      scales: { x: { time: true } },
      axes: [{ stroke: "#9aa4b2" }, { stroke: "#9aa4b2", label: "ms" }],
      series: [{}, ...series.hops.map((h, i) => ({ label: h.label, stroke: COLORS[i % COLORS.length], width: 1.5 }))],
    };
    const el = container.current;
    plot.current = new uPlot(options, toData(series), el);
    // Follow the card's width when the window is resized.
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver((entries) => {
            const width = Math.round(entries[0]?.contentRect.width ?? 0);
            if (width > 0) plot.current?.setSize({ width, height: 260 });
          });
    observer?.observe(el);
    return () => {
      observer?.disconnect();
      plot.current?.destroy();
      plot.current = null;
    };
    // Rebuild only when the set of hops changes; data updates go through setData below.
  }, [hopKey]);

  useEffect(() => {
    plot.current?.setData(toData(series));
  }, [series]);

  return (
    <section className="card">
      <h2>Latency per hop</h2>
      <div ref={container} />
    </section>
  );
}
