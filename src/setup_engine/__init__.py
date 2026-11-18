"""The setup engine: turns freeform brand-voice or component-library material
into the structured `config/brand-voice.json` / `config/components.json`
shapes, for a non-UTA fork. Only matters once someone forks the repo for a
different organization -- UTA's own usage never touches this (its config is
pre-committed, hand-authored -- see Phase 1 of the build).

Reuses `content_writer.extraction` for pulling text out of whatever material
was uploaded (a URL, a doc, a screenshot), the same handlers Content Writer
itself uses -- see `docs/design/content-writer-web-builder.md`'s "Setup engine (freeform ingestion)" section.
"""
