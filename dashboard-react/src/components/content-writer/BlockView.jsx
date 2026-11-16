import { useRef, useState } from 'react';
import { PencilIcon, TriangleAlertIcon, XCircleIcon } from '../Icons.jsx';
import { blockPrimaryText, wordCount, withBlockPrimaryText } from './api.js';

// Shared bits, reused across ResultView's SectionCard/ItemRow.
import { CopyButton, RefineMenu } from './shared.jsx';

const TYPE_LABELS = {
  hero: 'Hero', heading: 'Heading', text: 'Text', image: 'Image', quote: 'Quote',
  stat: 'Stat', links: 'Links', cta: 'Call to action', divider: 'Divider',
};

function PlaceholderBadge({ block }) {
  if (!block.isPlaceholder) return null;
  return (
    <span className="cw-placeholder-badge" title={block.placeholderNote || 'Illustrative, not sourced'}>
      <TriangleAlertIcon size={11} /> Placeholder
    </span>
  );
}

function LinkFields({ links, onChange, disabled, single }) {
  const list = links.length ? links : (single ? [{ text: '', url: '', isButton: true }] : []);
  function update(i, patch) {
    onChange(list.map((l, n) => (n === i ? { ...l, ...patch } : l)));
  }
  return (
    <div className="stack-8">
      {list.map((l, i) => (
        <div key={i} className="cw-link-fields">
          <input className="cw-input" value={l.text} placeholder="Link text"
                 onChange={(e) => update(i, { text: e.target.value })} disabled={disabled}
                 aria-label="Link text" />
          <input className="cw-input" value={l.url} placeholder="https://…" type="url"
                 onChange={(e) => update(i, { url: e.target.value })} disabled={disabled}
                 aria-label="Link URL" />
          {!single && (
            <button type="button" className="btn btn-icon-only" aria-label="Remove link" disabled={disabled}
                    onClick={() => onChange(list.filter((_, n) => n !== i))}>
              <XCircleIcon size={13} />
            </button>
          )}
        </div>
      ))}
      {!single && (
        <button type="button" className="btn btn-small" disabled={disabled}
                onClick={() => onChange([...list, { text: '', url: '', isButton: false }])}>
          Add link
        </button>
      )}
    </div>
  );
}

