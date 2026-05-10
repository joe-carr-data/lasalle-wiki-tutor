interface AvatarProps {
  kind: "agent" | "user";
}

export function Avatar({ kind }: AvatarProps) {
  if (kind === "user") {
    return (
      <div className="avatar avatar-user" aria-hidden="true">
        You
      </div>
    );
  }
  return (
    <div className="avatar avatar-agent" aria-label="La Salle Wiki Tutor">
      <span className="avatar-ls">LS</span>
    </div>
  );
}
