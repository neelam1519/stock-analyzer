"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { SchedulerStatus } from "@/lib/types";

export const JOB_NAMES: Record<string, string> = {
  news: "News",
  open_fill: "Open fill",
  monitor: "Monitor",
  end_of_day: "End of day",
  weekly: "Weekly",
};

export function useScheduler() {
  const query = useQuery({
    queryKey: ["scheduler"],
    queryFn: () => api<SchedulerStatus>("scheduler"),
    refetchInterval: 15_000,
    refetchOnWindowFocus: true,
  });
  const offset = query.data ? Date.parse(query.data.now) - query.dataUpdatedAt : 0;
  return { ...query, offset };
}

export function useNow(offset = 0) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    const first = setTimeout(tick, 0);
    const id = setInterval(tick, 1000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, []);
  return now == null ? null : now + offset;
}

const pad = (value: number) => value.toString().padStart(2, "0");

export function formatSpan(ms: number) {
  const total = Math.max(0, Math.floor(ms / 1000));
  const days = Math.floor(total / 86_400);
  const hours = Math.floor((total % 86_400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (days) return `${days}d ${hours}h`;
  if (hours) return `${hours}h ${pad(minutes)}m`;
  if (minutes) return `${minutes}m ${pad(seconds)}s`;
  return `${seconds}s`;
}

export function countdown(target: string | null, now: number) {
  if (!target) return "—";
  const ms = Date.parse(target) - now;
  return ms <= 0 ? "now" : `in ${formatSpan(ms)}`;
}

export function ago(at: string | null, now: number) {
  if (!at) return "never";
  const ms = now - Date.parse(at);
  return ms < 5000 ? "just now" : `${formatSpan(ms)} ago`;
}

const clock = new Intl.DateTimeFormat("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });
const dayClock = new Intl.DateTimeFormat("en-IN", {
  weekday: "short",
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "Asia/Kolkata",
});
const istDay = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" });
const shortDay = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: "Asia/Kolkata" });

export function istTime(at: string | null, now: number) {
  if (!at) return "—";
  const moment = new Date(at);
  return istDay.format(moment) === istDay.format(new Date(now)) ? clock.format(moment) : dayClock.format(moment);
}

export function istDate(day: string) {
  return shortDay.format(new Date(`${day}T12:00:00+05:30`));
}

const secondsClock = new Intl.DateTimeFormat("en-IN", {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
  timeZone: "Asia/Kolkata",
});

export function istClock(now: number) {
  return secondsClock.format(new Date(now));
}
