import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import Header from '../components/Header.jsx';
import { useData } from '../data/useData.jsx';
import { useContentHandoff } from '../data/useContentHandoff.jsx';
import MascotLoader from '../components/MascotLoader.jsx';
import {
  AlertCircleIcon, AlertDotIcon, UploadIcon, CopyIcon, CheckIcon,
  ExternalLinkIcon, ArrowLeftIcon, ImageIcon, ArrowRightLeftIcon, XCircleIcon,
  LinkIcon, GridIcon, FileTextIcon, PencilIcon, EyeIcon, CheckCircleIcon, ArrowRightIcon,
  BuilderIcon,
} from '../components/Icons.jsx';

// Web Builder: maps a StructuredContent (Content Writer's own output, or a
// raw URL/file extracted fresh -- see /api/web-builder/extract) onto UTA's
// real Sitecore component catalog in two phases -- a reviewable layout
// plan, then populated, ready-to-paste fields.
//
// Phase 2 is driven one component at a time via /regenerate-component
// (fired in parallel, not awaited together) rather than the batched
// /populate route, so each card fills in as its own call resolves instead
// of the whole page waiting on the slowest component -- the same
// per-component call this same route already serves for the explicit
// "Regenerate this component" action.

const EXTENSION_KIND = {
  pdf: 'pdf', docx: 'docx', doc: 'docx', pptx: 'pptx', ppt: 'pptx',
  xlsx: 'xlsx', xls: 'xlsx', md: 'markdown', markdown: 'markdown',
};

// A UTA design-system page URL per component, by best-effort slug
// convention (kebab-case of the name) -- not individually re-verified per
// entry; if a specific link 404s, the catalog index still gets you close.
function designPageUrl(name) {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
  return `https://ds.web.uta.edu/components/${slug}`;
}

// UTA's two design-system sites warn never to mix a "new look" component
// with a "classic look" one on the same page -- not enforced as a hard
// rule here (a reviewer might genuinely want the mix), just surfaced
// everywhere a component name shows up so it's easy to catch.
const VARIANT_BADGE = {
  new_look: { cls: 'badge-info', label: 'New' },
  classic_look: { cls: 'badge-muted', label: 'Classic' },
};

function VariantBadge({ variant }) {
  const info = VARIANT_BADGE[variant];
  if (!info) return null;
  return <span className={`badge ${info.cls}`} title="Visual style from UTA's design system">{info.label}</span>;
}

// A quiet, deterministic accent per catalog category (Hero, Listing, Nav, ...)
// -- not meant to carry meaning on its own (that's what the status badge and
// field-type icons are for), just a low-effort visual "these are the same
// kind of thing" cue when scanning a long page of cards.
const CATEGORY_PALETTE = ['#3E7CB1', '#B15E3E', '#4C9A6B', '#8A5FBF', '#C2933E', '#4F8FA6'];
function categoryColor(category) {
  if (!category) return 'transparent';
  let hash = 0;
  for (let i = 0; i < category.length; i++) hash = (hash * 31 + category.charCodeAt(i)) >>> 0;
  return CATEGORY_PALETTE[hash % CATEGORY_PALETTE.length];
}

// Button "color" values come from the model as free text (a UTA brand name,
// a hex code, a CSS keyword) -- only render a swatch when the browser can
// actually resolve it to a real color, rather than guessing at a brand palette.
function isCssColor(value) {
  try {
    return typeof CSS !== 'undefined' && CSS.supports('color', value);
  } catch {
    return false;
  }
}

// `variant="square"` (default) is a small inline thumbnail next to a name --
// renders nothing when there's no screenshot, since it sits beside text that
// already carries the name. `variant="rail"` is the plan preview's bigger,
// wide block-image -- it always renders a box (a soft placeholder when there's
// no screenshot yet) so the rail's rhythm of image-then-text stays intact.
// `enlargeable` (rail only) makes a real screenshot click-to-zoom into a
// full-size lightbox -- the rail box itself stays compact enough to scan a
// whole page plan, so the lightbox is where you actually judge how a
// component looks. Disabled when the thumb sits inside its own clickable
// card (the swap gallery), since nesting a button in a button is invalid.
function ComponentThumb({ spec, size = 40, variant = 'square', enlargeable = true }) {
  const [enlarged, setEnlarged] = useState(false);
  if (variant === 'rail') {
    const hasImage = Boolean(spec?.screenshotAsset);
    const clickable = enlargeable && hasImage;
    const Tag = clickable ? 'button' : 'div';
    return (
      <>
        <Tag
          {...(clickable ? { type: 'button' } : {})}
          className="wb-rail-thumb"
          draggable={false}
          title={clickable ? 'Click to enlarge' : undefined}
          onClick={clickable ? (e) => { e.stopPropagation(); setEnlarged(true); } : undefined}
        >
          {hasImage ? (
            <img src={`/${spec.screenshotAsset}`} alt="" />
          ) : (
            <div className="wb-rail-thumb-placeholder">
              <ImageIcon size={20} />
            </div>
          )}
        </Tag>
        {enlarged && (
          <div className="modal-backdrop" onClick={() => setEnlarged(false)}>
            <img
              src={`/${spec.screenshotAsset}`} alt=""
              className="wb-lightbox-img"
              onClick={(e) => e.stopPropagation()}
            />
          </div>
        )}
      </>
    );
  }
  if (!spec?.screenshotAsset) return null;
  return (
    <img
      src={`/${spec.screenshotAsset}`} alt="" className="wb-component-thumb"
      style={{ width: size, height: size }}
    />
  );
}

