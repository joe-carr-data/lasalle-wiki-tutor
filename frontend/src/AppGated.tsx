import { useEffect, useState } from "react";
import App from "./App";
import { Gate } from "./components/Gate";
import { getStoredToken, onTokenCleared } from "./lib/auth";

/**
 * Top-level wrapper that gates the entire chat UI behind a single shared
 * access token. While unauthenticated, only the Gate screen mounts —
 * crucially, `<App>` is NOT mounted, so its on-load conversation fetch
 * doesn't fire prematurely (it would 401 and create a confusing flash).
 *
 * Re-mounts the Gate if the token is cleared mid-session (e.g. server
 * rotated the secret and a request returned 401). The user re-enters the
 * token and continues.
 */
export default function AppGated() {
  const [authed, setAuthed] = useState<boolean>(() => !!getStoredToken());

  useEffect(() => {
    return onTokenCleared(() => setAuthed(false));
  }, []);

  if (!authed) {
    return <Gate onAuthenticated={() => setAuthed(true)} />;
  }
  // Keying on a stable value forces a fresh App tree if the user logs out
  // and back in (drops in-memory chat state along with the stale token).
  return <App key="authed" />;
}
