import { Link, useNavigate } from 'react-router-dom';
import { useCallback, useEffect, useState } from 'react';
import Header from '../components/Header.jsx';
import { useData } from '../data/useData.jsx';
import { useContentHandoff } from '../data/useContentHandoff.jsx';
import MascotLoader from '../components/MascotLoader.jsx';
import { AlertCircleIcon, AlertDotIcon, ClockIcon, PencilIcon } from '../components/Icons.jsx';
import TemplatePicker from '../components/content-writer/TemplatePicker.jsx';
import BriefForm from '../components/content-writer/BriefForm.jsx';
import VoiceControls from '../components/content-writer/VoiceControls.jsx';
import QualityPanel from '../components/content-writer/QualityPanel.jsx';
import ResultView from '../components/content-writer/ResultView.jsx';
import HistoryDrawer from '../components/content-writer/HistoryDrawer.jsx';
import {
  blockPrimaryText, composedToStructuredContent, downloadBase64, fileToBase64, getJson,
  kindForFile, lines, postJson, withBlockPrimaryText,
} from '../components/content-writer/api.js';

// Brand-aware writing for every content type in the template registry
// (served by /api/content-writer/templates). Each draft comes back already
// reviewed -- deterministic house-style checks plus a critic following the
// vendored brand-voice method -- and every edit can be re-checked.

const DEFAULT_SETTINGS = {
  audience: '', goal: '', dials: {}, tone: [], length: '', targetWords: null, register: '',
  readingLevel: '', pointOfView: '', keywords: '', cta: '', mustInclude: '', avoid: '',
  useKnowledgeBase: true, language: 'English', variants: 1, itemCount: 5, budget: 2,
  strictness: 'mockup', model: '',
};
const EMPTY_SOURCE = { mode: 'none', url: '', file: null, fileError: '' };

function settingsPayload(s) {
  return {
    ...s,
    register: s.register || null,
    keywords: String(s.keywords || '').split(/[,\n]/).map((k) => k.trim()).filter(Boolean),
    mustInclude: lines(s.mustInclude),
    avoid: lines(s.avoid),
  };
}

function settingsFromRecord(r) {
  return {
    ...DEFAULT_SETTINGS,
    ...r,
    register: r.register || '',
    keywords: (r.keywords || []).join(', '),
    mustInclude: (r.mustInclude || []).join('\n'),
    avoid: (r.avoid || []).join('\n'),
  };
}

function pageText(page) {
  return (page?.sections || []).map((s) => [s.heading, s.body].filter(Boolean).join('\n')).join('\n\n');
}

