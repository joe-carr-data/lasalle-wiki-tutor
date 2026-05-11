import { useEffect, useState } from "react";
import { AdminDashboard } from "./AdminDashboard";
import { AdminGate } from "./AdminGate";
import { getStoredAdminToken, onAdminTokenCleared } from "./adminAuth";
import "./admin.css";

/**
 * Top-level wrapper for the /admin route. Parallel to ../AppGated.tsx but
 * uses a separate localStorage key and a separate header so the admin
 * session is fully independent of the evaluator session. Visiting /admin
 * never touches the chat UI's token, and signing out of one does not
 * affect the other.
 */
export default function AdminApp() {
  const [authed, setAuthed] = useState<boolean>(() => !!getStoredAdminToken());

  useEffect(() => {
    return onAdminTokenCleared(() => setAuthed(false));
  }, []);

  if (!authed) {
    return <AdminGate onAuthenticated={() => setAuthed(true)} />;
  }
  return <AdminDashboard />;
}
