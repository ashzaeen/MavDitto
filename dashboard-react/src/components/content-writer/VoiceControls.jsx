import { useState } from 'react';
import { ChevronDownIcon } from '../Icons.jsx';

const DIALS = ['formality', 'energy', 'technical_depth'];
const COVER_SOURCE = 'Cover everything in the source'; // matches templates.COVER_SOURCE

function Dial({ name, info, value, brandDefault, onChange, disabled }) {
  const id = `cw-dial-${name}`;
  const levels = info?.levels ?? {};
  return (
    <div className="cw-dial">
      <div className="cw-dial-head">
        <label htmlFor={id} className="run-label">{info?.label ?? name}</label>
        <span className="cw-dial-value">{value}/5</span>
      </div>
      <div className="cw-dial-track">
        <input
          id={id}
          type="range"
          min="1"
          max="5"
          step="1"
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          disabled={disabled}
          aria-valuetext={`${value} of 5: ${levels[String(value)] ?? ''}`}
        />
        <span className="cw-dial-ticks" aria-hidden="true">
          <span className="cw-dial-default" style={{ left: `${((brandDefault - 1) / 4) * 100}%` }}
                title={`Brand default: ${brandDefault}`} />
        </span>
      </div>
      <div className="cw-dial-level">
        {levels[String(value)]}
        {value === brandDefault && <span className="cw-dial-tag">brand default</span>}
      </div>
    </div>
  );
}

