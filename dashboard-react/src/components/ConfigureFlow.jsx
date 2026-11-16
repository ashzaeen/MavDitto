import { useRef, useState } from 'react';
import { UploadIcon } from './Icons.jsx';

// The freeform-ingestion flow: upload material (a URL or a file), infer a
// draft config shape, review/edit it, save. Shared by the setup wizard's
// "No, this isn't for UTA" Configure screens and Settings' "Redo brand
// voice" / "Redo component catalog" actions -- same flow either way, see
// the design doc's own note that the review screen "is effectively a
// smaller version of Web Builder's Phase 1 approval loop... worth checking
// whether that UI can be shared" (this is that reuse, one level up: the
// flow itself is shared, not just the review-before-save principle).
//
// The review step deliberately shows the draft as editable JSON rather than
// a bespoke field-by-field form -- honest about the tradeoff: less polished,
// but a real, working "confirm or correct before it's saved" step without
// building a second full form for an already-large feature.

const EXTENSION_KIND = {
  pdf: 'pdf', docx: 'docx', doc: 'docx', pptx: 'pptx', ppt: 'pptx',
  xlsx: 'xlsx', xls: 'xlsx', md: 'markdown', markdown: 'markdown',
};

function kindForFile(file) {
  if (file.type.startsWith('image/')) return 'image';
  const ext = file.name.split('.').pop()?.toLowerCase();
  return EXTENSION_KIND[ext] || null;
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || '');
      resolve(result.slice(result.indexOf(',') + 1));
    };
    reader.onerror = () => reject(reader.error ?? new Error('could not read the file'));
    reader.readAsDataURL(file);
  });
}

const KIND_LABEL = {
  'brand-voice': 'brand voice',
  'components': 'component catalog',
};

export default function ConfigureFlow({ kind, onSaved }) {
  const inputRef = useRef(null);
  const [inputMode, setInputMode] = useState('url');
  const [url, setUrl] = useState('');
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [draftText, setDraftText] = useState(null);
  const [saved, setSaved] = useState(false);

  const label = KIND_LABEL[kind];
  const ingestEndpoint = kind === 'brand-voice'
    ? '/api/setup/ingest-brand-voice' : '/api/setup/ingest-components';

  function pickFile(selected) {
    if (!selected) return;
    if (!kindForFile(selected)) {
      setError('Unsupported file type — use PDF, Word, PowerPoint, Excel, Markdown, or an image.');
      return;
    }
    setError('');
    setFile(selected);
  }

  async function infer(event) {
    event.preventDefault();
    setError('');
    setSaved(false);
    let input;
    if (inputMode === 'url') {
      if (!url.trim()) {
        setError('A URL is required.');
        return;
      }
      input = { kind: 'url', url: url.trim() };
    } else {
      if (!file) {
        setError('A file is required.');
        return;
      }
      input = { kind: kindForFile(file), fileBase64: await fileToBase64(file), mediaType: file.type || undefined };
    }

    setBusy(true);
    try {
      const response = await fetch(ingestEndpoint, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ inputs: [input] }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? `HTTP ${response.status}`);
      setDraftText(JSON.stringify(body.draft, null, 2));
    } catch (e) {
      setError(String(e.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setError('');
    let parsed;
    try {
      parsed = JSON.parse(draftText);
    } catch (e) {
      setError('The draft isn’t valid JSON — fix it before saving.');
      return;
    }
    setBusy(true);
    try {
      const body = kind === 'brand-voice' ? { brandVoice: parsed } : { components: parsed };
      const response = await fetch('/api/setup/save', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      const responseBody = await response.json();
      if (!response.ok) throw new Error(responseBody.error ?? `HTTP ${response.status}`);
      setSaved(true);
      onSaved?.();
    } catch (e) {
      setError(String(e.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack-12">
      {!draftText ? (
        <form className="run-form" style={{ borderTop: 0, paddingTop: 0 }} onSubmit={infer}>
          <div className="chip-row">
            <button type="button" className={`chip ${inputMode === 'url' ? 'active' : ''}`}
                   onClick={() => setInputMode('url')}>
              URL
            </button>
            <button type="button" className={`chip ${inputMode === 'upload' ? 'active' : ''}`}
                   onClick={() => setInputMode('upload')}>
              Upload File
            </button>
          </div>

          {inputMode === 'url' ? (
            <label className="run-field">
              <span className="run-label">Link to {label} material</span>
              <input type="url" placeholder="https://..." value={url}
                    onChange={(e) => setUrl(e.target.value)} disabled={busy} />
            </label>
          ) : (
            <div
              className={`alt-drop ${file ? 'alt-drop--filled' : ''}`}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); pickFile(e.dataTransfer.files?.[0]); }}
              onClick={() => inputRef.current?.click()}
              role="button"
              tabIndex={0}
            >
              <input ref={inputRef} type="file"
                    accept=".pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.md,.markdown,image/*"
                    hidden onChange={(e) => pickFile(e.target.files?.[0])} />
              {file ? (
                <span className="alt-drop-label">{file.name}</span>
              ) : (
                <>
                  <UploadIcon size={20} style={{ color: 'var(--ink-3)' }} />
                  <span className="alt-drop-label">Drop a file here, or click to browse</span>
                </>
              )}
            </div>
          )}
          {error && <div className="run-error">{error}</div>}
          <div className="run-actions">
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {busy ? 'Inferring…' : `Infer ${label}`}
            </button>
          </div>
        </form>
      ) : (
        <div className="stack-12">
          <div className="run-label">
            Review before saving — this is inferred, not guaranteed accurate. Edit directly if anything looks wrong.
          </div>
          <textarea
            className="config-draft-editor"
            value={draftText}
            onChange={(e) => { setDraftText(e.target.value); setSaved(false); }}
            spellCheck={false}
          />
          {error && <div className="run-error">{error}</div>}
          {saved && <div className="card notice notice-good">Saved.</div>}
          <div className="run-actions">
            <button type="button" className="btn btn-primary" onClick={save} disabled={busy}>
              {busy ? 'Saving…' : `Save ${label}`}
            </button>
            <button type="button" className="btn" onClick={() => { setDraftText(null); setSaved(false); }} disabled={busy}>
              Start Over
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
