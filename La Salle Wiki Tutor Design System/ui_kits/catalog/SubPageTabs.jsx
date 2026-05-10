// SubPageTabs.jsx
function SubPageTabs({ tabs, value, onChange }) {
  return (
    <div className="cat-tabs" role="tablist">
      {tabs.map(t => (
        <button
          key={t.id}
          className={"cat-tab" + (value === t.id ? " on" : "")}
          onClick={() => onChange(t.id)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
window.SubPageTabs = SubPageTabs;
