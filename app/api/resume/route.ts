import { NextResponse } from "next/server";
import {
  analyzeResume,
  extractPdfText,
  EmptyResumeError,
  PdfExtractionError,
} from "@/lib/resume/index";

/** Refuse oversized uploads before reading them into memory. */
const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

export async function POST(request: Request) {
  const contentType = request.headers.get("content-type") ?? "";

  let resumeText: string;

  try {
    if (contentType.includes("multipart/form-data")) {
      const form = await request.formData();
      const file = form.get("file");

      if (!(file instanceof File)) {
        return NextResponse.json({ error: "No file was uploaded." }, { status: 400 });
      }
      if (file.size > MAX_UPLOAD_BYTES) {
        return NextResponse.json(
          { error: "That file is larger than 10MB." },
          { status: 400 }
        );
      }
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        return NextResponse.json(
          { error: "Only PDF files are supported. Paste the text for other formats." },
          { status: 400 }
        );
      }

      const bytes = new Uint8Array(await file.arrayBuffer());
      resumeText = await extractPdfText(bytes);
    } else {
      const body = (await request.json()) as { text?: unknown };
      if (typeof body.text !== "string") {
        return NextResponse.json({ error: "Provide resume text." }, { status: 400 });
      }
      resumeText = body.text;
    }
  } catch (err) {
    if (err instanceof PdfExtractionError) {
      return NextResponse.json({ error: err.message }, { status: 400 });
    }
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Could not read the resume." },
      { status: 400 }
    );
  }

  try {
    const analysis = await analyzeResume(resumeText);
    return NextResponse.json(analysis);
  } catch (err) {
    if (err instanceof EmptyResumeError) {
      return NextResponse.json({ error: err.message }, { status: 400 });
    }
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Could not analyze the resume." },
      { status: 500 }
    );
  }
}
