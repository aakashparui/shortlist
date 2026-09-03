import { analyzeResumeHeuristic } from "./heuristic.js";
import { analyzeResumeWithClaude } from "./claude.js";
import type { ResumeAnalysis } from "./types.js";

export { analyzeResumeHeuristic } from "./heuristic.js";
export { analyzeResumeWithClaude, ResumeAnalysisError } from "./claude.js";
export { extractPdfText, PdfExtractionError } from "./pdf.js";
export type { ResumeAnalysis, SuggestedSearch } from "./types.js";

/** Below this there isn't enough text to say anything useful. */
const MIN_RESUME_CHARS = 120;

export class EmptyResumeError extends Error {}

/**
 * Analyzes a resume, preferring Claude when an API key is configured and
 * falling back to the offline heuristic if it is missing or the call fails.
 * The result records which path ran, so the UI can be honest about it.
 */
export async function analyzeResume(resumeText: string): Promise<ResumeAnalysis> {
  const text = resumeText.trim();
  if (text.length < MIN_RESUME_CHARS) {
    throw new EmptyResumeError(
      `Resume text is too short to analyze (${text.length} characters). Paste the full resume.`
    );
  }

  if (!process.env.ANTHROPIC_API_KEY) {
    return analyzeResumeHeuristic(text);
  }

  try {
    const analysis = await analyzeResumeWithClaude(text);
    // An empty suggestion list is a failed analysis, not a valid answer.
    if (analysis.searches.length > 0) return analysis;
    return {
      ...analyzeResumeHeuristic(text),
      fallbackReason: "Claude returned no suggestions.",
    };
  } catch (err) {
    return {
      ...analyzeResumeHeuristic(text),
      fallbackReason: err instanceof Error ? err.message : String(err),
    };
  }
}
