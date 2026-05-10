import { forwardRef, type ReactNode } from "react";

interface ShellProps {
  sidebar: ReactNode;
  topBar: ReactNode;
  thread: ReactNode;
  composer: ReactNode;
  threadOverlay?: ReactNode;
  /**
   * Whether the sidebar is visually open. On mobile (<= 768 px) the
   * sidebar is hidden behind a translateX by default and toggled in via
   * this prop. On wider viewports the prop is ignored — the sidebar is
   * always part of the grid.
   */
  sidebarOpen?: boolean;
  /** Tap-to-close handler for the mobile backdrop. */
  onSidebarClose?: () => void;
}

export const Shell = forwardRef<HTMLDivElement, ShellProps>(function Shell(
  { sidebar, topBar, thread, composer, threadOverlay, sidebarOpen = false, onSidebarClose }: ShellProps,
  threadRef,
) {
  return (
    <div className={`app${sidebarOpen ? " app-sidebar-open" : ""}`}>
      <div className="sidebar-host">{sidebar}</div>
      {/*
        Backdrop only renders when the sidebar is open on mobile. CSS
        hides it on desktop so its `pointer-events` never block clicks.
      */}
      {sidebarOpen && (
        <button
          type="button"
          className="sidebar-backdrop"
          aria-label="Close menu"
          onClick={onSidebarClose}
        />
      )}
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
