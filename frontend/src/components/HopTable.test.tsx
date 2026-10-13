import { render, screen, within } from "@testing-library/react";
import { sampleHops } from "../test/fixtures";
import { formatLocation, HopTable } from "./HopTable";

test("formatLocation mirrors the CLI", () => {
  expect(formatLocation(null)).toBe("");
  expect(formatLocation(sampleHops[0].geo)).toBe("local");
  expect(formatLocation({ ...sampleHops[2].geo!, status: "unknown" })).toBe("unknown location");
  expect(formatLocation(sampleHops[2].geo)).toBe("Patan, NP");
  expect(formatLocation(sampleHops[4].geo)).toBe("Sydney, AU ~approx");
});

test("renders one row per hop with host, location, ASN and loss styling", () => {
  render(<HopTable hops={sampleHops} />);
  const rows = screen.getAllByRole("row").slice(1);
  expect(rows).toHaveLength(5);
  expect(within(rows[0]).getByText("dsldevice.lan (192.168.1.254)")).toBeInTheDocument();
  expect(within(rows[1]).getByText("no reply")).toBeInTheDocument();
  expect(rows[1]).toHaveClass("silent");
  expect(within(rows[2]).getByText("30%")).toHaveClass("loss-bad");
  expect(within(rows[2]).getByText("AS141767")).toBeInTheDocument();
  expect(within(rows[4]).getByText("0%")).toHaveClass("loss-ok");
  expect(within(rows[4]).getByText("389.8")).toBeInTheDocument();
});