function SpecialFeaturesList({ features }) {
  const [open, setOpen] = useState(false);
  if (!features?.length) return null;
  return (
    <div className="wb-special-features" style={{ marginTop: 'var(--space-3)' }}>
      <button type="button" className="btn btn-icon btn-small" onClick={() => setOpen((v) => !v)}>
        {open ? 'Hide' : 'Show'} special features ({features.length})
      </button>
      {open && (
        <ul className="wb-special-features-list">
          {features.map((sf, i) => (
            <li key={i} className={sf.importance === 'critical' ? 'wb-special-feature--critical' : ''}>
              <strong>{sf.name}</strong>
              {sf.importance === 'critical' && <span className="badge badge-warn" style={{ marginLeft: 'var(--space-2)' }}>critical</span>}
              <div className="muted small">{sf.description}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

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

function planKey(content, plan) {
  try {
    const shape = plan.rows.map((r) => `${r.component}:${(r.sectionIndices ?? []).join(',')}`).join('|');
    return `webbuilder-pasted:${content?.pageTitle ?? ''}:${shape}`;
  } catch {
    return 'webbuilder-pasted:fallback';
  }
}

function loadPastedState(key) {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch {
    return new Set();
  }
}

function savePastedState(key, pastedSet) {
  try {
    window.localStorage.setItem(key, JSON.stringify([...pastedSet]));
  } catch {
    /* private window / storage disabled -- paste tracking just won't persist */
  }
}

// Per-field "copied into Sitecore" tracking, mirroring the whole-component
// paste tracker above but keyed by card -> set of field indices.
function loadCopiedState(key) {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return Object.fromEntries(Object.entries(parsed).map(([k, v]) => [k, new Set(v)]));
  } catch {
    return {};
  }
}

function saveCopiedState(key, copiedByCard) {
  try {
    const plain = Object.fromEntries(Object.entries(copiedByCard).map(([k, v]) => [k, [...v]]));
    window.localStorage.setItem(key, JSON.stringify(plain));
  } catch {
    /* private window / storage disabled -- copy tracking just won't persist */
  }
}

function CopyButton({ text, label = 'Copy', iconOnly = false, onCopied }) {
  const [copied, setCopied] = useState(false);
  if (!text) return null;
  return (
    <button
      type="button"
      className={`btn ${iconOnly ? 'btn-icon-only' : 'btn-icon'} btn-small`}
      title={iconOnly ? label : undefined}
      onClick={async (e) => {
        e.stopPropagation();
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          onCopied?.();
          setTimeout(() => setCopied(false), 1400);
        } catch {
          /* clipboard permission denied; the text is still visible to select */
        }
      }}
    >
      {copied ? <CheckIcon size={11} style={{ color: 'var(--status-success-text)' }} /> : <CopyIcon size={11} />}
      {!iconOnly && (copied ? 'Copied' : label)}
    </button>
  );
}

// --------------------------------------------------------------------------
// Phase 1: layout plan, as a vertical page-preview rail (each block shows the
// component's real screenshot, in page order) + a gallery-style swap modal.
// --------------------------------------------------------------------------

function SwapGalleryModal({ row, catalog, onPick, onClose }) {
  useEffect(() => {
    function handleKeyDown(e) { if (e.key === 'Escape') onClose(); }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  const alternatives = row.alternatives ?? [];
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-window wb-swap-modal card" onClick={(e) => e.stopPropagation()}
        role="dialog" aria-modal="true" aria-labelledby="swap-modal-title"
      >
        <div className="modal-header">
          <div className="modal-title-row">
            <div>
              <h2 id="swap-modal-title" className="h2 llm-modal-title">Swap “{row.component}”</h2>
              <div className="small muted">Alternatives that also fit “{row.mapsTo}”</div>
            </div>
          </div>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Close dialog" title="Close dialog">
            <XCircleIcon size={16} />
          </button>
        </div>
        <div className="modal-body">
          {alternatives.length === 0 ? (
            <div className="muted small">No alternatives were suggested for this row.</div>
          ) : (
            <div className="wb-swap-gallery">
              {alternatives.map((name) => {
                const spec = catalog?.[name];
                return (
                  <button key={name} type="button" className="wb-swap-card" onClick={() => { onPick(name); onClose(); }}>
                    <ComponentThumb spec={spec} variant="rail" enlargeable={false} />
                    <div className="wb-swap-card-body">
                      <div className="wb-swap-card-head">
                        <span className="wb-swap-card-name">{name}</span>
                        <VariantBadge variant={spec?.visualVariant} />
                      </div>
                      {spec?.purpose && <p className="small muted wb-swap-card-purpose">{spec.purpose}</p>}
                      <a
                        href={designPageUrl(name)} target="_blank" rel="noopener noreferrer"
                        className="notice-link small" onClick={(e) => e.stopPropagation()}
                      >
                        View on design system <ExternalLinkIcon size={10} />
                      </a>
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function PlanPreviewRail({ plan, catalog, onSwap, onRemove, onReorder }) {
  const [openSwapIndex, setOpenSwapIndex] = useState(null);
  const [dragIndex, setDragIndex] = useState(null);
  const [dragOverIndex, setDragOverIndex] = useState(null);

  return (
    <div className="wb-plan-rail">
      {plan.rows.map((row, i) => {
        const spec = catalog?.[row.component];
        const structural = (row.sectionIndices ?? []).length === 0;
        return (
          <div
            key={i}
            className={`wb-plan-block ${structural ? 'wb-plan-block--structural' : ''} ${dragOverIndex === i ? 'wb-plan-block--drag-over' : ''}`}
            draggable={!structural}
            onDragStart={() => setDragIndex(i)}
            onDragOver={(e) => { if (!structural) { e.preventDefault(); setDragOverIndex(i); } }}
            onDragLeave={() => setDragOverIndex((cur) => (cur === i ? null : cur))}
            onDrop={(e) => {
              e.preventDefault();
              setDragOverIndex(null);
              if (dragIndex !== null && dragIndex !== i) onReorder(dragIndex, i);
              setDragIndex(null);
            }}
          >
            <ComponentThumb spec={spec} variant="rail" />
            <div className="wb-plan-block-body">
              <div className="wb-plan-block-head">
                <span
                  className="wb-drag-handle"
                  title={structural ? 'structural placement -- not reorderable' : 'drag to reorder'}
                >
                  {structural ? '' : '⠿'}
                </span>
                <span className="muted small">{row.order}</span>
                <span className="wb-plan-block-name">{row.component}</span>
                <VariantBadge variant={spec?.visualVariant} />
              </div>
              <div className="muted small">Maps to: {row.mapsTo}</div>
              <p className="small wb-plan-block-rationale">{row.rationale}</p>
              <div className="wb-plan-block-actions">
                {row.alternatives?.length > 0 && (
                  <button type="button" className="btn btn-secondary btn-small" onClick={() => setOpenSwapIndex(i)}>
                    <ArrowRightLeftIcon size={12} /> Swap
                  </button>
                )}
                <button type="button" className="btn btn-icon btn-small" onClick={() => onRemove(i)}>
                  Remove
                </button>
              </div>
            </div>
          </div>
        );
      })}
      {openSwapIndex !== null && (
        <SwapGalleryModal
          row={plan.rows[openSwapIndex]} catalog={catalog}
          onPick={(name) => onSwap(openSwapIndex, name)}
          onClose={() => setOpenSwapIndex(null)}
        />
      )}
    </div>
  );
}

// --------------------------------------------------------------------------
// Phase 2: populated fields, one card per component
// --------------------------------------------------------------------------

const STATUS_BADGE = {
  valid: { cls: 'badge-good', label: 'Valid' },
  adjusted: { cls: 'badge-warn', label: 'Adjusted' },
  needs_review: { cls: 'badge-bad', label: 'Needs Review' },
};

const STATUS_ICON = { valid: CheckCircleIcon, adjusted: AlertDotIcon, needs_review: XCircleIcon };

// A light icon per field shape, just enough to make a long field list
// scannable at a glance -- plaintext/date/enum stay icon-less since they're
// the default shape and an icon on every single row would just be noise.
const FIELD_TYPE_ICON = {
  link: LinkIcon,
  image: ImageIcon,
  listing: GridIcon,
  button: ArrowRightIcon,
  richtext: FileTextIcon,
};

// Whether a field participates in the guided copy-to-Sitecore walkthrough --
// scoped to the fields that are genuinely "one value, one Sitecore field"
// (button/listing/image already have their own per-item copy affordances and
// don't map cleanly onto a single "next field" step).
function isGuidedField(field) {
  if (!field || field.skipped) return false;
  if (field.fieldType === 'link') return Boolean(field.url);
  if (field.fieldType === 'plaintext' || field.fieldType === 'richtext' || field.fieldType === 'date') {
    return Boolean(field.text);
  }
  return false;
}

function isEmphasisField(field) {
  return field.fieldType === 'plaintext' && /title|heading|headline/i.test(field.name);
}

function CharCount({ text, limit }) {
  if (!limit) return null;
  const over = text.length > limit;
  return <span className={`wb-char-count ${over ? 'wb-char-count--over' : ''}`}>{text.length}/{limit}</span>;
}

function EditableText({ value, multiline, rows = 3, onChange }) {
  return multiline ? (
    <textarea className="wb-field-editable" rows={rows} value={value} onChange={(e) => onChange(e.target.value)} />
  ) : (
    <input className="wb-field-editable" value={value} onChange={(e) => onChange(e.target.value)} />
  );
}

// Every field is one self-contained row: a header line (label + controls,
// always together) and the value directly beneath it. Label and controls
// used to live in separate CSS-grid columns from the value itself, so the
// label visually lined up with the copy button on row one while the actual
// value sat on row two, disconnected from both -- this keeps everything
// about one field in one visual block instead.
function FieldBlock({ field, edited, copied, focused, onEdit, onCopy, rowRef }) {
  const [rawEdit, setRawEdit] = useState(false);
  const Icon = FIELD_TYPE_ICON[field.fieldType];
  const rowClass = `wb-field-row ${focused ? 'wb-field-row--focused' : ''} ${copied ? 'wb-field-row--copied' : ''}`;

  // Fires once the underlying CopyButton/click-to-copy actually wrote to the
  // clipboard -- separate from that control's own local "Copied" flash, this
  // is what drives the shared per-card copied-state + guided-advance.
  async function copyAndMark(text) {
    try {
      await navigator.clipboard.writeText(text);
      onCopy?.();
    } catch {
      /* clipboard permission denied; the text is still visible to select */
    }
  }

  function head(controls, { showCopied = false } = {}) {
    return (
      <div className="wb-field-row-head">
        {Icon && <Icon size={12} className="wb-field-row-icon" />}
        <span className="wb-field-row-label">{field.name}{field.isPageLevel ? ' (page)' : ''}</span>
        {edited && <span className="wb-edited-tag">edited</span>}
        {showCopied && copied && (
          <span className="wb-copied-tag" title="Copied">
            <CheckIcon size={10} /> Copied
          </span>
        )}
        {controls && <div className="wb-field-row-controls">{controls}</div>}
      </div>
    );
  }

  if (field.skipped) {
    // An empty dash is a dead end -- this field already has a working
    // in-place editor for plaintext/richtext, so offer it directly instead
    // of just announcing absence.
    const writable = field.fieldType === 'plaintext' || field.fieldType === 'richtext';
    return (
      <div className={rowClass} ref={rowRef}>
        {head(null)}
        <div className="wb-field-row-body wb-empty-field muted small">
          <span>Not found in the source.</span>
          {writable && (
            <button
              type="button" className="btn btn-icon btn-small"
              onClick={() => onEdit({ ...field, skipped: false, text: '' })}
            >
              Write It In
            </button>
          )}
        </div>
      </div>
    );
  }

  switch (field.fieldType) {
    case 'button':
      return (
        <div className={rowClass} ref={rowRef}>
          {head(null)}
          <div className="wb-field-row-body">
            <div className="wb-cta-trio-list">
              {(field.buttons ?? []).map((btn, bi) => (
                <div key={bi} className="wb-cta-trio">
                  <div className="wb-cta-trio-row">
                    <span className="muted small wb-cta-trio-label">Label:</span>
                    <EditableText
                      value={btn.text}
                      onChange={(v) => {
                        const buttons = field.buttons.map((b, i) => (i === bi ? { ...b, text: v } : b));
                        onEdit({ ...field, buttons });
                      }}
                    />
                  </div>
                  <div className="wb-cta-trio-row">
                    <span className="muted small wb-cta-trio-label">URL:</span>
                    <span className="small" style={{ wordBreak: 'break-all' }}>{btn.url}</span>
                    <CopyButton text={btn.url} label="Copy URL" iconOnly />
                  </div>
                  {btn.color && (
                    <div className="wb-cta-trio-row">
                      <span className="muted small wb-cta-trio-label">Color:</span>
                      {isCssColor(btn.color) && <span className="wb-color-swatch" style={{ background: btn.color }} />}
                      <span className="small">{btn.color}</span>
                      {btn.colorRationale && <span className="muted small">— {btn.colorRationale}</span>}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      );
    case 'link':
      return (
        <div className={rowClass} ref={rowRef}>
          {head(field.url && <CopyButton text={field.text || field.url} onCopied={() => onCopy?.()} />, { showCopied: true })}
          <div
            className={`wb-field-row-body small ${field.url ? 'wb-field-row-body--clickable' : ''}`}
            onClick={() => field.url && copyAndMark(field.text || field.url)}
            title={field.url ? 'Click to copy' : undefined}
          >
            {field.text} <span className="muted">→</span> <span style={{ wordBreak: 'break-all' }}>{field.url}</span>
          </div>
        </div>
      );
    case 'image':
      return (
        <div className={rowClass} ref={rowRef}>
          {head(null)}
          <div className="wb-field-row-body">
            <div className="small">{field.roleNote}</div>
            {field.altTextHandoff && (
              <Link to="/alt-text" className="notice-link small">
                Generate alt text in the Alt Text tool <ExternalLinkIcon size={10} />
              </Link>
            )}
          </div>
        </div>
      );
    case 'enum':
      return (
        <div className={rowClass} ref={rowRef}>
          {head(null)}
          <div className="wb-field-row-body small">{field.enumValue}</div>
        </div>
      );
    case 'listing':
      return (
        <div className={rowClass} ref={rowRef}>
          {head(null)}
          <div className="wb-field-row-body">
            {(field.listItems ?? []).map((it, i) => {
              const text = [it.title, it.description].filter(Boolean).join(': ');
              return (
                <div key={i} className="wb-listing-item">
                  <div className="wb-listing-item-row">
                    {it.title && <strong className="small">{it.title}</strong>}
                    <span style={{ flex: 1 }} />
                    <CopyButton text={text || it.url} iconOnly />
                  </div>
                  {it.description && <div className="small">{it.description}</div>}
                  {it.url && <div className="small muted" style={{ wordBreak: 'break-all' }}>{it.url}</div>}
                </div>
              );
            })}
          </div>
        </div>
      );
    default: { // plaintext, richtext, date
      const isRichtext = field.fieldType === 'richtext';
      const plainText = isRichtext ? field.text.replace(/<[^>]+>/g, '') : field.text;
      const controls = isRichtext
        ? (field.text && (
            <>
              <button
                type="button" className="btn btn-icon-only btn-small"
                title={rawEdit ? 'Preview formatted' : 'Edit raw HTML'}
                onClick={() => setRawEdit((v) => !v)}
              >
                {rawEdit ? <EyeIcon size={12} /> : <PencilIcon size={12} />}
              </button>
              <CopyButton text={field.text} label="Copy formatted" onCopied={() => onCopy?.()} />
              <CopyButton text={plainText} label="Copy plain" onCopied={() => onCopy?.()} />
            </>
          ))
        : (field.text && <CopyButton text={field.text} onCopied={() => onCopy?.()} />);
      return (
        <div className={rowClass} ref={rowRef}>
          {head(controls, { showCopied: true })}
          <div className={`wb-field-row-body ${isEmphasisField(field) ? 'wb-field-row-body--emphasis' : ''}`}>
            {isRichtext && !rawEdit && field.text ? (
              <div
                className="wb-richtext-preview wb-field-row-body--clickable"
                onClick={() => copyAndMark(plainText)}
                title="Click to copy plain text"
                dangerouslySetInnerHTML={{ __html: field.text }}
              />
            ) : (
              <EditableText
                value={field.text} multiline={isRichtext || field.text.length > 80}
                rows={isRichtext ? 7 : 3}
                onChange={(v) => onEdit({ ...field, text: v })}
              />
            )}
            <CharCount text={field.text} limit={field.charLimit} />
          </div>
        </div>
      );
    }
  }
}

function SkeletonCard({ row }) {
  return (
    <div className="card section-card wb-skel-card">
      <div className="section-head">
        <h2 className="section-title">{row.component}</h2>
        <span className="skel wb-skel-line" style={{ width: 70, height: 20 }} />
      </div>
      <span className="skel wb-skel-line" />
      <span className="skel wb-skel-line" style={{ width: '80%' }} />
      <span className="skel wb-skel-line" style={{ width: '60%' }} />
    </div>
  );
}

function PopulatedCard({
  item, index, order, spec, pasted, onTogglePasted, onRegenerate, regenerating, onFieldEdit, editedKeys,
  dense, copiedFieldSet, focusedFieldIndex, onFieldCopied, onStartCopy, onRowRef,
}) {
  const badge = STATUS_BADGE[item.status] ?? STATUS_BADGE.valid;
  const StatusIcon = STATUS_ICON[item.status] ?? STATUS_ICON.valid;
  const hasPageLevelFields = item.fields.some((f) => f.isPageLevel);

  return (
    <div className="wb-plan-block">
      {!dense && (
        <div className="wb-thumb-wrap">
          <ComponentThumb spec={spec} variant="rail" />
          <span className="wb-order-chip">{order}</span>
          <span
            className={`wb-thumb-status-badge wb-thumb-status-badge--${item.status}`}
            role="img" aria-label={badge.label} title={badge.label}
          >
            <StatusIcon size={12} />
          </span>
          <span className="wb-ghost-order" aria-hidden="true">{String(order).padStart(2, '0')}</span>
          <span className="wb-thumb-category-bar" style={{ background: categoryColor(spec?.category) }} />
        </div>
      )}
      <div className="wb-populated-card-body">
        <div className="wb-card-header">
          <div className="wb-card-title-row">
            <h2 className="section-title">
              {dense && <span className="muted small wb-dense-order">{order}.</span>}
              {item.component}
              <VariantBadge variant={spec?.visualVariant} />
              {dense && <span className={`badge ${badge.cls}`}>{badge.label}</span>}
              {hasPageLevelFields && (
                <span
                  className="badge-muted"
                  title="These fields live on the parent page, not the component itself -- unconfirmed by the public design system."
                >
                  <AlertDotIcon size={10} /> page-level fields
                </span>
              )}
            </h2>
          </div>
          <div className="wb-card-toolbar">
            {!dense && (
              <>
                <a
                  href={designPageUrl(item.component)} target="_blank" rel="noopener noreferrer"
                  className="btn btn-icon-only btn-small" title="View on design system"
                >
                  <ExternalLinkIcon size={12} />
                </a>
                <button type="button" className="btn btn-icon btn-small" onClick={() => onRegenerate(index)} disabled={regenerating}>
                  {regenerating ? 'Regenerating…' : 'Regenerate'}
                </button>
              </>
            )}
            <button type="button" className="btn btn-primary btn-small" onClick={onStartCopy}>
              Start copying <ArrowRightIcon size={11} />
            </button>
          </div>
        </div>

        {item.fields.length === 0 ? (
          <p className="muted small">No fields to populate — structural placement only.</p>
        ) : (
          <div className="wb-field-list">
            {item.fields.map((f, fi) => (
              <FieldBlock
                key={fi} field={f} edited={editedKeys.has(fi)}
                copied={copiedFieldSet.has(fi)} focused={focusedFieldIndex === fi}
                onEdit={(nextField) => onFieldEdit(index, fi, nextField)}
                onCopy={() => onFieldCopied(fi)}
                rowRef={(el) => onRowRef(fi, el)}
              />
            ))}
          </div>
        )}

        {!dense && item.warnings.length > 0 && (
          <div className="card notice notice-muted">
            {item.warnings.map((w, i) => <p key={i} className="muted small" style={{ margin: 0 }}>{w}</p>)}
          </div>
        )}

        {!dense && <SpecialFeaturesList features={spec?.specialFeatures} />}

        <label className="wb-paste-row small">
          <input type="checkbox" checked={pasted} onChange={() => onTogglePasted(index)} />
          Mark as pasted into Sitecore
        </label>
      </div>
    </div>
  );
}

export default function WebBuilderPage() {
  const { live } = useData();
  const { content: handoffContent } = useContentHandoff();
  const inputRef = useRef(null);
  const [configStatus, setConfigStatus] = useState(null);
  const [catalog, setCatalog] = useState(null);

  useEffect(() => {
    if (!live) return;
    fetch('/api/config/status').then((r) => r.json()).then(setConfigStatus).catch(() => {});
  }, [live]);

  const [inputMode, setInputMode] = useState(handoffContent ? 'handoff' : 'url');
  const [url, setUrl] = useState('');
  const [file, setFile] = useState(null);
  const [fileError, setFileError] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const [content, setContent] = useState(null);
  const [plan, setPlan] = useState(null);
  const [populated, setPopulated] = useState(null);   // array | null, entries may have status "loading"
  const [pastedSet, setPastedSet] = useState(new Set());
  const [pastedKey, setPastedKey] = useState('');
  const [editedKeys, setEditedKeys] = useState({});    // { [cardIndex]: Set<fieldIndex> }
  const [undoStacks, setUndoStacks] = useState({});    // { [cardIndex]: PopulatedComponent[] }
  const [regeneratingIndex, setRegeneratingIndex] = useState(null);
  const [copiedFields, setCopiedFields] = useState({}); // { [cardIndex]: Set<fieldIndex> }
  const [copiedKey, setCopiedKey] = useState('');
  const [focusTarget, setFocusTarget] = useState(null); // { cardIndex, fieldIndex } | null
  const [denseMode, setDenseMode] = useState(false);    // "Paste mode" toggle
  const fieldRowRefs = useRef({});
  const cardSectionRefs = useRef({});

  function pickFile(selected) {
    if (!selected) return;
    if (!kindForFile(selected)) {
      setFileError('Unsupported file type — use PDF, Word, PowerPoint, Excel, Markdown, or an image.');
      return;
    }
    setFileError('');
    setFile(selected);
  }

  async function getContent() {
    if (inputMode === 'handoff') return handoffContent;
    let body;
    if (inputMode === 'url') {
      if (!url.trim()) throw new Error('A page URL is required.');
      body = { kind: 'url', url: url.trim() };
    } else {
      if (!file) throw new Error('A file is required.');
      body = { kind: kindForFile(file), fileBase64: await fileToBase64(file), mediaType: file.type || undefined };
    }
    const response = await fetch('/api/web-builder/extract', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const responseBody = await response.json();
    if (!response.ok) throw new Error(responseBody.error ?? `HTTP ${response.status}`);
    return responseBody;
  }

  async function makePlan(event) {
    event.preventDefault();
    setError('');
    setPlan(null);
    setPopulated(null);
    setBusy(true);
    try {
      const structuredContent = await getContent();
      setContent(structuredContent);
      const response = await fetch('/api/web-builder/plan', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ structuredContent }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? `HTTP ${response.status}`);
      setPlan(body);
    } catch (e) {
      setError(String(e.message ?? e));
    } finally {
      setBusy(false);
    }
  }

  function removeRow(index) {
    setPlan((prev) => ({ ...prev, rows: prev.rows.filter((_, i) => i !== index) }));
  }

  function swapRow(index, newComponent) {
    setPlan((prev) => {
      const rows = [...prev.rows];
      const old = rows[index];
      rows[index] = {
        ...old, component: newComponent,
        alternatives: [old.component, ...old.alternatives.filter((a) => a !== newComponent)],
      };
      return { ...prev, rows };
    });
  }

  function reorderRows(fromIndex, toIndex) {
    setPlan((prev) => {
      const rows = [...prev.rows];
      const [moved] = rows.splice(fromIndex, 1);
      rows.splice(toIndex, 0, moved);
      return { ...prev, rows: rows.map((r, i) => ({ ...r, order: i + 1 })) };
    });
  }

  function populateOneRow(row, index) {
    fetch('/api/web-builder/regenerate-component', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ structuredContent: content, row }),
    })
      .then((r) => r.json().then((body) => ({ ok: r.ok, body })))
      .then(({ ok, body }) => {
        setPopulated((prev) => {
          if (!prev) return prev;
          const next = [...prev];
          next[index] = ok ? body.component : {
            component: row.component, sectionIndices: row.sectionIndices, fields: [],
            warnings: [body.error ?? 'population failed'], status: 'needs_review',
          };
          return next;
        });
      })
      .catch((e) => {
        setPopulated((prev) => {
          if (!prev) return prev;
          const next = [...prev];
          next[index] = {
            component: row.component, sectionIndices: row.sectionIndices, fields: [],
            warnings: [String(e.message ?? e)], status: 'needs_review',
          };
          return next;
        });
      });
  }

  function approveAndPopulate() {
    setError('');
    const key = planKey(content, plan);
    setPastedKey(key);
    setPastedSet(loadPastedState(key));
    const cKey = `${key}:copied`;
    setCopiedKey(cKey);
    setCopiedFields(loadCopiedState(cKey));
    setFocusTarget(null);
    setEditedKeys({});
    setUndoStacks({});
    fieldRowRefs.current = {};
    setPopulated(plan.rows.map((row) => ({
      component: row.component, sectionIndices: row.sectionIndices,
      fields: [], warnings: [], status: 'loading',
    })));
    plan.rows.forEach((row, i) => populateOneRow(row, i));
  }

  function regenerateCard(index) {
    const row = plan.rows[index];
    setUndoStacks((prev) => ({ ...prev, [index]: [...(prev[index] ?? []), populated[index]] }));
    setRegeneratingIndex(index);
    setPopulated((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], status: 'loading' };
      return next;
    });
    fetch('/api/web-builder/regenerate-component', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ structuredContent: content, row }),
    })
      .then((r) => r.json().then((body) => ({ ok: r.ok, body })))
      .then(({ ok, body }) => {
        setPopulated((prev) => {
          const next = [...prev];
          next[index] = ok ? body.component : { ...next[index], status: 'needs_review', warnings: [body.error] };
          return next;
        });
        setEditedKeys((prev) => ({ ...prev, [index]: new Set() }));
        setCopiedFields((prev) => {
          const next = { ...prev, [index]: new Set() };
          saveCopiedState(copiedKey, next);
          return next;
        });
      })
      .finally(() => setRegeneratingIndex(null));
  }

  function regenerateAll() {
    setEditedKeys({});
    setUndoStacks({});
    setCopiedFields({});
    saveCopiedState(copiedKey, {});
    setFocusTarget(null);
    setPopulated((prev) => prev.map((p) => ({ ...p, status: 'loading' })));
    plan.rows.forEach((row, i) => populateOneRow(row, i));
  }

  function togglePasted(index) {
    setPastedSet((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index); else next.add(index);
      savePastedState(pastedKey, next);
      return next;
    });
  }

  function editField(cardIndex, fieldIndex, nextField) {
    setUndoStacks((prev) => ({ ...prev, [cardIndex]: [...(prev[cardIndex] ?? []), populated[cardIndex]] }));
    setPopulated((prev) => {
      const next = [...prev];
      const fields = [...next[cardIndex].fields];
      fields[fieldIndex] = nextField;
      next[cardIndex] = { ...next[cardIndex], fields };
      return next;
    });
    setEditedKeys((prev) => {
      const set = new Set(prev[cardIndex] ?? []);
      set.add(fieldIndex);
      return { ...prev, [cardIndex]: set };
    });
  }

  function undoCard(cardIndex) {
    setUndoStacks((prev) => {
      const stack = prev[cardIndex] ?? [];
      if (stack.length === 0) return prev;
      const previousState = stack[stack.length - 1];
      setPopulated((pop) => {
        const next = [...pop];
        next[cardIndex] = previousState;
        return next;
      });
      return { ...prev, [cardIndex]: stack.slice(0, -1) };
    });
  }

  function scrollToField(cardIndex, fieldIndex) {
    fieldRowRefs.current[`${cardIndex}:${fieldIndex}`]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  // The heart of the "copy & advance" workflow: after a field is copied,
  // jump straight to the next not-yet-copied field that's actually a
  // single-value Sitecore paste target, so a reviewer can work a whole card
  // top to bottom without hunting for what's left.
  function focusNextField(cardIndex, fromFieldIndex) {
    const fields = populated?.[cardIndex]?.fields ?? [];
    const alreadyCopied = copiedFields[cardIndex] ?? new Set();
    for (let i = fromFieldIndex; i < fields.length; i++) {
      if (isGuidedField(fields[i]) && !alreadyCopied.has(i)) {
        scrollToField(cardIndex, i);
        setFocusTarget({ cardIndex, fieldIndex: i });
        setTimeout(() => {
          setFocusTarget((cur) => (cur?.cardIndex === cardIndex && cur?.fieldIndex === i ? null : cur));
        }, 2600);
        return;
      }
    }
    setFocusTarget(null);
  }

  function handleFieldCopied(cardIndex, fieldIndex) {
    setCopiedFields((prev) => {
      const set = new Set(prev[cardIndex] ?? []);
      set.add(fieldIndex);
      const next = { ...prev, [cardIndex]: set };
      saveCopiedState(copiedKey, next);
      return next;
    });
    focusNextField(cardIndex, fieldIndex + 1);
  }

  function startGuidedCopy(cardIndex) {
    focusNextField(cardIndex, 0);
  }

  function scrollToCard(cardIndex) {
    cardSectionRefs.current[cardIndex]?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  const pastedCount = populated ? populated.filter((_, i) => pastedSet.has(i)).length : 0;
  const componentsCount = populated?.length ?? 0;
  const anyLoading = populated?.some((p) => p.status === 'loading') ?? false;
  const statusCounts = populated
    ? populated.reduce((acc, p) => { acc[p.status] = (acc[p.status] ?? 0) + 1; return acc; }, {})
    : {};
  const catalogByName = useMemo(() => {
    if (!catalog) return null;
    return Object.fromEntries(catalog.map((c) => [c.name, c]));
  }, [catalog]);

  // Alternatives' purpose blurbs come from the catalog -- fetched once, best
  // effort (the swap picker still works with just names if this fails).
  useEffect(() => {
    if (!live || catalog) return;
    fetch('/api/web-builder/catalog').then((r) => (r.ok ? r.json() : null)).then((d) => {
      if (d?.components) setCatalog(d.components);
    }).catch(() => {});
  }, [live, catalog]);

  return (
    <div className="app">
      <Header active="web-builder" crumbs={['Web Builder']} />
      <div className="page-body">
        <div>
          <h1 className="h1">Web Builder</h1>
          <div className="meta-line muted">
            Map content onto UTA's real Sitecore components — a reviewable
            layout plan first, then populated, ready-to-paste fields.
          </div>
        </div>

        {!live ? (
          <div className="card notice notice-muted">
            <AlertDotIcon />
            <span>
              Viewing a static export. To build a layout, serve the dashboard
              with its backend: <code className="code-inline">python -m src.server</code>
            </span>
          </div>
        ) : configStatus && !configStatus.components ? (
          <div className="card notice notice-muted">
            <AlertDotIcon />
            <span>
              No component catalog is configured yet. <Link to="/setup">Run setup</Link> to
              get started.
            </span>
          </div>
        ) : (
          <div className="stack-32">
            <div className="card run-card">
              <form className="run-form run-form--top-level" onSubmit={makePlan}>
                <div className="chip-row">
                  {handoffContent && (
                    <button type="button" className={`chip ${inputMode === 'handoff' ? 'active' : ''}`}
                           onClick={() => setInputMode('handoff')}>
                      Use Content Writer Output
                    </button>
                  )}
                  <button type="button" className={`chip ${inputMode === 'url' ? 'active' : ''}`}
                         onClick={() => setInputMode('url')}>
                    Enter URL
                  </button>
                  <button type="button" className={`chip ${inputMode === 'upload' ? 'active' : ''}`}
                         onClick={() => setInputMode('upload')}>
                    Upload File
                  </button>
                </div>

                {inputMode === 'handoff' && handoffContent && (
                  <div className="meta-line muted">
                    Using <strong>{handoffContent.pageTitle}</strong> from Content Writer
                    ({handoffContent.sections.length} sections).
                  </div>
                )}

                {inputMode === 'url' && (
                  <label className="run-field">
                    <span className="run-label">Page URL</span>
                    <input type="url" placeholder="https://www.uta.edu/admissions/apply"
                          value={url} onChange={(e) => setUrl(e.target.value)} disabled={busy} />
                  </label>
                )}

                {inputMode === 'upload' && (
                  <div
                    className={`dropzone alt-drop ${file ? 'dropzone--filled alt-drop--filled' : ''}`}
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
                        <UploadIcon size={22} style={{ color: 'var(--ink-3)' }} />
                        <span className="alt-drop-label">Drop a file here, or click to browse</span>
                      </>
                    )}
                  </div>
                )}
                {fileError && (
                  <div className="run-error">
                    <AlertCircleIcon size={14} style={{ color: 'var(--status-danger-text)', flex: 'none' }} />
                    <span>{fileError}</span>
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
                    {busy ? 'Working…' : 'Build Layout Plan'}
                  </button>
                </div>
              </form>
            </div>

            {busy && (
              <MascotLoader
                toolIcon={BuilderIcon}
                indeterminateMessages={[
                  'Reading the page content…',
                  'Matching sections to the component catalog…',
                  'Drafting the layout plan…',
                ]}
              />
            )}

            {plan && !populated && (
              <div className="stack-12">
                <div className="section-title">Layout Plan</div>
                {plan.unmatchedNotes?.length > 0 && (
                  <div className="card notice notice-bad">
                    {plan.unmatchedNotes.map((n, i) => <p key={i} style={{ margin: 0 }}>{n}</p>)}
                  </div>
                )}
                <PlanPreviewRail plan={plan} catalog={catalogByName} onSwap={swapRow} onRemove={removeRow} onReorder={reorderRows} />
                <div className="run-actions">
                  <button type="button" className="btn btn-primary" onClick={approveAndPopulate} disabled={busy}>
                    Approve & Populate Fields
                  </button>
                </div>
              </div>
            )}

            {populated && (
              <div className="stack-12">
                <div className="wb-progress-header">
                  <div className="section-title">Populated Fields</div>
                  <div className="controls-row" style={{ gap: 8 }}>
                    <div className="chip-row">
                      <button type="button" className={`chip ${!denseMode ? 'active' : ''}`} onClick={() => setDenseMode(false)}>
                        Review Mode
                      </button>
                      <button type="button" className={`chip ${denseMode ? 'active' : ''}`} onClick={() => setDenseMode(true)}>
                        Paste Mode
                      </button>
                    </div>
                    <button type="button" className="btn btn-icon" onClick={() => {
                      setPlan((prev) => ({ ...prev }));
                      setPopulated(null);
                    }}>
                      <ArrowLeftIcon size={12} /> Back To Plan
                    </button>
                    <button type="button" className="btn btn-secondary" onClick={regenerateAll} disabled={anyLoading}>
                      Regenerate All
                    </button>
                  </div>
                </div>

                <div className="wb-summary-strip">
                  <span>{componentsCount} component{componentsCount === 1 ? '' : 's'}</span>
                  {statusCounts.valid > 0 && <span className="wb-summary-chip wb-summary-chip--good">{statusCounts.valid} valid</span>}
                  {statusCounts.adjusted > 0 && <span className="wb-summary-chip wb-summary-chip--warn">{statusCounts.adjusted} adjusted</span>}
                  {statusCounts.needs_review > 0 && <span className="wb-summary-chip wb-summary-chip--bad">{statusCounts.needs_review} needs review</span>}
                  <span className="wb-summary-sep" />
                  <span>{pastedCount} of {componentsCount} pasted</span>
                </div>
                <div className="progress-track">
                  <div className="progress-fill" style={{ width: `${componentsCount ? (pastedCount / componentsCount) * 100 : 0}%` }} />
                </div>

                {plan.rows.length > 3 && (
                  <div className="wb-jumpnav">
                    {populated.map((item, i) => (
                      <button
                        key={i} type="button"
                        className={`wb-jumpnav-chip ${item.status !== 'loading' ? `wb-jumpnav-chip--${item.status}` : ''}`}
                        onClick={() => scrollToCard(i)} title={item.component}
                      >
                        <span className="wb-jumpnav-order">{plan.rows[i].order}</span>
                        <span className="wb-jumpnav-name">{item.component}</span>
                      </button>
                    ))}
                  </div>
                )}

                {populated.map((item, i) => (
                  item.status === 'loading' ? (
                    <SkeletonCard key={i} row={plan.rows[i]} />
                  ) : (
                    <div key={i} style={{ position: 'relative' }} ref={(el) => { cardSectionRefs.current[i] = el; }}>
                      <PopulatedCard
                        item={item} index={i} order={plan.rows[i].order} spec={catalogByName?.[item.component]}
                        pasted={pastedSet.has(i)} onTogglePasted={togglePasted}
                        onRegenerate={regenerateCard} regenerating={regeneratingIndex === i}
                        onFieldEdit={editField} editedKeys={editedKeys[i] ?? new Set()}
                        dense={denseMode}
                        copiedFieldSet={copiedFields[i] ?? new Set()}
                        focusedFieldIndex={focusTarget?.cardIndex === i ? focusTarget.fieldIndex : null}
                        onFieldCopied={(fi) => handleFieldCopied(i, fi)}
                        onStartCopy={() => startGuidedCopy(i)}
                        onRowRef={(fi, el) => { fieldRowRefs.current[`${i}:${fi}`] = el; }}
                      />
                      {(undoStacks[i]?.length ?? 0) > 0 && (
                        <button
                          type="button" className="btn btn-icon btn-small"
                          style={{ position: 'absolute', top: 16, right: 16 }}
                          onClick={() => undoCard(i)}
                        >
                          Undo
                        </button>
                      )}
                    </div>
                  )
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
