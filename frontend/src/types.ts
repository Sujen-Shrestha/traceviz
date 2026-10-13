export type GeoStatus = "geo" | "local" | "unknown";
export type SessionStatus = "running" | "completed" | "failed" | "stopped";
export type SessionKind = "trace" | "monitor";
export type Protocol = "icmp" | "udp" | "tcp";

export interface Geo {
  status: GeoStatus;
  lat: number | null;
  lon: number | null;
  city: string | null;
  country: string | null;
  country_name: string | null;
  asn: number | null;
  org: string | null;
  approximate: boolean;
}

export interface Hop {
  hop: number;
  ip: string | null;
  hostname: string | null;
  sent: number;
  received: number;
  loss_pct: number;
  last_ms: number | null;
  avg_ms: number | null;
  best_ms: number | null;
  worst_ms: number | null;
  jitter_ms: number | null;
  geo: Geo | null;
}

export interface LatencyJump {
  from_hop: number;
  to_hop: number;
  from_place: string | null;
  to_place: string | null;
  delta_ms: number;
}

export interface HopNote {
  hop: number;
  kind: "harmless" | "problem";
  message: string;
}

export interface Summary {
  target: string;
  status: SessionStatus;
  reached: boolean;
  hop_count: number;
  last_hop: number | null;
  last_ip: string | null;
  last_place: string | null;
  last_avg_ms: number | null;
  last_loss_pct: number | null;
  countries: string[];
  asns: number[];
  jumps: LatencyJump[];
  notes: HopNote[];
}

export interface SessionMessage {
  type: "state";
  id: number;
  target: string;
  target_ip: string;
  protocol: Protocol;
  kind: SessionKind;
  status: SessionStatus;
  error: string | null;
  destination_reached: boolean;
  suggest_other_protocol: boolean;
  hops: Hop[];
  summary: Summary;
}

export interface Health {
  probe_ok: boolean;
  probe_error: string | null;
  geo_available: boolean;
  attribution: string;
}

export interface StartRequest {
  target: string;
  kind: SessionKind;
  protocol: Protocol;
  max_hops?: number;
  cycles?: number;
}

export interface StartResponse {
  id: number;
  target: string;
  target_ip: string;
}
