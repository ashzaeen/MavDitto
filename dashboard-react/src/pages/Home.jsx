import Header from '../components/Header.jsx';
import ToolCard from '../components/ToolCard.jsx';
import { TOOLS } from '../data/tools.js';

// The hub every tool hangs off of -- replaces the old Home, which was really
// just the Migration Validator's own landing form wearing a "Home" label.
// See the rehaul doc's "Home reimagined as a true hub": clear starting
// points, not one form. A persisted "recent scans" history is a good later
// feature (explicitly deferred -- see the doc's Phase 6), so for now this is
// exactly the curated entry points plus the global search already living in
// the top bar.
export default function Home() {
  return (
    <div className="app">
      <Header active="home" />
      <div className="page-body">
        <div>
          <h1 className="h1">MavDitto</h1>
          <div className="meta-line muted">
            Migration validation, accessibility, and link-health tools for
            UTA's Web Publishing team.
          </div>
        </div>

        <div className="stack-12">
          <div className="section-title">Start something new</div>
          <div className="tool-card-grid">
            {TOOLS.map((t) => (
              <ToolCard key={t.key} icon={t.icon} name={t.name} description={t.description} to={t.to} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
