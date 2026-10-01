import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
const limit = 64 * 1024;
const requestHeaders = ["accept", "content-type", "cookie", "origin", "x-csrf-token", "idempotency-key", "last-event-id"];
const responseHeaders = ["content-type", "cache-control", "x-content-type-options", "referrer-policy", "x-accel-buffering"];

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const target = new URL(`/v1/${path.map(encodeURIComponent).join("/")}`, process.env.FORGE_API_URL ?? "http://127.0.0.1:8000");
  target.search = request.nextUrl.search;
  const headers = new Headers();
  for (const key of requestHeaders) {
    const value = request.headers.get(key);
    if (value !== null) headers.set(key, value);
  }
  let body: Uint8Array | undefined;
  if (request.body && !["GET", "HEAD"].includes(request.method)) {
    const reader = request.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > limit) {
        await reader.cancel();
        return Response.json({ detail: { code: "INPUT_TOO_LARGE" } }, { status: 413 });
      }
      chunks.push(value);
    }
    body = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  }
  try {
    const upstream = await fetch(target, { method: request.method, headers, body: body as BodyInit | undefined,
      cache: "no-store", redirect: "manual", signal: request.signal });
    const forwarded = new Headers({ "Cache-Control": "no-store" });
    for (const key of responseHeaders) {
      const value = upstream.headers.get(key);
      if (value !== null) forwarded.set(key, value);
    }
    for (const cookie of upstream.headers.getSetCookie()) forwarded.append("set-cookie", cookie);
    return new Response(upstream.body, { status: upstream.status, headers: forwarded });
  } catch {
    return Response.json({ detail: { code: "API_UNAVAILABLE" } }, { status: 502 });
  }
}

export { proxy as GET, proxy as POST, proxy as PATCH, proxy as PUT, proxy as DELETE, proxy as HEAD };
