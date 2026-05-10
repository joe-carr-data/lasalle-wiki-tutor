import { ChevronDown } from "./icons";

interface JumpToLatestProps {
  visible: boolean;
  lang: "en" | "es";
  onJump: () => void;
}

export function JumpToLatest({ visible, lang, onJump }: JumpToLatestProps) {
  if (!visible) return null;
  return (
    <button
      type="button"
      className="jump-to-latest"
      onClick={onJump}
      aria-label={lang === "es" ? "Ir al último mensaje" : "Jump to latest"}
    >
      <ChevronDown className="ico-sm" />
      <span>{lang === "es" ? "Ir al último" : "Jump to latest"}</span>
    </button>
  );
}
