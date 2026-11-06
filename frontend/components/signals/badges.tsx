import type { Regime, SignalItem } from "@/lib/types";

const ACTION_TONE: Record<SignalItem["action"], string> = {
  BUY: "bg-positive/15 text-positive border-positive/30",
  SELL: "bg-negative/15 text-negative border-negative/30",
  HOLD: "bg-surface-strong text-muted border-line",
};

const VERDICT_TONE: Record<string, string> = {
  buy: "text-positive",
  wait: "text-accent",
  avoid: "text-negative",
};

const REGIME_TONE: Record<Regime["name"], string> = {
  bull: "text-positive",
  neutral: "text-accent",
  bear: "text-negative",
  volatile: "text-negative",
  unknown: "text-muted",
};

export function ActionBadge({ action }: { action: SignalItem["action"] }) {
  return <span className={`rounded border px-1.5 py-0.5 font-mono text-[11px] font-semibold ${ACTION_TONE[action]}`}>{action}</span>;
}

export function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict) return <span className="text-xs text-muted">—</span>;
  return <span className={`font-mono text-xs font-semibold uppercase ${VERDICT_TONE[verdict] ?? "text-muted"}`}>AI: {verdict}</span>;
}

export function regimeTone(name: Regime["name"]) {
  return REGIME_TONE[name] ?? "text-muted";
}

export function ScoreBar({ score }: { score: number }) {
  const tone = score >= 70 ? "bg-positive" : score <= 35 ? "bg-negative" : "bg-accent";
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-16 overflow-hidden rounded bg-surface-strong">
        <div className={`h-full ${tone}`} style={{ width: `${Math.max(2, Math.min(100, score))}%` }} />
      </div>
      <span className="w-8 text-right font-mono text-xs tabular-nums">{score.toFixed(0)}</span>
    </div>
  );
}
