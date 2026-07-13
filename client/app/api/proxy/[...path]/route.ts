import { type NextRequest, NextResponse } from 'next/server'

const ENGINE_URL = process.env.ENGINE_URL ?? 'http://localhost:8090'

async function handler(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params
  const upstreamPath = '/' + path.join('/')
  const url = `${ENGINE_URL}${upstreamPath}`

  try {
    const res = await fetch(url, {
      method: request.method,
      headers: { 'Content-Type': 'application/json' },
      body: request.method !== 'GET' && request.method !== 'HEAD' ? request.body : undefined,
      cache: 'no-store',
    })

    const data: unknown = await res.json()
    return NextResponse.json(data, { status: res.status })
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Unknown error'
    return NextResponse.json(
      { error: 'Engine unreachable', detail: message },
      { status: 503 }
    )
  }
}

export const GET = handler
export const POST = handler
export const PUT = handler
export const DELETE = handler
