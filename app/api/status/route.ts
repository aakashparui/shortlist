import { NextResponse } from "next/server";
import { setStatus } from "@/lib/statuses";
import { JOB_STATUSES, type JobStatus } from "@/lib/types";

function isJobStatus(value: unknown): value is JobStatus {
  return typeof value === "string" && (JOB_STATUSES as readonly string[]).includes(value);
}

export async function POST(request: Request) {
  let body: { key?: unknown; status?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const key = typeof body.key === "string" ? body.key.trim() : "";
  if (!key) {
    return NextResponse.json({ error: "A job key is required." }, { status: 400 });
  }
  if (!isJobStatus(body.status)) {
    return NextResponse.json(
      { error: `status must be one of: ${JOB_STATUSES.join(", ")}.` },
      { status: 400 }
    );
  }

  try {
    await setStatus(key, body.status);
    return NextResponse.json({ key, status: body.status });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Could not save status." },
      { status: 500 }
    );
  }
}
