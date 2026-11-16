import { useMemo, useState } from 'react';
import Header from '../components/Header.jsx';
import ToolCard from '../components/ToolCard.jsx';
import { SearchIcon } from '../components/Icons.jsx';
import { TOOLS } from '../data/tools.js';

// The overflow destination once the suite outgrows Home's curated row --
// see the rehaul doc's All Tools hub. Exhaustive rather than curated, same
// ToolCard, plus a filter so it stays browsable as the list grows.
export default function AllTools() {
  const [query, setQuery] = useState('');

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return TOOLS;
    return TOOLS.filter(
      (t) => t.name.toLowerCase().includes(q) || t.description.toLowerCase().includes(q)
    );
  }, [query]);

  return (
    <div className="app">
      <Header active="all-tools" crumbs={['All Tools']} />
      <div className="page-body">
        <div>
          <h1 className="h1">All Tools</h1>
          <div className="meta-line muted">Every capability MavDitto offers, in one place.</div>
        </div>

        <label className="card search-box" style={{ maxWidth: 360 }}>
          <span className="sr-only">Filter Tools</span>
          <SearchIcon style={{ color: 'var(--ink-3)', flex: 'none' }} />
          <input
            type="search"
            placeholder="Filter by name or keyword"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>

        {visible.length === 0 ? (
          <div className="card empty-card">
            <p className="muted">No tool matches "{query}".</p>
          </div>
        ) : (
          <div className="tool-card-grid">
            {visible.map((t) => (
              <ToolCard key={t.key} icon={t.icon} name={t.name} description={t.description} to={t.to} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
