# Dashboard and server

The React dashboard and the small standard-library server behind it. The other tools' screens (Alt Text, Broken Links, Content Writer, Web Builder, Setup) live in the same app; their API is listed in [ARCHITECTURE.md](ARCHITECTURE.md#3-server-api).

## The migration results dashboard

```bash
python -m src.server --results data/run --port 8000
```

`src/server.py` serves the built React app and a JSON API: the migration endpoints
(`GET /api/data`, `GET`/`POST /api/run`, `POST /api/run/cancel`, `POST /api/judge`)
plus one group per tool (alt text, link check, content writer, web builder, setup and
config). The full list is in [docs/ARCHITECTURE.md](ARCHITECTURE.md#3-server-api).
Standard library only — this is a single-user tool on localhost, and a web
framework would be a dependency earning nothing. It binds to `127.0.0.1` and
should stay there: the run endpoint fetches arbitrary URLs on request.

Opened as a static bundle with no server behind it, the dashboard still works —
it falls back to `public/data.json` from `python -m src.export_web` and the run
form says it needs the server. Everything else is computed by the pipeline, so
the dashboard never fetches a page or loads a model itself.

It is written for a reviewer or a manager rather than the tool's author, which
sets the priorities:

* **Compare two sites** — two fields and a Run button, at the top of the page
  and open by default when there is nothing to show yet. Progress reports the
  stage and the counts as they become known; Stop is checked between pages, not
  only between stages, because a stop button that waits out a crawl is not a
  stop button.

* **Review screen** — verdict first, then the concrete losses, then the two
  pages rendered as documents, side by side: real headings, paragraphs, lists
  and tables, each in its own page's own order, each block coloured by what
  happened to it. A page-wide word diff was the original design and it fails
  exactly where it matters: on a page that really changed it marks every
  word, so both columns come out solid red and solid green and say nothing.
  A flat list of word-budget passage cards was the second design, and it
  fails differently: a section with twenty paragraphs slices into a handful
  of ~80-word blobs that all carry the same heading label, which reads as
  repetition rather than as the section it is. Rendering the actual document
  structure fixes both — a list that dropped one bullet shows as that list
  with one bullet struck through, not as an unlabeled card among many.
* **Did every page make it across?** — the discovery result, shown first and
  above everything else: old pages found, how many matched, and **how many have
  no counterpart at all**, each listed with a link. This cannot come out of a
  content diff — a page that does not exist has nothing to compare — so without
  it the worst outcome in a migration would be missing from the report a
  reviewer actually reads. Pages that were listed but would not load are shown
  separately, and net-new pages are shown apart from losses.
* **Summary header** — pages checked, how many need a human, how many came
  through clean, and a single bar showing the shape of the batch. Pages that
  could not be fetched are counted apart: a page nobody could read is not a
  page that lost content.
* **Ranked table** — worst first, colour-coded by tier, filterable by tier,
  by search, and by whether a page has caveats. Both URLs are clickable, so a
  reviewer can open the old Wayback capture beside the live page.
* **Detail view** — the verdict with its reasons and caveats, then four tabs:
  **what changed** (the judge's explanation), the structural counts, the
  findings, and **old vs new text side by side**.

That last tab is the one that matters. A reviewer can only judge whether a
rewrite dropped something by reading both versions, and no score substitutes
for that — so dropped passages are listed first, with the old text beside an
explicit "no counterpart on the new page" where the new text should be.

Caveats are shown expanded rather than tucked away. They are the reasons not to
take a tier at face value, and burying them would defeat the point of having
them.

**Export**: the sidebar offers the filtered pages as a review checklist CSV —
the plan's "fix it checklist" — with a `done` column, the tier, what to check,
and both links, so a content editor can work through it in Excel.

### Word-level highlighting

In the side-by-side, removed words are struck through in red and added words
are green, toggleable. Reading two blocks of prose and spotting the difference
by eye is exactly the manual work this tool exists to remove.

Figures the rewrite dropped are called out on the passage header — `amount $75
missing`, `date February 15 missing` — because "a number is missing" is only
actionable next to the sentence it went missing from.

### The one chart

Coverage against similarity, one dot per comparable page. It is the only chart
here because it is the only thing the table cannot say: the two measures
disagree, and the pages that matter are where they disagree most. A page far
right and low down reads as "barely changed" by similarity while most of its
text is gone — the shaded region is that trap.

On the demo set, `academics 2024` sits at **86% similarity, 41% coverage**.

Pages that could not be compared are absent rather than plotted at zero; they
have no coordinates and inventing some would be a lie.

The dot colour was checked with the dataviz validator against both the light
and dark chart surfaces rather than chosen by eye. That check also caught a
real bug in the v1 palette: the amber swatch carried white text at 2.69:1,
below the 4.5:1 floor, so it was darkened to 5.14:1. Tier identity is carried
by the label inside every chip, never by colour alone.

## React dashboard

```bash
cd dashboard-react && npm install && npm run dev    # against a running src.server
```

Built from a design brief and mockups. See [`dashboard-react/README.md`](../dashboard-react/README.md) for its
own notes.

There was briefly a second dashboard in Streamlit, written before this one
existed. It is gone: two front ends over one pipeline meant every feature had
to be built twice, and the run form would have been the second time. Nothing
was lost in the move except the coverage-vs-similarity scatter, which has not
been ported yet.

**What the wiring added.** The brief predates several of the pipeline's
findings, so this was not only a matter of swapping in real numbers: coverage
now sits beside similarity, the structural panel lists *which* headings went
rather than only how many, caveats appear on the rows that are not clean, and
a `/missing` screen exists at all. Two things from the brief changed on purpose
— the copy panels named Sitecore and WordPress and now name the hosts actually
loaded, and the
loading state's progress bar went, because the load is a JSON fetch and a
progress bar that cannot progress is a lie.

**On verifying it.** `npm run smoke` loads every route headlessly, fails on any
console error, and asserts something specific rendered. That last part was
added after a length-only check passed a main table showing "Showing 0 of 3" —
a `useMemo` was missing its data dependency, so it kept the empty first-render
result forever. A build that compiles says nothing about whether the app runs.
