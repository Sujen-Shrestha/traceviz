import { useEffect, useRef, useState } from "react";
import { getHealth, openSessionSocket, startSession, stopSession } from "./api";
import { HopTable } from "./components/HopTable";
import { LatencyChart } from "./components/LatencyChart";
import { SummaryPanel } from "./components/SummaryPanel";
import { TargetForm } from "./components/TargetForm";
import { WorldMap } from "./map/WorldMap";
import { appendSample, emptySeries, type MonitorSeries } from "./monitorSeries";
import type { Health, SessionMessage, StartRequest } from "./types";

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [session, setSession] = useState<SessionMessage | null>(null);
  const [series, setSeries] = useState<MonitorSeries>(emptySeries);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const closeSocket = useRef<(() => void) | null>(null);
  const currentId = useRef<number | null>(null); // only this session's messages are shown
  const lastStatus = useRef<SessionMessage["status"] | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    getHealth().then(setHealth, (e: unknown) => setError(`Cannot reach the traceviz server: ${message(e)}`));
    return () => {
      mounted.current = false;
      closeSocket.current?.();
    };
  }, []);

  async function start(req: StartRequest) {
    setError(null);
    setBusy(true);
    closeSocket.current?.();
    currentId.current = null;
    lastStatus.current = null;
    setSession(null);
    setSeries(emptySeries());
    try {
      const { id } = await startSession(req);
      if (!mounted.current) return; // the page went away while starting; its session stops on its own
      currentId.current = id;
      closeSocket.current = openSessionSocket(
        id,
        (msg) => {
          if (msg.id !== currentId.current) return; // late frame from a previous session
          lastStatus.current = msg.status;
          setSession(msg);
          if (msg.kind === "monitor") setSeries((s) => appendSample(s, msg, Date.now() / 1000));
        },
        () => {
          // A close after the final message is normal; while still running it means we lost it.
          if (id !== currentId.current || lastStatus.current !== "running") return;
          lastStatus.current = "stopped";
          setError("Lost connection to the traceviz server — the session was stopped.");
          setSession((s) => (s && s.id === id ? { ...s, status: "stopped" } : s));
        },
      );
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }

  async function stop() {
    if (!session) return;
    try {
      await stopSession(session.id);
    } catch (e) {
      setError(message(e));
    }
  }

  return (
    <div className="app">
      <header>
        <h1>traceviz</h1>
        <span className="muted">visual traceroute</span>
      </header>
      {health && !health.probe_ok && (
        <div className="banner error" role="alert">Probing is unavailable: {health.probe_error}</div>
      )}
      {health && !health.geo_available && (
        <div className="banner warn">No geolocation database — run <code>traceviz fetch-geo</code> to see hop locations.</div>
      )}
      <TargetForm onStart={start} onStop={stop} running={session?.status === "running"} busy={busy} />
      {error && <div className="banner error" role="alert">{error}</div>}
      {session?.status === "failed" && (
        <div className="banner error" role="alert">Probe failed: {session.error}</div>
      )}
      {session?.suggest_other_protocol && (
        <div className="banner warn">No hops answered beyond the first. ICMP may be filtered — try TCP 443.</div>
      )}
      <section className="card map-card">
        <WorldMap
          hops={session?.hops ?? []}
          autoFitKey={session && session.status !== "running" ? String(session.id) : undefined}
          resetKey={session ? String(session.id) : undefined}
        />
      </section>
      {session && <SummaryPanel summary={session.summary} />}
      {session?.kind === "monitor" && <LatencyChart series={series} />}
      {session && <HopTable hops={session.hops} />}
      <footer className="muted">{health?.attribution ?? ""} · Map data: Natural Earth</footer>
    </div>
  );
}
