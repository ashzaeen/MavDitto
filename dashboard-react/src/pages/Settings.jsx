import { useEffect, useState } from 'react';
import Header from '../components/Header.jsx';
import ConfigureFlow from '../components/ConfigureFlow.jsx';
import BrandVoiceEditor from '../components/BrandVoiceEditor.jsx';
import KnowledgeBaseEditor from '../components/KnowledgeBaseEditor.jsx';
import { AlertDotIcon } from '../components/Icons.jsx';

// "Redo brand voice" / "Redo component catalog" -- re-opens the same
// freeform intake flow the setup wizard uses, with a confirmation step
// first since redoing either invalidates in-flight Content Writer/Web
// Builder sessions built against the old config, per the design doc.

function RedoSection({ kind, title, description }) {
  const [confirmed, setConfirmed] = useState(false);

  return (
    <div className="card section-card">
      <div className="section-head">
        <h2 className="section-title">{title}</h2>
      </div>
      <p className="meta-line muted" style={{ marginBottom: 12 }}>{description}</p>
      {!confirmed ? (
        <button type="button" className="btn" onClick={() => setConfirmed(true)}>
          Redo {title.toLowerCase()}…
        </button>
      ) : (
        <div className="stack-12">
          <div className="card notice notice-muted">
            <AlertDotIcon />
            <span>
              This replaces the current config and affects every Content
              Writer/Web Builder session started after it's saved.
            </span>
          </div>
          <ConfigureFlow kind={kind} onSaved={() => setConfirmed(false)} />
          <button type="button" className="btn btn-icon btn-small" onClick={() => setConfirmed(false)}>
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}

export default function Settings() {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    fetch('/api/config/status').then((r) => r.json()).then(setStatus).catch(() => {});
  }, []);

  return (
    <div className="app">
      <Header active="settings" crumbs={['Settings']} />
      <div className="page-body">
        <div>
          <h1 className="h1">Settings</h1>
          <div className="meta-line muted">
            Reconfigure the brand voice profile and component catalog Content
            Writer and Web Builder run against.
          </div>
        </div>

        {status && (
          <div className="meta-line muted">
            Brand voice: {status.brandVoice ? 'configured' : 'not configured'} · Component
            catalog: {status.components ? 'configured' : 'not configured'}
          </div>
        )}

        {status?.brandVoice && (
          <div className="card section-card">
            <div className="section-head">
              <h2 className="section-title">Brand voice details</h2>
            </div>
            <p className="meta-line muted" style={{ marginBottom: 12 }}>
              Voice constants, house style, audiences and the tone matrix Content Writer
              writes with and reviews against.
            </p>
            <BrandVoiceEditor />
          </div>
        )}

        <div className="card section-card">
          <div className="section-head">
            <h2 className="section-title">Knowledge base</h2>
          </div>
          <p className="meta-line muted" style={{ marginBottom: 12 }}>
            Verified facts Content Writer may cite. Any figure in a draft that isn't here, in
            the brief, or in the source material is flagged.
          </p>
          <KnowledgeBaseEditor />
        </div>

        <RedoSection
          kind="brand-voice"
          title="Brand voice"
          description="Rebuild the whole profile from new source material."
        />
        <RedoSection
          kind="components"
          title="Component catalog"
          description="The component list Web Builder matches content onto."
        />
      </div>
    </div>
  );
}
