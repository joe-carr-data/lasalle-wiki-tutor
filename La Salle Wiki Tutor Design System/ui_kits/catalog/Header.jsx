// Header.jsx — top nav with wordmark + language toggle
const { useState: useStateH } = React;

function Header({ lang, onLang, onApply }) {
  const items = lang === "en"
    ? ["Education", "Research", "Faculty", "Campus Life", "Admissions"]
    : ["Estudios",  "Investigación", "Profesorado", "Vida en el Campus", "Admisiones"];
  return (
    <header className="cat-header">
      <div className="cat-header-inner">
        <a className="cat-wordmark" href="#">
          <span className="mark">LS</span>
          <span>
            LaSalle
            <span className="small">Ramon Llull · Barcelona</span>
          </span>
        </a>
        <nav className="cat-nav">
          {items.map((it, i) => (
            <a key={it} href="#" className={i === 0 ? "on" : ""}>{it}</a>
          ))}
        </nav>
        <div className="cat-lang">
          <button className={lang === "en" ? "on" : ""} onClick={() => onLang("en")}>EN</button>
          <button className={lang === "es" ? "on" : ""} onClick={() => onLang("es")}>ES</button>
        </div>
        <button className="cat-apply" onClick={onApply}>
          {lang === "en" ? "Apply" : "Inscríbete"}
        </button>
      </div>
    </header>
  );
}

window.Header = Header;
