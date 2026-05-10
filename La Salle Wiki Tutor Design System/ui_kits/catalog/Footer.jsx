// Footer.jsx
function Footer({ lang }) {
  return (
    <footer className="cat-footer">
      <div className="cat-footer-inner">
        <div>
          <div className="lock">LaSalle</div>
          <p>Ramon Llull University · Barcelona</p>
          <p>Sant Joan de La Salle, 42 · 08022 Barcelona</p>
        </div>
        <div>
          <h5>{lang === "en" ? "Education" : "Estudios"}</h5>
          <a href="#">{lang === "en" ? "Bachelor's degrees" : "Grados"}</a>
          <a href="#">{lang === "en" ? "Master's degrees" : "Másteres"}</a>
          <a href="#">{lang === "en" ? "PhD programs" : "Doctorado"}</a>
          <a href="#">{lang === "en" ? "Specializations" : "Especializaciones"}</a>
        </div>
        <div>
          <h5>{lang === "en" ? "Connect" : "Contacta"}</h5>
          <a href="#">{lang === "en" ? "Admissions" : "Admisiones"}</a>
          <a href="#">{lang === "en" ? "Visit campus" : "Visita el campus"}</a>
          <a href="#">{lang === "en" ? "International students" : "Estudiantes internacionales"}</a>
          <a href="#">{lang === "en" ? "Wiki Tutor" : "Tutor IA"}</a>
        </div>
      </div>
    </footer>
  );
}
window.Footer = Footer;
