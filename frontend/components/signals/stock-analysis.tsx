"use client";

import { useQuery } from "@tanstack/react-query";

import { Card } from "@/components/card";
import { ActionBadge, ScoreBar, VerdictBadge } from "@/components/signals/badges";
import { api } from "@/lib/api";
import { formatPrice } from "@/lib/format";
import type { StockAnalysis } from "@/lib/types";

const INDICATOR_LABELS: [string, string, number][] = [
  ["rsi14", "RSI 14", 0],
  ["adx14", "ADX 14", 0],
  ["atr14", "ATR 14", 2],
  ["volume_ratio20", "Vol / 20d", 2],
  ["high52w_distance_pct", "From 52w high %", 1],
  ["relative_strength_nifty", "RS vs NIFTY 3m %", 1],
  ["macd", "MACD", 2],
  ["macd_signal", "MACD signal", 2],
];

function List({ title, items, tone }: { title: string; items: string[]; tone: string }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h3 className={`mb-1 text-xs font-medium ${tone}`}>{title}</h3>
      <ul className="grid gap-1 text-sm">
        {items.map((item) => (
          <li key={item} className="text-muted">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function StockAnalysisCards({ symbol }: { symbol: string }) {
  const { data } = useQuery({
    queryKey: ["analysis", symbol],
    queryFn: () => api<StockAnalysis>(`stocks/${encodeURIComponent(symbol)}/analysis`),
  });
  if (!data) return null;
  const { signal, indicators, research } = data;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title={`Signal${signal ? ` · ${signal.as_of}` : ""}`} action={signal ? <ActionBadge action={signal.action} /> : null}>
        {signal ? (
          <div className="grid gap-3">
            <ScoreBar score={signal.score} />
            {signal.entry ? (
              <div className="grid grid-cols-3 gap-2 font-mono text-sm">
                <div>
                  <div className="text-xs text-muted">Entry</div>
                  {formatPrice(signal.entry)}
                </div>
                <div>
                  <div className="text-xs text-muted">Stop</div>
                  <span className="text-negative">{formatPrice(signal.stop)}</span>
                </div>
                <div>
                  <div className="text-xs text-muted">Target</div>
                  <span className="text-positive">{formatPrice(signal.target)}</span>
                </div>
              </div>
            ) : null}
            <p className="text-xs text-muted">{signal.rationale}</p>
            {indicators ? (
              <dl className="grid grid-cols-2 gap-x-4 gap-y-1 border-t border-line pt-3 text-xs sm:grid-cols-4">
                {INDICATOR_LABELS.map(([key, label, digits]) => (
                  <div key={key}>
                    <dt className="text-muted">{label}</dt>
                    <dd className="font-mono">{indicators[key] == null ? "—" : Number(indicators[key]).toFixed(digits)}</dd>
                  </div>
                ))}
              </dl>
            ) : null}
          </div>
        ) : (
          <p className="text-sm text-muted">No signal yet. Run analysis from Settings.</p>
        )}
      </Card>

      <Card title="AI research" action={research ? <VerdictBadge verdict={research.verdict} /> : null}>
        {research ? (
          <div className="grid gap-3">
            <p className="text-sm">{research.summary}</p>
            <List title="Bull case" items={research.bull_case} tone="text-positive" />
            <List title="Bear case" items={research.bear_case} tone="text-negative" />
            <List title="Key risks" items={research.key_risks} tone="text-accent" />
            <p className="font-mono text-[11px] text-muted">
              {research.model} · {research.as_of} · conviction {(research.conviction * 100).toFixed(0)}%
            </p>
          </div>
        ) : (
          <p className="text-sm text-muted">Research notes are written for the top BUY candidates when you run “Research top picks”.</p>
        )}
      </Card>
    </div>
  );
}
