// Small helpers shared by the Content Writer components.

export async function postJson(url, body) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  let data = {};
  try {
    data = await response.json();
  } catch {
    throw new Error(`The server returned HTTP ${response.status} with no readable body.`);
  }
  if (!response.ok) throw new Error(data.error ?? `HTTP ${response.status}`);
  return data;
}

export async function getJson(url) {
  const response = await fetch(url);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error ?? `HTTP ${response.status}`);
  return data;
}

// Extension -> the `kind` the server's extraction dispatch expects.
const EXTENSION_KIND = {
  pdf: 'pdf', docx: 'docx', doc: 'docx', pptx: 'pptx', ppt: 'pptx',
  xlsx: 'xlsx', xls: 'xlsx', md: 'markdown', markdown: 'markdown',
};

export function kindForFile(file) {
  if (file.type.startsWith('image/')) return 'image';
  const ext = file.name.split('.').pop()?.toLowerCase();
  return EXTENSION_KIND[ext] || null;
}

export function fileToBase64(file) {
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

export function downloadBase64(filename, mime, base64) {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: mime }));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function lines(text) {
  return String(text || '').split('\n').map((s) => s.trim()).filter(Boolean);
}

export function wordCount(text) {
  return (String(text || '').match(/[A-Za-z0-9][A-Za-z0-9'’-]*/g) || []).length;
}

// Compose mode: which field on a block carries its "main" text -- the one
// Refine/selection acts on when no more specific field is being edited.
const BLOCK_TEXT_FIELD = {
  hero: 'body', heading: 'heading', text: 'body', image: 'imageCaption',
  quote: 'quoteText', stat: 'statLabel', links: '', cta: 'body', divider: '',
};

export function blockPrimaryText(block) {
  const field = BLOCK_TEXT_FIELD[block.type] ?? 'body';
  return field ? (block[field] || '') : '';
}

export function withBlockPrimaryText(block, text) {
  const field = BLOCK_TEXT_FIELD[block.type] ?? 'body';
  return field ? { ...block, [field]: text } : block;
}

// Mirrors ComposedPage.to_structured_content() in
// src/content_writer/models.py -- kept in sync by hand; a one-way,
// best-effort flatten so a composed page can hand off to Web Builder, which
// only understands headed text sections.
export function composedToSections(composed) {
  const out = [];
  for (const b of composed.blocks) {
    if (b.type === 'divider') continue;
    if (b.type === 'quote') {
      const body = `“${b.quoteText}”` + (b.quoteAttribution ? ` — ${b.quoteAttribution}` : '');
      out.push({ heading: b.heading || null, body, kind: 'quote', links: [], mediaRefs: [] });
    } else if (b.type === 'stat') {
      out.push({ heading: b.heading || null, body: `${b.statValue} — ${b.statLabel}`,
        kind: 'fact-list', links: [], mediaRefs: [] });
    } else if (b.type === 'image') {
      const caption = b.imageCaption ? ` ${b.imageCaption}` : '';
      out.push({ heading: b.heading || null, body: `[Image: ${b.imageAlt}]${caption}`, kind: 'body',
        links: [], mediaRefs: b.imageAlt ? [b.imageAlt] : [] });
    } else if (b.type === 'links') {
      out.push({ heading: b.heading || null, body: (b.links || []).map((l) => `- ${l.text}`).join('\n'),
        kind: 'fact-list', links: b.links || [], mediaRefs: [] });
    } else if (b.type === 'cta') {
      const link = (b.links || [])[0] || { text: b.heading, url: '', isButton: true };
      out.push({ heading: null, body: b.body || '', kind: 'cta', links: [link], mediaRefs: [] });
    } else {
      const body = [b.subheading, b.body].filter(Boolean).join('\n');
      out.push({ heading: b.heading || null, body, kind: b.type === 'hero' ? 'intro' : 'body',
        links: [], mediaRefs: [] });
    }
  }
  return out;
}

export function composedToStructuredContent(composed) {
  return {
    pageTitle: composed.title, register: composed.register, sections: composedToSections(composed),
    originalSections: [], sourceNote: '', costUsd: composed.costUsd, pageChromeContext: '',
    brandNotes: composed.brandNotes || [], review: composed.review,
  };
}
