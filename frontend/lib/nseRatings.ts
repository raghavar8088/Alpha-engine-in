// NSE Stock Ratings, the Fundamental Rating module's whole-market table.
// Backend: app/services/nse_ratings.py (fetching, storing, the refresher) and
// app/services/nse_ratings_logic.py (every rule), routes under /api/fundamentals/nse-ratings.
import {
  GradeKey,
  PnlStrength,
  RatingPillar,
  ResultsStrength,
  SkippedPillar,
  apiFetch,
} from "./api";

/** The nine tiers, plus the verdict that replaces a number when the data cannot carry one. */
export type OverallKey = GradeKey | "insufficient";

export interface RowFlag {
  k: string;
  lvl: "info" | "warn" | "bad";
  t: string;
}

export interface OverallComponent {
  key: "fundamentals" | "quarter" | "pnl";
  label: string;
  score: number;
  weight: number;
  eff: number;
}

export interface NseRatingRow {
  symbol: string;
  name: string | null;
  screener_name?: string | null;
  series?: string | null;
  sector?: string | null;
  industry?: string | null;
  index_label?: string | null;
  index_tier?: string | null;
  idx_rank?: number | null;

  overall: number | null;
  ovr_key: OverallKey | null;
  ovr_tier: string | null;
  ovr_status?: "rated" | "insufficient";
  ovr_reasons?: string[];
  ovr_formula?: string | null;
  ovr_components?: OverallComponent[];

  fund: number | null;
  fund_key: GradeKey | null;
  fund_tier: string | null;
  coverage: number | null;
  is_lender?: boolean;
  quarter: number | null;
  q_key: GradeKey | null;
  q_tier: string | null;
  pnl: number | null;
  pnl_key: GradeKey | null;
  pnl_tier: string | null;

  qlabel: string | null;
  qend: string | null;
  qyoy_label?: string | null;
  qprev_label?: string | null;
  rev: number | null;
  rev_yoy: number | null;
  rev_qoq: number | null;
  np: number | null;
  np_yoy: number | null;
  np_qoq: number | null;
  np_flag?: "distorted" | "base" | null;
  np_note?: string | null;
  op?: number | null;
  op_yoy?: number | null;
  op_qoq?: number | null;

  roce: number | null;
  roe: number | null;
  de: number | null;
  opm: number | null;
  net_margin?: number | null;
  sales_cagr: number | null;
  profit_cagr: number | null;
  pe: number | null;
  promoter: number | null;
  no_promoter?: boolean;
  institutional?: number | null;
  mcap: number | null;

  r3m: number | null;
  r6m: number | null;
  r1y: number | null;
  r2y: number | null;
  ret_asof?: string | null;
  ret_close?: number | null;
  ret_notes?: string[];
  ret_check?: string | null;
  ret_detail?: Record<
    string,
    {
      date: string | null;
      close?: number;
      factor?: number | null;
      adjusted?: string[];
      unadjusted?: string[];
      reason?: string;
    }
  >;
  screener_1y?: number | null;

  explain?: { strengths: string[]; weaknesses: string[]; risks: string[]; text: string };
  tflags?: RowFlag[];
  sflags?: RowFlag[];
  freshness?: "current" | "due" | "outdated" | "unknown";
  behind?: number | null;
  next_q?: string | null;
  next_due?: string | null;
  pending?: boolean;
  last_meeting?: string | null;
  next_meeting?: string | null;

  basis?: string | null;
  source_url?: string | null;
  fetched_at?: string | null;
  fetch_error?: string | null;
  listed?: boolean;
}

