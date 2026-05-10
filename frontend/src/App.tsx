import { useEffect, useState } from 'react';
import './App.css';

// Minimal scaffold for Phase 5 — verifies that the React app boots and
// that the Vite dev proxy (or production StaticFiles mount) can reach
// the FastAPI backend's /health endpoint. Real chat UI replaces this in
// the next slice (Sidebar + Composer + ReasoningTimeline + …).

type Health = { status: string; assistant: string };

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch('/health')
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return (await r.json()) as Health;
      })
      .then(setHealth)
      .catch((e) => setError(String(e)));
  }, []);

  return (
    <main style={{ padding: '32px', fontFamily: 'system-ui, sans-serif' }}>
      <h1>LaSalle Wiki Tutor — frontend scaffold</h1>
      <p>
        Phase 5 is alive. The chat UI lands here in subsequent slices.
      </p>
      <h2>Backend connectivity</h2>
      {error && (
        <p style={{ color: 'crimson' }}>
          /health failed: {error} (start the FastAPI backend with{' '}
          <code>uv run uvicorn streaming:app --port 8000</code>)
        </p>
      )}
      {health && (
        <pre
          style={{
            background: '#f1f4f8',
            padding: '12px 16px',
            borderRadius: 8,
            display: 'inline-block',
          }}
        >
          {JSON.stringify(health, null, 2)}
        </pre>
      )}
    </main>
  );
}
