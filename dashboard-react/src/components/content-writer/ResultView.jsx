import { useEffect, useRef, useState } from 'react';
import { ChevronDownIcon, ChevronRightIcon, DownloadIcon, PencilIcon } from '../Icons.jsx';
import { wordCount } from './api.js';
import { CopyButton, RefineMenu } from './shared.jsx';
import BlockView from './BlockView.jsx';

function SectionCard({ index, section, original, actions, onChange, onRegenerate, onRefine,
  regenerating, refining, canUndo, onUndo, flagged }) {
  const [editing, setEditing] = useState(false);
  const [showOriginal, setShowOriginal] = useState(false);
  const bodyRef = useRef(null);
  const hasText = Boolean(section.body.trim() || (section.heading || '').trim());

  function getSelection() {
    if (editing) {
      const el = bodyRef.current;
      return el ? el.value.slice(el.selectionStart, el.selectionEnd).trim() : '';
    }
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !bodyRef.current?.contains(sel.anchorNode)) return '';
    return sel.toString().trim();
  }

  return (
    <article id={`cw-unit-${index}`} className={`card cw-section ${flagged ? 'is-flagged' : ''}`}>
      <header className="cw-section-head">
        {editing ? (
          <input className="cw-input cw-heading-input" value={section.heading ?? ''}
                 onChange={(e) => onChange({ ...section, heading: e.target.value || null })}
                 placeholder="No heading" aria-label={`Section ${index + 1} heading`} />
        ) : (
          <h3 className="cw-section-title">{section.heading || <span className="muted">No heading</span>}</h3>
        )}
        <span className="badge-muted">{section.kind}</span>
      </header>

      {editing ? (
        <textarea ref={bodyRef} className="cw-input cw-body-input" value={section.body}
                  rows={Math.max(4, Math.ceil(section.body.length / 70))}
                  onChange={(e) => onChange({ ...section, body: e.target.value })}
                  aria-label={`Section ${index + 1} body`} />
      ) : section.body ? (
        <div ref={bodyRef} className="cw-body">{section.body}</div>
      ) : null}

      {section.links?.length > 0 && (
        <div className="cw-links">
          {section.links.map((l, i) => (
            <span key={i} className={`badge ${l.isButton ? 'badge-info' : 'badge-muted'}`} title={l.url}>
              {l.isButton ? 'Button' : 'Link'}: {l.text || l.url}
            </span>
          ))}
        </div>
      )}

      {showOriginal && original && (
        <div className="cw-original">
          <div className="run-label">Original</div>
          {original.heading && <div className="cw-original-heading">{original.heading}</div>}
          <div className="cw-body">{original.body}</div>
        </div>
      )}

      <footer className="cw-section-foot">
        <span className="run-help">
          {hasText ? `${wordCount(section.body)} words` : 'Links only, no copy to rewrite'}
        </span>
        <div className="cw-actions">
          {canUndo && <button type="button" className="btn btn-small" onClick={onUndo}>Undo</button>}
          {original && hasText && (
            <button type="button" className="btn btn-small" aria-pressed={showOriginal}
                    onClick={() => setShowOriginal((v) => !v)}>
              {showOriginal ? 'Hide original' : 'Show original'}
            </button>
          )}
          <button type="button" className="btn btn-icon btn-small" aria-pressed={editing}
                  onClick={() => setEditing((v) => !v)}>
            <PencilIcon size={11} /> {editing ? 'Done' : hasText ? 'Edit' : 'Add copy'}
          </button>
          {hasText && (
            <>
              {section.body.trim() && (
                <RefineMenu actions={actions} busy={refining} getSelection={getSelection}
                            onRefine={(action, instruction, selection) => onRefine(index, action, instruction, selection)} />
              )}
              <button type="button" className="btn btn-small" onClick={() => onRegenerate(index)} disabled={regenerating}>
                {regenerating ? 'Regenerating…' : 'Regenerate'}
              </button>
              <CopyButton text={[section.heading, section.body].filter(Boolean).join('\n\n')} />
            </>
          )}
        </div>
      </footer>
    </article>
  );
}

function ItemRow({ index, item, limit, actions, onChange, onRefine, refining, canUndo, onUndo, flagged }) {
  const over = limit && item.text.length > limit;
  return (
    <li id={`cw-unit-${index}`} className={`cw-item ${flagged ? 'is-flagged' : ''}`}>
      <span className="cw-item-num">{index + 1}</span>
      <div className="cw-item-main">
        <textarea className="cw-input cw-item-input" value={item.text}
                  rows={Math.max(1, Math.ceil(item.text.length / 64))}
                  onChange={(e) => onChange({ ...item, text: e.target.value })} aria-label={`Option ${index + 1}`} />
        {item.note && <span className="run-help">{item.note}</span>}
      </div>
      <span className={`cw-count ${over ? 'is-over' : ''}`}
            title={limit ? `${limit}-character limit` : undefined}>
        {item.text.length}{limit ? `/${limit}` : ''}
      </span>
      <div className="cw-actions">
        {canUndo && <button type="button" className="btn btn-small" onClick={onUndo}>Undo</button>}
        <RefineMenu actions={actions} busy={refining} getSelection={() => ''}
                    onRefine={(action, instruction) => onRefine(index, action, instruction, '')} />
        <CopyButton text={item.text} />
      </div>
    </li>
  );
}

