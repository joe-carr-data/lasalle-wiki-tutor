import { forwardRef, type ReactNode } from "react";

interface ShellProps {
  sidebar: ReactNode;
  topBar: ReactNode;
  thread: ReactNode;
  composer: ReactNode;
  threadOverlay?: ReactNode;
}

export const Shell = forwardRef<HTMLDivElement, ShellProps>(function Shell(
  { sidebar, topBar, thread, composer, threadOverlay }: ShellProps,
  threadRef,
) {
  return (
    <div className="app">
      {sidebar}
      <main className="main">
        {topBar}
        <div className="thread-wrap">
          <div className="thread" role="log" aria-live="polite" ref={threadRef}>
            <div className="thread-inner">{thread}</div>
          </div>
          {threadOverlay}
        </div>
        {composer}
      </main>
    </div>
  );
});