export default function ContentWriterPage() {
  const { live } = useData();
  const { setContent } = useContentHandoff();
  const navigate = useNavigate();

  const [meta, setMeta] = useState(null);
  const [metaError, setMetaError] = useState('');
  const [templateKey, setTemplateKey] = useState('rewrite-page');
  const [briefs, setBriefs] = useState({});
  const [source, setSource] = useState(EMPTY_SOURCE);
  const [settings, setSettings] = useState(DEFAULT_SETTINGS);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [active, setActive] = useState(0);
  const [resultTemplate, setResultTemplate] = useState(null);
  const [resultRequest, setResultRequest] = useState(null);
  const [busyUnit, setBusyUnit] = useState(null);
  const [undo, setUndo] = useState({});
  const [stale, setStale] = useState({});
  const [rechecking, setRechecking] = useState(false);

  const [historyOpen, setHistoryOpen] = useState(false);
  const [runs, setRuns] = useState([]);
  const [runsLoading, setRunsLoading] = useState(false);

  useEffect(() => {
    if (!live) return;
    getJson('/api/content-writer/templates').then(setMeta).catch((e) => setMetaError(String(e.message || e)));
  }, [live]);

  const template = meta?.templates.find((t) => t.key === templateKey);
  const brief = briefs[templateKey] ?? {};
  const shownTemplate = meta?.templates.find((t) => t.key === resultTemplate) ?? template;
  const variant = result?.variants?.[active];

  function chooseTemplate(key) {
    setTemplateKey(key);
    // Dials are per content type: a new type starts from its brand default.
    setSettings((s) => ({ ...s, dials: {}, length: '', targetWords: null }));
    setError('');
  }

  async function buildSource() {
    const mode = template.requires_source && source.mode === 'none' ? 'url' : source.mode;
    if (mode === 'url' && source.url.trim()) return { kind: 'url', url: source.url.trim() };
    if (mode === 'upload' && source.file) {
      return { kind: kindForFile(source.file), fileBase64: await fileToBase64(source.file),
        mediaType: source.file.type || undefined };
    }
    return null;
  }

  async function write(event) {
    event.preventDefault();
    setError('');
    let src;
    try {
      src = await buildSource();
    } catch (e) {
      setError(`Could not read the file: ${e.message || e}`);
      return;
    }
    if (template.requires_source && !src) {
      setError('Add a page URL or a file to rewrite.');
      return;
    }
    const missing = template.fields
      .filter((f) => f.required && !String(brief[f.name] ?? '').trim()).map((f) => f.label);
    if (missing.length && !src && !template.requires_source && template.key !== 'summary') {
      setError(`Fill in: ${missing.join(', ')}.`);
      return;
    }
    const request = { templateKey, brief, settings: settingsPayload(settings), budget: settings.budget };
    if (src) request.source = src;
    setBusy(true);
    try {
      const data = await postJson('/api/content-writer/generate', request);
      setResult(data);
      setResultTemplate(templateKey);
      setResultRequest(request);
      setActive(0);
      setUndo({});
      setStale({});
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  const updateVariant = useCallback((fn) => {
    setResult((prev) => {
      const variants = [...prev.variants];
      variants[active] = fn(variants[active]);
      return { ...prev, variants };
    });
  }, [active]);

  function unitOf(v, i) {
    if (v.kind === 'items') return v.items[i];
    if (v.kind === 'blocks') return v.composed.blocks[i];
    return v.page.sections[i];
  }

  function replaceUnit(i, next, { keepUndo = false } = {}) {
    if (!keepUndo) {
      setUndo((u) => ({ ...u, [active]: { ...(u[active] || {}), [i]: unitOf(variant, i) } }));
    }
    updateVariant((v) => {
      if (v.kind === 'items') {
        return { ...v, items: v.items.map((it, n) => (n === i ? { ...next, chars: next.text.length } : it)) };
      }
      if (v.kind === 'blocks') {
        return { ...v, composed: { ...v.composed,
          blocks: v.composed.blocks.map((b, n) => (n === i ? next : b)) } };
      }
      return { ...v, page: { ...v.page, sections: v.page.sections.map((s, n) => (n === i ? next : s)) } };
    });
    setStale((s) => ({ ...s, [active]: true }));
  }

  function onUnitChange(i, next) {
    // Typing is not an undo step; only regenerate/refine are.
    replaceUnit(i, next, { keepUndo: true });
  }

  function onUndo(i) {
    const prev = undo[active]?.[i];
    if (prev == null) return;
    replaceUnit(i, prev, { keepUndo: true });
    setUndo((u) => {
      const forVariant = { ...(u[active] || {}) };
      delete forVariant[i];
      return { ...u, [active]: forVariant };
    });
  }

  async function onRegenerate(i) {
    setBusyUnit({ index: i, kind: 'regenerate' });
    setError('');
    try {
      if (variant.kind === 'blocks') {
        const composed = variant.composed;
        const data = await postJson('/api/content-writer/regenerate-block', {
          block: composed.blocks[i], index: i, allBlocks: composed.blocks,
          pageTitle: composed.title, prompt: resultRequest?.brief?.prompt ?? '',
          settings: settingsPayload(settings), budget: 0.5,
        });
        replaceUnit(i, data.block);
        return;
      }
      const page = variant.page;
      const data = await postJson('/api/content-writer/regenerate-section', {
        section: page.sections[i], pageTitle: page.pageTitle, register: page.register,
        settings: settingsPayload(settings), templateKey: resultTemplate,
        contextText: pageText(page), budget: 0.5,
      });
      replaceUnit(i, data.section);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusyUnit(null);
    }
  }

  async function onRefine(i, action, instruction, selection) {
    const unit = unitOf(variant, i);
    const whole = variant.kind === 'items' ? unit.text
      : variant.kind === 'blocks' ? blockPrimaryText(unit) : unit.body;
    const text = selection && whole.includes(selection) ? selection : whole;
    setBusyUnit({ index: i, kind: 'refine' });
    setError('');
    try {
      const data = await postJson('/api/content-writer/refine', {
        text, action, instruction, templateKey: resultTemplate,
        contextText: variant.kind === 'items' ? '' : pageText(variant.page),
        settings: settingsPayload(settings), budget: 0.5,
      });
      const merged = text === whole ? data.text : whole.replace(text, data.text);
      if (variant.kind === 'items') replaceUnit(i, { ...unit, text: merged });
      else if (variant.kind === 'blocks') replaceUnit(i, withBlockPrimaryText(unit, merged));
      else replaceUnit(i, { ...unit, body: merged });
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusyUnit(null);
    }
  }

  async function recheck() {
    setRechecking(true);
    setError('');
    try {
      const body = {
        templateKey: resultTemplate, brief: resultRequest?.brief ?? {}, settings: settingsPayload(settings),
        sourceText: pageText({ sections: variant.page?.originalSections }), budget: 0.3,
      };
      if (variant.kind === 'items') body.items = variant.items.map((it) => it.text);
      else if (variant.kind === 'blocks') body.blocks = variant.composed.blocks;
      else body.sections = variant.page.sections;
      const data = await postJson('/api/content-writer/review', body);
      updateVariant((v) => ({ ...v, review: data.review }));
      setStale((s) => ({ ...s, [active]: false }));
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setRechecking(false);
    }
  }

  async function onExport(format) {
    try {
      const body = variant.kind === 'items'
        ? { format, title: shownTemplate?.label ?? 'Options', items: variant.items.map((it) => it.text) }
        : variant.kind === 'blocks'
          ? { format, title: variant.composed.title, subtitle: variant.composed.subtitle,
            blocks: variant.composed.blocks }
          : { format, title: variant.page.pageTitle, sections: variant.page.sections };
      const data = await postJson('/api/content-writer/export', body);
      downloadBase64(data.filename, data.mime, data.base64);
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  function onJump(i) {
    document.getElementById(`cw-unit-${i}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  async function openHistory() {
    setHistoryOpen(true);
    setRunsLoading(true);
    try {
      setRuns((await getJson('/api/content-writer/history')).runs);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setRunsLoading(false);
    }
  }

  async function openRun(id) {
    try {
      const rec = await getJson(`/api/content-writer/history/${encodeURIComponent(id)}`);
      const req = rec.request || {};
      setTemplateKey(req.templateKey);
      setBriefs((b) => ({ ...b, [req.templateKey]: req.brief || {} }));
      setSettings(settingsFromRecord(req.settings || {}));
      setSource(req.source?.kind === 'url' ? { ...EMPTY_SOURCE, mode: 'url', url: req.source.url || '' } : EMPTY_SOURCE);
      setResult(rec.result);
      setResultTemplate(req.templateKey);
      setResultRequest(req);
      setActive(0);
      setUndo({});
      setStale({});
      setHistoryOpen(false);
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  async function deleteRun(id) {
    try {
      setRuns((await postJson('/api/content-writer/history/delete', { id })).runs);
    } catch (e) {
      setError(String(e.message || e));
    }
  }

  const brandLabel = meta ? (meta.brand.isUta ? "UTA's" : `${meta.brand.name}'s`) : 'the';

  return (
    <div className="app">
      <Header active="content-writer" crumbs={['Content Writer']} />
      <div className="page-body">
        <div className="cw-page-head">
          <div>
            <h1 className="h1">Content Writer</h1>
            <div className="meta-line muted">
              Write or rewrite web copy in {brandLabel} brand voice. Every draft is checked
              against the house style and the verified facts before you see it.
            </div>
          </div>
          {live && meta && (
            <button type="button" className="btn btn-icon" onClick={openHistory}>
              <ClockIcon size={13} /> Saved drafts
            </button>
          )}
        </div>

        {!live ? (
          <div className="card notice notice-muted">
            <AlertDotIcon />
            <span>
              Viewing a static export. To write content, serve the dashboard with its backend:{' '}
              <code className="code-inline">python -m src.server</code>
            </span>
          </div>
        ) : metaError ? (
          <div className="card notice notice-muted">
            <AlertDotIcon />
            <span>
              {metaError} <Link to="/setup">Run setup</Link> if no brand voice is configured yet.
            </span>
          </div>
        ) : !meta ? (
          <p className="muted small">Loading…</p>
        ) : (
          <div className="cw-workspace">
            <form className="cw-compose" onSubmit={write} aria-label="Write">
              <section className="card cw-step">
                <h2 className="cw-step-title"><span className="cw-step-num">1</span> What are you writing?</h2>
                <TemplatePicker groups={meta.groups} templates={meta.templates} value={templateKey}
                                onChange={chooseTemplate} disabled={busy} />
              </section>

              <section className="card cw-step">
                <h2 className="cw-step-title"><span className="cw-step-num">2</span> The brief</h2>
                <BriefForm template={template} brief={brief} disabled={busy}
                           urlPlaceholder={meta.brand.isUta ? 'https://www.uta.edu/admissions/apply' : undefined}
                           onBriefChange={(b) => setBriefs((all) => ({ ...all, [templateKey]: b }))}
                           source={source} onSourceChange={setSource} />
              </section>

              <section className="card cw-step">
                <h2 className="cw-step-title"><span className="cw-step-num">3</span> Voice and tone</h2>
                <VoiceControls meta={meta} template={template} settings={settings}
                               onChange={setSettings} disabled={busy}
                               hasSource={(source.mode === 'url' && !!source.url.trim())
                                 || (source.mode === 'upload' && !!source.file)} />
              </section>

              {error && (
                <div className="run-error" role="alert">
                  <AlertCircleIcon size={14} style={{ color: 'var(--status-danger-text)', flex: 'none' }} />
                  <span>{error}</span>
                </div>
              )}

              <div className="cw-submit">
                <button type="submit" className="btn btn-primary" disabled={busy}>
                  {busy ? 'Writing…' : template.key === 'rewrite-page' ? 'Rewrite page' : `Write ${template.label.toLowerCase()}`}
                </button>
                {settings.variants > 1 && <span className="run-help">{settings.variants} drafts, each reviewed</span>}
              </div>
            </form>

            <div className={`cw-output ${busy || !result ? 'is-idle' : ''}`} aria-live="polite">
              {busy ? (
                <MascotLoader
                  toolIcon={PencilIcon}
                  indeterminateMessages={[
                    template.requires_source || source.mode !== 'none' ? 'Reading the source material…' : 'Reading the brief…',
                    `Writing in ${brandLabel} brand voice…`,
                    'Checking house style and every figure…',
                    'Running the brand review…',
                  ]}
                />
              ) : !result ? (
                <div className="cw-empty">
                  <p className="cw-empty-title">Your draft appears here.</p>
                  <p className="muted small">
                    Pick a content type, fill in the brief, and adjust the tone if you need to.
                    Drafts come back with a quality review and notes on which brand guidelines
                    shaped them. You can edit, refine a selection, or regenerate any section.
                  </p>
                </div>
              ) : (
                <div className="stack-16">
                  {result.notice && (
                    <div className="card notice notice-muted"><AlertDotIcon /><span>{result.notice}</span></div>
                  )}
                  {result.variants.length > 1 && (
                    <div className="chip-row" role="tablist" aria-label="Drafts">
                      {result.variants.map((v, i) => (
                        <button key={i} type="button" role="tab" aria-selected={active === i}
                                className={`chip ${active === i ? 'active' : ''}`} onClick={() => setActive(i)}>
                          Draft {i + 1}
                          <span className={`cw-tab-dot ${v.review?.passes ? 'is-pass' : 'is-fail'}`}
                                aria-label={v.review?.passes ? 'passes review' : 'has issues'} />
                        </button>
                      ))}
                    </div>
                  )}
                  {variant && (
                    <div className="cw-result">
                      <ResultView
                        variant={variant}
                        template={shownTemplate}
                        actions={meta.refineActions}
                        onUnitChange={onUnitChange}
                        onRegenerate={onRegenerate}
                        onRefine={onRefine}
                        busyUnit={busyUnit}
                        undo={undo[active] || {}}
                        onUndo={onUndo}
                        onExport={onExport}
                        onSendToWebBuilder={() => {
                          setContent(variant.kind === 'blocks'
                            ? composedToStructuredContent(variant.composed) : variant.page);
                          navigate('/web-builder');
                        }}
                      />
                      <QualityPanel
                        review={variant.review}
                        brandNotes={variant.brandNotes}
                        attempts={variant.attempts}
                        unitLabel={variant.kind === 'items' ? 'Option' : variant.kind === 'blocks' ? 'Block' : 'Section'}
                        onJump={onJump}
                        stale={!!stale[active]}
                        onRecheck={recheck}
                        rechecking={rechecking}
                      />
                    </div>
                  )}
                  <p className="run-help">
                    Cost ${Number(result.costUsd || 0).toFixed(4)}
                    {result.historyId ? ' · saved to Saved drafts' : ''}
                  </p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <HistoryDrawer open={historyOpen} runs={runs} loading={runsLoading} templates={meta?.templates ?? []}
                     onOpen={openRun} onDelete={deleteRun} onClose={() => setHistoryOpen(false)} />
    </div>
  );
}
