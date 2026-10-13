import { geoGraticule10, geoNaturalEarth1, geoPath } from "d3-geo";
import { useMemo } from "react";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";
import world from "world-atlas/countries-110m.json";
import type { Hop } from "../types";
import { mapPoints } from "./points";

const WIDTH = 960;
const HEIGHT = 500;

const topology = world as unknown as Topology<{ countries: GeometryCollection }>;
const land = feature(topology, topology.objects.countries);
const projection = geoNaturalEarth1().fitSize([WIDTH, HEIGHT], { type: "Sphere" });
const path = geoPath(projection);
const spherePath = path({ type: "Sphere" }) ?? "";
const graticulePath = path(geoGraticule10()) ?? "";
const landPath = path(land) ?? "";

export function WorldMap({ hops }: { hops: Hop[] }) {
  const points = useMemo(() => mapPoints(hops), [hops]);
  const arcs = points.slice(1).map((p, i) => {
    const from = points[i];
    return path({ type: "LineString", coordinates: [[from.lon, from.lat], [p.lon, p.lat]] }) ?? "";
  });
  return (
    <svg className="world-map" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label="Route map">
      <path className="sphere" d={spherePath} />
      <path className="graticule" d={graticulePath} />
      <path className="land" d={landPath} data-testid="land" />
      {arcs.map((d, i) => (
        <path key={`arc-${i}`} className="arc" d={d} data-testid="arc" style={{ animationDelay: `${i * 0.3}s` }} />
      ))}
      {points.map((p) => {
        const xy = projection([p.lon, p.lat]);
        if (!xy) return null;
        const hopsLabel = p.hops.join(",");
        return (
          <g
            key={hopsLabel}
            className={p.approximate ? "hop-marker approx" : "hop-marker"}
            transform={`translate(${xy[0]},${xy[1]})`}
            data-testid="marker"
          >
            <title>{`Hop ${p.hops.join(", ")}: ${p.label}${p.approximate ? " (approximate)" : ""}`}</title>
            <circle r={5} />
            <text x={8} y={4}>{`${hopsLabel} ${p.label}`}</text>
          </g>
        );
      })}
      {points.length === 0 && (
        <text className="map-empty" x={WIDTH / 2} y={HEIGHT - 24} textAnchor="middle">No locatable hops yet</text>
      )}
    </svg>
  );
}
