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
    </header>
  );
}
