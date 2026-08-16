import { Fragment } from "react";

/**
 * Highlight the case-insensitive matches of `query` within `text` using `<mark>` (BP25,
 * R3-S4 L19) — so a searched list shows WHY a row matched. A blank query renders the text
 * unchanged. The query is regex-escaped, so a user typing `.` or `(` is safe.
 */
export function Highlight({ text, query }: { text: string; query: string }) {
  const q = query.trim();
  if (!q) return <>{text}</>;
  const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = text.split(new RegExp(`(${escaped})`, "ig"));
  const lower = q.toLowerCase();
  return (
    <>
      {parts.map((part, i) =>
        part !== "" && part.toLowerCase() === lower ? (
          <mark key={i} className="rounded-sm bg-accent/15 px-0.5 text-inherit">
            {part}
          </mark>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}
