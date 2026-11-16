import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Header from '../components/Header.jsx';
import RunForm from '../components/RunForm.jsx';
import { HelpCircleIcon } from '../components/Icons.jsx';

// The Migration Validator's own setup screen -- what used to live at "/"
// wearing a "Home" label. Comparing two sites used to be a collapsible card
// sharing space with a results table it had nothing to do with yet -- before
// a run exists there is no table, and after one exists the form is not what
// anyone is there to look at. Splitting it out gives the one thing a person
// does first (paste two URLs) a page with nothing else competing for it.
//
// The explanatory copy ("A page can read as 86% similar...") used to sit
// above the fold as landing-page prose; the rehaul doc asks for action-first
// screens with explanation pushed into a small info affordance instead.

export default function MigrationHome() {
  const navigate = useNavigate();
  const [showInfo, setShowInfo] = useState(false);

  return (
    <div className="app">
      <Header active="migration" crumbs={['Migration Validator']} />
      <div className="page-body">
        <div>
          <div className="run-title-row">
            <h1 className="h1">Did your migration keep everything?</h1>
            <button
              type="button"
              className="icon-btn"
              aria-label="What do similarity and coverage mean?"
              onClick={() => setShowInfo((v) => !v)}
            >
              <HelpCircleIcon size={15} />
            </button>
          </div>
          <div className="meta-line muted">
            Point it at the old site and its replacement. It crawls both, works
            out which old page became which new one, and checks whether the
            words actually survived the move — not just whether the two pages
            look similar.
          </div>
        </div>

        {showInfo && (
          <div className="card notice notice-muted">
            A page can read as 86% similar with 41% of its text unaccounted
            for. Similarity is the number that hides that. Coverage is the
            one that doesn't.
          </div>
        )}

        <RunForm forceOpen onFinished={() => navigate('/migration/results')} />
      </div>
    </div>
  );
}
