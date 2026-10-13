import { hop, LOCAL, sampleHops } from "../test/fixtures";
import { clusterPoints, formatHops, mapPoints } from "./points";

test("only geolocated hops become points, in order", () => {
  const points = mapPoints(sampleHops);
  expect(points.map((p) => p.hops)).toEqual([[3], [4], [5]]);
  expect(points[0]).toMatchObject({ lat: 27.67, lon: 85.32, label: "Patan, NP", approximate: false });
  expect(points[2].approximate).toBe(true);
});

test("consecutive hops at the same coordinates merge into one point", () => {
  const sydney = sampleHops[4].geo;
  const points = mapPoints([hop({ hop: 7, geo: sydney }), hop({ hop: 8, geo: sydney }), hop({ hop: 9, geo: LOCAL })]);
  expect(points).toHaveLength(1);
  expect(points[0].hops).toEqual([7, 8]);
});

test("no locatable hops gives no points", () => {
  expect(mapPoints([hop({ hop: 1, geo: LOCAL }), hop({ hop: 2, geo: null })])).toEqual([]);
});

test("country-only results use the country name as label", () => {
  const geo = { ...sampleHops[2].geo!, city: null, country: null, country_name: "Nepal" };
  expect(mapPoints([hop({ hop: 1, geo })])[0].label).toBe("Nepal");
});

test("formatHops compresses consecutive runs", () => {
  expect(formatHops([3])).toBe("3");
  expect(formatHops([4, 5])).toBe("4–5");
  expect(formatHops([7, 8, 9, 10, 15, 14])).toBe("7–10, 14–15");
  expect(formatHops([3, 6])).toBe("3, 6");
});

test("points that would overlap on screen merge into one cluster", () => {
  const project = ([lon, lat]: [number, number]): [number, number] => [lon * 10, -lat * 10];
  const points = mapPoints([
    hop({ hop: 4, geo: { ...sampleHops[2].geo!, city: "New Delhi", country: "IN", lat: 28.6, lon: 77.2 } }),
    hop({ hop: 5, geo: { ...sampleHops[2].geo!, city: "Gurugram", country: "IN", lat: 28.5, lon: 77.0 } }),
    hop({ hop: 6, geo: sampleHops[3].geo }),
    hop({ hop: 7, geo: { ...sampleHops[4].geo!, city: "Southbank", lat: -37.8, lon: 144.9, approximate: false } }),
  ]);
  const clusters = clusterPoints(points, project, 14);
  expect(clusters.map((c) => c.label)).toEqual(["4–5 New Delhi, IN +1", "6 London, GB", "7 Southbank, AU"]);
  expect(clusters[0].title).toBe("Hop 4: New Delhi, IN\nHop 5: Gurugram, IN");
  expect(clusters[0]).toMatchObject({ x: 772, y: -286 });
});

test("points the projection can't place are skipped", () => {
  expect(clusterPoints(mapPoints(sampleHops), () => null)).toEqual([]);
});
