import { useState } from "react";
import type { Protocol, SessionKind, StartRequest } from "../types";

interface Props {
  onStart: (req: StartRequest) => void;
  onStop: () => void;
  running: boolean;
  busy: boolean;
}

export function TargetForm({ onStart, onStop, running, busy }: Props) {
  const [target, setTarget] = useState("");
  const [kind, setKind] = useState<SessionKind>("trace");
  const [protocol, setProtocol] = useState<Protocol>("icmp");
  return (
    <form
      className="card target-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (target.trim()) onStart({ target: target.trim(), kind, protocol });
      }}
    >
      <input
        aria-label="Target host"
        placeholder="google.com or 1.1.1.1"
        value={target}
        onChange={(e) => setTarget(e.target.value)}
        disabled={running}
        autoFocus
      />
      <select aria-label="Mode" value={kind} onChange={(e) => setKind(e.target.value as SessionKind)} disabled={running}>
        <option value="trace">Trace</option>
        <option value="monitor">Monitor</option>
      </select>
      <select aria-label="Protocol" value={protocol} onChange={(e) => setProtocol(e.target.value as Protocol)} disabled={running}>
        <option value="icmp">ICMP</option>
        <option value="udp">UDP</option>
        <option value="tcp">TCP 443</option>
      </select>
      {running ? (
        <button type="button" className="stop" onClick={onStop}>Stop</button>
      ) : (
        <button type="submit" disabled={busy || !target.trim()}>Start</button>
      )}
    </form>
  );
}
