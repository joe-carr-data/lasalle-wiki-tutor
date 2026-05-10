import { Menu } from "./icons";

interface TopBarProps {
  title: string;
  lang: "en" | "es";
  /** Show a hamburger that opens the sidebar on mobile. Hidden by CSS on wider viewports. */
  onMenuClick?: () => void;
}

export function TopBar({ title, lang, onMenuClick }: TopBarProps) {
  return (
    <header className="topbar">
      <div className="topbar-left">
        {onMenuClick && (
          <button
            type="button"
            className="topbar-menu-btn"
            aria-label="Open menu"
            onClick={onMenuClick}
          >
            <Menu className="ico" />
          </button>
        )}
        <div className="topbar-title">{title}</div>
        <span className="topbar-tag">{lang.toUpperCase()}</span>
      </div>
    </header>
  );
}
