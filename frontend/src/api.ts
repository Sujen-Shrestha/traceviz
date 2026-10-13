import type { Health, SessionMessage, StartRequest, StartResponse } from "./types";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

interface ErrorBody {
  detail?: string | { msg: string }[];
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`.trim();
    try {
      const body = (await res.json()) as ErrorBody;
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((d) => d.msg).join("; ");
    } catch {
      // not JSON: keep the status line
    }
    throw new ApiError(message, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function getHealth(): Promise<Health> {
  return fetch("/api/health").then((r) => parse<Health>(r));
}

export function startSession(req: StartRequest): Promise<StartResponse> {
  return fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  }).then((r) => parse<StartResponse>(r));
}

export function stopSession(id: number): Promise<void> {
  return fetch(`/api/sessions/${id}/stop`, { method: "POST" }).then((r) => parse<void>(r));
}

export function openSessionSocket(
  id: number,
  onMessage: (msg: SessionMessage) => void,
  onClose?: (code: number) => void,
): () => void {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${window.location.host}/ws/sessions/${id}`);
  ws.onmessage = (event) => onMessage(JSON.parse(event.data as string) as SessionMessage);
  ws.onclose = (event) => onClose?.(event.code);
  return () => ws.close();
}