// Audience, goal, tone (dials + presets), length, register, reading level,
// point of view -- then the advanced drawer. Dials show the profile's own
// wording for each level, so "Formality 4" means what this brand says it means.
export default function VoiceControls({ meta, template, settings, onChange, disabled, hasSource }) {
  const [advanced, setAdvanced] = useState(false);
  // A page built from source material defaults to keeping all of it.
  const coverable = Boolean(hasSource && template.covers_source);
  const defaults = meta.toneByContext[template.key] ?? {};
  const note = defaults.note;
  const set = (patch) => onChange({ ...settings, ...patch });
  const dialValue = (d) => settings.dials?.[d] ?? defaults[d] ?? 3;
  const dialsChanged = DIALS.some((d) => settings.dials?.[d] != null && settings.dials[d] !== (defaults[d] ?? 3));
  const isItems = template.output_kind === 'items';
  const isBlocks = template.output_kind === 'blocks';
  const presets = template.length_presets ?? [];

  return (
    <div className="stack-16">
      <label className="run-field">
        <span className="run-label">Audience</span>
        <select value={settings.audience} onChange={(e) => set({ audience: e.target.value })} disabled={disabled}>
          <option value="">
            {template.default_audience
              ? `${meta.audiences.find((a) => a.key === template.default_audience)?.label ?? 'General'} (usual for this type)`
              : 'General'}
          </option>
          {meta.audiences.map((a) => <option key={a.key} value={a.key}>{a.label}</option>)}
        </select>
        {settings.audience && (
          <span className="run-help">{meta.audiences.find((a) => a.key === settings.audience)?.description}</span>
        )}
      </label>
      <label className="run-field">
        <span className="run-label">Goal</span>
        <select value={settings.goal} onChange={(e) => set({ goal: e.target.value })} disabled={disabled}>
          <option value="">Not specified</option>
          {meta.goals.map((g) => <option key={g.key} value={g.key}>{g.label}</option>)}
        </select>
      </label>

      {meta.modelProviders?.length > 0 && (
        <label className="run-field">
          <span className="run-label">Model</span>
          <select value={settings.model} onChange={(e) => set({ model: e.target.value })} disabled={disabled}>
            <option value="">Automatic (recommended)</option>
            {meta.modelProviders.map((p) => (
              <optgroup key={p.key} label={p.active ? `${p.label} (active)` : p.label}>
                {p.models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}{m.id === p.defaultModel ? ' — recommended' : ''}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          {!settings.model && (
            <span className="run-help">
              A slower, more expensive top-tier model is available above if you want to spend
              more on one important page -- Automatic favors speed and cost for everyday use.
            </span>
          )}
        </label>
      )}

      <fieldset className="cw-dials">
        <legend className="run-label">Tone</legend>
        {note && <p className="run-help cw-dials-note">{note}</p>}
        {DIALS.map((d) => (
          <Dial
            key={d}
            name={d}
            info={meta.toneDimensions[d]}
            value={dialValue(d)}
            brandDefault={defaults[d] ?? 3}
            onChange={(v) => set({ dials: { ...settings.dials, [d]: v } })}
            disabled={disabled}
          />
        ))}
        {dialsChanged && (
          <button type="button" className="btn btn-small cw-reset" onClick={() => set({ dials: {} })} disabled={disabled}>
            Reset to brand default
          </button>
        )}
        <div className="chip-row" aria-label="Tone adjustments">
          {meta.toneOptions.map((t) => (
            <button
              key={t}
              type="button"
              aria-pressed={settings.tone.includes(t)}
              className={`chip ${settings.tone.includes(t) ? 'active' : ''}`}
              onClick={() => set({ tone: settings.tone.includes(t)
                ? settings.tone.filter((x) => x !== t) : [...settings.tone, t] })}
              disabled={disabled}
            >
              {t}
            </button>
          ))}
        </div>
      </fieldset>

      {isBlocks && (
        <div className="cw-strictness">
          <span className="run-label">Placeholders</span>
          <div className="chip-row" role="radiogroup" aria-label="Placeholder strictness">
            {meta.strictnessOptions.map((o) => (
              <button
                key={o.key}
                type="button"
                role="radio"
                aria-checked={settings.strictness === o.key}
                className={`chip ${settings.strictness === o.key ? 'active' : ''}`}
                onClick={() => set({ strictness: o.key })}
                disabled={disabled}
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="cw-grid-2">
        {isItems ? (
          <label className="run-field">
            <span className="run-label">Options to write</span>
            <input type="number" className="cw-input" min="1" max={meta.maxItems} value={settings.itemCount}
                   onChange={(e) => set({ itemCount: Number(e.target.value) })} disabled={disabled} />
          </label>
        ) : (
          <label className="run-field">
            <span className="run-label">Length</span>
            <select
              value={settings.targetWords ? 'custom'
                : (settings.length || (coverable ? COVER_SOURCE : presets[0]?.label) || '')}
              onChange={(e) => (e.target.value === 'custom'
                ? set({ targetWords: settings.targetWords || 400 })
                : set({ length: e.target.value, targetWords: null }))}
              disabled={disabled}
            >
              {coverable && <option value={COVER_SOURCE}>{COVER_SOURCE}</option>}
              {presets.map((p) => (
                <option key={p.label} value={p.label}>{p.words ? `${p.label} (~${p.words} words)` : p.label}</option>
              ))}
              {template.key !== 'rewrite-page' && <option value="custom">Custom word count</option>}
            </select>
            {coverable && !settings.targetWords && (settings.length || COVER_SOURCE) === COVER_SOURCE && (
              <span className="run-help">Every date, time, name, number and policy in the source is carried over.</span>
            )}
            {settings.targetWords ? (
              <input type="number" className="cw-input" min="20" max="3000" step="10" value={settings.targetWords}
                     onChange={(e) => set({ targetWords: Number(e.target.value) })} disabled={disabled}
                     aria-label="Target word count" />
            ) : null}
          </label>
        )}
        <label className="run-field">
          <span className="run-label">Register</span>
          <select value={settings.register} onChange={(e) => set({ register: e.target.value })} disabled={disabled}>
            <option value="">Auto-detect</option>
            {meta.registers.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
          </select>
        </label>
        <label className="run-field">
          <span className="run-label">Reading level</span>
          <select value={settings.readingLevel} onChange={(e) => set({ readingLevel: e.target.value })} disabled={disabled}>
            <option value="">Audience default</option>
            {meta.readingLevels.map((r) => <option key={r} value={r}>{r[0].toUpperCase() + r.slice(1)}</option>)}
          </select>
        </label>
        <label className="run-field">
          <span className="run-label">Point of view</span>
          <select value={settings.pointOfView} onChange={(e) => set({ pointOfView: e.target.value })} disabled={disabled}>
            {meta.pointsOfView.map((p) => <option key={p.key} value={p.key}>{p.label}</option>)}
          </select>
        </label>
      </div>

      <button
        type="button"
        className="cw-disclosure"
        aria-expanded={advanced}
        onClick={() => setAdvanced((v) => !v)}
      >
        <ChevronDownIcon size={13} className={advanced ? 'cw-rot' : ''} />
        More options
        {!advanced && (settings.keywords || settings.cta || settings.mustInclude || settings.avoid
          || settings.variants > 1 || settings.language !== 'English') && (
          <span className="cw-dot" aria-label="Some options are set" />
        )}
      </button>

      {advanced && (
        <div className="stack-16 cw-advanced">
          <label className="run-field">
            <span className="run-label">Search keywords</span>
            <input className="cw-input" value={settings.keywords} onChange={(e) => set({ keywords: e.target.value })}
                   placeholder="Comma or line separated" disabled={disabled} />
          </label>
          <label className="run-field">
            <span className="run-label">Call to action</span>
            <input className="cw-input" value={settings.cta} onChange={(e) => set({ cta: e.target.value })}
                   placeholder="e.g. Apply by Dec. 1" disabled={disabled} />
          </label>
          <label className="run-field">
            <span className="run-label">Must include</span>
            <textarea className="cw-input" rows={2} value={settings.mustInclude}
                      onChange={(e) => set({ mustInclude: e.target.value })} placeholder="One per line" disabled={disabled} />
          </label>
          <label className="run-field">
            <span className="run-label">Avoid</span>
            <textarea className="cw-input" rows={2} value={settings.avoid}
                      onChange={(e) => set({ avoid: e.target.value })} placeholder="Topics, words or claims to leave out" disabled={disabled} />
          </label>
          <div className="cw-grid-2">
            <label className="run-field">
              <span className="run-label">Variants</span>
              <select value={settings.variants} onChange={(e) => set({ variants: Number(e.target.value) })} disabled={disabled}>
                {Array.from({ length: meta.maxVariants }, (_, i) => i + 1).map((n) => (
                  <option key={n} value={n}>{n === 1 ? '1 draft' : `${n} drafts to compare`}</option>
                ))}
              </select>
            </label>
            <label className="run-field">
              <span className="run-label">Language</span>
              <select value={settings.language} onChange={(e) => set({ language: e.target.value })} disabled={disabled}>
                {meta.languages.map((l) => <option key={l} value={l}>{l}</option>)}
              </select>
            </label>
            <label className="run-field">
              <span className="run-label">Spend cap (USD)</span>
              <input type="number" className="cw-input" min="0.1" max="20" step="0.1" value={settings.budget}
                     onChange={(e) => set({ budget: Number(e.target.value) })} disabled={disabled} />
            </label>
          </div>
          <label className="cw-check">
            <input type="checkbox" checked={settings.useKnowledgeBase}
                   onChange={(e) => set({ useKnowledgeBase: e.target.checked })} disabled={disabled} />
            <span>
              Cite verified facts from the knowledge base
              <span className="run-help"> ({meta.knowledgeBaseCount} on file, editable in Settings)</span>
            </span>
          </label>
        </div>
      )}
    </div>
  );
}
