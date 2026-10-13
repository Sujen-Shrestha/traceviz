import type { Summary } from "../types";

const ms0 = (v: number | null) => (v === null ? "—" : `${v.toFixed(0)} ms`);

export function resultLine(s: Summary): [string, string] {
  const stats = `${ms0(s.last_avg_ms)} avg · ${(s.last_loss_pct ?? 0).toFixed(0)}% loss`;
  if (s.reached) return ["Reached", `${s.target} in ${s.hop_count} hops · ${stats}`];
  const last = `last reply from hop ${s.last_hop} (${s.last_place ?? s.last_ip}) · ${stats}`;
  if (s.status === "running") return ["Tracing", `${s.target} · ${last}`];
  return ["No reply", `${s.target} didn't answer · ${last}`];
}

export function SummaryPanel({ summary: s }: { summary: Summary }) {
  if (s.last_hop === null) {
    return <section className="card summary"><p className="muted">No hops have answered yet.</p></section>;
  }
  const [label, text] = resultLine(s);
  return (
    <section className="card summary">
      <h2>Summary</h2>
      <dl>
        <dt>{label}</dt>
        <dd>{text}</dd>
        {s.countries.length > 0 && (<><dt>Route</dt><dd>{s.countries.join(" → ")}</dd></>)}
        {s.asns.length > 0 && (<><dt>Networks</dt><dd>{s.asns.map((a) => `AS${a}`).join(" → ")}</dd></>)}
        {s.jumps.length > 0 && (
          <>
            <dt>Biggest jumps</dt>
            <dd>
              <ul>
                {s.jumps.map((j) => (
                  <li key={`${j.from_hop}-${j.to_hop}`}>
                    hop {j.from_hop} → {j.to_hop} {j.from_place ?? "?"} → {j.to_place ?? "?"}{" "}
                    <strong>+{j.delta_ms.toFixed(0)} ms</strong>
                  </li>
                ))}
              </ul>
            </dd>
          </>
        )}
        {s.notes.length > 0 && (
          <>
            <dt>Notes</dt>
            <dd>
              <ul>
                {s.notes.map((n) => (
                  <li key={`${n.kind}-${n.hop}`} className={`note-${n.kind}`}>{n.message}</li>
                ))}
              </ul>
            </dd>
          </>
        )}
      </dl>
    </section>
  );
}
