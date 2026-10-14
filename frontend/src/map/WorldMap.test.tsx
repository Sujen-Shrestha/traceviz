import { fireEvent, render, screen } from "@testing-library/react";
import { hop, LOCAL, sampleHops } from "../test/fixtures";
import { WorldMap } from "./WorldMap";

test("draws land, one marker per located point and arcs between them", () => {
  render(<WorldMap hops={sampleHops} />);
  expect(screen.getByTestId("land").getAttribute("d")!.length).toBeGreaterThan(1000);
  const markers = screen.getAllByTestId("marker");
  expect(markers).toHaveLength(3);
  expect(markers[2]).toHaveClass("approx");
  expect(markers[0]).toHaveTextContent("3 Patan, NP");
  expect(screen.getAllByTestId("arc")).toHaveLength(2);
});

test("says so when nothing can be placed", () => {
  render(<WorldMap hops={[hop({ hop: 1, geo: LOCAL })]} />);
  expect(screen.queryAllByTestId("marker")).toHaveLength(0);
  expect(screen.getByText("No locatable hops yet")).toBeInTheDocument();
});

const NEPAL = { ...sampleHops[2].geo!, city: "Patan", country: "NP", lat: 27.67, lon: 85.32 };
const DELHI = { ...sampleHops[2].geo!, city: "New Delhi", country: "IN", lat: 28.6, lon: 77.2 };

test("zooming in splits markers that overlap at world scale", () => {
  render(<WorldMap hops={[hop({ hop: 3, geo: NEPAL }), hop({ hop: 4, geo: DELHI })]} />);
  expect(screen.getAllByTestId("marker")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", { name: "Zoom in" }));
  expect(screen.getAllByTestId("marker")).toHaveLength(2);
  fireEvent.click(screen.getByRole("button", { name: "Reset zoom" }));
  expect(screen.getAllByTestId("marker")).toHaveLength(1);
});

test("fit route zooms the map and marker size stays constant", () => {
  render(<WorldMap hops={sampleHops} />);
  const layer = screen.getByTestId("zoom-layer");
  expect(layer.getAttribute("transform")).toBe("translate(0,0) scale(1)");
  fireEvent.click(screen.getByRole("button", { name: "Fit route" }));
  expect(layer.getAttribute("transform")).not.toBe("translate(0,0) scale(1)");
  expect(screen.getAllByTestId("marker")[0].querySelector("circle")!.getAttribute("r")).toBe("5");
});

test("auto-fits once when the fit key changes", () => {
  const { rerender } = render(<WorldMap hops={sampleHops} />);
  const layer = screen.getByTestId("zoom-layer");
  expect(layer.getAttribute("transform")).toBe("translate(0,0) scale(1)");
  rerender(<WorldMap hops={sampleHops} autoFitKey="7" />);
  expect(layer.getAttribute("transform")).not.toBe("translate(0,0) scale(1)");
});

test("a new session resets the zoom", () => {
  const { rerender } = render(<WorldMap hops={sampleHops} resetKey="1" />);
  fireEvent.click(screen.getByRole("button", { name: "Fit route" }));
  const layer = screen.getByTestId("zoom-layer");
  expect(layer.getAttribute("transform")).not.toBe("translate(0,0) scale(1)");
  rerender(<WorldMap hops={[]} resetKey="2" />);
  expect(layer.getAttribute("transform")).toBe("translate(0,0) scale(1)");
});
