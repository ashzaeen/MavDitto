import { useMemo, useState } from 'react';
import { SearchIcon } from '../Icons.jsx';

// Every content type, grouped. Search filters by label and description; the
// selected template's description sits under the list so the writer always
// knows what they picked without hovering.
export default function TemplatePicker({ groups, templates, value, onChange, disabled }) {
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();
  const filtered = useMemo(
    () => templates.filter((t) => !q || `${t.label} ${t.description}`.toLowerCase().includes(q)),
    [templates, q],
  );
  const selected = templates.find((t) => t.key === value);

  return (
    <div className="cw-picker">
      <label className="cw-search">
        <SearchIcon size={13} />
        <input
          type="search"
          placeholder="Find a content type"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Find a content type"
        />
      </label>
      <div className="cw-picker-groups">
        {groups.map((group) => {
          const items = filtered.filter((t) => t.group === group);
          if (!items.length) return null;
          return (
            <div key={group} className="cw-picker-group" role="radiogroup" aria-label={group}>
              <div className="cw-picker-group-label">{group}</div>
              {items.map((t) => (
                <button
                  key={t.key}
                  type="button"
                  role="radio"
                  aria-checked={value === t.key}
                  className={`cw-picker-item ${value === t.key ? 'is-selected' : ''}`}
                  onClick={() => onChange(t.key)}
                  disabled={disabled}
                >
                  {t.label}
                </button>
              ))}
            </div>
          );
        })}
        {!filtered.length && <p className="muted small">No content type matches “{query}”.</p>}
      </div>
      {selected && <p className="cw-picker-desc">{selected.description}</p>}
    </div>
  );
}
