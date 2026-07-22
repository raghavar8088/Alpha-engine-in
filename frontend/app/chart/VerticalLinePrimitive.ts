/** A vertical line spanning the full pane height at one point in time.
 *
 * Every other drawing here (trendline, zone, position box…) is a LineSeries or
 * BaselineSeries — a value plotted against time. That representation cannot
 * express this shape at all: a series is one price per timestamp, and a
 * vertical line is every price at a single timestamp. It has to be drawn
 * directly on the canvas, which is exactly what the Series Primitives API is
 * for. This is adapted from TradingView's own reference implementation
 * (lightweight-charts plugin-examples/src/plugins/vertical-line), trimmed to
 * just the line — no axis label — since nothing here needs one yet.
 */

import type { CanvasRenderingTarget2D } from "fancy-canvas";
import type {
  Coordinate,
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  SeriesOptionsMap,
  SeriesType,
  Time,
} from "lightweight-charts";

/** Centres a `widthMedia`-wide stroke on `positionMedia`, in bitmap pixels — the
 * same rounding TradingView's own primitives use so a 1px line lands crisply
 * rather than straddling two device pixels on a high-DPI screen. */
function centeredBitmapRect(positionMedia: number, pixelRatio: number, widthMedia: number) {
  const scaled = Math.round(pixelRatio * positionMedia);
  const bitmapWidth = Math.round(widthMedia * pixelRatio);
  const offset = Math.floor(bitmapWidth * 0.5);
  return { position: scaled - offset, length: bitmapWidth };
}

class VertLineRenderer implements IPrimitivePaneRenderer {
  constructor(private x: Coordinate | null, private color: string, private width: number) {}

  draw(target: CanvasRenderingTarget2D): void {
    target.useBitmapCoordinateSpace((scope) => {
      if (this.x === null) return;
      const ctx = scope.context;
      const rect = centeredBitmapRect(this.x, scope.horizontalPixelRatio, this.width);
      ctx.fillStyle = this.color;
      ctx.fillRect(rect.position, 0, rect.length, scope.bitmapSize.height);
    });
  }
}

class VertLinePaneView implements IPrimitivePaneView {
  private x: Coordinate | null = null;

  constructor(private source: VertLine) {}

  update(): void {
    this.x = this.source.chart.timeScale().timeToCoordinate(this.source.time);
  }

  renderer(): IPrimitivePaneRenderer {
    return new VertLineRenderer(this.x, this.source.color, this.source.width);
  }
}

export class VertLine implements ISeriesPrimitive<Time> {
  readonly chart: IChartApi;
  readonly series: ISeriesApi<SeriesType>;
  time: Time;
  color: string;
  width: number;
  private view: VertLinePaneView;

  constructor(chart: IChartApi, series: ISeriesApi<keyof SeriesOptionsMap>, time: Time, color: string, width = 1) {
    this.chart = chart;
    this.series = series;
    this.time = time;
    this.color = color;
    this.width = width;
    this.view = new VertLinePaneView(this);
  }

  updateAllViews(): void {
    this.view.update();
  }

  paneViews(): IPrimitivePaneView[] {
    return [this.view];
  }
}