export interface NseRatingsPage {
  rows: NseRatingRow[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  sort: string;
  order: "asc" | "desc";
}

export interface NseRatingsQuery {
  search?: string;
  index?: string;
  sector?: string;
  ratings?: OverallKey[];
  quarter?: string;
  data?: string;
  sort?: string;
  order?: "asc" | "desc";
  page?: number;
  pageSize?: number;
}

export interface NseRatingsStatus {
  running: boolean;
  step: string | null;
  started_at: string | null;
  finished_at: string | null;
  queue: number;
  done: number;
  ok: number;
  failed: number;
  current: string | null;
  note: string | null;
  last_error: string | null;
  queue_reasons?: Record<string, number>;
}

export interface NseRatingsSummary {
  counts: Record<string, number>;
  indices: { key: string; label: string; count: number }[];
  sectors: { key: string; count: number }[];
  ratings: Record<string, number>;
  quarter_bands: Record<string, number>;
  series: Record<string, number>;
  quarter_filters: { key: string; label: string }[];
  data_filters: { key: string; label: string }[];
  jobs: {
    universe?: { at?: string; listed?: number; by_series?: Record<string, number>; in_index?: number } | null;
    meetings?: { at?: string; from?: string; to?: string; symbols?: number } | null;
    returns?: { at?: string; as_of?: string; anchors?: Record<string, string | null>; with_1y?: number } | null;
    errors: Record<string, string>;
  };
  status: NseRatingsStatus;
  methodology: {
    overall_weights: Record<string, number>;
    min_pillars: number;
    min_applicable_coverage: number;
    overdue_insufficient: number;
    rules: string[];
  };
  sources: Record<string, string>;
}

export interface NseRatingDetail {
  row: NseRatingRow;
  rating: {
    score: number | null;
    grade: string;
    grade_key: GradeKey;
    tier?: string;
    verdict: string;
    coverage: number;
    is_lender?: boolean;
    pillars: RatingPillar[];
    skipped: SkippedPillar[];
    summary: string;
    screener_pros?: string[];
    screener_cons?: string[];
    basis?: string;
    source_url?: string;
    data_missing?: string[];
  } | null;
  results: ResultsStrength | null;
  pnl: PnlStrength | null;
  brief: string | null;
  statements: {
    quarters: Record<string, (number | null)[]>;
    quarters_periods: string[];
    profit_loss: Record<string, (number | null)[]>;
    profit_loss_periods: string[];
  } | null;
  about: string | null;
  weights: Record<string, number>;
  refresh?: { ok: boolean; error?: string; quarter?: string | null; live?: boolean };
}

function query(q: NseRatingsQuery, fields?: "export"): string {
  const p = new URLSearchParams();
  if (q.search) p.set("search", q.search);
  if (q.index) p.set("index", q.index);
  if (q.sector) p.set("sector", q.sector);
  if (q.ratings?.length) p.set("rating", q.ratings.join(","));
  if (q.quarter) p.set("quarter", q.quarter);
  if (q.data) p.set("data", q.data);
  if (q.sort) p.set("sort", q.sort);
  if (q.order) p.set("order", q.order);
  if (q.page) p.set("page", String(q.page));
  if (q.pageSize) p.set("page_size", String(q.pageSize));
  if (fields) p.set("fields", fields);
  return p.toString();
}

export async function fetchNseRatings(q: NseRatingsQuery): Promise<NseRatingsPage> {
  return apiFetch(`/api/fundamentals/nse-ratings?${query(q)}`);
}

/** Every row matching the filters, symbol and grade only: what a TradingView export needs. */
export async function fetchNseRatingsExport(q: NseRatingsQuery): Promise<NseRatingsPage> {
  return apiFetch(`/api/fundamentals/nse-ratings?${query({ ...q, page: 1, pageSize: 3000 }, "export")}`);
}

export async function fetchNseRatingsSummary(): Promise<NseRatingsSummary> {
  return apiFetch("/api/fundamentals/nse-ratings/summary");
}

export async function fetchNseRatingDetail(symbol: string): Promise<NseRatingDetail> {
  return apiFetch(`/api/fundamentals/nse-ratings/stock/${encodeURIComponent(symbol)}`);
}

/** Read one company from screener.in now. A live page read takes a few seconds. */
export async function refreshNseRating(symbol: string): Promise<NseRatingDetail> {
  return apiFetch(`/api/fundamentals/nse-ratings/stock/${encodeURIComponent(symbol)}/refresh`, {
    method: "POST",
    timeoutMs: 120000,
  });
}

export type NseRefreshWhat = "due" | "universe" | "meetings" | "returns" | "rebuild";

export async function runNseRatingsRefresh(
  what: NseRefreshWhat = "due",
): Promise<{ started: boolean; reason?: string }> {
  return apiFetch("/api/fundamentals/nse-ratings/refresh", {
    method: "POST",
    body: JSON.stringify({ what }),
  });
}
