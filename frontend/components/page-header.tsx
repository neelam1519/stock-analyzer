export function PageHeader({ title, description }: { title: string; description?: string }) {
  return (
    <header className="mb-6">
      <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
      {description ? <p className="mt-1 text-sm text-muted">{description}</p> : null}
    </header>
  );
}

export function ComingSoon({ phase, children }: { phase: number; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line p-6 text-sm text-muted">
      <span className="mb-2 inline-block rounded bg-surface-strong px-2 py-0.5 font-mono text-xs text-foreground">
        Phase {phase}
      </span>
      <p>{children}</p>
    </div>
  );
}