function BlockBody({ block, editing, onChange }) {
  const set = (patch) => onChange({ ...block, ...patch });
  switch (block.type) {
    case 'hero':
      return editing ? (
        <div className="stack-8">
          <input className="cw-input cw-heading-input" value={block.heading} placeholder="Heading"
                 onChange={(e) => set({ heading: e.target.value })} aria-label="Hero heading" />
          <input className="cw-input" value={block.subheading} placeholder="Subheading"
                 onChange={(e) => set({ subheading: e.target.value })} aria-label="Hero subheading" />
          <textarea className="cw-input" rows={2} value={block.body} placeholder="Lead-in text (optional)"
                    onChange={(e) => set({ body: e.target.value })} aria-label="Hero body" />
        </div>
      ) : (
        <div className="cw-block-hero">
          <h2 className="cw-block-hero-title">{block.heading}</h2>
          {block.subheading && <p className="cw-block-hero-sub">{block.subheading}</p>}
          {block.body && <p>{block.body}</p>}
        </div>
      );

    case 'heading':
      return editing
        ? <input className="cw-input cw-heading-input" value={block.heading}
                 onChange={(e) => set({ heading: e.target.value })} aria-label="Heading" />
        : <h3 className="cw-section-title">{block.heading}</h3>;

    case 'text':
      return editing ? (
        <div className="stack-8">
          <input className="cw-input cw-heading-input" value={block.heading} placeholder="No heading"
                 onChange={(e) => set({ heading: e.target.value })} aria-label="Section heading" />
          <textarea className="cw-input cw-body-input" rows={Math.max(4, Math.ceil(block.body.length / 70))}
                    value={block.body} onChange={(e) => set({ body: e.target.value })} aria-label="Body text" />
        </div>
      ) : (
        <>
          {block.heading && <h3 className="cw-section-title">{block.heading}</h3>}
          {block.body && <div className="cw-body">{block.body}</div>}
        </>
      );

    case 'image':
      return editing ? (
        <div className="stack-8">
          <label className="run-field">
            <span className="run-label">Alt text</span>
            <input className="cw-input" value={block.imageAlt}
                   onChange={(e) => set({ imageAlt: e.target.value })} aria-label="Image alt text" />
          </label>
          <label className="run-field">
            <span className="run-label">Caption (optional)</span>
            <input className="cw-input" value={block.imageCaption}
                   onChange={(e) => set({ imageCaption: e.target.value })} aria-label="Image caption" />
          </label>
        </div>
      ) : (
        <div className="cw-block-image">
          <div className="cw-block-image-label">Image</div>
          <div className="cw-block-image-alt">{block.imageAlt || <span className="muted">No alt text</span>}</div>
          {block.imageCaption && <div className="cw-block-image-caption">{block.imageCaption}</div>}
        </div>
      );

    case 'quote':
      return editing ? (
        <div className="stack-8">
          <textarea className="cw-input" rows={2} value={block.quoteText} placeholder="Quote"
                    onChange={(e) => set({ quoteText: e.target.value })} aria-label="Quote text" />
          <input className="cw-input" value={block.quoteAttribution} placeholder="Attribution"
                 onChange={(e) => set({ quoteAttribution: e.target.value })} aria-label="Quote attribution" />
        </div>
      ) : (
        <blockquote className="cw-block-quote">
          “{block.quoteText}”
          {block.quoteAttribution && <footer>— {block.quoteAttribution}</footer>}
        </blockquote>
      );

    case 'stat':
      return editing ? (
        <div className="cw-grid-2">
          <input className="cw-input" value={block.statValue} placeholder="e.g. 40,000+"
                 onChange={(e) => set({ statValue: e.target.value })} aria-label="Stat value" />
          <input className="cw-input" value={block.statLabel} placeholder="e.g. Total enrollment"
                 onChange={(e) => set({ statLabel: e.target.value })} aria-label="Stat label" />
        </div>
      ) : (
        <div className="cw-block-stat">
          <span className="cw-block-stat-value">{block.statValue}</span>
          <span className="cw-block-stat-label">{block.statLabel}</span>
        </div>
      );

    case 'links':
      return editing
        ? <LinkFields links={block.links} onChange={(links) => set({ links })} />
        : (
          <ul className="cw-block-links">
            {block.links.map((l, i) => (
              <li key={i}><a href={l.url} target="_blank" rel="noreferrer">{l.text || l.url}</a></li>
            ))}
          </ul>
        );

    case 'cta':
      return editing ? (
        <div className="stack-8">
          <input className="cw-input" value={block.heading} placeholder="Button label"
                 onChange={(e) => set({ heading: e.target.value })} aria-label="CTA label" />
          <LinkFields single links={block.links}
                     onChange={(links) => set({ links: links.map((l) => ({ ...l, text: block.heading, isButton: true })) })} />
        </div>
      ) : (
        <div className="cw-block-cta">
          <span className="cw-block-cta-button">{block.heading}</span>
          {block.links?.[0]?.url && <span className="run-help">{block.links[0].url}</span>}
        </div>
      );

    case 'divider':
      return <hr className="cw-block-divider" />;

    default:
      return null;
  }
}

