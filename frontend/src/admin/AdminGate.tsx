import { useEffect, useRef, useState } from "react";
import { Loader2 } from "../components/icons";
import { setStoredAdminToken, validateAdminToken } from "./adminAuth";

interface AdminGateProps {
  onAuthenticated: () => void;
}

export function AdminGate({ onAuthenticated }: AdminGateProps) {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy) return;
    const value = token.trim();
    if (!value) {
      setError("Paste the admin token to continue.");
      return;
    }
    setBusy(true);
    setError(null);
    const result = await validateAdminToken(value);
    setBusy(false);
    if (result.ok) {
      setStoredAdminToken(value);
      onAuthenticated();
      return;
    }
    if (result.reason === "invalid") {
      setError("That admin token doesn't match. Try again.");
    } else if (result.reason === "rate_limited") {
      setError(`Too many attempts. Try again in ${result.retryAfter ?? 60}s.`);
    } else if (result.reason === "unconfigured") {
      setError(
        "The server has no admin token configured. Ask the operator to set WIKI_TUTOR_ADMIN_TOKEN.",
      );
    } else {
      setError("Couldn't reach the server. Check your connection.");
    }
  }

  return (
    <div className="admin-stage">
      <form className="admin-card admin-card--login" onSubmit={submit}>
        <div className="admin-mark" aria-hidden="true">LS</div>
        <div className="admin-eyebrow">LaSalle Wiki Tutor</div>
        <h1 className="admin-title">Operator dashboard</h1>
        <p className="admin-body">
          IP roster and conversation drill-down for the LaSalle Wiki Tutor
          deployment.
        </p>

        <input
          ref={inputRef}
          type="password"
          autoComplete="off"
          spellCheck={false}
          className="admin-input"
          placeholder="Admin token"
          value={token}
          onChange={(e) => {
            setToken(e.target.value);
            if (error) setError(null);
          }}
          disabled={busy}
          aria-label="Admin token"
          aria-invalid={!!error}
        />
        {error && (
          <div className="admin-error" role="alert">
            {error}
          </div>
        )}
        <button
          type="submit"
          className="admin-submit"
          disabled={busy || !token.trim()}
        >
          {busy ? (
            <>
              <Loader2 className="ico-sm tl-spin" />
              <span>Checking…</span>
            </>
          ) : (
            <span>Sign in</span>
          )}
        </button>
      </form>
    </div>
  );
}
