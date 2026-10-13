import { render, screen } from "@testing-library/react";
import { sampleMessage } from "../test/fixtures";
import type { Summary } from "../types";
import { resultLine, SummaryPanel } from "./SummaryPanel";

const base = sampleMessage.summary;

test("result line for reached, unanswered and running traces", () => {
  expect(resultLine(base)).toEqual(["Reached", "one.one.one.one in 5 hops · 390 ms avg · 0% loss"]);
  const noReply: Summary = { ...base, reached: false };
  expect(resultLine(noReply)).toEqual([
    "No reply", "one.one.one.one didn't answer · last reply from hop 5 (Sydney, AU) · 390 ms avg · 0% loss",
  ]);
  expect(resultLine({ ...noReply, status: "running" })[0]).toBe("Tracing");
});

test("renders route, networks, jumps and notes", () => {
  render(<SummaryPanel summary={base} />);
  expect(screen.getByText("Nepal → United Kingdom → Australia")).toBeInTheDocument();
  expect(screen.getByText("AS141767 → AS13335")).toBeInTheDocument();
  expect(screen.getByText(/hop 4 → 5/)).toHaveTextContent("London, GB → Sydney, AU +236 ms");
  expect(screen.getByText(/hop 3: 30% loss/)).toHaveClass("note-harmless");
});

test("problem notes are highlighted and empty summaries say so", () => {
  const problem: Summary = { ...base, notes: [{ hop: 3, kind: "problem", message: "packet loss starts at hop 3" }] };
  render(<SummaryPanel summary={problem} />);
  expect(screen.getByText("packet loss starts at hop 3")).toHaveClass("note-problem");
  render(<SummaryPanel summary={{ ...base, last_hop: null }} />);
  expect(screen.getByText("No hops have answered yet.")).toBeInTheDocument();
});
