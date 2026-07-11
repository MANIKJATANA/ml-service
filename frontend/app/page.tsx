// F0 placeholder — also a smoke check that the Tailwind v4 token pipeline renders
// (bg-canvas / rounded-card / hairline / shadow / text tokens / accent).
// Replaced by the role-based redirect in F1 (decisions/0030).
export default function Home() {
  return (
    <main className="flex min-h-dvh items-center justify-center bg-canvas p-6">
      <div className="rounded-card border border-hairline bg-surface p-8 shadow-sm">
        <h1 className="text-display-md text-ink">Photo Distribution</h1>
        <p className="mt-2 text-body text-ink-muted">
          Frontend foundations ready — <span className="font-medium text-accent">F0</span>.
        </p>
      </div>
    </main>
  );
}
