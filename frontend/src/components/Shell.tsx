import type { ReactNode } from "react";

interface ShellProps {
  sidebar: ReactNode;
  topBar: ReactNode;
  thread: ReactNode;
  composer: ReactNode;
}

export function Shell({ sidebar, topBar, thread, composer }: ShellProps) {
  return (
    <div className="app">
      {sidebar}
      <main className="main">
        {topBar}
        <div className="thread" role="log" aria-live="polite">
          <div className="thread-inner">{thread}</div>
        </div>
        {composer}
      </main>
    </div>
  );
}
