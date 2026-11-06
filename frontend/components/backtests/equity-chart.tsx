"use client";

import { ColorType, createChart, LineSeries, type Time } from "lightweight-charts";
import { useEffect, useRef } from "react";

import type { BacktestDetail } from "@/lib/types";

function cssVar(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function EquityChart({ points }: { points: BacktestDetail["equity"] }) {
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!container.current || points.length === 0) return;
    const chart = createChart(container.current, {
      autoSize: true,
      handleScroll: false,
      handleScale: false,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: cssVar("--muted") },
      grid: { vertLines: { color: cssVar("--line") }, horzLines: { color: cssVar("--line") } },
      rightPriceScale: { borderColor: cssVar("--line") },
      timeScale: { borderColor: cssVar("--line") },
    });
    const start = points[0].equity;
    const benchStart = points.find((p) => p.benchmark != null)?.benchmark ?? null;
    const strategy = chart.addSeries(LineSeries, { color: cssVar("--accent"), lineWidth: 2, title: "Strategy", priceLineVisible: false });
    strategy.setData(points.map((p) => ({ time: p.time as Time, value: (p.equity / start) * 100 })));
    if (benchStart) {
      const bench = chart.addSeries(LineSeries, {
        color: cssVar("--muted"),
        lineWidth: 1,
        lineStyle: 2,
        title: "NIFTY 50",
        priceLineVisible: false,
      });
      bench.setData(
        points.filter((p) => p.benchmark != null).map((p) => ({ time: p.time as Time, value: ((p.benchmark as number) / benchStart) * 100 })),
      );
    }
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [points]);

  return <div ref={container} className="h-[300px] w-full" />;
}
