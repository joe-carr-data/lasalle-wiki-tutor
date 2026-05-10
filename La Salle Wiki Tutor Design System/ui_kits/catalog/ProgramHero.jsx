// ProgramHero.jsx — sky-into-navy gradient hero with serif title + script tag
function ProgramHero({ eyebrow, title, deck, tag }) {
  return (
    <section className="cat-hero">
      <div className="cat-hero-inner">
        <div className="cat-eyebrow">
          {eyebrow.map((e, i) => (
            <React.Fragment key={i}>
              {i > 0 && <span className="sep">·</span>}
              {e}
            </React.Fragment>
          ))}
        </div>
        <h1 className="cat-title">{title}</h1>
        {deck ? <p className="cat-deck">{deck}</p> : null}
      </div>
      {tag ? <div className="cat-tag">{tag}</div> : null}
    </section>
  );
}

window.ProgramHero = ProgramHero;
