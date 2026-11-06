"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ITEMS } from "@/lib/nav";

export function SidebarNav() {
  const pathname = usePathname();
  return (
    <nav className="flex gap-1 overflow-x-auto md:flex-col">
      {NAV_ITEMS.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`whitespace-nowrap rounded-md px-3 py-2 text-sm transition-colors ${
              active ? "bg-surface-strong text-foreground" : "text-muted hover:bg-surface hover:text-foreground"
            }`}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function SidebarNavFallback() {
  return (
    <nav className="flex gap-1 overflow-x-auto md:flex-col">
      {NAV_ITEMS.map((item) => (
        <Link key={item.href} href={item.href} className="whitespace-nowrap rounded-md px-3 py-2 text-sm text-muted">
          {item.label}
        </Link>
      ))}
    </nav>
  );
}
