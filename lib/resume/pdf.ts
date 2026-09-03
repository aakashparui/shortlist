/**
 * Minimum characters before we consider a PDF to have real text. Scanned
 * resumes extract as a handful of stray glyphs or nothing at all, and should
 * be reported as such rather than silently analyzed as an empty document.
 */
const MIN_USEFUL_CHARS = 80;

export class PdfExtractionError extends Error {}

/** Pulls the text layer out of a PDF. Throws if there isn't a usable one. */
export async function extractPdfText(data: Uint8Array): Promise<string> {
  // Imported lazily: pdfjs pulls in a large bundle, and the paste-text path
  // shouldn't pay for it.
  const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");

  // `destroy()` lives on the loading task, not the document proxy — keep the
  // task around so the cleanup in `finally` can reach it.
  const task = pdfjs.getDocument({ data, verbosity: 0 });

  let doc;
  try {
    doc = await task.promise;
  } catch (err) {
    await task.destroy().catch(() => {});
    throw new PdfExtractionError(
      `Could not read the PDF: ${err instanceof Error ? err.message : String(err)}`
    );
  }

  const pages: string[] = [];
  try {
    for (let i = 1; i <= doc.numPages; i++) {
      const page = await doc.getPage(i);
      const content = await page.getTextContent();
      const text = content.items
        .map((item) => ("str" in item ? item.str : ""))
        .join(" ");
      pages.push(text);
    }
  } finally {
    await task.destroy().catch(() => {});
  }

  const text = pages.join("\n").replace(/[ \t]+/g, " ").trim();

  if (text.length < MIN_USEFUL_CHARS) {
    throw new PdfExtractionError(
      "This PDF has no readable text layer — it looks like a scan or an image. " +
        "Paste the resume text instead."
    );
  }

  return text;
}
