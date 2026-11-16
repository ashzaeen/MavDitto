import { useEffect, useState } from 'react';
import {
  SparklesIcon,
  CheckIcon,
  XCircleIcon,
  EyeIcon,
  EyeOffIcon,
  ShieldCheckIcon,
  ExternalLinkIcon,
} from './Icons.jsx';

export default function LlmConfigModal({ isOpen, onClose, onConfigSaved }) {
  const [activeProvider, setActiveProvider] = useState('claude');
  const [keys, setKeys] = useState({ claude: '', openai: '', gemini: '' });
  const [status, setStatus] = useState(null);
  const [showKey, setShowKey] = useState({ claude: false, openai: false, gemini: false });
  const [testing, setTesting] = useState({ claude: false, openai: false, gemini: false });
  const [testResult, setTestResult] = useState({ claude: null, openai: null, gemini: null });
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  useEffect(() => {
    if (!isOpen) return;

    // Fetch current server-side configuration status
    fetch('/api/config/llm')
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) {
          setStatus(data);
          let initial = data.activeProvider;
          if (!data[initial]?.configured) {
            if (data.openai?.configured) initial = 'openai';
            else if (data.gemini?.configured) initial = 'gemini';
            else if (data.claude?.configured) initial = 'claude';
          }
          setActiveProvider(initial || 'claude');
          setKeys({
            claude: data.claude?.masked || '',
            openai: data.openai?.masked || '',
            gemini: data.gemini?.masked || '',
          });
        }
      })
      .catch(() => {});
  }, [isOpen]);

  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === 'Escape' && isOpen) onClose();
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  async function handleTest(provider) {
    setTesting((prev) => ({ ...prev, [provider]: true }));
    setTestResult((prev) => ({ ...prev, [provider]: null }));

    try {
      const res = await fetch('/api/config/llm/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider,
          key: keys[provider],
        }),
      });
      const data = await res.json();
      setTestResult((prev) => ({
        ...prev,
        [provider]: data.ok
          ? { ok: true, text: 'Connected successfully' }
          : { ok: false, text: data.error || 'Connection failed' },
      }));
    } catch (err) {
      setTestResult((prev) => ({
        ...prev,
        [provider]: { ok: false, text: err.message || 'Network error testing API key' },
      }));
    } finally {
      setTesting((prev) => ({ ...prev, [provider]: false }));
    }
  }

  async function handleSave(e) {
    e.preventDefault();
    setIsSaving(true);
    setSaveSuccess(false);

    let providerToSave = activeProvider;
    const hasKey = (p) => Boolean((keys[p] && !keys[p].includes('...')) || status?.[p]?.configured);
    if (!hasKey(providerToSave)) {
      if (hasKey('openai')) providerToSave = 'openai';
      else if (hasKey('gemini')) providerToSave = 'gemini';
      else if (hasKey('claude')) providerToSave = 'claude';
    }

    try {
      const res = await fetch('/api/config/llm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          activeProvider: providerToSave,
          claude: keys.claude,
          openai: keys.openai,
          gemini: keys.gemini,
        }),
      });

      if (res.ok) {
        const updated = await res.json();
        setStatus(updated);
        setActiveProvider(updated.activeProvider || providerToSave);
        setSaveSuccess(true);
        if (onConfigSaved) onConfigSaved(updated);
        setTimeout(() => {
          setSaveSuccess(false);
          onClose();
        }, 1200);
      }
    } catch {
      // Handle error gracefully
    } finally {
      setIsSaving(false);
    }
  }

  const providers = [
    {
      id: 'claude',
      badge: 'Claude API',
      color: '#d97706',
      badgeBg: 'rgba(217, 119, 6, 0.12)',
      placeholder: 'sk-ant-api03-...',
      docUrl: 'https://console.anthropic.com/settings/keys',
    },
    {
      id: 'openai',
      badge: 'OpenAI API',
      color: '#10a37f',
      badgeBg: 'rgba(16, 163, 127, 0.12)',
      placeholder: 'sk-proj-...',
      docUrl: 'https://platform.openai.com/api-keys',
    },
    {
      id: 'gemini',
      badge: 'Gemini API',
      color: '#2563eb',
      badgeBg: 'rgba(37, 99, 235, 0.12)',
      placeholder: 'AIzaSy...',
      docUrl: 'https://aistudio.google.com/app/apikey',
    },
  ];

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal-window llm-modal-card card"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="llm-modal-title"
      >
        <div className="modal-header">
          <div className="modal-title-row">
            <span className="llm-header-icon-box">
              <SparklesIcon size={16} />
            </span>
            <div>
              <h2 id="llm-modal-title" className="h2 llm-modal-title">
                Configure LLM Providers
              </h2>
              <div className="small muted">
                Set local API keys for AI-assisted tools across MavDitto.
              </div>
            </div>
          </div>
          <button
            type="button"
            className="icon-btn"
            onClick={onClose}
            aria-label="Close dialog"
            title="Close dialog"
          >
            <XCircleIcon size={16} />
          </button>
        </div>

        <form onSubmit={handleSave} className="modal-body">
          <div className="form-group">
            <label className="form-label">Providers</label>
            <div className="small muted">
              Select the active provider used for automated generation (Alt Text, LLM Judge,
              Content Writer), then add its API key below.
            </div>
          </div>

          <div className="provider-list">
            {providers.map((p) => {
              const isConfigured = status?.[p.id]?.configured;
              const isActive = activeProvider === p.id;
              const result = testResult[p.id];
              const isTesting = testing[p.id];
              const isShown = showKey[p.id];
              const radioId = `llm-provider-${p.id}`;

              return (
                <div
                  key={p.id}
                  className={`provider-card card ${isActive ? 'provider-card--active' : ''}`}
                  onClick={(e) => {
                    if (e.target.closest('.btn-toggle-visibility, .btn-test-conn, .provider-doc-link')) return;
                    setActiveProvider(p.id);
                  }}
                >
                  <div className="provider-card-head">
                    <label className="provider-select" htmlFor={radioId}>
                      <input
                        type="radio"
                        id={radioId}
                        name="activeProvider"
                        className="provider-radio"
                        checked={isActive}
                        onChange={() => setActiveProvider(p.id)}
                      />
                      <span
                        className="provider-badge"
                        style={{ color: p.color, background: p.badgeBg }}
                      >
                        {p.badge}
                      </span>
                    </label>

                    <div className="provider-card-status">
                      {isConfigured ? (
                        <span className="badge badge-good">
                          <CheckIcon size={11} /> Configured
                        </span>
                      ) : (
                        <span className="badge-muted">Not Set</span>
                      )}
                    </div>
                  </div>

                  <div className="provider-input-row">
                    <div className="provider-input-wrapper">
                      <input
                        type={isShown ? 'text' : 'password'}
                        className="provider-input"
                        placeholder={p.placeholder}
                        value={keys[p.id]}
                        onFocus={() => {
                          if (!status?.[activeProvider]?.configured) {
                            setActiveProvider(p.id);
                          }
                        }}
                        onChange={(e) => {
                          const val = e.target.value;
                          setKeys((prev) => ({ ...prev, [p.id]: val }));
                          setTestResult((prev) => ({ ...prev, [p.id]: null }));
                          if (val.trim()) {
                            setActiveProvider(p.id);
                          }
                        }}
                        autoComplete="off"
                        spellCheck="false"
                        aria-label={`${p.badge} key`}
                      />
                      <button
                        type="button"
                        className="btn-toggle-visibility"
                        onClick={() =>
                          setShowKey((prev) => ({ ...prev, [p.id]: !prev[p.id] }))
                        }
                        title={isShown ? 'Hide key' : 'Show key'}
                        aria-label={isShown ? 'Hide key' : 'Show key'}
                      >
                        {isShown ? <EyeOffIcon size={13} /> : <EyeIcon size={13} />}
                      </button>
                    </div>

                    <button
                      type="button"
                      className="btn btn-secondary btn-test-conn"
                      onClick={() => handleTest(p.id)}
                      disabled={isTesting || (!keys[p.id] && !isConfigured)}
                      title="Test API Key Connection"
                    >
                      {isTesting ? 'Testing…' : 'Test'}
                    </button>
                  </div>

                  {result && (
                    <div
                      className={`provider-test-result ${
                        result.ok ? 'test-result--good' : 'test-result--bad'
                      }`}
                    >
                      <span className="test-result-indicator" />
                      <span className="small">{result.text}</span>
                    </div>
                  )}

                  <div className="provider-card-footer">
                    <a
                      href={p.docUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="provider-doc-link small muted"
                    >
                      Get API Key <ExternalLinkIcon size={11} />
                    </a>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="modal-footer-info small muted">
            <ShieldCheckIcon size={14} style={{ flex: 'none', color: 'var(--ink-3)' }} />
            <span>
              Keys are stored securely in local app storage (<code>data/llm_config.json</code>) and
              never sent to third-party tracking services.
            </span>
          </div>

          <div className="modal-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={isSaving}>
              Cancel
            </button>
            <button
              type="submit"
              className={`btn btn-primary ${saveSuccess ? 'btn-save-success' : ''}`}
              disabled={isSaving}
            >
              {isSaving ? 'Saving…' : saveSuccess ? 'Saved!' : 'Save Changes'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
