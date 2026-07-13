import { NextRequest, NextResponse } from "next/server";
import { spawn } from "child_process";
import { randomUUID } from "crypto";
import path from "path";
import type { BacktestConfig, BacktestJobStatus } from "@/lib/types";

// Shared in-process job store. Exported so the [jobId] route can read it.
export const jobs = new Map<
  string,
  BacktestJobStatus & { stdoutChunks: string[] }
>();

const ENGINE_DIR = path.resolve(process.cwd(), "../engine");
const BINARY = path.join(ENGINE_DIR, "backtest");
const OUTPUT_DIR = path.join(ENGINE_DIR, "backtest_results");

// GET /api/backtest — list all jobs
export async function GET() {
  const list = Array.from(jobs.values()).map((j) => ({
    id: j.id,
    status: j.status,
    progress: j.progress,
    message: j.message,
    out_dir: j.out_dir,
  }));
  return NextResponse.json(list);
}

// POST /api/backtest — submit a new backtest job
export async function POST(req: NextRequest) {
  const cfg: BacktestConfig = await req.json();

  const id = randomUUID();
  const job: BacktestJobStatus & { stdoutChunks: string[] } = {
    id,
    status: "RUNNING",
    progress: 0,
    stdoutChunks: [],
  };
  jobs.set(id, job);

  const args = buildArgs(cfg);
  const proc = spawn(BINARY, args, { cwd: ENGINE_DIR });

  proc.stdout.on("data", (chunk: Buffer) => {
    const text = chunk.toString();
    job.stdoutChunks.push(text);
    const m = text.match(/\[\s*([\d.]+)%\]\s*(.*)/);
    if (m) {
      job.progress = parseFloat(m[1]) / 100;
      job.message = m[2].trim();
      jobs.set(id, job);
    }
  });

  proc.stderr.on("data", (chunk: Buffer) => {
    job.message = chunk.toString().slice(0, 200);
    jobs.set(id, job);
  });

  proc.on("close", (code) => {
    if (code === 0) {
      job.status = "DONE";
      job.progress = 1;
    } else {
      job.status = "ERROR";
      job.error = `exit code ${code}`;
    }
    jobs.set(id, job);
  });

  return NextResponse.json({ job_id: id }, { status: 202 });
}

function buildArgs(cfg: BacktestConfig): string[] {
  const args: string[] = [
    `--backtest-output-dir=${OUTPUT_DIR}`,
    `--backtest-capital=${cfg.capital}`,
    `--backtest-instruments=${cfg.instruments}`,
    `--backtest-data-source=${cfg.data_source}`,
    `--backtest-progress`,
  ];
  if (cfg.years && cfg.years > 0 && !cfg.from) {
    args.push(`--backtest-years=${cfg.years}`);
  } else {
    if (cfg.from) args.push(`--backtest-from=${cfg.from}`);
    if (cfg.to) args.push(`--backtest-to=${cfg.to}`);
  }
  if (cfg.strategies && cfg.strategies.length > 0) {
    args.push(`--backtest-strategies=${cfg.strategies.join(",")}`);
  }
  if (cfg.max_concurrent > 0) {
    args.push(`--backtest-max-concurrent=${cfg.max_concurrent}`);
  }
  return args;
}
