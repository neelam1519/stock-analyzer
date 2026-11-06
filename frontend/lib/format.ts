const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2, minimumFractionDigits: 2 });
const dateTime = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Asia/Kolkata",
});

export const formatPrice = (value: number | null) => (value == null ? "—" : inr.format(value));
export const formatDateTime = (value: string | null) => (value ? dateTime.format(new Date(value)) : "—");
export const formatPct = (value: number | null) => (value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`);
export const toneFor = (value: number | null) =>
  value == null || value === 0 ? "text-muted" : value > 0 ? "text-positive" : "text-negative";

const compactInr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

export function formatInrCompact(value: number | null | undefined) {
  if (value == null) return "—";
  const sign = value < 0 ? "−" : "";
  const abs = Math.abs(value);
  if (abs >= 1e7) return `${sign}₹${compactInr.format(abs / 1e7)}Cr`;
  if (abs >= 1e5) return `${sign}₹${compactInr.format(abs / 1e5)}L`;
  return `${sign}₹${compactInr.format(Math.round(abs * 100) / 100)}`;
}

export function formatSignedInr(value: number | null | undefined) {
  if (value == null) return "—";
  return `${value > 0 ? "+" : ""}${formatInrCompact(value)}`;
}
