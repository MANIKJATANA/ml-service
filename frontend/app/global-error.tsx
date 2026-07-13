"use client";

/**
 * Root-layout fallback — the only boundary above the root layout, so it must render its
 * own <html>/<body> and can't use the app's Tailwind/fonts/providers (they live in the
 * layout it's replacing). Kept deliberately minimal with inline styles.
 */
export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100dvh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "1rem",
          padding: "1rem",
          textAlign: "center",
          fontFamily: "system-ui, -apple-system, sans-serif",
          background: "#f8f9fa",
          color: "#0d1729",
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: "1.5rem" }}>Something went wrong</h1>
          <p style={{ marginTop: "0.25rem", color: "#5a6578" }}>Please reload the page.</p>
        </div>
        <button
          type="button"
          onClick={() => reset()}
          style={{
            padding: "0.5rem 1rem",
            borderRadius: "8px",
            border: "1px solid #e3e8ef",
            background: "#ffffff",
            color: "#0d1729",
            fontSize: "0.875rem",
            cursor: "pointer",
          }}
        >
          Try again
        </button>
      </body>
    </html>
  );
}
