import { Settings, Share2 } from "./icons";

interface TopBarProps {
  title: string;
  lang: "en" | "es";
}

export function TopBar({ title, lang }: TopBarProps) {
  return (
    <header className="topbar">
      <div className="topbar-left">
        <div className="topbar-title">{title}</div>
        <span className="topbar-tag">{lang.toUpperCase()}</span>
      </div>
      <div className="topbar-right">
        <button className="icon-btn" aria-label="Share">
          <Share2 className="ico-sm" />
        </button>
        <button className="icon-btn" aria-label="Settings">
          <Settings className="ico-sm" />
        </button>
      </div>
    </header>
  );
}
