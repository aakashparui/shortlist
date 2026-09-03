import Anthropic from "@anthropic-ai/sdk";
import { zodOutputFormat } from "@anthropic-ai/sdk/helpers/zod";
import { z } from "zod";
import type { ResumeAnalysis } from "./types.js";

/** Resume text beyond this is trimmed by page, never mid-analysis. */
const MAX_RESUME_CHARS = 60_000;

const AnalysisSchema = z.object({
  searches: z
    .array(
      z.object({
        query: z
          .string()
          .describe("A job title to search job boards for, lowercase, no seniority prefix"),
        reason: z
          .string()
          .describe("One short sentence citing evidence from the resume"),
        confidence: z.number().describe("0 to 1, how strongly the resume supports this role"),
      })
    )
    .describe("Between 3 and 5 role titles, strongest first"),
  skills: z.array(z.string()).describe("Concrete tools and technologies named in the resume"),
  location: z
    .string()
    .describe("The candidate's location, or an empty string if none is stated"),
});

const SYSTEM_PROMPT = `You read a candidate's resume and decide which job titles they should search for on job boards.

Return role titles as they are actually posted by employers — "payments analyst", not "payments professional"; "frontend developer", not "React expert". Prefer titles a recruiter would use in a listing.

Base every suggestion on evidence in the resume. Favour the candidate's recent and repeated work over a single passing mention. Include one adjacent role they are plausibly qualified for, if there is a clear one.

Do not include a seniority prefix in the query — job boards match better without it.`;

export class ResumeAnalysisError extends Error {}

/**
 * Analyzes a resume with Claude. Throws ResumeAnalysisError on any failure so
 * the caller can fall back to the offline heuristic.
 */
export async function analyzeResumeWithClaude(resumeText: string): Promise<ResumeAnalysis> {
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) {
    throw new ResumeAnalysisError("ANTHROPIC_API_KEY is not set.");
  }

  const trimmed = resumeText.slice(0, MAX_RESUME_CHARS);
  const client = new Anthropic({ apiKey });

  let response;
  try {
    response = await client.messages.parse({
      model: "claude-opus-5",
      max_tokens: 16000,
      system: SYSTEM_PROMPT,
      output_config: {
        format: zodOutputFormat(AnalysisSchema),
        effort: "low",
      },
      messages: [
        {
          role: "user",
          content: `Here is the resume:\n\n${trimmed}`,
        },
      ],
    });
  } catch (err) {
    if (err instanceof Anthropic.AuthenticationError) {
      throw new ResumeAnalysisError("ANTHROPIC_API_KEY was rejected.");
    }
    if (err instanceof Anthropic.RateLimitError) {
      throw new ResumeAnalysisError("Anthropic API rate limit reached.");
    }
    if (err instanceof Anthropic.APIError) {
      throw new ResumeAnalysisError(`Anthropic API error ${err.status}: ${err.message}`);
    }
    throw new ResumeAnalysisError(
      err instanceof Error ? err.message : "Unexpected error calling Anthropic."
    );
  }

  if (response.stop_reason === "refusal") {
    throw new ResumeAnalysisError("The model declined to analyze this document.");
  }

  const parsed = response.parsed_output;
  if (!parsed) {
    throw new ResumeAnalysisError("Could not parse the model's response.");
  }

  return {
    searches: parsed.searches
      .filter((s) => s.query.trim().length > 0)
      .slice(0, 5)
      .map((s) => ({
        query: s.query.trim().toLowerCase(),
        reason: s.reason.trim(),
        // Clamp: the schema describes the range but doesn't enforce it.
        confidence: Math.max(0, Math.min(1, s.confidence)),
      })),
    skills: parsed.skills.map((s) => s.trim()).filter(Boolean),
    location: parsed.location.trim() || null,
    method: "claude",
  };
}
