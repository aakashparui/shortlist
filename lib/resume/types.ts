/** A search the app suggests running, derived from a resume. */
export interface SuggestedSearch {
  /** The role title to search for, e.g. "payments analyst". */
  query: string;
  /** Why this was suggested — shown to the user so the guess is auditable. */
  reason: string;
  /** 0–1. Higher means stronger evidence in the resume. */
  confidence: number;
}

export interface ResumeAnalysis {
  searches: SuggestedSearch[];
  /** Skills detected in the resume, for display. */
  skills: string[];
  /** Location parsed from the resume, if one was recognized. */
  location: string | null;
  /** Which analyzer produced this — "claude" or "heuristic". */
  method: "claude" | "heuristic";
  /** Set when the Claude path was attempted but fell back to the heuristic. */
  fallbackReason?: string;
}
