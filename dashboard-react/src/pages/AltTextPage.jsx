import { useEffect, useRef, useState } from 'react';
import Header from '../components/Header.jsx';
import { useData } from '../data/useData.jsx';
import MascotLoader from '../components/MascotLoader.jsx';
import {
  AlertCircleIcon, AlertDotIcon, CheckIcon, CopyIcon, DownloadIcon,
  ImageIcon, SettingsIcon, UploadIcon, XCircleIcon,
} from '../components/Icons.jsx';

// A standalone utility, not tied to any migration run: describe one image, or
// a whole batch of them, or every real image on one page, in a professional
// tone appropriate for a university site. The two modes share a unified run
// card: Image Scan collects a batch (pasted and/or picked, up to
// MAX_UPLOAD_TOTAL) and posts it as one request to /api/alt-text/images; a
// URL posts to /api/alt-text/page and gets one row back per image found there.

const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];

// Two different entry points into the same pending batch, each with its own
// ceiling: pasting is a single clipboard payload someone could accidentally
// dump a huge folder's worth of images into, so it is capped tighter per
// paste than a deliberate multi-file picker/drop is. MAX_UPLOAD_TOTAL is the
// hard ceiling either way -- a paste that would push the batch past it is
// trimmed to whatever room is left, same as a picked/dropped selection.
const MAX_PASTE_PER_EVENT = 20;
const MAX_UPLOAD_TOTAL = 50;

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

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

function toCsv(rows) {
  const escape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const head = ['src', 'current alt', 'suggested alt', 'status'];
  const body = rows.map((r) => {
    const o = r.outcome;
    const status = !o ? '' : o.generated ? 'generated' : o.isDecorative ? 'decorative' : o.skippedReason;
    return [r.src, r.currentAlt, o?.generated ? o.altText : '', status].map(escape).join(',');
  });
  return [head.map(escape).join(','), ...body].join('\n');
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  if (!text) return null;
  return (
    <button
      type="button"
      className="btn btn-icon btn-small"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1400);
        } catch {
          /* clipboard permission denied; the text is still visible to select */
        }
      }}
    >
      {copied ? <CheckIcon size={11} style={{ color: 'var(--status-success-text)' }} /> : <CopyIcon size={11} />}
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

function toBatchCsv(rows) {
  const escape = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
  const head = ['file name', 'suggested alt', 'status'];
  const body = rows.map((r) => {
    const o = r.outcome;
    const status = !o ? '' : o.generated ? 'generated' : o.isDecorative ? 'decorative' : o.skippedReason;
    return [r.name, o?.generated ? o.altText : '', status].map(escape).join(',');
  });
  return [head.map(escape).join(','), ...body].join('\n');
}

// --- upload or paste a batch of images ----------------------------------

let pendingIdSeq = 0;

