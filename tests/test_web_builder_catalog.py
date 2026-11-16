from src.web_builder.catalog import by_name, content_components, dynamic_components, load_catalog


def test_load_catalog_reads_the_committed_config():
    catalog = load_catalog()
    assert len(catalog) == 77
    names = {c.name for c in catalog}
    assert "Accordion" in names
    assert "Hero Landing" in names


def test_content_components_excludes_dynamic_and_chrome():
    catalog = load_catalog()
    components = content_components(catalog)
    names = {c.name for c in components}
    assert "Featured News" not in names
    assert "News Listing" not in names
    assert "Header" not in names
    assert "Footer" not in names
    assert "Accordion" in names


def test_dynamic_components_returns_only_the_flagged_entries():
    catalog = load_catalog()
    names = {c.name for c in dynamic_components(catalog)}
    assert names == {"Featured News", "News Listing", "Featured Topic Listing", "News Topic Archive"}


def test_by_name_is_keyed_by_the_exact_component_name():
    catalog = load_catalog()
    lookup = by_name(catalog)
    assert lookup["Accordion"].category == "Page Content"


def test_no_component_carries_a_character_limit_field():
    """A structural guard against regression -- the whole point of the
    catalog correction was to stop claiming character limits the public
    design system never published."""
    catalog = load_catalog()
    for c in catalog:
        assert not hasattr(c, "characterLimit")
        assert not hasattr(c, "titleLimit")
