// TEMPORARY wiring-demo page, served at /temp. Remove with the rest of the demo.
"use client";

import { useState, type CSSProperties } from "react";

type DemoEvent = {
  id: number;
  source: string;
  detail: string;
  created_at: string;
};

export default function TempDemo() {
  const [result, setResult] = useState<unknown>(null);
  const [events, setEvents] = useState<DemoEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadEvents() {
    const res = await fetch("/api/temp");
    const data = await res.json();
    setEvents(data.events ?? []);
  }

  async function run() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/temp", { method: "POST" });
      setResult(await res.json());
      await loadEvents();
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main
      style={{
        fontFamily: "system-ui, sans-serif",
        maxWidth: 760,
        margin: "40px auto",
        padding: "0 16px",
      }}
    >
      <h1>Wiring demo (temp)</h1>
      <p>
        FE &rarr; BE &rarr; ml-service over <b>HTTP API</b> and{" "}
        <b>Redis queue</b>, with Postgres writes from both BE and ml-service.
      </p>

      <div style={{ display: "flex", gap: 8, margin: "16px 0" }}>
        <button onClick={run} disabled={loading}>
          {loading ? "Running…" : "Run demo"}
        </button>
        <button onClick={loadEvents} disabled={loading}>
          Refresh events
        </button>
      </div>

      {error && <p style={{ color: "crimson" }}>Error: {error}</p>}

      {result != null && (
        <pre
          style={{
            background: "#f4f4f5",
            padding: 12,
            borderRadius: 8,
            overflowX: "auto",
          }}
        >
          {JSON.stringify(result, null, 2)}
        </pre>
      )}

      <h2>Recent Postgres events ({events.length})</h2>
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            <th style={cell}>id</th>
            <th style={cell}>source</th>
            <th style={cell}>detail</th>
            <th style={cell}>created_at</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id}>
              <td style={cell}>{e.id}</td>
              <td style={cell}>{e.source}</td>
              <td style={cell}>{e.detail}</td>
              <td style={cell}>{e.created_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}

const cell: CSSProperties = {
  border: "1px solid #ddd",
  padding: "6px 10px",
  textAlign: "left",
  fontSize: 14,
};
