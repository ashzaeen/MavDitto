import { useEffect, useRef } from 'react';
import { XCircleIcon } from '../Icons.jsx';

function when(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

// Saved runs, newest first. Opening one restores its template, brief,
// settings and drafts exactly as they were generated.
export default function HistoryDrawer({ open, runs, templates, onOpen, onDelete, onClose, loading }) {
  const closeRef = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    closeRef.current?.focus();
    const esc = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', esc);
    return () => document.removeEventListener('keydown', esc);
  }, [open, onClose]);
  if (!open) return null;
  const label = (key) => templates.find((t) => t.key === key)?.label ?? key;

  return (
    <div className="cw-drawer-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <aside className="cw-drawer card" role="dialog" aria-modal="true" aria-label="Saved drafts">
        <header className="cw-drawer-head">
          <h2 className="section-title">Saved drafts</h2>
          <button ref={closeRef} type="button" className="btn btn-icon-only" onClick={onClose} aria-label="Close">
            <XCircleIcon size={16} />
          </button>
        </header>
        {loading ? (
          <p className="muted small">Loading…</p>
        ) : !runs.length ? (
          <p className="muted small">Nothing saved yet. Every draft you write is kept here automatically.</p>
        ) : (
          <ul className="cw-history">
            {runs.map((r) => (
              <li key={r.id}>
                <button type="button" className="cw-history-open" onClick={() => onOpen(r.id)}>
                  <span className="cw-history-title">{r.title || 'Untitled'}</span>
                  <span className="run-help">
                    {label(r.templateKey)} · {when(r.createdAt)}
                    {r.variants > 1 ? ` · ${r.variants} drafts` : ''}
                  </span>
                </button>
                <button type="button" className="btn btn-small" onClick={() => onDelete(r.id)}
                        aria-label={`Delete ${r.title || 'draft'}`}>
                  Delete
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}
