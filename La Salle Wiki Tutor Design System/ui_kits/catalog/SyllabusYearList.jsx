// SyllabusYearList.jsx — grouped year-by-year subject list
function SyllabusYearList({ lang, years }) {
  return (
    <div>
      {years.map(y => (
        <div className="year-block" key={y.year}>
          <div className="year-head">
            <div className="year-title">
              {lang === "en" ? `Year ${y.year}` : `Curso ${y.year}`}
            </div>
            <div className="year-meta">{y.ects} ECTS · {y.subjects.length} {lang === "en" ? "subjects" : "asignaturas"}</div>
          </div>
          {y.subjects.map(s => (
            <div className="subj-row" key={s.id}>
              <div className="subj-name">
                {s.name}
                <span className="subj-id">{s.id}</span>
              </div>
              <div className="subj-ects">{s.ects} ECTS</div>
              <div className="subj-tag">{s.kind}</div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
window.SyllabusYearList = SyllabusYearList;
