import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "./App";
import * as api from "./api";
import { sampleMessage } from "./test/fixtures";
import type { SessionMessage } from "./types";

vi.mock("./api", () => ({
  ApiError: class ApiError extends Error {},
  getHealth: vi.fn(),
  startSession: vi.fn(),
  stopSession: vi.fn(),
  openSessionSocket: vi.fn(),
}));
// No JSX inside hoisted mock factories: they run before the JSX runtime import.
vi.mock("./components/LatencyChart", () => ({ LatencyChart: () => "latency-chart" }));

const healthy = { probe_ok: true, probe_error: null, geo_available: true, attribution: "IP geolocation by DB-IP" };
let push: (m: SessionMessage) => void = () => {};

beforeEach(() => {
  vi.mocked(api.getHealth).mockResolvedValue(healthy);
  vi.mocked(api.startSession).mockResolvedValue({ id: 7, target: "one.one.one.one", target_ip: "1.1.1.1" });
  vi.mocked(api.stopSession).mockResolvedValue(undefined);
  vi.mocked(api.openSessionSocket).mockImplementation((_id, onMessage) => {
    push = onMessage;
    return () => {};
  });
});

afterEach(() => vi.clearAllMocks());

async function startTrace(kind = "trace") {
  render(<App />);
  fireEvent.change(screen.getByLabelText("Target host"), { target: { value: " one.one.one.one " } });
  fireEvent.change(screen.getByLabelText("Mode"), { target: { value: kind } });
  fireEvent.click(screen.getByRole("button", { name: "Start" }));
  await waitFor(() => expect(api.openSessionSocket).toHaveBeenCalledWith(7, expect.any(Function), expect.any(Function)));
}

test("a trace streams into the map, summary and table", async () => {
  await startTrace();
  expect(api.startSession).toHaveBeenCalledWith({ target: "one.one.one.one", kind: "trace", protocol: "icmp" });
  act(() => push(sampleMessage));
  expect(screen.getByText("dsldevice.lan (192.168.1.254)")).toBeInTheDocument();
  expect(screen.getAllByTestId("marker")).toHaveLength(3);
  expect(screen.getByText("Nepal → United Kingdom → Australia")).toBeInTheDocument();
  expect(screen.queryByText("latency-chart")).not.toBeInTheDocument();
});

test("monitor shows the chart and Stop calls the API", async () => {
  await startTrace("monitor");
  act(() => push({ ...sampleMessage, kind: "monitor", status: "running" }));
  expect(screen.getByText("latency-chart")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  await waitFor(() => expect(api.stopSession).toHaveBeenCalledWith(7));
});

test("API errors are shown to the user", async () => {
  vi.mocked(api.startSession).mockRejectedValue(new Error("could not resolve nope.invalid: Name or service not known"));
  render(<App />);
  fireEvent.change(screen.getByLabelText("Target host"), { target: { value: "nope.invalid" } });
  fireEvent.click(screen.getByRole("button", { name: "Start" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("could not resolve nope.invalid");
});

test("probe and geo problems are surfaced as banners", async () => {
  vi.mocked(api.getHealth).mockResolvedValue({ ...healthy, probe_ok: false, probe_error: "needs NET_RAW", geo_available: false });
  render(<App />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Probing is unavailable: needs NET_RAW");
  expect(screen.getByText(/traceviz fetch-geo/)).toBeInTheDocument();
});

test("filtered ICMP suggests TCP", async () => {
  await startTrace();
  act(() => push({ ...sampleMessage, suggest_other_protocol: true }));
  expect(screen.getByText(/try TCP 443/)).toBeInTheDocument();
});

test("a failed probe shows its error", async () => {
  await startTrace();
  act(() => push({ ...sampleMessage, status: "failed", error: "mtr exploded" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Probe failed: mtr exploded");
});

test("messages from a previous session's socket are ignored", async () => {
  await startTrace();
  act(() => push({ ...sampleMessage, id: 3, target: "old.example" }));
  expect(screen.queryByText("dsldevice.lan (192.168.1.254)")).not.toBeInTheDocument();
  act(() => push(sampleMessage));
  expect(screen.getByText("dsldevice.lan (192.168.1.254)")).toBeInTheDocument();
});

test("a lost connection during a running session is reported", async () => {
  let close: (code: number) => void = () => {};
  vi.mocked(api.openSessionSocket).mockImplementation((_id, onMessage, onClose) => {
    push = onMessage;
    close = onClose ?? (() => {});
    return () => {};
  });
  await startTrace("monitor");
  act(() => push({ ...sampleMessage, kind: "monitor", status: "running" }));
  act(() => close(1006));
  expect(screen.getByRole("alert")).toHaveTextContent("Lost connection to the traceviz server");
  expect(screen.getByRole("button", { name: "Start" })).toBeInTheDocument();
});

test("a normal close after the final message is not an error", async () => {
  let close: (code: number) => void = () => {};
  vi.mocked(api.openSessionSocket).mockImplementation((_id, onMessage, onClose) => {
    push = onMessage;
    close = onClose ?? (() => {});
    return () => {};
  });
  await startTrace();
  act(() => push(sampleMessage));
  act(() => close(1000));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("unmounting while a start is pending doesn't open a socket", async () => {
  let resolve: (v: { id: number; target: string; target_ip: string }) => void = () => {};
  vi.mocked(api.startSession).mockReturnValue(new Promise((r) => { resolve = r; }));
  const { unmount } = render(<App />);
  fireEvent.change(screen.getByLabelText("Target host"), { target: { value: "a.com" } });
  fireEvent.click(screen.getByRole("button", { name: "Start" }));
  unmount();
  await act(async () => resolve({ id: 9, target: "a.com", target_ip: "1.2.3.4" }));
  expect(api.openSessionSocket).not.toHaveBeenCalled();
});