const EXPORTS = [
  { key: 'pdf', label: 'PDF' },
  { key: 'docx', label: 'Word (.docx)' },
  { key: 'md', label: 'Markdown' },
  { key: 'html', label: 'HTML' },
  { key: 'txt', label: 'Plain text' },
];

export function ExportMenu({ onExport, disabled }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const close = (e) => { if (!ref.current?.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);
  return (
    <div className="cw-menu" ref={ref}>
      <button type="button" className="btn btn-icon" aria-haspopup="menu" aria-expanded={open}
              onClick={() => setOpen((v) => !v)} disabled={disabled}>
        <DownloadIcon /> Export <ChevronDownIcon size={11} />
      </button>
      {open && (
        <div className="cw-menu-pop cw-menu-pop--right card" role="menu">
          {EXPORTS.map((x) => (
            <button key={x.key} type="button" role="menuitem" className="cw-menu-item"
                    onClick={() => { setOpen(false); onExport(x.key); }}>
              {x.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// One variant's draft: a page (sections) or a list of short options.
export default function ResultView({ variant, template, actions, onUnitChange, onRegenerate,
  onRefine, busyUnit, undo, onUndo, onSendToWebBuilder, onExport }) {
  const flagged = new Set((variant.review?.issues || [])
    .filter((i) => i.severity === 'critical' && i.section != null).map((i) => i.section));

  if (variant.kind === 'items') {
    return (
      <div className="stack-12">
        <div className="cw-result-bar">
          <div className="meta-line muted">{variant.items.length} options</div>
          <ExportMenu onExport={onExport} />
        </div>
        <ol className="card cw-items">
          {variant.items.map((item, i) => (
            <ItemRow key={i} index={i} item={item} limit={template.char_limit} actions={actions}
                     onChange={(v) => onUnitChange(i, v)} onRefine={onRefine}
                     refining={busyUnit?.index === i && busyUnit.kind === 'refine'}
                     canUndo={undo[i] != null} onUndo={() => onUndo(i)} flagged={flagged.has(i)} />
          ))}
        </ol>
      </div>
    );
  }

  if (variant.kind === 'blocks') {
    const composed = variant.composed;
    const wordTotal = composed.blocks.reduce((n, b) => n + wordCount(b.body || b.quoteText || ''), 0);
    return (
      <div className="stack-12">
        <div className="cw-result-bar">
          <div className="cw-result-title">
            <h2 className="h2 cw-page-title">{composed.title}</h2>
            {composed.subtitle && <p className="cw-page-subtitle">{composed.subtitle}</p>}
            <div className="meta-line muted">
              {composed.blocks.length} block{composed.blocks.length === 1 ? '' : 's'} · {wordTotal} words
            </div>
          </div>
          <div className="cw-actions">
            <ExportMenu onExport={onExport} />
            <button type="button" className="btn btn-primary btn-icon" onClick={onSendToWebBuilder}>
              Send to Web Builder <ChevronRightIcon size={12} />
            </button>
          </div>
        </div>
        <BlockView blocks={composed.blocks} actions={actions} onUnitChange={onUnitChange}
                   onRegenerate={onRegenerate} onRefine={onRefine} busyUnit={busyUnit} undo={undo}
                   onUndo={onUndo} flagged={flagged} />
      </div>
    );
  }

  const page = variant.page;
  return (
    <div className="stack-12">
      <div className="cw-result-bar">
        <div className="cw-result-title">
          <h2 className="h2 cw-page-title">{page.pageTitle}</h2>
          <div className="meta-line muted">
            {page.register} register · {page.sections.length} section{page.sections.length === 1 ? '' : 's'} ·{' '}
            {page.sections.reduce((n, s) => n + wordCount(s.body), 0)} words
          </div>
        </div>
        <div className="cw-actions">
          <ExportMenu onExport={onExport} />
          <button type="button" className="btn btn-primary btn-icon" onClick={onSendToWebBuilder}>
            Send to Web Builder <ChevronRightIcon size={12} />
          </button>
        </div>
      </div>
      {page.sections.map((s, i) => (
        <SectionCard
          key={i}
          index={i}
          section={s}
          original={page.originalSections?.[i] && template.key === 'rewrite-page' ? page.originalSections[i] : null}
          actions={actions}
          onChange={(v) => onUnitChange(i, v)}
          onRegenerate={onRegenerate}
          onRefine={onRefine}
          regenerating={busyUnit?.index === i && busyUnit.kind === 'regenerate'}
          refining={busyUnit?.index === i && busyUnit.kind === 'refine'}
          canUndo={undo[i] != null}
          onUndo={() => onUndo(i)}
          flagged={flagged.has(i)}
        />
      ))}
    </div>
  );
}
