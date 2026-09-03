"use client";

import { useRef, useState } from "react";
import { FileText, Upload, Sparkles, Wand2 } from "lucide-react";
import type { ResumeAnalysis } from "@/lib/resume/types";

export default function ResumePanel({
  onPick,
}: {
  onPick: (query: string, location: string | null) => void;
}) {
  const [analysis, setAnalysis] = useState<ResumeAnalysis | null>(null);
  const [pasting, setPasting] = useState(false);
  const [text, setText] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  async function send(init: RequestInit) {
    setLoading(true);
    setError("");
    try {
      const res = await fetch("/api/resume", init);
      const data = await res.json();
      if (!res.ok) {
        setError(data.error ?? "Could not analyze the resume.");
        return;
      }
      setAnalysis(data as ResumeAnalysis);
      setPasting(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unexpected error.");
    } finally {
      setLoading(false);
    }
  }

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    void send({ method: "POST", body: form });
    // Allow re-selecting the same file after a failure.
    e.target.value = "";
  }

  function onAnalyzeText() {
    if (!text.trim()) {
      setError("Paste your resume text first.");
      return;
    }
    void send({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
  }

  return (
    <div className="panel">
      <h2 className="panel-title">
        <FileText size={13} /> From your resume
      </h2>

      {!analysis && !pasting && (
        <>
          <p className="panel-hint">
            Upload your resume and we&apos;ll work out which roles to search for.
          </p>
          <button
            type="button"
            className="btn-primary"
            onClick={() => fileInput.current?.click()}
            disabled={loading}
          >
            {loading ? (
              <>
                <span className="spinner" /> Reading…
              </>
            ) : (
              <>
                <Upload size={15} /> Upload PDF
              </>
            )}
          </button>
          <button
            type="button"
            className="btn-link"
            onClick={() => {
              setPasting(true);
              setError("");
            }}
            disabled={loading}
          >
            or paste the text
          </button>
        </>
      )}

      {pasting && (
        <>
          <textarea
            className="resume-textarea"
            placeholder="Paste your resume here…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={loading}
            rows={7}
          />
          <button
            type="button"
            className="btn-primary"
            onClick={onAnalyzeText}
            disabled={loading}
          >
            {loading ? (
              <>
                <span className="spinner" /> Analyzing…
              </>
            ) : (
              <>
                <Sparkles size={15} /> Analyze
              </>
            )}
          </button>
          <button
            type="button"
            className="btn-link"
            onClick={() => setPasting(false)}
            disabled={loading}
          >
            cancel
          </button>
        </>
      )}

      {analysis && (
        <>
          <div className="analysis-meta">
            <span className={`method-tag method-${analysis.method}`}>
              {analysis.method === "claude" ? (
                <>
                  <Sparkles size={11} /> Claude
                </>
              ) : (
                <>
                  <Wand2 size={11} /> Keyword match
                </>
              )}
            </span>
            {analysis.location && <span className="analysis-loc">{analysis.location}</span>}
          </div>

          {analysis.fallbackReason && (
            <p className="panel-hint panel-hint-warn">
              Claude unavailable ({analysis.fallbackReason}) — used keyword matching.
            </p>
          )}

          <p className="panel-hint">Tap a role to search for it:</p>
          <ul className="suggestion-list">
            {analysis.searches.map((s) => (
              <li key={s.query}>
                <button
                  type="button"
                  className="suggestion"
                  onClick={() => onPick(s.query, analysis.location)}
                  title={s.reason}
                >
                  <span className="suggestion-query">{s.query}</span>
                  <span
                    className="suggestion-bar"
                    style={{ width: `${Math.round(s.confidence * 100)}%` }}
                    aria-hidden="true"
                  />
                  <span className="suggestion-reason">{s.reason}</span>
                </button>
              </li>
            ))}
          </ul>

          {analysis.skills.length > 0 && (
            <div className="skill-chips">
              {analysis.skills.slice(0, 10).map((s) => (
                <span key={s} className="skill-chip">
                  {s}
                </span>
              ))}
            </div>
          )}

          <button
            type="button"
            className="btn-link"
            onClick={() => {
              setAnalysis(null);
              setText("");
            }}
          >
            use a different resume
          </button>
        </>
      )}

      {error && <p className="msg msg-error">{error}</p>}

      <input
        ref={fileInput}
        type="file"
        accept="application/pdf,.pdf"
        onChange={onFile}
        hidden
      />
    </div>
  );
}
