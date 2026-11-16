import { useRef } from 'react';
import { AlertCircleIcon, UploadIcon, XCircleIcon } from '../Icons.jsx';
import { kindForFile } from './api.js';

const SOURCE_MODES = [
  { key: 'none', label: 'No source' },
  { key: 'url', label: 'Page URL' },
  { key: 'upload', label: 'Upload file' },
];

// The template's own fields, rendered from the registry, plus optional
// source material. A template that requires a source (rewrite) hides the
// "No source" choice; one that takes none (CTAs) hides the whole block.
export default function BriefForm({ template, brief, onBriefChange, source, onSourceChange,
  disabled, urlPlaceholder = 'https://www.example.edu/page' }) {
  const inputRef = useRef(null);
  const modes = template.requires_source ? SOURCE_MODES.slice(1) : SOURCE_MODES;
  const mode = template.requires_source && source.mode === 'none' ? 'url' : source.mode;

  function set(name, value) {
    onBriefChange({ ...brief, [name]: value });
  }

  function pickFile(file) {
    if (!file) return;
    if (!kindForFile(file)) {
      onSourceChange({ ...source, file: null,
        fileError: 'Unsupported file type. Use PDF, Word, PowerPoint, Excel, Markdown, or an image.' });
      return;
    }
    onSourceChange({ ...source, mode: 'upload', file, fileError: '' });
  }

  return (
    <div className="stack-16">
      {template.fields.map((f) => (
        <label key={f.name} className="run-field">
          <span className="run-label">
            {f.label}
            {f.required && !template.requires_source && <span className="cw-req" aria-hidden="true"> *</span>}
          </span>
          {f.type === 'textarea' ? (
            <textarea
              className="cw-input"
              rows={f.name === 'text' ? 8 : 4}
              value={brief[f.name] ?? ''}
              placeholder={f.placeholder}
              onChange={(e) => set(f.name, e.target.value)}
              disabled={disabled}
            />
          ) : (
            <input
              className="cw-input"
              type={f.type === 'url' ? 'url' : 'text'}
              value={brief[f.name] ?? ''}
              placeholder={f.type === 'date' ? 'e.g. Oct. 12, 2026' : f.placeholder}
              onChange={(e) => set(f.name, e.target.value)}
              disabled={disabled}
            />
          )}
          {f.help && <span className="run-help">{f.help}</span>}
        </label>
      ))}

      {(template.accepts_source || template.requires_source) && (
        <div className="cw-source">
          <span className="run-label">
            {template.requires_source ? 'Source material' : 'Source material (optional)'}
          </span>
          <div className="chip-row">
            {modes.map((m) => (
              <button
                key={m.key}
                type="button"
                className={`chip ${mode === m.key ? 'active' : ''}`}
                onClick={() => onSourceChange({ ...source, mode: m.key })}
                disabled={disabled}
              >
                {m.label}
              </button>
            ))}
          </div>
          {mode === 'url' && (
            <input
              className="cw-input"
              type="url"
              placeholder={urlPlaceholder}
              value={source.url}
              onChange={(e) => onSourceChange({ ...source, url: e.target.value })}
              disabled={disabled}
              aria-label="Source page URL"
            />
          )}
          {mode === 'upload' && (
            <div
              className={`dropzone alt-drop cw-drop ${source.file ? 'dropzone--filled alt-drop--filled' : ''}`}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); pickFile(e.dataTransfer.files?.[0]); }}
              onClick={() => inputRef.current?.click()}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') inputRef.current?.click(); }}
              role="button"
              tabIndex={0}
            >
              <input
                ref={inputRef}
                type="file"
                accept=".pdf,.docx,.doc,.pptx,.ppt,.xlsx,.xls,.md,.markdown,image/*"
                hidden
                onChange={(e) => pickFile(e.target.files?.[0])}
              />
              {source.file ? (
                <span className="alt-drop-label cw-file">
                  {source.file.name}
                  <button
                    type="button"
                    className="btn btn-icon-only"
                    aria-label="Remove file"
                    onClick={(e) => { e.stopPropagation(); onSourceChange({ ...source, file: null }); }}
                  >
                    <XCircleIcon size={14} />
                  </button>
                </span>
              ) : (
                <>
                  <UploadIcon size={20} style={{ color: 'var(--ink-3)' }} />
                  <span className="alt-drop-label">Drop a file, or click to browse</span>
                  <span className="alt-drop-hint">PDF, Word, PowerPoint, Excel, Markdown, or an image</span>
                </>
              )}
            </div>
          )}
          {source.fileError && (
            <div className="run-error">
              <AlertCircleIcon size={14} style={{ color: 'var(--status-danger-text)', flex: 'none' }} />
              <span>{source.fileError}</span>
            </div>
          )}
          {mode !== 'none' && !template.requires_source && (
            <span className="run-help">
              Facts may come from the source as well as the brief. Nothing outside them is added.
            </span>
          )}
        </div>
      )}
    </div>
  );
}
