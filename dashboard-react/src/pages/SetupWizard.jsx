import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import Header from '../components/Header.jsx';
import ConfigureFlow from '../components/ConfigureFlow.jsx';
import { CheckCircleIcon } from '../components/Icons.jsx';

// First-run "Is this for UTA?" flow -- see the design doc's white-label
// architecture. UTA's own config is pre-committed (Phase 1 of the build),
// so "Yes" here is just a confirmation, not an ingestion step; "No" opens
// the same freeform Configure flow Settings' "Redo" actions use.

export default function SetupWizard() {
  const [choice, setChoice] = useState(null); // null | 'uta' | 'other'
  const [status, setStatus] = useState(null);

  useEffect(() => {
    fetch('/api/config/status').then((r) => r.json()).then(setStatus).catch(() => {});
  }, []);

  return (
    <div className="app">
      <Header active={null} crumbs={['Setup']} />
      <div className="page-body">
        <div>
          <h1 className="h1">Set up MavDitto</h1>
          <div className="meta-line muted">
            Content Writer and Web Builder need a brand voice profile and a
            component catalog before they can run.
          </div>
        </div>

        {choice === null && (
          <div className="wizard-choice-row">
            <button type="button" className="card wizard-choice-card" onClick={() => setChoice('uta')}>
              <div className="wizard-choice-title">Yes, this is for UTA</div>
              <div className="wizard-choice-desc">
                Use UTA's pre-built brand voice profile and Sitecore component catalog — already set up, nothing to upload.
              </div>
            </button>
            <button type="button" className="card wizard-choice-card" onClick={() => setChoice('other')}>
              <div className="wizard-choice-title">No, a different organization</div>
              <div className="wizard-choice-desc">
                Upload your own brand voice material and component library, and MavDitto will infer a starting config from it.
              </div>
            </button>
          </div>
        )}

        {choice === 'uta' && (
          <div className="card notice notice-good">
            <CheckCircleIcon size={15} />
            <span>
              {status?.brandVoice && status?.components
                ? "UTA's brand voice and component catalog are already configured. "
                : 'UTA config is expected to be pre-committed, but at least one file is currently missing. '}
              <Link to="/">Go to Home</Link> or <Link to="/settings">check Settings</Link>.
            </span>
          </div>
        )}

        {choice === 'other' && (
          <div className="stack-24">
            <div className="card section-card">
              <div className="section-head">
                <h2 className="section-title">1. Brand voice</h2>
              </div>
              <ConfigureFlow kind="brand-voice" />
            </div>
            <div className="card section-card">
              <div className="section-head">
                <h2 className="section-title">2. Component catalog</h2>
              </div>
              <ConfigureFlow kind="components" />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