function BlockCard({ index, block, actions, onChange, onRegenerate, onRefine, regenerating,
  refining, canUndo, onUndo, flagged }) {
  const [editing, setEditing] = useState(false);
  const bodyRef = useRef(null);
  const primary = blockPrimaryText(block);
  const canRefine = primary.trim().length > 0 && block.type !== 'links' && block.type !== 'divider';

  function getSelection() {
    const sel = window.getSelection();
    if (editing || !sel || sel.isCollapsed || !bodyRef.current?.contains(sel.anchorNode)) return '';
    return sel.toString().trim();
  }

  return (
    <article id={`cw-unit-${index}`} className={`card cw-section cw-block cw-block--${block.type} ${flagged ? 'is-flagged' : ''}`}>
      <header className="cw-section-head">
        <span className="badge-muted">{TYPE_LABELS[block.type] ?? block.type}</span>
        <PlaceholderBadge block={block} />
      </header>

      <div ref={bodyRef}>
        <BlockBody block={block} editing={editing} onChange={onChange} />
      </div>

      {block.isPlaceholder && block.placeholderNote && !editing && (
        <p className="cw-placeholder-note">{block.placeholderNote}</p>
      )}
      {block.isPlaceholder && editing && (
        <label className="run-field">
          <span className="run-label">Placeholder note</span>
          <input className="cw-input" value={block.placeholderNote}
                 onChange={(e) => onChange({ ...block, placeholderNote: e.target.value })}
                 aria-label="Placeholder note" />
        </label>
      )}

      {block.type !== 'divider' && (
        <footer className="cw-section-foot">
          <span className="run-help">{primary ? `${wordCount(primary)} words` : ''}</span>
          <div className="cw-actions">
            {canUndo && <button type="button" className="btn btn-small" onClick={onUndo}>Undo</button>}
            <button type="button" className="btn btn-icon btn-small" aria-pressed={editing}
                    onClick={() => setEditing((v) => !v)}>
              <PencilIcon size={11} /> {editing ? 'Done' : 'Edit'}
            </button>
            {canRefine && (
              <RefineMenu actions={actions} busy={refining} getSelection={getSelection}
                          onRefine={(action, instruction, selection) => onRefine(index, action, instruction, selection)} />
            )}
            <button type="button" className="btn btn-small" onClick={() => onRegenerate(index)} disabled={regenerating}>
              {regenerating ? 'Regenerating…' : 'Regenerate'}
            </button>
            {primary && <CopyButton text={primary} />}
          </div>
        </footer>
      )}
    </article>
  );
}

// Compose mode's draft: an ordered list of typed blocks, each independently
// editable, refinable and regeneratable -- consecutive stat blocks render
// grouped into one band, matching how they export.
export default function BlockView({ blocks, actions, onUnitChange, onRegenerate, onRefine,
  busyUnit, undo, onUndo, flagged }) {
  const groups = [];
  let i = 0;
  while (i < blocks.length) {
    if (blocks[i].type === 'stat') {
      const start = i;
      while (i < blocks.length && blocks[i].type === 'stat') i += 1;
      groups.push({ kind: 'stat-band', start, end: i });
    } else {
      groups.push({ kind: 'single', start: i, end: i + 1 });
      i += 1;
    }
  }

  return (
    <div className="stack-12">
      {groups.map((g) => (g.kind === 'stat-band' ? (
        <div key={g.start} className="cw-block-stat-band">
          {blocks.slice(g.start, g.end).map((b, n) => {
            const idx = g.start + n;
            return (
              <BlockCard key={idx} index={idx} block={b} actions={actions}
                        onChange={(v) => onUnitChange(idx, v)} onRegenerate={onRegenerate} onRefine={onRefine}
                        regenerating={busyUnit?.index === idx && busyUnit.kind === 'regenerate'}
                        refining={busyUnit?.index === idx && busyUnit.kind === 'refine'}
                        canUndo={undo[idx] != null} onUndo={() => onUndo(idx)} flagged={flagged.has(idx)} />
            );
          })}
        </div>
      ) : (
        <BlockCard key={g.start} index={g.start} block={blocks[g.start]} actions={actions}
                  onChange={(v) => onUnitChange(g.start, v)} onRegenerate={onRegenerate} onRefine={onRefine}
                  regenerating={busyUnit?.index === g.start && busyUnit.kind === 'regenerate'}
                  refining={busyUnit?.index === g.start && busyUnit.kind === 'refine'}
                  canUndo={undo[g.start] != null} onUndo={() => onUndo(g.start)} flagged={flagged.has(g.start)} />
      )))}
    </div>
  );
}
