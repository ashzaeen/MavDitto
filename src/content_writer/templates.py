"""Content types the writer can produce -- each one a brief form, an output
shape, and the writing instructions specific to that kind of copy.

The registry drives both sides: the server serves it as-is to the frontend
(so a new template is one entry here, no JSX change), and `generate.py`
reads `instructions`/`sections_hint`/`char_limit` when building the prompt.
Default tone dials per template live in the brand profile's
`tone_by_context`, not here -- they are a brand decision, not a format one.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

GROUPS = ("Web page copy", "News & events", "Micro-copy & SEO")


@dataclass(frozen=True)
class Field_:
    name: str
    label: str
    type: str = "text"          # text | textarea | url | date
    required: bool = False
    help: str = ""
    placeholder: str = ""


@dataclass(frozen=True)
class LengthPreset:
    label: str
    words: int | None           # None = relative to the source (rewrite only)
    instruction: str


PAGE_LENGTHS = (
    LengthPreset("Short", 200, "About 200 words in total."),
    LengthPreset("Standard", 450, "About 450 words in total."),
    LengthPreset("Long", 900, "About 900 words in total."),
)
REWRITE_LENGTHS = (
    LengthPreset("Match original", None, "Keep each section's length close to its original length."),
    LengthPreset("Condense", None, "Condense each section into tighter, web-ready copy -- cut padding, keep every fact."),
    LengthPreset("Expand", None, "Expand thin source material (e.g. a sparse slide bullet) into fuller web copy that "
                                 "reads naturally on a page, without inventing facts that are not present in the source."),
)
NEWS_LENGTHS = (
    LengthPreset("Brief", 250, "About 250 words."),
    LengthPreset("Standard", 500, "About 500 words."),
    LengthPreset("Feature", 900, "About 900 words."),
)
SHORT_LENGTHS = (
    LengthPreset("Standard", None, "Keep each item as tight as the format allows."),
)
COMPOSE_LENGTHS = (
    LengthPreset("Compact", None, "6-8 blocks: a hero, 2-3 supporting blocks, and one call to action."),
    LengthPreset("Standard", None, "10-14 blocks -- follow the request's own shape (images, quotes, "
                                   "stats, links, CTAs) as closely as it specifies."),
    LengthPreset("Rich", None, "16 or more blocks -- use this when the request asks for many of one "
                               "kind (e.g. \"8 links\") so there is room for all of them."),
)

_KEY_POINTS = Field_("key_points", "Key points and facts", "textarea",
                     help="One per line. Only these facts (plus the knowledge base and any source "
                          "material) may appear -- nothing is invented.")
_QUOTES = Field_("quotes", "Quotes (with attribution)", "textarea",
                 help="Paste real quotes as: Name, title: \"quote\". The writer uses only these, "
                      "verbatim, and never makes one up.")


@dataclass(frozen=True)
class ContentTemplate:
    key: str
    label: str
    group: str
    description: str
    fields: tuple[Field_, ...] = ()
    output_kind: str = "page"                # page | items | blocks
    requires_source: bool = False
    accepts_source: bool = True
    length_presets: tuple[LengthPreset, ...] = PAGE_LENGTHS
    char_limit: int | None = None            # per item, items templates only
    default_audience: str = ""
    sections_hint: str = ""
    instructions: str = ""

    @property
    def covers_source(self) -> bool:
        """Page templates that build a page *from* source material, where the
        writer usually wants every detail carried over (a syllabus turned into
        a course page). Summary condenses by design; rewrite already goes
        section by section."""
        return self.output_kind == "page" and self.key not in ("summary", "rewrite-page", "compose-page")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["fields"] = [asdict(f) for f in self.fields]
        d["length_presets"] = [asdict(p) for p in self.length_presets]
        d["covers_source"] = self.covers_source
        return d


TEMPLATES: tuple[ContentTemplate, ...] = (
    # --- Web page copy ------------------------------------------------------
    ContentTemplate(
        key="rewrite-page", label="Rewrite an existing page", group="Web page copy",
        description="Bring a live page or an uploaded document into the brand voice, section by section.",
        requires_source=True, length_presets=REWRITE_LENGTHS,
        instructions="Rewrite every source section in place. Keep every fact, figure, date, name and "
                     "requirement; never merge, split, add, or drop sections."),
    ContentTemplate(
        key="new-page", label="New page from a brief", group="Web page copy",
        description="Draft a web page from a topic and the facts it needs to carry.",
        fields=(Field_("topic", "What is this page about?", required=True,
                       placeholder="e.g. Tutoring services for first-year students"),
                _KEY_POINTS,
                Field_("outline", "Sections you want (optional)", "textarea",
                       help="One heading per line, in order.")),
        sections_hint="An intro, then body sections with clear headings (following the source's own "
                      "structure when there is one), and a closing call to action only if the brief "
                      "or source gives a real next step.",
        instructions="Open with what the reader can do or learn on this page. Headings should be "
                     "scannable and specific, not clever."),
    ContentTemplate(
        key="program-page", label="Academic program page", group="Web page copy",
        description="A degree or certificate page: what you'll learn, requirements, outcomes, next steps.",
        fields=(Field_("program_name", "Program name", required=True,
                       placeholder="e.g. Bachelor of Science in Nursing"),
                Field_("college", "College or department"),
                Field_("format", "Format and length", placeholder="e.g. Online, 12 months"),
                _KEY_POINTS,
                Field_("requirements", "Admission requirements", "textarea"),
                Field_("outcomes", "Careers and outcomes", "textarea",
                       help="Only outcomes you can source."),
                Field_("deadlines", "Deadlines", "textarea")),
        default_audience="prospective-undergrad",
        sections_hint="Overview, What you'll learn, Admission requirements, Careers and outcomes, "
                      "Deadlines and cost if given, and a call to action to apply or request information.",
        instructions="Write for someone deciding whether to apply. Requirements and deadlines must "
                     "be copied exactly as given -- they are commitments, not copy."),
    ContentTemplate(
        key="landing-page", label="Landing or campaign page", group="Web page copy",
        description="A focused page with one goal and one primary call to action.",
        fields=(Field_("campaign_goal", "What should the reader do?", required=True,
                       placeholder="e.g. Register for Preview Day"),
                Field_("offer", "What they get", "textarea"),
                _KEY_POINTS,
                Field_("deadline", "Deadline or date", "date")),
        sections_hint="A headline section that states the offer, 2-3 short supporting sections, "
                      "and the call to action repeated at the end.",
        instructions="Every section must serve the single goal. Keep sections short."),
    ContentTemplate(
        key="department-page", label="Department or about page", group="Web page copy",
        description="Who a unit is, what it does, and how to reach it.",
        fields=(Field_("unit_name", "Department, office or center", required=True),
                Field_("what_we_do", "What it does", "textarea", required=True),
                Field_("services", "Services or programs", "textarea"),
                Field_("contact", "Contact details", "textarea",
                       help="Copied exactly -- phone numbers are formatted to the style rules.")),
        default_audience="community",
        sections_hint="About, What we do, Services, Contact.",
        instructions="Institutional register unless the reader is a student looking for help."),
    ContentTemplate(
        key="compose-page", label="Compose a page (free-form)", group="Web page copy",
        description="Describe the page in your own words -- sections, images, quotes, figures, "
                    "links, calls to action -- and get a fully designed page, not just paragraphs.",
        fields=(Field_(
            "prompt", "Describe the page", "textarea", required=True,
            placeholder="e.g. A page about what makes UTA great, with a hero and a CTA button, "
                        "4 images, a pull quote, a stats band, and 8 links.",
            help="Say what the page is about and any specific blocks you want -- images, quotes, "
                "figures, links, CTA buttons -- and how many. Anything not grounded in the "
                "brief, the source or the knowledge base is written to match what you asked "
                "for and clearly labeled as a placeholder."),),
        output_kind="blocks", length_presets=COMPOSE_LENGTHS,
        instructions="Plan the page as an ordered sequence of typed blocks before writing them: "
                     "a hero, then whichever mix of text, image, quote, stat, links and CTA "
                     "blocks the request calls for, in a sensible reading order. Group 2 or "
                     "more stat blocks together so they read as one figures band. Every quote, "
                     "stat, link target and image scene must come from the brief, the source or "
                     "the verified facts, or be clearly invented to match the request's shape "
                     "and marked as a placeholder with a note explaining what it stands in for. "
                     "Treat any count the request states literally: if it says \"4 images,\" write "
                     "exactly 4 image blocks (spread through the page, not clustered in one spot), "
                     "not 1; if it says a CTA belongs \"at the beginning,\" the second block (right "
                     "after the hero) is a CTA block, and if it says one belongs \"near the end,\" "
                     "the second-to-last content block (before any closing divider) is a CTA block."),
    # --- News & events --------------------------------------------------------
    ContentTemplate(
        key="news-story", label="News story", group="News & events",
        description="An inverted-pyramid news article.",
        fields=(Field_("topic", "What happened?", required=True),
                Field_("who_what_when_where", "Who, what, when, where, why", "textarea", required=True),
                _QUOTES,
                Field_("more_info", "Where readers learn more", "url")),
        length_presets=NEWS_LENGTHS, default_audience="community",
        sections_hint="A lead paragraph with the news, then supporting paragraphs in descending "
                      "importance, quotes where supplied, and a closing paragraph with where to learn more. "
                      "Section headings are optional for news.",
        instructions="Lead with the news itself in the first sentence. AP style. Attribute every "
                     "quote; use only supplied quotes."),
    ContentTemplate(
        key="event-announcement", label="Event announcement", group="News & events",
        description="An event listing or announcement with every logistic a reader needs.",
        fields=(Field_("event_name", "Event name", required=True),
                Field_("date_time", "Date and time", required=True, placeholder="e.g. Oct. 12, 10 a.m.-2 p.m."),
                Field_("location", "Location", required=True),
                Field_("audience_for", "Who it's for"),
                Field_("registration", "How to register or RSVP", help="URL or instructions."),
                Field_("cost", "Cost"),
                Field_("details", "What happens there", "textarea")),
        length_presets=(LengthPreset("Listing", 120, "About 120 words."),
                        LengthPreset("Announcement", 300, "About 300 words.")),
        default_audience="current-students",
        sections_hint="The essentials (what, when, where, who, how to register) first, then details.",
        instructions="Dates, times, locations and costs are copied exactly as given."),
    ContentTemplate(
        key="press-release", label="Press release", group="News & events",
        description="A media-ready release with dateline, quotes and boilerplate.",
        fields=(Field_("announcement", "The announcement", required=True),
                Field_("dateline", "Dateline", placeholder="ARLINGTON, Texas"),
                Field_("key_facts", "Key facts", "textarea", required=True),
                _QUOTES,
                Field_("media_contact", "Media contact", "textarea")),
        length_presets=NEWS_LENGTHS, default_audience="media",
        sections_hint="Headline as the page title; dateline and lead paragraph; body in descending "
                      "importance; quotes where supplied; the organization boilerplate from the knowledge "
                      "base if present; media contact last.",
        instructions="Formal, factual, AP style. No marketing adjectives."),
    ContentTemplate(
        key="spotlight", label="Faculty, student or alumni spotlight", group="News & events",
        description="A story-led profile of one person.",
        fields=(Field_("person_name", "Name", required=True),
                Field_("role", "Role", placeholder="e.g. Nursing student, alumna, professor of physics"),
                Field_("degrees", "Degrees (for alumni)", placeholder="e.g. '99 PhD, '94 MS, Physics"),
                Field_("story_points", "Their story", "textarea", required=True),
                _QUOTES),
        length_presets=NEWS_LENGTHS, default_audience="alumni-donors",
        sections_hint="A scene-setting opening about the person, 2-4 sections that follow their "
                      "story, and a close that looks ahead.",
        instructions="Let the person's own supplied words carry the piece. Never invent a detail "
                     "of someone's life."),
    # --- Micro-copy & SEO -------------------------------------------------------
    ContentTemplate(
        key="headlines", label="Headlines and page titles", group="Micro-copy & SEO",
        description="Options for a headline or <title>, 60 characters or fewer.",
        fields=(Field_("page_topic", "What is the page or story about?", required=True),
                _KEY_POINTS),
        output_kind="items", length_presets=SHORT_LENGTHS, char_limit=60,
        instructions="Each option takes a different angle. Specific beats clever."),
    ContentTemplate(
        key="meta-descriptions", label="Meta descriptions", group="Micro-copy & SEO",
        description="Search-result descriptions, 155 characters or fewer.",
        fields=(Field_("page_topic", "What does the page let the reader do?", required=True),
                Field_("page_url", "Page URL (optional)", "url"),
                _KEY_POINTS),
        output_kind="items", length_presets=SHORT_LENGTHS, char_limit=155,
        instructions="Say what the page lets the reader do. Work in the target keywords naturally."),
    ContentTemplate(
        key="ctas", label="Calls to action and button labels", group="Micro-copy & SEO",
        description="Verb-first labels that say exactly what happens.",
        fields=(Field_("action_goal", "What happens when they click?", required=True,
                       placeholder="e.g. Opens the graduate application"),
                Field_("context", "Where the button appears")),
        output_kind="items", length_presets=SHORT_LENGTHS, char_limit=30, accepts_source=False,
        instructions="2 to 5 words each, starting with a verb. Never \"Click here\" or \"Learn more\" alone."),
    ContentTemplate(
        key="faq-set", label="FAQ set", group="Micro-copy & SEO",
        description="Questions and answers, each answer leading with the direct answer.",
        fields=(Field_("topic", "Topic", required=True),
                Field_("questions", "Questions to answer (optional)", "textarea",
                       help="One per line. Leave blank to have the likely questions drafted."),
                _KEY_POINTS),
        sections_hint="One section per question: the heading is the question, the body the answer. "
                      "Every section's kind is faq-item.",
        instructions="Answer in the first sentence, then give the detail. Never answer beyond the "
                     "supplied facts -- say where to find out instead."),
    ContentTemplate(
        key="summary", label="Summary or TL;DR", group="Micro-copy & SEO",
        description="A short summary of a page, document, or pasted text.",
        fields=(Field_("text", "Text to summarize", "textarea",
                       help="Or attach a URL or file as source material instead."),),
        length_presets=(LengthPreset("One line", 30, "One sentence, about 30 words."),
                        LengthPreset("Short", 80, "About 80 words."),
                        LengthPreset("Paragraph", 150, "About 150 words.")),
        sections_hint="One section, no heading.",
        instructions="Keep every figure, date and requirement that matters to the reader; drop "
                     "everything else."),
)

BY_KEY = {t.key: t for t in TEMPLATES}


def get(key: str) -> ContentTemplate:
    if key not in BY_KEY:
        raise ValueError(f"unknown template {key!r}; expected one of {', '.join(BY_KEY)}")
    return BY_KEY[key]


COVER_SOURCE = "Cover everything in the source"


def covers(template: ContentTemplate, label: str, target_words: int | None,
           has_source: bool) -> bool:
    """Full-coverage mode: a page built from a source, with no shorter length
    chosen. The default whenever a source is attached -- a 7-page syllabus
    squeezed into the 200-word "Short" default lost 18 of 20 key details."""
    return (has_source and template.covers_source and not target_words
            and label in ("", COVER_SOURCE))


def length_instruction(template: ContentTemplate, label: str, target_words: int | None,
                       source_words: int | None = None) -> str:
    if target_words:
        return f"About {target_words} words in total."
    if source_words and covers(template, label, None, True):
        return (f"Carry every fact in the source material into the page: every date, time, "
                f"place, name, contact detail, number, requirement and policy. Reorganize, "
                f"group and tighten the wording for the web, but never summarize a detail away. "
                f"The source has about {source_words} words of content, so the page will be "
                f"of similar length.")
    for p in template.length_presets:
        if p.label == label:
            return p.instruction
    return template.length_presets[0].instruction if template.length_presets else ""


def missing_required(template: ContentTemplate, brief: dict[str, Any], has_source: bool) -> list[str]:
    """Required brief fields left blank. A template that accepts source
    material treats an attached source as satisfying its brief -- the facts
    come from there instead."""
    if template.requires_source:
        return [] if has_source else ["source material (a URL or file)"]
    if template.key == "summary":
        return [] if (has_source or str(brief.get("text", "")).strip()) else ["text or source material"]
    if template.key == "compose-page":
        # A source is optional grounding material here, never a substitute
        # for the prompt -- it's the prompt that says which blocks to write
        # and how many, something no attached document can supply on its own.
        return [] if str(brief.get("prompt", "")).strip() else ["a description of the page"]
    if has_source and template.accepts_source:
        return []
    return [f.label for f in template.fields
            if f.required and not str(brief.get(f.name, "")).strip()]
