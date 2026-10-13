import { ApiError, getHealth, startSession, stopSession } from "./api";

function respond(status: number, body: unknown) {
  return vi.fn().mockResolvedValue(new Response(body === undefined ? null : JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json" },
  }));
}

afterEach(() => vi.unstubAllGlobals());

test("startSession posts the request and returns the created session", async () => {
  const fetchMock = respond(201, { id: 3, target: "a.com", target_ip: "1.2.3.4" });
  vi.stubGlobal("fetch", fetchMock);
  await expect(startSession({ target: "a.com", kind: "trace", protocol: "icmp" }))
    .resolves.toEqual({ id: 3, target: "a.com", target_ip: "1.2.3.4" });
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toBe("/api/sessions");
  expect(init.method).toBe("POST");
  expect(JSON.parse(init.body)).toEqual({ target: "a.com", kind: "trace", protocol: "icmp" });
});

test("string detail becomes the error message", async () => {
  vi.stubGlobal("fetch", respond(422, { detail: "could not resolve nope.invalid: Name or service not known" }));
  const err = await startSession({ target: "nope.invalid", kind: "trace", protocol: "icmp" }).catch((e) => e);
  expect(err).toBeInstanceOf(ApiError);
  expect(err.status).toBe(422);
  expect(err.message).toBe("could not resolve nope.invalid: Name or service not known");
});

test("validation detail lists are joined", async () => {
  vi.stubGlobal("fetch", respond(422, { detail: [{ msg: "too short" }, { msg: "bad protocol" }] }));
  const err = await startSession({ target: "", kind: "trace", protocol: "icmp" }).catch((e) => e);
  expect(err.message).toBe("too short; bad protocol");
});

test("non-JSON errors fall back to the status line", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("boom", { status: 502, statusText: "Bad Gateway" })));
  await expect(getHealth()).rejects.toThrow("502 Bad Gateway");
});

test("stopSession accepts 204", async () => {
  vi.stubGlobal("fetch", respond(204, undefined));
  await expect(stopSession(3)).resolves.toBeUndefined();
});
