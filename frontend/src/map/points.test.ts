import { hop, LOCAL, sampleHops } from "../test/fixtures";
import { mapPoints } from "./points";

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
