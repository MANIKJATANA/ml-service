// TEMPORARY wiring-demo proxy: forwards to the backend server-side so the
// browser never needs CORS. Remove with the rest of the demo.
import { NextResponse } from "next/server";

const BACKEND_URL = process.env.BACKEND_URL ?? "http://backend:8000";

export async function POST() {
  const res = await fetch(`${BACKEND_URL}/temp/run`, {
    method: "POST",
    cache: "no-store",
  });
  return NextResponse.json(await res.json(), { status: res.status });
}

export async function GET() {
  const res = await fetch(`${BACKEND_URL}/temp/events`, { cache: "no-store" });
  return NextResponse.json(await res.json(), { status: res.status });
}
