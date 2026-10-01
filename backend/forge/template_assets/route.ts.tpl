import {NextRequest} from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

async function proxy(request: NextRequest, context: {params: Promise<{path: string[]}>}) {
  const {path} = await context.params;
  if (path[0] !== "todos" || path.length > 2) return new Response(null, {status: 404});
  const base = process.env.GENERATED_API_URL;
  if (!base) return Response.json({detail: "API unavailable"}, {status: 503});
  const target = new URL("/v1/" + path.map(encodeURIComponent).join("/"), base);
  const writing = request.method !== "GET";
  if (writing && request.headers.get("origin") !== request.nextUrl.origin) {
    return Response.json({detail: "Origin rejected"}, {status: 403});
  }
  let body: Uint8Array | undefined;
  if (writing && request.body) {
    const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
    while (true) {const part = await reader.read(); if (part.done) break;
      size += part.value.byteLength;
      if (size > 16384) {await reader.cancel(); return new Response(null, {status: 413});}
      chunks.push(part.value);
    }
    body = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) {body.set(chunk, offset); offset += chunk.byteLength;}
  }
  try {
    const response = await fetch(target, {method: request.method, cache: "no-store", redirect: "manual",
      headers: {"Content-Type": "application/json"}, body: body as BodyInit | undefined, signal: request.signal});
    return new Response(response.body, {status: response.status,
      headers: {"Content-Type": "application/json", "Cache-Control": "no-store"}});
  } catch {return Response.json({detail: "API unavailable"}, {status: 502});}
}
export {proxy as GET, proxy as POST, proxy as PATCH, proxy as DELETE};
