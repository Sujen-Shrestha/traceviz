import { render, screen } from "@testing-library/react";
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
