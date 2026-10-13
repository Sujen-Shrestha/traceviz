import type { Geo, Hop } from "../types";

const ms = (v: number | null) => (v === null ? "—" : v.toFixed(1));

export function formatLocation(geo: Geo | null): string {
  if (!geo) return "";
  if (geo.status === "local") return "local";
  if (geo.status === "unknown") return "unknown location";
  const place = [geo.city, geo.country].filter(Boolean).join(", ");
  return geo.approximate ? `${place} ~approx` : place;
}

function host(h: Hop): string {
  if (h.ip === null) return "no reply";
  return h.hostname && h.hostname !== h.ip ? `${h.hostname} (${h.ip})` : h.ip;
}

function lossClass(loss: number): string {
  if (loss === 0) return "loss-ok";
  return loss < 20 ? "loss-warn" : "loss-bad";
}

export function HopTable({ hops }: { hops: Hop[] }) {
  return (
    <section className="card">
      <table className="hops">
        <thead>
          <tr>
            {["#", "Host", "Location", "ASN", "Loss", "Sent", "Last", "Avg", "Best", "Worst", "Jitter"].map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {hops.map((h) => (
            <tr key={h.hop} className={h.ip === null ? "silent" : undefined}>
              <td className="num">{h.hop}</td>
              <td>{host(h)}</td>
              <td>{formatLocation(h.geo)}</td>
              <td>{h.geo?.asn ? `AS${h.geo.asn}` : ""}</td>
              <td className={`num ${lossClass(h.loss_pct)}`}>{h.loss_pct.toFixed(0)}%</td>
              <td className="num">{h.sent}</td>
              <td className="num">{ms(h.last_ms)}</td>
              <td className="num">{ms(h.avg_ms)}</td>
              <td className="num">{ms(h.best_ms)}</td>
              <td className="num">{ms(h.worst_ms)}</td>
              <td className="num">{ms(h.jitter_ms)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
