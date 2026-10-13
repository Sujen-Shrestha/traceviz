import type { Geo, Hop, SessionMessage } from "../types";

const geo = (city: string | null, country: string, name: string, lat: number, lon: number,
             asn: number | null = null, approximate = false): Geo => ({
  status: "geo", lat, lon, city, country, country_name: name, asn, org: null, approximate,
});

export const LOCAL: Geo = { status: "local", lat: null, lon: null, city: null, country: null,
  country_name: null, asn: null, org: null, approximate: false };

export function hop(partial: Partial<Hop> & { hop: number }): Hop {
  return { ip: `10.0.0.${partial.hop}`, hostname: null, sent: 10, received: 10, loss_pct: 0,
    last_ms: 1, avg_ms: 1, best_ms: 1, worst_ms: 1, jitter_ms: 0, geo: null, ...partial };
}

export const sampleHops: Hop[] = [
  hop({ hop: 1, ip: "192.168.1.254", hostname: "dsldevice.lan", avg_ms: 1.5, geo: LOCAL }),
  hop({ hop: 2, ip: null, received: 0, loss_pct: 100, last_ms: null, avg_ms: null, best_ms: null,
        worst_ms: null, jitter_ms: null }),
  hop({ hop: 3, ip: "103.186.196.182", avg_ms: 7.4, loss_pct: 30, received: 7,
        geo: geo("Patan", "NP", "Nepal", 27.67, 85.32, 141767) }),
  hop({ hop: 4, ip: "195.66.226.214", avg_ms: 153.9, geo: geo("London", "GB", "United Kingdom", 51.5, -0.12) }),
  hop({ hop: 5, ip: "1.1.1.1", hostname: "one.one.one.one", avg_ms: 389.8,
        geo: geo("Sydney", "AU", "Australia", -33.87, 151.21, 13335, true) }),
];

export function withHops(hops: Hop[]): SessionMessage {
  return { ...sampleMessage, hops };
}

export const sampleMessage: SessionMessage = {
  type: "state",
  id: 7,
  target: "one.one.one.one",
  target_ip: "1.1.1.1",
  protocol: "icmp",
  kind: "trace",
  status: "completed",
  error: null,
  destination_reached: true,
  suggest_other_protocol: false,
  hops: sampleHops,
  summary: {
    target: "one.one.one.one",
    status: "completed",
    reached: true,
    hop_count: 5,
    last_hop: 5,
    last_ip: "1.1.1.1",
    last_place: "Sydney, AU",
    last_avg_ms: 389.8,
    last_loss_pct: 0,
    countries: ["Nepal", "United Kingdom", "Australia"],
    asns: [141767, 13335],
    jumps: [{ from_hop: 4, to_hop: 5, from_place: "London, GB", to_place: "Sydney, AU", delta_ms: 236 }],
    notes: [{ hop: 3, kind: "harmless", message: "hop 3: 30% loss doesn't carry on to later hops — harmless." }],
  },
};
