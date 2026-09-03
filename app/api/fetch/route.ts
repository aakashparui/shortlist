import { NextResponse } from "next/server";
import { fetchAllJobs } from "@/lib/sources/index";
import { JSearchApiError, JSearchConfigError } from "@/lib/sources/jsearch";
import { saveJobs } from "@/lib/storage";

/** Pages walked for an interactive fetch, tuned for responsiveness. */
const UI_MAX_PAGES = 2;

export async function POST(request: Request) {
  let body: { query?: string; location?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const query = body.query?.trim();
  const location = body.location?.trim();
  if (!query || !location) {
    return NextResponse.json(
      { error: "Both query and location are required." },
      { status: 400 }
    );
  }

  try {
    // Shallower than the scheduled run: someone is watching a spinner, and
    // each extra page is another ~20s API round trip.
    const jobs = await fetchAllJobs(query, location, { maxPages: UI_MAX_PAGES });
    const { newlyAdded, totalSaved } = await saveJobs(jobs);
    return NextResponse.json({ fetched: jobs.length, newlyAdded, totalSaved });
  } catch (err) {
    if (err instanceof JSearchConfigError || err instanceof JSearchApiError) {
      return NextResponse.json({ error: err.message }, { status: 502 });
    }
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Unexpected error." },
      { status: 500 }
    );
  }
}
