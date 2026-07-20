import { NextRequest, NextResponse } from "next/server";

// Server-side only — never prefixed NEXT_PUBLIC_, so neither of these reach the
// browser bundle. The browser calls this same-origin route; this route is the
// only thing that knows the backend's real address and shared secret.
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
const APP_SHARED_SECRET = process.env.APP_SHARED_SECRET || "";

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
