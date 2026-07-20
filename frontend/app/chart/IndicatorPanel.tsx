"use client";

/** Indicator on/off + parameter controls for the Chart module.
 *
 * Purely a controlled view over `IndicatorConfig` — it holds no state and
 * triggers no fetches. Selection lives in the chart page's component state
 * (cross-session persistence is deliberately out of scope here). */

export interface IndicatorConfig {
  ema: { on: boolean; periods: number[] };
  sma: { on: boolean; periods: number[] };
  vwap: { on: boolean };
  bollinger: { on: boolean; period: number; mult: number };
  supertrend: { on: boolean; period: number; mult: number };
  rsi: { on: boolean; period: number };
  macd: { on: boolean; fast: number; slow: number; signal: number };
  heikinAshi: boolean;
  logScale: boolean;
  levels: { previousClose: boolean; dayRange: boolean; openingRange: boolean; openingRangeMinutes: number };
}

export const DEFAULT_INDICATORS: IndicatorConfig = {
  ema: { on: false, periods: [20, 50] },
  sma: { on: false, periods: [200] },
  vwap: { on: false },
  bollinger: { on: false, period: 20, mult: 2 },
  supertrend: { on: false, period: 10, mult: 3 },
  rsi: { on: false, period: 14 },
  macd: { on: false, fast: 12, slow: 26, signal: 9 },
  heikinAshi: false,
  logScale: false,
  levels: { previousClose: false, dayRange: false, openingRange: false, openingRangeMinutes: 15 },
};

export const EMA_COLORS = ["#f2b705", "#2196f3", "#ab47bc"];
export const SMA_COLORS = ["#ff7043", "#26c6da", "#8d6e63"];

interface Props {
  config: IndicatorConfig;
  onChange: (next: IndicatorConfig) => void;
  /** Session-anchored indicators only make sense on intraday bars. */
  intraday: boolean;
}

