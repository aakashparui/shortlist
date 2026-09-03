"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";

type Status = "idle" | "loading" | "error" | "success";

export interface Prefill {
  query: string;
  location: string;
  /** Changes on every pick, so choosing the same suggestion twice still applies. */
  nonce: number;
}

export default function FetchForm({ prefill }: { prefill?: Prefill }) {
  const [query, setQuery] = useState("");
  const [location, setLocation] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [message, setMessage] = useState("");
  const router = useRouter();

  useEffect(() => {
    if (!prefill) return;
    setQuery(prefill.query);
    if (prefill.location) setLocation(prefill.location);
    setStatus("idle");
    setMessage("");
    // Keyed on nonce so re-picking the same role re-applies the prefill.
  }, [prefill?.nonce, prefill?.query, prefill?.location, prefill]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmedQuery = query.trim();
    const trimmedLocation = location.trim();

    // Both are required — the API defaults to US listings without a location.
    // Say so rather than silently doing nothing, which reads as a broken button.
    if (!trimmedQuery || !trimmedLocation) {
      setStatus("error");
      setMessage(
        !trimmedQuery && !trimmedLocation
          ? "Enter a role and a location to search."
          : !trimmedQuery
            ? "Enter a role to search for."
            : "Enter a location — without one the API returns US listings."
      );
      return;
    }

    setStatus("loading");
    setMessage("");

    try {
      const res = await fetch("/api/fetch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: trimmedQuery, location: trimmedLocation }),
      });
      const data = await res.json();

      if (!res.ok) {
        setStatus("error");
        setMessage(data.error ?? "Fetch failed.");
        return;
      }

      setStatus("success");
      setMessage(
        data.newlyAdded === 0
          ? `No new roles — ${data.totalSaved} already saved.`
          : `Added ${data.newlyAdded} new role${data.newlyAdded === 1 ? "" : "s"} (${data.totalSaved} total).`
      );
      router.refresh();
    } catch (err) {
      setStatus("error");
      setMessage(err instanceof Error ? err.message : "Unexpected error.");
    }
  }

  const isLoading = status === "loading";

  return (
    <form className="panel" onSubmit={handleSubmit}>
      <h2 className="panel-title">
        <Search size={13} /> New search
      </h2>

      <div className="field">
        <label className="field-label" htmlFor="q-role">
          Role
        </label>
        <input
          id="q-role"
          type="text"
          placeholder="e.g. payments analyst"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          disabled={isLoading}
          aria-required="true"
          aria-invalid={status === "error" && !query.trim() ? true : undefined}
        />
      </div>

      <div className="field">
        <label className="field-label" htmlFor="q-location">
          Location
        </label>
        <input
          id="q-location"
          type="text"
          placeholder="e.g. India"
          value={location}
          onChange={(e) => setLocation(e.target.value)}
          disabled={isLoading}
          aria-required="true"
          aria-invalid={status === "error" && !location.trim() ? true : undefined}
        />
      </div>

      <button type="submit" className="btn-primary" disabled={isLoading}>
        {isLoading ? (
          <>
            <span className="spinner" /> Fetching…
          </>
        ) : (
          <>
            <Search size={15} /> Fetch roles
          </>
        )}
      </button>

      {message && (
        <p className={`msg ${status === "error" ? "msg-error" : "msg-success"}`}>{message}</p>
      )}
    </form>
  );
}