function UploadPanel() {
  const [pending, setPending] = useState([]); // {id, file, name, mediaType, previewUrl}
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [results, setResults] = useState(null); // [{name, outcome}]
  const [budgetSummary, setBudgetSummary] = useState('');
  const inputRef = useRef(null);
  const dropRef = useRef(null);

  // Object URLs are per-blob, not per-render -- revoke every one still
  // outstanding when the panel itself goes away, not just on an explicit
  // Clear (switching to Page Scan and back should not leak them).
  useEffect(() => () => {
    pending.forEach((item) => URL.revokeObjectURL(item.previewUrl));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function addFiles(files, { capPerAdd } = {}) {
    const incoming = Array.from(files || []);
    const supported = incoming.filter((f) => ACCEPTED_TYPES.includes(f.type));
    const unsupportedCount = incoming.length - supported.length;

    let batch = supported;
    const perAddCapped = capPerAdd && batch.length > capPerAdd;
    if (perAddCapped) batch = batch.slice(0, capPerAdd);

    const room = Math.max(0, MAX_UPLOAD_TOTAL - pending.length);
    const overallCapped = batch.length > room;
    batch = batch.slice(0, room);

    const items = batch.map((file) => ({
      id: ++pendingIdSeq,
      file,
      name: file.name || `pasted-image-${pendingIdSeq}.png`,
      mediaType: file.type,
      previewUrl: URL.createObjectURL(file),
    }));

    const notes = [];
    if (unsupportedCount > 0) {
      notes.push(`${unsupportedCount} unsupported file${unsupportedCount === 1 ? '' : 's'} skipped`);
    }
    if (perAddCapped) notes.push(`only the first ${capPerAdd} pasted images were added`);
    if (overallCapped) notes.push(`the ${MAX_UPLOAD_TOTAL}-image limit was reached`);
    setNotice(notes.join('; '));
    setError('');
    setResults(null);
    if (items.length) setPending((prev) => [...prev, ...items]);
  }

  function removeOne(id) {
    setPending((prev) => {
      const target = prev.find((item) => item.id === id);
      if (target) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((item) => item.id !== id);
    });
    setResults(null);
  }

  function clearAll() {
    pending.forEach((item) => URL.revokeObjectURL(item.previewUrl));
    setPending([]);
    setResults(null);
    setNotice('');
    setError('');
  }

  function handlePaste(e) {
    const items = e.clipboardData?.items;
    if (!items || !items.length) return;
    const files = [];
    for (const item of items) {
      if (item.kind === 'file' && ACCEPTED_TYPES.includes(item.type)) {
        const f = item.getAsFile();
        if (f) files.push(f);
      }
    }
    if (files.length) {
      e.preventDefault();
      addFiles(files, { capPerAdd: MAX_PASTE_PER_EVENT });
    }
  }

  async function generate() {
    if (!pending.length) return;
    setBusy(true);
    setError('');
    setResults(null);
    try {
      const images = await Promise.all(pending.map(async (item) => ({
        name: item.name,
        mediaType: item.mediaType,
        imageBase64: await fileToBase64(item.file),
      })));
      const response = await fetch('/api/alt-text/images', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ images }),
      });
      const body = await response.json();
      if (!response.ok) {
        setError(body.error ?? `HTTP ${response.status}`);
        return;
      }
      setResults(body.images ?? []);
      setBudgetSummary(body.budget ?? '');
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="stack-16">
      <div
        ref={dropRef}
        className={`dropzone ${pending.length ? 'dropzone--filled' : ''}`}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => {
          e.preventDefault();
          addFiles(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        onPaste={handlePaste}
        role="button"
        tabIndex={0}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED_TYPES.join(',')}
          multiple
          hidden
          onChange={(e) => {
            addFiles(e.target.files);
            e.target.value = '';
          }}
        />
        {pending.length ? (
          <div className="alt-pending-grid">
            {pending.map((item) => (
              <div className="alt-pending-chip" key={item.id}>
                <img src={item.previewUrl} alt="" />
                <button
                  type="button"
                  className="alt-pending-remove"
                  title="Remove"
                  onClick={(e) => {
                    e.stopPropagation();
                    removeOne(item.id);
                  }}
                >
                  <XCircleIcon size={16} />
                </button>
              </div>
            ))}
            {pending.length < MAX_UPLOAD_TOTAL && (
              <div className="alt-pending-add" title="Add more">
                <UploadIcon size={18} />
              </div>
            )}
          </div>
        ) : (
          <>
            <UploadIcon size={22} style={{ color: 'var(--ink-3)' }} />
            <span className="alt-drop-label">
              Drop images here, click to browse, or paste from the clipboard
            </span>
            <span className="alt-drop-hint">
              JPEG, PNG, GIF or WebP — up to {MAX_UPLOAD_TOTAL} uploaded at once,
              or {MAX_PASTE_PER_EVENT} pasted at once
            </span>
          </>
        )}
      </div>

      {pending.length > 0 && (
        <div className="run-actions">
          <button type="button" className="btn btn-primary" onClick={generate} disabled={busy}>
            {busy
              ? 'Describing…'
              : `Generate Alt Text (${pending.length} image${pending.length === 1 ? '' : 's'})`}
          </button>
          <button type="button" className="btn" onClick={clearAll} disabled={busy}>
            Clear All
          </button>
        </div>
      )}

      {notice && (
        <div className="meta-line muted">{notice}</div>
      )}

      {busy && (
        <MascotLoader
          toolIcon={ImageIcon}
          indeterminateMessages={[
            'Looking closely at each image…',
            'Writing a screen-reader-ready description…',
          ]}
        />
      )}

      {error && (
        <div className="run-error">
          <AlertCircleIcon size={14} style={{ color: 'var(--status-danger-text)', flex: 'none' }} />
          <span>{error}</span>
        </div>
      )}

      {results && (
        <div className="stack-12">
          <div className="section-head">
            <h2 className="section-title">Results</h2>
          </div>
          <div className="controls-row">
            <div className="meta-line muted">
              {results.length} image{results.length === 1 ? '' : 's'} described
              {budgetSummary ? ` · ${budgetSummary}` : ''}
            </div>
            {results.length > 0 && (
              <button
                type="button"
                className="btn btn-icon"
                onClick={() => download('mavditto-alt-text.csv', toBatchCsv(results))}
              >
                <DownloadIcon /> Export CSV
              </button>
            )}
          </div>

          <div className="card table-card">
            <div className="row-grid row-grid--alt table-head">
              <span>Image</span>
              <span>File name</span>
              <span>Suggested alt</span>
              <span className="text-right">Action</span>
            </div>
            {results.map((row, i) => {
              const preview = pending[i]?.previewUrl;
              return (
                <div className="row-grid row-grid--alt rowline" key={row.name + i}>
                  <div className="alt-thumb-cell">
                    {preview ? (
                      <img src={preview} alt="" className="alt-thumb" />
                    ) : (
                      <div className="alt-thumb-fallback">
                        <ImageIcon size={18} />
                      </div>
                    )}
                  </div>
                  <span className="alt-current-cell">{row.name}</span>
                  <span className="alt-suggested-cell">
                    {row.outcome?.generated ? (
                      row.outcome.altText
                    ) : row.outcome?.isDecorative ? (
                      <span className="alt-decorative-badge alt-decorative-badge--compact">
                        <AlertDotIcon size={10} /> Decorative · Skipped
                      </span>
                    ) : (
                      <span className="muted small">{row.outcome?.skippedReason || '—'}</span>
                    )}
                  </span>
                  <div className="alt-action-cell text-right">
                    {row.outcome?.generated ? (
                      <CopyButton text={row.outcome.altText} />
                    ) : (
                      <span className="muted small">—</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// --- scan every image on a page -----------------------------------------

function ScanPanel() {
  const [url, setUrl] = useState('');
  const [showOptions, setShowOptions] = useState(false);
  const [maxImages, setMaxImages] = useState(40);
  const [budget, setBudget] = useState(1.0);
  const [includeHeader, setIncludeHeader] = useState(false);
  const [includeFooter, setIncludeFooter] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [scan, setScan] = useState(null);

  async function run(event) {
    event.preventDefault();
    if (!url.trim()) {
      setError('A page URL is required.');
      return;
    }
    setBusy(true);
    setError('');
    setScan(null);
    try {
      const response = await fetch('/api/alt-text/page', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: url.trim(), maxImages, budget, includeHeader, includeFooter,
        }),
      });
      const body = await response.json();
      if (!response.ok) {
        setError(body.error ?? `HTTP ${response.status}`);
        return;
      }
      setScan(body);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  const images = scan?.images ?? [];

  return (
    <div className="stack-16">
      <form className="run-form" style={{ borderTop: 0, padding: 0 }} onSubmit={run}>
        <label className="run-field">
          <span className="run-label">Page URL</span>
          <input
            type="url"
            placeholder="https://example.edu/campus-life"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={busy}
          />
        </label>

        <button
          type="button"
          className="btn btn-icon btn-small run-options-toggle"
          onClick={() => setShowOptions((v) => !v)}
        >
          <SettingsIcon size={12} />
          {showOptions ? 'Hide Options' : 'Options'}
        </button>

        {showOptions && (
          <div className="run-options">
            <label className="run-field run-field--narrow">
              <span className="run-label">Images per page</span>
              <input
                type="number" min="1" max="100" step="1"
                value={maxImages}
                onChange={(e) => setMaxImages(Number(e.target.value))}
                disabled={busy}
              />
              <span className="run-help">
                Decorative images are always skipped and don't count against this.
              </span>
            </label>
            <label className="run-field run-field--narrow">
              <span className="run-label">Spend cap (USD)</span>
              <input
                type="number" min="0.05" max="100" step="0.05"
                value={budget}
                onChange={(e) => setBudget(Number(e.target.value))}
                disabled={busy}
              />
              <span className="run-help">Checked before every image, so it cannot overrun.</span>
            </label>
            <div className="run-checks">
              <label>
                <input
                  type="checkbox"
                  checked={includeHeader}
                  onChange={(e) => setIncludeHeader(e.target.checked)}
                  disabled={busy}
                />
                Include header images
                <span className="run-inline-help">
                  The site masthead/logo — usually the same on every page.
                </span>
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={includeFooter}
                  onChange={(e) => setIncludeFooter(e.target.checked)}
                  disabled={busy}
                />
                Include footer images
                <span className="run-inline-help">
                  Footer and prefooter icons/graphics — also usually repeated site-wide.
                </span>
              </label>
            </div>
          </div>
        )}

        {error && (
          <div className="run-error">
            <AlertCircleIcon size={14} style={{ color: 'var(--status-danger-text)', flex: 'none' }} />
            <span>{error}</span>
          </div>
        )}

        <div className="run-actions">
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? 'Scanning…' : 'Scan Page'}
          </button>
        </div>
      </form>

      {busy && (
        <MascotLoader
          toolIcon={ImageIcon}
          indeterminateMessages={[
            'Finding every image on the page…',
            'Writing a description for each one…',
            'Skipping anything purely decorative…',
          ]}
        />
      )}

      {scan && (
        <div className="stack-12">
          <div className="section-head">
            <h2 className="section-title">Images</h2>
          </div>
          <div className="controls-row">
            <div className="meta-line muted">
              {scan.page.title ? `${scan.page.title} — ` : ''}
              {images.length} image{images.length === 1 ? '' : 's'} found · {scan.budget}
            </div>
            {images.length > 0 && (
              <button
                type="button"
                className="btn btn-icon"
                onClick={() => download('mavditto-alt-text.csv', toCsv(images))}
              >
                <DownloadIcon /> Export CSV
              </button>
            )}
          </div>

          {images.length === 0 ? (
            <div className="card empty-card">
              <p className="muted">No images were found on this page.</p>
            </div>
          ) : (
            <div className="card table-card">
              <div className="row-grid row-grid--alt table-head">
                <span>Image</span>
                <span>Current alt</span>
                <span>Suggested alt</span>
                <span className="text-right">Action</span>
              </div>
              {images.map((row, i) => (
                <div className="row-grid row-grid--alt rowline" key={row.src + i}>
                  <a
                    href={row.src}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="alt-thumb-cell"
                    title={row.src}
                  >
                    <img
                      src={row.src}
                      alt=""
                      className="alt-thumb"
                      onError={(e) => {
                        e.currentTarget.style.display = 'none';
                        if (e.currentTarget.nextSibling) {
                          e.currentTarget.nextSibling.style.display = 'flex';
                        }
                      }}
                    />
                    <div className="alt-thumb-fallback" style={{ display: 'none' }}>
                      <ImageIcon size={18} />
                    </div>
                  </a>
                  <span className="alt-current-cell">
                    {row.currentAlt ? (
                      row.currentAlt
                    ) : (
                      <span className="muted">— none —</span>
                    )}
                  </span>
                  <span className="alt-suggested-cell">
                    {row.outcome?.generated ? (
                      row.outcome.altText
                    ) : row.outcome?.isDecorative ? (
                      <span className="alt-decorative-badge alt-decorative-badge--compact">
                        <AlertDotIcon size={10} /> Decorative · Skipped
                      </span>
                    ) : (
                      <span className="muted small">{row.outcome?.skippedReason || '—'}</span>
                    )}
                  </span>
                  <div className="alt-action-cell text-right">
                    {row.outcome?.generated ? (
                      <CopyButton text={row.outcome.altText} />
                    ) : (
                      <span className="muted small">—</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// --- the page ------------------------------------------------------------

const MODES = [
  { key: 'scan', label: 'Page Scan' },
  { key: 'upload', label: 'Image Scan' },
];

export default function AltTextPage() {
  const { live } = useData();
  const [mode, setMode] = useState('scan');

  return (
    <div className="app">
      <Header active="alt-text" crumbs={['Alt Text Generator']} />
      <div className="page-body">
        <div>
          <h1 className="h1">Alt Text Generator</h1>
          <div className="meta-line muted">
            Professional, screen-reader-ready alt text for one image or every
            real image on a page. Decorative images are recognized and left
            alone rather than given a caption they don't need.
          </div>
        </div>

        {!live ? (
          <div className="card notice notice-muted">
            <AlertDotIcon />
            <span>
              Viewing a static export. To generate alt text, serve the
              dashboard with its backend:{' '}
              <code className="code-inline">python -m src.server</code>
            </span>
          </div>
        ) : (
          <div className="stack-16">
            <div className="card run-card">
              <div className="run-form run-form--top-level">
                <div className="chip-row">
                  {MODES.map((m) => (
                    <button
                      key={m.key}
                      type="button"
                      className={`chip ${mode === m.key ? 'active' : ''}`}
                      onClick={() => setMode(m.key)}
                    >
                      {m.label}
                    </button>
                  ))}
                </div>
                {mode === 'upload' ? <UploadPanel /> : <ScanPanel />}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