export default function IndicatorPanel({ config, onChange, intraday }: Props) {
  const set = (patch: Partial<IndicatorConfig>) => onChange({ ...config, ...patch });

  const periodList = (
    label: string,
    key: "ema" | "sma",
    colors: string[],
  ) => (
    <div className="row">
      <label className="toggle">
        <input
          type="checkbox"
          checked={config[key].on}
          onChange={(e) => set({ [key]: { ...config[key], on: e.target.checked } } as Partial<IndicatorConfig>)}
        />
        <span>{label}</span>
      </label>
      {config[key].on && (
        <div className="params">
          {config[key].periods.map((p, i) => (
            <span key={i} className="param-chip">
              <i className="swatch" style={{ background: colors[i % colors.length] }} />
              <input
                type="number"
                min={1}
                max={400}
                value={p}
                onChange={(e) => {
                  const periods = [...config[key].periods];
                  periods[i] = Math.max(1, Math.min(400, Number(e.target.value) || 1));
                  set({ [key]: { ...config[key], periods } } as Partial<IndicatorConfig>);
                }}
              />
              {config[key].periods.length > 1 && (
                <button
                  className="chip-x"
                  title="Remove"
                  onClick={() => {
                    const periods = config[key].periods.filter((_, j) => j !== i);
                    set({ [key]: { ...config[key], periods } } as Partial<IndicatorConfig>);
                  }}
                >
                  ×
                </button>
              )}
            </span>
          ))}
          {config[key].periods.length < 3 && (
            <button
              className="chip-add"
              onClick={() => set({ [key]: { ...config[key], periods: [...config[key].periods, 100] } } as Partial<IndicatorConfig>)}
            >
              +
            </button>
          )}
        </div>
      )}
    </div>
  );

  const numberParam = (value: number, onSet: (n: number) => void, min: number, max: number, step = 1) => (
    <input
      type="number"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => {
        const n = Number(e.target.value);
        if (!Number.isNaN(n)) onSet(Math.max(min, Math.min(max, n)));
      }}
    />
  );

  return (
    <div className="panel">
      <div className="group">
        <div className="group-title">Overlays</div>
        {periodList("EMA", "ema", EMA_COLORS)}
        {periodList("SMA", "sma", SMA_COLORS)}

        <div className="row">
          <label className={intraday ? "toggle" : "toggle disabled"}>
            <input
              type="checkbox"
              disabled={!intraday}
              checked={config.vwap.on && intraday}
              onChange={(e) => set({ vwap: { on: e.target.checked } })}
            />
            <span>VWAP {!intraday && <em>(intraday only)</em>}</span>
          </label>
        </div>

        <div className="row">
          <label className="toggle">
            <input
              type="checkbox"
              checked={config.bollinger.on}
              onChange={(e) => set({ bollinger: { ...config.bollinger, on: e.target.checked } })}
            />
            <span>Bollinger</span>
          </label>
          {config.bollinger.on && (
            <div className="params">
              {numberParam(config.bollinger.period, (n) => set({ bollinger: { ...config.bollinger, period: n } }), 2, 200)}
              {numberParam(config.bollinger.mult, (n) => set({ bollinger: { ...config.bollinger, mult: n } }), 0.5, 5, 0.5)}
            </div>
          )}
        </div>

        <div className="row">
          <label className="toggle">
            <input
              type="checkbox"
              checked={config.supertrend.on}
              onChange={(e) => set({ supertrend: { ...config.supertrend, on: e.target.checked } })}
            />
            <span>Supertrend</span>
          </label>
          {config.supertrend.on && (
            <div className="params">
              {numberParam(config.supertrend.period, (n) => set({ supertrend: { ...config.supertrend, period: n } }), 2, 100)}
              {numberParam(config.supertrend.mult, (n) => set({ supertrend: { ...config.supertrend, mult: n } }), 0.5, 10, 0.5)}
            </div>
          )}
        </div>
      </div>

      <div className="group">
        <div className="group-title">Sub-panes</div>
        <div className="row">
          <label className="toggle">
            <input
              type="checkbox"
              checked={config.rsi.on}
              onChange={(e) => set({ rsi: { ...config.rsi, on: e.target.checked } })}
            />
            <span>RSI</span>
          </label>
          {config.rsi.on && (
            <div className="params">{numberParam(config.rsi.period, (n) => set({ rsi: { ...config.rsi, period: n } }), 2, 100)}</div>
          )}
        </div>
        <div className="row">
          <label className="toggle">
            <input
              type="checkbox"
              checked={config.macd.on}
              onChange={(e) => set({ macd: { ...config.macd, on: e.target.checked } })}
            />
            <span>MACD</span>
          </label>
          {config.macd.on && (
            <div className="params">
              {numberParam(config.macd.fast, (n) => set({ macd: { ...config.macd, fast: n } }), 2, 100)}
              {numberParam(config.macd.slow, (n) => set({ macd: { ...config.macd, slow: n } }), 3, 200)}
              {numberParam(config.macd.signal, (n) => set({ macd: { ...config.macd, signal: n } }), 2, 100)}
            </div>
          )}
        </div>
      </div>

      <div className="group">
        <div className="group-title">Reference levels</div>
        <div className="row">
          <label className="toggle">
            <input
              type="checkbox"
              checked={config.levels.previousClose}
              onChange={(e) => set({ levels: { ...config.levels, previousClose: e.target.checked } })}
            />
            <span>Previous close</span>
          </label>
        </div>
        <div className="row">
          <label className="toggle">
            <input
              type="checkbox"
              checked={config.levels.dayRange}
              onChange={(e) => set({ levels: { ...config.levels, dayRange: e.target.checked } })}
            />
            <span>Day high / low</span>
          </label>
        </div>
        <div className="row">
          <label className={intraday ? "toggle" : "toggle disabled"}>
            <input
              type="checkbox"
              disabled={!intraday}
              checked={config.levels.openingRange && intraday}
              onChange={(e) => set({ levels: { ...config.levels, openingRange: e.target.checked } })}
            />
            <span>Opening range {!intraday && <em>(intraday only)</em>}</span>
          </label>
          {config.levels.openingRange && intraday && (
            <div className="params">
              {numberParam(
                config.levels.openingRangeMinutes,
                (n) => set({ levels: { ...config.levels, openingRangeMinutes: n } }),
                5,
                120,
                5,
              )}
              <span className="unit">min</span>
            </div>
          )}
        </div>
      </div>

      <div className="group">
        <div className="group-title">Display</div>
        <div className="row">
          <label className="toggle">
            <input type="checkbox" checked={config.heikinAshi} onChange={(e) => set({ heikinAshi: e.target.checked })} />
            <span>Heikin-Ashi</span>
          </label>
        </div>
        <div className="row">
          <label className="toggle">
            <input type="checkbox" checked={config.logScale} onChange={(e) => set({ logScale: e.target.checked })} />
            <span>Log scale</span>
          </label>
        </div>
        <button className="reset" onClick={() => onChange(DEFAULT_INDICATORS)}>
          Reset all
        </button>
      </div>

      <style jsx>{`
        .panel { display: flex; flex-direction: column; gap: 14px; padding: 14px; background: var(--canvas-soft); border: 1px solid var(--panel-border); border-radius: 10px; width: 232px; flex-shrink: 0; max-height: 620px; overflow-y: auto; }
        .group { display: flex; flex-direction: column; gap: 7px; }
        .group-title { font-size: 10px; font-weight: 800; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-faint); }
        .row { display: flex; flex-direction: column; gap: 5px; }
        .toggle { display: flex; align-items: center; gap: 7px; font-size: 12.5px; font-weight: 600; cursor: pointer; }
        .toggle.disabled { cursor: not-allowed; opacity: 0.5; }
        .toggle input { cursor: inherit; }
        .toggle em { font-style: normal; font-size: 10px; color: var(--text-faint); font-weight: 500; }
        .params { display: flex; flex-wrap: wrap; align-items: center; gap: 5px; padding-left: 21px; }
        .params input { width: 52px; background: var(--panel); border: 1px solid var(--panel-border); border-radius: 6px; padding: 3px 6px; font-size: 11.5px; font-variant-numeric: tabular-nums; }
        .param-chip { display: inline-flex; align-items: center; gap: 4px; }
        .swatch { width: 8px; height: 8px; border-radius: 2px; display: inline-block; flex-shrink: 0; }
        .chip-x, .chip-add { background: var(--panel); border: 1px solid var(--panel-border); border-radius: 5px; width: 19px; height: 19px; line-height: 1; font-size: 12px; color: var(--text-muted); cursor: pointer; padding: 0; }
        .chip-x:hover, .chip-add:hover { color: var(--text); }
        .unit { font-size: 10.5px; color: var(--text-faint); }
        .reset { margin-top: 4px; background: none; border: 1px solid var(--panel-border); border-radius: 7px; padding: 5px 9px; font-size: 11px; font-weight: 700; color: var(--text-muted); cursor: pointer; }
        .reset:hover { color: var(--text); }
      `}</style>
    </div>
  );
}
