import { hop, LOCAL, sampleHops } from "../test/fixtures";
import { clusterPoints, clusterRoute, fitTransform, formatHops, mapPoints, markerScale } from "./points";

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

describe("fitTransform", () => {
  const box = { width: 960, height: 500, padding: 40 };

  test("frames all points with padding", () => {
    expect(fitTransform([[100, 100], [300, 200]], box)).toEqual({ k: 4.2, x: -360, y: -380 });
  });

  test("a single point gets a sensible zoom, not infinite", () => {
    expect(fitTransform([[100, 100]], box)).toEqual({ k: 7, x: -220, y: -450 });
  });

  test("never zooms out past the world or beyond the max", () => {
    expect(fitTransform([], box)).toEqual({ k: 1, x: 0, y: 0 });
    expect(fitTransform([[0, 0], [960, 500]], box).k).toBe(1);
    expect(fitTransform([[100, 100], [101, 100]], { ...box, maxScale: 5 }).k).toBe(5);
  });
});

test("markerScale keeps markers the same on-screen size at any map width", () => {
  expect(markerScale(960, 960)).toBe(1);
  expect(markerScale(960, 480)).toBe(2); // half-width map: draw markers twice as big in map units
  expect(markerScale(960, 1920)).toBe(0.5);
  expect(markerScale(960, 3840)).toBe(0.25); // very wide maps: markers must not grow
  expect(markerScale(960, 0)).toBe(1); // not laid out yet (e.g. tests): no scaling
  expect(markerScale(960, 100)).toBe(4); // clamped
});

const flat = ([lon, lat]: [number, number]): [number, number] => [lon, lat];
const at = (hopNo: number, lon: number, lat = 0) =>
  hop({ hop: hopNo, geo: { ...sampleHops[2].geo!, city: `C${hopNo}`, lat, lon } });

test("a point joins the nearest cluster, not the first one in range", () => {
  const { clusters } = clusterRoute(mapPoints([at(1, 0), at(2, 30), at(3, 16)]), flat, 24);
  expect(clusters.map((c) => c.hops)).toEqual([[1], [2, 3]]);
});

test("the route follows hop order through clusters, including returns", () => {
  // Sydney -> LA -> back near Sydney -> Tokyo
  const { route } = clusterRoute(mapPoints([at(1, 151, -33), at(2, -118, 34), at(3, 151.5, -33.5), at(4, 139, 35)]), flat, 24);
  expect(route).toEqual([0, 1, 0, 2]);
});
