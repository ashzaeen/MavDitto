"""Broken Link Inspector -- a link-health audit for one page or a whole
subsite, independent of the migration-comparison pipeline.

See ``docs/design/broken-link-inspector.md``
for the feature design this package implements. Start at ``pipeline.py``:
``run_page_scan`` and ``run_site_scan`` are the two entry points everything
else in this package supports.
"""
