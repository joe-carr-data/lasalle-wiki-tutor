import { useEffect, useRef, useState } from "react";
import { Loader2, Lock } from "./icons";
import { setStoredToken, validateToken } from "../lib/auth";

interface GateProps {
  /** Called once the token validates. The bare token is also stored. */
  onAuthenticated: () => void;
  /** Default UI language. Detected later from the user's first question. */
  lang?: "en" | "es";
}

const COPY = {
  en: {
    title: "Wiki Tutor — restricted access",
    body: "This evaluation environment is private. Please paste the access token you were given.",
    placeholder: "Access token",
    submit: "Enter",
    submitting: "Checking…",
    invalid: "That token doesn't match. Try again.",
    rateLimited: (s: number) => `Too many attempts. Try again in ${s}s.`,
    network: "Couldn't reach the server. Check your connection and try again.",
    empty: "Paste the token to continue.",
  },
  es: {
    title: "Wiki Tutor — acceso restringido",
    body: "Este entorno de evaluación es privado. Pega el token de acceso que te facilitamos.",
    placeholder: "Token de acceso",
    submit: "Entrar",
    submitting: "Comprobando…",
    invalid: "El token no coincide. Inténtalo de nuevo.",
    rateLimited: (s: number) => `Demasiados intentos. Reintenta en ${s}s.`,
    network: "No se pudo contactar el servidor. Revisa la conexión.",
    empty: "Pega el token para continuar.",
  },
};

export function Gate({ onAuthenticated, lang = "en" }: GateProps) {
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const t = COPY[lang];

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy) return;
    const value = token.trim();
    if (!value) {
      setError(t.empty);
      return;
    }
    setBusy(true);
    setError(null);
    const result = await validateToken(value);
    setBusy(false);
    if (result.ok) {
      setStoredToken(value);
      onAuthenticated();
      return;
    }
    if (result.reason === "rate_limited") {
      setError(t.rateLimited(result.retryAfter ?? 60));
    } else if (result.reason === "network") {
      setError(t.network);
    } else {
      setError(t.invalid);
    }
  }

  return (
    <div className="gate-backdrop">
      <form className="gate-card" onSubmit={submit}>
        <div className="gate-icon" aria-hidden="true">
          <Lock />
        </div>
        <h1 className="gate-title">{t.title}</h1>
        <p className="gate-body">{t.body}</p>
        <input
          ref={inputRef}
          type="password"
          autoComplete="off"
          spellCheck={false}
          className="gate-input"
          placeholder={t.placeholder}
          value={token}
          onChange={(e) => {
            setToken(e.target.value);
            if (error) setError(null);
          }}
          disabled={busy}
          aria-label={t.placeholder}
          aria-invalid={!!error}
        />
        {error && (
          <div className="gate-error" role="alert">
            {error}
          </div>
        )}
        <button type="submit" className="gate-submit" disabled={busy || !token.trim()}>
          {busy ? (
            <>
              <Loader2 className="ico-sm tl-spin" />
              <span>{t.submitting}</span>
            </>
          ) : (
            <span>{t.submit}</span>
          )}
        </button>
      </form>
    </div>
  );
}
