"use client";

import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  LineSeries,
  type Time,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { Candle, LinePoint } from "@/lib/types";

const OVERLAY_COLORS: Record<string, string> = { ema20: "#e3a33b", ema50: "#5b8ff9", ema200: "#b07cf0" };

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function PriceChart({
  candles,
  overlays = {},
  intraday,
}: {
  candles: Candle[];
  overlays?: Record<string, LinePoint[]>;
  intraday: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current) return;
    const positive = cssVar("--positive");
    const negative = cssVar("--negative");
    const chart = createChart(container.current, {
      autoSize: true,
      handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: true },
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: cssVar("--muted"),
        fontFamily: "var(--font-geist-mono)",
      },
      grid: { vertLines: { color: cssVar("--line") }, horzLines: { color: cssVar("--line") } },
      rightPriceScale: { borderColor: cssVar("--line") },
      timeScale: { borderColor: cssVar("--line"), timeVisible: intraday, secondsVisible: false },
    });
    const price = chart.addSeries(CandlestickSeries, {
      upColor: positive,
      downColor: negative,
      borderVisible: false,
      wickUpColor: positive,
      wickDownColor: negative,
    });
    const volume = chart.addSeries(HistogramSeries, { priceScaleId: "", priceFormat: { type: "volume" } });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    price.setData(candles.map((c) => ({ time: c.time as Time, open: c.open, high: c.high, low: c.low, close: c.close })));
    volume.setData(
      candles.map((c) => ({
        time: c.time as Time,
        value: c.volume,
        color: `${c.close >= c.open ? positive : negative}66`,
      })),
    );
    for (const [key, points] of Object.entries(overlays)) {
      if (points.length === 0) continue;
      const line = chart.addSeries(LineSeries, {
        color: OVERLAY_COLORS[key] ?? cssVar("--muted"),
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        title: key.toUpperCase(),
      });
      line.setData(points.map((p) => ({ time: p.time as Time, value: p.value })));
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [candles, overlays, intraday]);

  return <div ref={container} className="h-[420px] w-full" />;
}
