import { useEffect, useState } from 'react';
import { AlertCircleIcon, CheckCircleIcon } from './Icons.jsx';
import { getJson, lines, postJson } from './content-writer/api.js';

const READING = ['grade 8', 'grade 9', 'grade 10', 'grade 12', 'college'];
const DIALS = [['formality', 'Formality'], ['energy', 'Energy'], ['technical_depth', 'Technical depth']];

function slug(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'audience';
}

function RowTable({ columns, rows, onChange, newRow, addLabel }) {
  const update = (i, key, value) => onChange(rows.map((r, n) => (n === i ? { ...r, [key]: value } : r)));
  return (
    <div className="bv-scroll">
      <table className="bv-table">
        <thead>
          <tr>{columns.map((c) => <th key={c.key}>{c.label}</th>)}<th aria-label="Actions" /></tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map((c) => (
                <td key={c.key} className={c.narrow ? 'bv-narrow' : undefined}>
                  {c.render ? c.render(r, (v) => update(i, c.key, v)) : (
                    <input className="cw-input" value={r[c.key] ?? ''} aria-label={c.label}
                           onChange={(e) => update(i, c.key, e.target.value)} />
                  )}
                </td>
              ))}
              <td className="bv-actions">
                <button type="button" className="btn btn-small" onClick={() => onChange(rows.filter((_, n) => n !== i))}>
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" className="btn btn-small" style={{ marginTop: 8 }} onClick={() => onChange([...rows, newRow()])}>
        {addLabel}
      </button>
    </div>
  );
}

// The v2 brand profile fields Content Writer reads -- voice constants,
// house style, audiences, and the tone matrix -- editable in place. Saves
// through the same /api/setup/save the setup wizard uses.
export default function BrandVoiceEditor() {
  const [bv, setBv] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getJson('/api/config/brand-voice').then((d) => setBv(d.brandVoice)).catch((e) => setError(String(e.message || e)));
    getJson('/api/content-writer/templates').then((d) => setTemplates(d.templates)).catch(() => {});
  }, []);

  if (error && !bv) {
    return <div className="run-error"><AlertCircleIcon size={14} /><span>{error}</span></div>;
  }
  if (!bv) return <p className="muted small">Loading…</p>;

  const set = (patch) => { setBv({ ...bv, ...patch }); setSaved(false); };
  const terms = bv.terminology;
  const registers = Object.entries(bv.registers).map(([k, r]) => ({ key: k.replace('_', '-'), label: r.label || k }));

  async function save() {
    setSaving(true);
    setError('');
    try {
      await postJson('/api/setup/save', { brandVoice: bv });
      setSaved(true);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bv-editor">
      <div className="bv-block">
        <h3 className="bv-block-title">Voice constants: We Are / We Are Not</h3>
        <p className="run-help">What the brand always is, and the line on the other side of it. Evidence records where each came from.</p>
        <RowTable
          columns={[{ key: 'we_are', label: 'We are' }, { key: 'we_are_not', label: 'We are not' },
            { key: 'evidence', label: 'Evidence' }]}
          rows={bv.we_are}
          onChange={(rows) => set({ we_are: rows })}
          newRow={() => ({ we_are: '', we_are_not: '', evidence: '' })}
          addLabel="Add a row"
        />
      </div>

      <div className="bv-block">
        <h3 className="bv-block-title">Preferred terms</h3>
        <RowTable
          columns={[{ key: 'use', label: 'Write' }, { key: 'instead_of', label: 'Instead of' }, { key: 'note', label: 'Note' }]}
          rows={terms.preferred}
          onChange={(rows) => set({ terminology: { ...terms, preferred: rows } })}
          newRow={() => ({ use: '', instead_of: '', note: '' })}
          addLabel="Add a term"
        />
      </div>

      <div className="cw-grid-2">
        <label className="run-field">
          <span className="bv-block-title">Banned words and phrases</span>
          <textarea className="cw-input" rows={6} value={terms.banned.join('\n')}
                    onChange={(e) => set({ terminology: { ...terms, banned: lines(e.target.value) } })} />
          <span className="run-help">One per line. Any draft using one fails review.</span>
        </label>
        <label className="run-field">
          <span className="bv-block-title">Claims that need a source</span>
          <textarea className="cw-input" rows={6} value={(terms.needs_source || []).join('\n')}
                    onChange={(e) => set({ terminology: { ...terms, needs_source: lines(e.target.value) } })} />
          <span className="run-help">Superlatives like "award-winning": allowed only when the brief, source or knowledge base says so.</span>
        </label>
        <label className="run-field">
          <span className="bv-block-title">House style rules</span>
          <textarea className="cw-input" rows={6} value={terms.style_rules.join('\n')}
                    onChange={(e) => set({ terminology: { ...terms, style_rules: lines(e.target.value) } })} />
          <span className="run-help">One rule per line.</span>
        </label>
      </div>

      <div className="bv-block">
        <h3 className="bv-block-title">Audiences</h3>
        <RowTable
          columns={[
            { key: 'label', label: 'Audience' },
            { key: 'description', label: 'Who they are' },
            { key: 'reading_level', label: 'Reading level', render: (r, on) => (
              <select value={r.reading_level || ''} onChange={(e) => on(e.target.value)} aria-label="Reading level">
                <option value="">None</option>
                {READING.map((x) => <option key={x} value={x}>{x}</option>)}
              </select>) },
            { key: 'default_register', label: 'Register', render: (r, on) => (
              <select value={r.default_register || ''} onChange={(e) => on(e.target.value || null)} aria-label="Register">
                <option value="">Auto</option>
                {registers.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
              </select>) },
          ]}
          rows={bv.audiences}
          onChange={(rows) => set({ audiences: rows.map((a) => ({ ...a, key: a.key || slug(a.label) })) })}
          newRow={() => ({ key: '', label: '', description: '', reading_level: 'grade 10', default_register: null })}
          addLabel="Add an audience"
        />
      </div>

      {templates.length > 0 && (
        <div className="bv-block">
          <h3 className="bv-block-title">Tone by content type</h3>
          <p className="run-help">The default dial settings (1 to 5) for each content type. Writers can still adjust them per draft.</p>
          <div className="bv-scroll">
            <table className="bv-table">
              <thead>
                <tr><th>Content type</th>{DIALS.map(([, l]) => <th key={l}>{l}</th>)}<th>Guidance</th></tr>
              </thead>
              <tbody>
                {templates.map((t) => {
                  const row = bv.tone_by_context[t.key] ?? { formality: 3, energy: 3, technical_depth: 2, note: '' };
                  const put = (k, v) => set({ tone_by_context: { ...bv.tone_by_context, [t.key]: { ...row, [k]: v } } });
                  return (
                    <tr key={t.key}>
                      <td>{t.label}</td>
                      {DIALS.map(([k, l]) => (
                        <td key={k} className="bv-narrow">
                          <input type="number" min="1" max="5" className="cw-input" value={row[k]}
                                 aria-label={`${t.label} ${l}`}
                                 onChange={(e) => put(k, Math.max(1, Math.min(5, Number(e.target.value) || 1)))} />
                        </td>
                      ))}
                      <td>
                        <input className="cw-input" value={row.note ?? ''} aria-label={`${t.label} guidance`}
                               onChange={(e) => put('note', e.target.value)} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="bv-save-row">
        <button type="button" className="btn btn-primary" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save brand voice'}
        </button>
        {saved && <span className="cw-verdict is-pass"><CheckCircleIcon size={14} /> Saved</span>}
        {error && <span className="run-error"><AlertCircleIcon size={14} /> {error}</span>}
      </div>
    </div>
  );
}
