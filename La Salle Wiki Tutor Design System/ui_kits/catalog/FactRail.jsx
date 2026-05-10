// FactRail.jsx — sticky right rail with practical facts and apply CTA
function FactRail({ lang, id, facts, ctaLabel, onCta }) {
  return (
    <aside className="cat-rail">
      <div className="fact-card">
        <h4>{lang === "en" ? "At a glance" : "De un vistazo"}</h4>
        <div className="fact-list">
          {facts.map(([lbl, val, mono]) => (
            <div className="fact-line" key={lbl}>
              <div className="lbl">{lbl}</div>
              <div className="val">
                {mono ? <span className="mono">{val}</span> : val}
              </div>
            </div>
          ))}
        </div>
        <button className="fact-cta" onClick={onCta}>{ctaLabel}</button>
        <div className="fact-id">{id}</div>
      </div>
    </aside>
  );
}
window.FactRail = FactRail;
