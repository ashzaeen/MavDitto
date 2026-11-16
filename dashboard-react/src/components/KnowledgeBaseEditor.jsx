import { useEffect, useState } from 'react';
import { AlertCircleIcon, CheckCircleIcon } from './Icons.jsx';
import { getJson, postJson } from './content-writer/api.js';

// Verified facts Content Writer may cite. Anything that reads like a
// statistic and is not here, in the brief, or in the source material is
// flagged as critical by the review -- so this list is what makes specific,
// sourced copy possible.
export default function KnowledgeBaseEditor() {
  const [facts, setFacts] = useState(null);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getJson('/api/config/knowledge-base').then((d) => setFacts(d.facts)).catch((e) => setError(String(e.message || e)));
  }, []);

  if (!facts) {
    return error ? <div className="run-error"><AlertCircleIcon size={14} /><span>{error}</span></div>
      : <p className="muted small">Loading…</p>;
  }

  const update = (i, key, value) => {
    setFacts(facts.map((f, n) => (n === i ? { ...f, [key]: value } : f)));
    setSaved(false);
  };

  async function save() {
    setSaving(true);
    setError('');
    try {
      setFacts((await postJson('/api/config/knowledge-base', { facts })).facts);
      setSaved(true);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="bv-editor">
      <div className="bv-scroll">
        <table className="bv-table">
          <thead>
            <tr><th>Title</th><th>Fact, exactly as it may be cited</th><th>Source URL</th><th>As of</th><th aria-label="Actions" /></tr>
          </thead>
          <tbody>
            {facts.map((f, i) => (
              <tr key={f.id || i}>
                <td><input className="cw-input" value={f.title} aria-label="Title" onChange={(e) => update(i, 'title', e.target.value)} /></td>
                <td>
                  <textarea className="cw-input" rows={2} value={f.fact} aria-label="Fact"
                            onChange={(e) => update(i, 'fact', e.target.value)} />
                </td>
                <td><input className="cw-input" type="url" value={f.source_url} aria-label="Source URL" onChange={(e) => update(i, 'source_url', e.target.value)} /></td>
                <td className="bv-narrow"><input className="cw-input" value={f.as_of} aria-label="As of" placeholder="YYYY-MM-DD" onChange={(e) => update(i, 'as_of', e.target.value)} /></td>
                <td className="bv-actions">
                  <button type="button" className="btn btn-small" onClick={() => { setFacts(facts.filter((_, n) => n !== i)); setSaved(false); }}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="bv-save-row">
        <button type="button" className="btn btn-small"
                onClick={() => setFacts([...facts, { id: '', title: '', fact: '', source_url: '', as_of: '', tags: [] }])}>
          Add a fact
        </button>
        <button type="button" className="btn btn-primary" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save knowledge base'}
        </button>
        {saved && <span className="cw-verdict is-pass"><CheckCircleIcon size={14} /> Saved</span>}
        {error && <span className="run-error"><AlertCircleIcon size={14} /> {error}</span>}
      </div>
    </div>
  );
}
