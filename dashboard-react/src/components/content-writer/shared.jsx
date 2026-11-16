import { useEffect, useRef, useState } from 'react';
import { CheckIcon, ChevronDownIcon, CopyIcon, SparklesIcon } from '../Icons.jsx';

// Shared by ResultView's SectionCard/ItemRow and BlockView's BlockCard.

export function CopyButton({ text, label = 'Copy' }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className="btn btn-icon btn-small"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1400);
        } catch { /* clipboard blocked; the text is still selectable */ }
      }}
    >
      {copied ? <CheckIcon size={11} style={{ color: 'var(--status-success-text)' }} /> : <CopyIcon size={11} />}
      {copied ? 'Copied' : label}
    </button>
  );
}

// A small popover of refine actions. Opening it captures whatever text the
// writer had selected inside this unit's body; with nothing selected the
// action applies to the whole unit.
export function RefineMenu({ actions, onRefine, busy, getSelection }) {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState('');
  const [target, setTarget] = useState('');
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    const esc = (e) => { if (e.key === 'Escape') setOpen(false); };
    document.addEventListener('mousedown', close);
    document.addEventListener('keydown', esc);
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc); };
  }, [open]);

  function run(action) {
    setOpen(false);
    onRefine(action, action === 'custom' ? custom : '', target);
    setCustom('');
  }

  return (
    <div className="cw-menu" ref={ref}>
      <button
        type="button"
        className="btn btn-icon btn-small"
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={busy}
        // mousedown, not click: reading the selection before focus moves to
        // the button would clear it.
        onMouseDown={() => setTarget(getSelection())}
        onClick={() => setOpen((v) => !v)}
      >
        <SparklesIcon size={12} /> {busy ? 'Refining…' : 'Refine'} <ChevronDownIcon size={11} />
      </button>
      {open && (
        <div className="cw-menu-pop card" role="menu">
          <div className="run-help cw-menu-scope">
            {target ? `Selected: “${target.length > 60 ? `${target.slice(0, 60)}…` : target}”` : 'Applies to the whole block'}
          </div>
          {actions.filter((a) => a.key !== 'custom').map((a) => (
            <button key={a.key} type="button" role="menuitem" className="cw-menu-item" onClick={() => run(a.key)}>
              {a.label}
            </button>
          ))}
          <form className="cw-menu-custom" onSubmit={(e) => { e.preventDefault(); if (custom.trim()) run('custom'); }}>
            <input className="cw-input" value={custom} onChange={(e) => setCustom(e.target.value)}
                   placeholder="Or describe the change…" aria-label="Custom refinement" />
            <button type="submit" className="btn btn-small" disabled={!custom.trim()}>Apply</button>
          </form>
        </div>
      )}
    </div>
  );
}
