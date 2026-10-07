import { NextRequest, NextResponse } from "next/server";

// Server-side only — never prefixed NEXT_PUBLIC_, so neither of these reach the
// browser bundle. The browser calls this same-origin route; this route is the
// only thing that knows the backend's real address and shared secret.
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
const APP_SHARED_SECRET = process.env.APP_SHARED_SECRET || "";

// Run this proxy in MUMBAI, next to the backend (AWS ap-south-1) and the users.
//
// Without it Vercel ran the function in its default region, Washington DC (iad1). Every API
// call from a browser in India went Mumbai edge -> Washington -> the Mumbai backend ->
// Washington -> Mumbai: response headers read `x-vercel-id: bom1::iad1::...`. Measured on
// 2026-10-07 the same request took 0.86 s median that way against 0.022 s at the backend
// itself - about 840 ms of every single call was the trip across the world, and a page that
// loads in five dependent steps paid it five times. frontend/vercel.json sets the same
// region for the project; this keeps the route pinned even if that file is ever lost.
export const preferredRegion = "bom1";

async function proxy(req: NextRequest, path: string[]): Promise<NextResponse> {
  const targetUrl = `${BACKEND_URL}/api/${path.join("/")}${req.nextUrl.search}`;

  const headers = new Headers(req.headers);
  headers.delete("host");
  headers.delete("content-length");
  if (APP_SHARED_SECRET) headers.set("x-app-secret", APP_SHARED_SECRET);

  const hasBody = !["GET", "HEAD"].includes(req.method);
  const upstream = await fetch(targetUrl, {
    method: req.method,
    headers,
    body: hasBody ? await req.text() : undefined,
  });

  const contentType = upstream.headers.get("Content-Type") || "application/json";

  // Server-sent events must be piped through untouched — buffering with .text()
  // would never resolve until the stream ended, which for a live feed is never.
  // Only SSE takes this path; every other response keeps the original buffered
  // behaviour byte for byte.
  if (contentType.includes("text/event-stream")) {
    return new NextResponse(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": contentType,
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
        Connection: "keep-alive",
      },
    });
  }

  const body = await upstream.text();
  return new NextResponse(body, {
    status: upstream.status,
    headers: { "Content-Type": contentType },
  });
}

type RouteParams = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, { params }: RouteParams) {
  return proxy(req, (await params).path);
}
export async function POST(req: NextRequest, { params }: RouteParams) {
  return proxy(req, (await params).path);
}
export async function PUT(req: NextRequest, { params }: RouteParams) {
  return proxy(req, (await params).path);
}
export async function DELETE(req: NextRequest, { params }: RouteParams) {
  return proxy(req, (await params).path);
}
export async function PATCH(req: NextRequest, { params }: RouteParams) {
  return proxy(req, (await params).path);
}
