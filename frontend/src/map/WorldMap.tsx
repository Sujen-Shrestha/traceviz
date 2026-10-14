import { geoGraticule10, geoNaturalEarth1, geoPath } from "d3-geo";
import { select } from "d3-selection";
import { zoom, zoomIdentity, type ZoomBehavior, type ZoomTransform } from "d3-zoom";
import { useEffect, useMemo, useRef, useState } from "react";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";
import world from "world-atlas/countries-110m.json";
import type { Hop } from "../types";
import { clusterRoute, fitTransform, mapPoints, markerScale } from "./points";

const WIDTH = 960;
const HEIGHT = 500;
const MAX_ZOOM = 40;
const STEP = 1.5;

const topology = world as unknown as Topology<{ countries: GeometryCollection }>;
const land = feature(topology, topology.objects.countries);
const projection = geoNaturalEarth1().fitSize([WIDTH, HEIGHT], { type: "Sphere" });
const path = geoPath(projection);
const spherePath = path({ type: "Sphere" }) ?? "";
const graticulePath = path(geoGraticule10()) ?? "";
const landPath = path(land) ?? "";

interface Props {
  hops: Hop[];
  /** When this changes to a non-empty value, the map zooms to fit the route once. */
  autoFitKey?: string;
  /** When this changes, the zoom resets (a new session starts from the whole world). */
  resetKey?: string;
}

export function WorldMap({ hops, autoFitKey, resetKey }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const behavior = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const [transform, setTransform] = useState<ZoomTransform>(zoomIdentity);
  const [unitsPerPx, setUnitsPerPx] = useState(1);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver((entries) =>
      setUnitsPerPx(markerScale(WIDTH, entries[0]?.contentRect.width ?? 0)),
    );
    observer.observe(svg);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const z = zoom<SVGSVGElement, unknown>()
      .extent([[0, 0], [WIDTH, HEIGHT]])
      .scaleExtent([1, MAX_ZOOM])
      .translateExtent([[0, 0], [WIDTH, HEIGHT]])
      .on("zoom", (event: { transform: ZoomTransform }) => setTransform(event.transform));
    behavior.current = z;
    select(svg).call(z);
    return () => {
      select(svg).on(".zoom", null);
    };
  }, []);

  const points = useMemo(() => mapPoints(hops), [hops]);
  // Cluster in screen space so markers separate as you zoom in.
  const { clusters, route } = useMemo(
    () =>
      clusterRoute(
        points,
        (lonLat) => {
          const p = projection(lonLat);
          return p ? (transform.apply(p) as [number, number]) : null;
        },
        24 * unitsPerPx,
      ),
    [points, transform, unitsPerPx],
  );

  function apply(next: ZoomTransform) {
    if (svgRef.current && behavior.current) select(svgRef.current).call(behavior.current.transform, next);
  }
  function scaleBy(factor: number) {
    if (svgRef.current && behavior.current) select(svgRef.current).call(behavior.current.scaleBy, factor);
  }
  function fitRoute() {
    const projected = points
      .map((p) => projection([p.lon, p.lat]))
      .filter((p): p is [number, number] => p !== null);
    const t = fitTransform(projected, { width: WIDTH, height: HEIGHT, padding: 48, maxScale: MAX_ZOOM });
    apply(zoomIdentity.translate(t.x, t.y).scale(t.k));
  }

  const applyRef = useRef(apply);
  applyRef.current = apply;
  useEffect(() => {
    applyRef.current(zoomIdentity);
  }, [resetKey]);

  const fitRef = useRef(fitRoute);
  fitRef.current = fitRoute;
  useEffect(() => {
    if (autoFitKey) fitRef.current();
  }, [autoFitKey]);

  // Arcs follow the hop order between clusters; keyed by the clusters they join so they keep
  // their animation when unrelated markers split or merge while zooming.
  const seen = new Map<string, number>();
  const arcs = route.slice(1).map((to, i) => {
    const a = clusters[route[i]];
    const b = clusters[to];
    const pair = `${a.hops[0]}-${b.hops[0]}`;
    const n = (seen.get(pair) ?? 0) + 1; // a route can cross the same pair twice
    seen.set(pair, n);
    return {
      key: `${pair}#${n}`,
      d: path({ type: "LineString", coordinates: [[a.lon, a.lat], [b.lon, b.lat]] }) ?? "",
    };
  });

  return (
    <div className="map-wrap">
      <svg ref={svgRef} className="world-map" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Route map">
        <g data-testid="zoom-layer" transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
          <path className="sphere" d={spherePath} />
          <path className="graticule" d={graticulePath} />
          <path className="land" d={landPath} data-testid="land" />
          {arcs.map((arc, i) => (
            <path key={arc.key} className="arc" d={arc.d} data-testid="arc" style={{ animationDelay: `${i * 0.3}s` }} />
          ))}
        </g>
        {clusters.map((c) => (
          <g
            key={c.hops.join(",")}
            className={c.approximate ? "hop-marker approx" : "hop-marker"}
            transform={`translate(${c.x},${c.y}) scale(${unitsPerPx})`}
            data-testid="marker"
          >
            <title>{c.title}</title>
            <circle r={5} />
            <text x={8} y={4}>{c.label}</text>
          </g>
        ))}
        {clusters.length === 0 && (
          <text className="map-empty" x={WIDTH / 2} y={HEIGHT - 24} textAnchor="middle">No locatable hops yet</text>
        )}
      </svg>
      <div className="map-controls">
        <button type="button" aria-label="Zoom in" title="Zoom in" onClick={() => scaleBy(STEP)}>+</button>
        <button type="button" aria-label="Zoom out" title="Zoom out" onClick={() => scaleBy(1 / STEP)}>−</button>
        <button type="button" aria-label="Fit route" title="Fit route" onClick={fitRoute} disabled={points.length === 0}>⤢</button>
        <button type="button" aria-label="Reset zoom" title="Reset zoom" onClick={() => apply(zoomIdentity)}>⟲</button>
      </div>
    </div>
  );
}
