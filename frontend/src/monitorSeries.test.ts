import { appendSample, emptySeries, MAX_POINTS } from "./monitorSeries";
import { hop, withHops } from "./test/fixtures";

const msg = (...hops: ReturnType<typeof hop>[]) => withHops(hops);

test("first sample creates one series per answering hop", () => {
  const s = appendSample(emptySeries(), msg(hop({ hop: 1, last_ms: 2 }), hop({ hop: 2, ip: null, last_ms: null })), 100);
  expect(s.times).toEqual([100]);
  expect(s.hops).toEqual([{ hop: 1, label: "1: 10.0.0.1", values: [2] }]);
});

test("samples closer than one second are dropped", () => {
  const first = appendSample(emptySeries(), msg(hop({ hop: 1, last_ms: 2 })), 100);
  expect(appendSample(first, msg(hop({ hop: 1, last_ms: 3 })), 100.5)).toBe(first);
});

test("new hops are back-filled with gaps and vanished hops get a gap", () => {
  let s = appendSample(emptySeries(), msg(hop({ hop: 1, last_ms: 2 })), 100);
  s = appendSample(s, msg(hop({ hop: 2, hostname: "r2", last_ms: 9 })), 101);
  expect(s.times).toEqual([100, 101]);
  expect(s.hops).toEqual([
    { hop: 1, label: "1: 10.0.0.1", values: [2, null] },
    { hop: 2, label: "2: r2", values: [null, 9] },
  ]);
});

test("history is capped", () => {
  let s = emptySeries();
  for (let i = 0; i < MAX_POINTS + 5; i++) s = appendSample(s, msg(hop({ hop: 1, last_ms: i })), i);
  expect(s.times).toHaveLength(MAX_POINTS);
  expect(s.times[0]).toBe(5);
  expect(s.hops[0].values[0]).toBe(5);
});
