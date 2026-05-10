interface CitationChipProps {
  href: string;
  label: string;
}

export function CitationChip({ href, label }: CitationChipProps) {
  return (
    <a
      className="cite-chip"
      href={href}
      target="_blank"
      rel="noreferrer"
      title={href}
    >
      <span className="cite-dot" />
      <span className="cite-chip-label">{label}</span>
    </a>
  );
}
