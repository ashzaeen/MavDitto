import { useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import Header from '../components/Header.jsx';
import RiskBadge from '../components/RiskBadge.jsx';
import JudgePanel from '../components/JudgePanel.jsx';
import DetailHeader from '../components/DetailHeader.jsx';
import { usePages } from '../data/useData.jsx';
import { CheckIcon, AlertCircleIcon } from '../components/Icons.jsx';

// The review screen answers one question: what happened to this page?
//
// The first design showed the whole page as a single word-level diff, and
// that marks everything on a page that really changed: both panels come out
// solid red and solid green, and the aligner starts matching coincidental
// words between unrelated sentences, so the few unmarked fragments are noise.
//
// The second design fixed that by chunking on a word budget and showing each
// chunk as its own card -- better, but a section with twenty paragraphs still
// sliced into a handful of ~80-word blobs that all carried the same heading
// label, which reads as a stream of identical-looking cards rather than the
// section it actually was.
//
// So the page is rendered as a document now: real headings, paragraphs,
// lists and tables, in the order the page itself puts them in, each side in
// its own natural order, each block coloured by what happened to it. A list
// that dropped one bullet reads as that list with one bullet struck through,
// not as one vague "reworded" card.

function href(url) {
  return /^https?:\/\//i.test(url) ? url : `https://${url}`;
}

function shortUrl(url) {
  return String(url ?? '').replace(/^https?:\/\//i, '').replace(/\/$/, '');
}

function hostOf(url) {
  try {
    return new URL(href(url)).host.replace(/^www\./, '');
  } catch {
    return '';
  }
}

function segStyle(kind) {
  if (kind === 'removed') {
    return {
      background: 'var(--status-danger-bg)',
      textDecoration: 'line-through',
      textDecorationColor: 'var(--status-danger-text)',
      padding: '0 2px',
      borderRadius: 3,
    };
  }
  if (kind === 'added') {
    return {
      background: 'var(--status-success-bg)',
      textDecoration: 'underline',
      textDecorationStyle: 'dashed',
      textDecorationColor: 'var(--status-success-text)',
      padding: '0 2px',
      borderRadius: 3,
    };
  }
  return {};
}

function Segments({ segments }) {
  return (
    <>
      {segments.map((s, i) => (
        <span key={i} style={segStyle(s.kind)}>
          {s.text}
        </span>
      ))}
    </>
  );
}

const VERDICT_LABEL = { reworded: 'Rewritten', dropped: 'No Longer Here', added: 'New' };

function VerdictTag({ verdict }) {
  if (!verdict || verdict === 'kept') return null;
  return <span className={`doc-tag doc-tag-${verdict}`}>{VERDICT_LABEL[verdict]}</span>;
}

/** One structural unit of the document -- a heading, a paragraph, a list, or
 * a table -- rendered as exactly that and coloured by what happened to it. */
function BlockNode({ block, dim }) {
  const verdict = block.verdict || 'kept';
  const wrapClass = `doc-block doc-verdict-${verdict}${dim ? ' doc-dim' : ''}`;

  if (block.type === 'heading') {
    const Level = `h${Math.min(4, Math.max(2, block.level || 2))}`;
    return (
      <div className={wrapClass}>
        <Level className="doc-heading">
          {block.text} <VerdictTag verdict={verdict} />
        </Level>
      </div>
    );
  }

  if (block.type === 'list') {
    const ListTag = block.ordered ? 'ol' : 'ul';
    return (
      <div className={wrapClass}>
        <ListTag className="doc-list">
          {block.items.map((item, i) => (
            <li key={i} className={`doc-item-${item.verdict}`}>{item.text}</li>
          ))}
        </ListTag>
        <VerdictTag verdict={verdict} />
      </div>
    );
  }

  if (block.type === 'table') {
    return (
      <div className={wrapClass}>
        <table className="doc-table">
          {block.columns?.length > 0 && (
            <thead>
              <tr>{block.columns.map((c, i) => <th key={i}>{c}</th>)}</tr>
            </thead>
          )}
          <tbody>
            {block.items.map((row, i) => (
              <tr key={i} className={`doc-item-${row.verdict}`}>
                {row.text.split(' | ').map((cell, j) => <td key={j}>{cell}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
        <VerdictTag verdict={verdict} />
      </div>
    );
  }

  // paragraph / quote
  const Wrapper = block.type === 'quote' ? 'blockquote' : 'p';
  return (
    <div className={wrapClass}>
      <Wrapper className="doc-para">
        {block.worthHighlighting && block.segments ? (
          <Segments segments={block.segments} />
        ) : (
          block.text
        )}
      </Wrapper>
      <VerdictTag verdict={verdict} />
      {verdict === 'reworded' && !block.worthHighlighting && (
        <span className="doc-noise-note">
          Too different for a word-by-word mark-up to mean anything — read it in full.
        </span>
      )}
    </div>
  );
}

function DocumentColumn({ label, blocks, onlyChanges }) {
  return (
    <div className="doc-col">
      <div className="doc-col-label">{label}</div>
      {blocks.map((block, i) => (
        <BlockNode
          key={i}
          block={block}
          dim={onlyChanges && block.type !== 'heading' && (block.verdict ?? 'kept') === 'kept'}
        />
      ))}
    </div>
  );
}

export default function PageDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const PAGES = usePages();
  const [onlyChanges, setOnlyChanges] = useState(false);

  const index = PAGES.findIndex((p) => String(p.id) === id);
  const safeIndex = index === -1 ? 0 : index;
  const page = PAGES[safeIndex];
  const detail = page?.detail;

  // Counted from the old-page document, plus what the new page alone added --
  // a quick orientation before scrolling the two columns.
  const summary = useMemo(() => {
    const out = { reworded: 0, dropped: 0, added: 0 };
    for (const b of detail?.oldDocument ?? []) {
      if (b.type !== 'heading' && out[b.verdict] !== undefined) out[b.verdict] += 1;
    }
    for (const b of detail?.newDocument ?? []) {
      if (b.type !== 'heading' && b.verdict === 'added') out.added += 1;
    }
    return out;
  }, [detail]);

  if (!PAGES.length) {
    return (
      <div className="app migration-scope">
        <Header active="migration" crumbs={['Migration Validator', 'Migrated Pages', 'Loading…']} />
        <div className="page-body">
          <div className="card empty-card">Loading…</div>
        </div>
      </div>
    );
  }

  const goTo = (i) => {
    const clamped = Math.max(0, Math.min(PAGES.length - 1, i));
    navigate(`/migration/pages/${PAGES[clamped].id}`);
  };

  const structural = detail
    ? [
        {
          label: 'Headings',
          oldVal: detail.headingsOld,
          newVal: detail.headingsNew,
          lost: detail.headingsDropped.length,
          items: detail.headingsDropped,
        },
        {
          label: 'Images',
          oldVal: detail.imagesOld,
          newVal: detail.imagesNew,
          lost: detail.imagesDropped,
          note: detail.missingAlt > 0 ? `${detail.missingAlt} missing alt text` : '',
        },
        {
          label: 'Links',
          oldVal: detail.linksOld,
          newVal: detail.linksNew,
          lost: detail.brokenLinks,
        },
        ...(detail.documentsOld > 0
          ? [
              {
                label: 'Documents',
                oldVal: detail.documentsOld,
                newVal: detail.documentsNew,
                lost: detail.documentsDropped.length,
                items: detail.documentsDropped,
              },
            ]
          : []),
      ]
    : [];

  return (
    <div className="app migration-scope">
      <Header
        active="migration"
        crumbs={['Migration Validator', 'Migrated Pages', shortUrl(page.newUrl) || page.label || 'Page Detail']}
      />
      <div className="page-body">
        <DetailHeader
          backTo="/migration/results"
          backLabel="Back to migrated pages"
          index={safeIndex}
          total={PAGES.length}
          onPrev={() => goTo(safeIndex - 1)}
          onNext={() => goTo(safeIndex + 1)}
          meta={
            <>
              <RiskBadge tier={page.tier} />
              <a href={href(page.oldUrl)} target="_blank" rel="noopener noreferrer">
                {shortUrl(page.oldUrl)} ↗
              </a>
              <span className="meta-arrow">→</span>
              <a href={href(page.newUrl)} target="_blank" rel="noopener noreferrer">
                {shortUrl(page.newUrl)} ↗
              </a>
            </>
          }
        />

        {!detail ? (
          <div className="card empty-card">
            <p className="muted">
              {page.problems?.length
                ? `This pair could not be compared: ${page.problems.join('; ')}`
                : 'No comparison was recorded for this page.'}
            </p>
          </div>
        ) : (
          <div className="stack-24">
            {/* Two numbers, and what they mean together. Similarity alone is
                the one that hides loss, so it never appears on its own. */}
            <div className="score-row">
              <div className="card score-tile">
                <span className="score-label">Coverage</span>
                <span className="score-value">{page.coverage ?? '—'}%</span>
                <span className="score-help">
                  of the old page's text has a counterpart
                </span>
              </div>
              <div className="card score-tile">
                <span className="score-label">Similarity</span>
                <span className="score-value">{page.similarity ?? '—'}%</span>
                <span className="score-help">how alike the two read overall</span>
              </div>
              <div className="card score-tile score-tile--wide">
                <span className="score-label">Reading</span>
                <span className="score-reading">{detail.interpretation}</span>
                {detail.caveats.length > 0 && (
                  <ul className="score-caveats">
                    {detail.caveats.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            <JudgePanel page={page} detail={detail} />

            {structural.length > 0 && (
              <div className="card section-card">
                <h2 className="section-title">Findings</h2>
                <div className="findings-grid">
                  {structural.map((s) => (
                    <div
                      className={`findings-card ${s.lost > 0 ? 'findings-card--loss' : ''}`}
                      key={s.label}
                    >
                      <div className="findings-card-head">
                        {s.lost > 0 ? (
                          <AlertCircleIcon size={13} style={{ color: 'var(--status-danger-text)' }} />
                        ) : (
                          <CheckIcon size={13} style={{ color: 'var(--status-success-text)' }} />
                        )}
                        <span>{s.label}</span>
                      </div>
                      <div className="findings-card-counts">
                        <span>{s.oldVal} → {s.newVal}</span>
                        {s.lost > 0 && (
                          <span className="findings-card-lost">{s.lost} no counterpart</span>
                        )}
                      </div>
                      {s.note && <div className="muted small">{s.note}</div>}
                      {s.items?.length > 0 && (
                        <ul className="loss-list">
                          {s.items.slice(0, 6).map((item, i) => (
                            <li key={i}>{item}</li>
                          ))}
                          {s.items.length > 6 && (
                            <li className="muted">… and {s.items.length - 6} more</li>
                          )}
                        </ul>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="card section-card">
              <div className="section-head">
                <h2 className="section-title">The pages, side by side</h2>
                <label className="doc-toggle">
                  <input
                    type="checkbox"
                    checked={onlyChanges}
                    onChange={(e) => setOnlyChanges(e.target.checked)}
                  />
                  Dim what didn't change
                </label>
              </div>
              <div className="doc-summary">
                {summary.reworded > 0 && (
                  <span><span className="dot" style={{ background: 'var(--status-warning-text)' }} /> {summary.reworded} rewritten</span>
                )}
                {summary.dropped > 0 && (
                  <span><span className="dot" style={{ background: 'var(--status-danger-text)' }} /> {summary.dropped} dropped</span>
                )}
                {summary.added > 0 && (
                  <span><span className="dot" style={{ background: 'var(--status-success-text)' }} /> {summary.added} new</span>
                )}
                {!summary.reworded && !summary.dropped && !summary.added && (
                  <span className="muted">Nothing on this page changed.</span>
                )}
              </div>

              {(detail.oldDocument?.length || detail.newDocument?.length) ? (
                <div className="doc-columns">
                  <DocumentColumn label="Old" blocks={detail.oldDocument}
                                  onlyChanges={onlyChanges} />
                  <DocumentColumn label="New" blocks={detail.newDocument}
                                  onlyChanges={onlyChanges} />
                </div>
              ) : (
                <p className="muted small">No comparable text on this page.</p>
              )}
            </div>

          </div>
        )}
      </div>
    </div>
  );
}
