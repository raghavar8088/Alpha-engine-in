import { NextRequest, NextResponse } from "next/server";
import { jobs } from "../route";

type Ctx = { params: Promise<{ jobId: string }> };

// GET /api/backtest/{jobId} — job status + optional sub-resource
export async function GET(req: NextRequest, { params }: Ctx) {
  const { jobId } = await params;
  const job = jobs.get(jobId);
  if (!job) return NextResponse.json({ error: "not found" }, { status: 404 });

  const sub = new URL(req.url).searchParams.get("view");

  if (sub === "equity_curve") {
    // Return equity curve from stdout JSON fragments — not available until DONE.
    if (job.status !== "DONE") {
      return NextResponse.json({ error: "job not complete" }, { status: 409 });
    }
    return NextResponse.json({ equity: [] }); // results written to disk; client reads via /results
  }

  return NextResponse.json({
    id: job.id,
    status: job.status,
    progress: job.progress,
    message: job.message,
    error: job.error,
    out_dir: job.out_dir,
  });
}

// DELETE /api/backtest/{jobId} — remove job from store
export async function DELETE(_req: NextRequest, { params }: Ctx) {
  const { jobId } = await params;
  jobs.delete(jobId);
  return new NextResponse(null, { status: 204 });
}
