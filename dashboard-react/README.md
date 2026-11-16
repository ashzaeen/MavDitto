# MavDitto dashboard (React)

The migration-validation dashboard, wired to real pipeline output. Vite + React
Router, no CSS framework — plain custom properties for theming (`src/theme.css`).

## Run it

```bash
npm install && npm run build
python -m src.server        # from the repo root: http://127.0.0.1:8000
```

That serves this app and gives it a backend, which is what lets **Compare two
sites** start a run from the page. For front-end work, `npm run dev` proxies
`/api` to the same server (see `vite.config.js`), so both halves stay live.

Without a server it still runs as a static bundle: it falls back to
`public/data.json` from `python -m src.export_web`, and the run form says it
needs the backend rather than failing quietly.

## Where the data comes from

`GET /api/data` when a server is there, `public/data.json` when it is not.
Same shape either way: `src/export_web.py` in the repo root is the contract and
`tests/test_export_web.py` asserts it.

Runs are `POST /api/run`, polled with `GET /api/run` about once a second, and
stoppable with `POST /api/run/cancel`. When a run finishes the app reloads its
data rather than leaving the previous run on screen.

## Screens

| Route | What it answers |
| --- | --- |
| `/` | Start here — paste the two site roots and run a comparison |
| `/results` | Which pages need attention, ranked worst first |
| `/missing` | **Which old pages never arrived at all** |
| `/pages/:id` | What changed on one page, rendered as a document |
| `/redirects` | The old → new map, exportable |
| `/alt-text` | Alt text for an uploaded image, or every image on a URL |

`/` used to be a collapsible card sharing the results table's page, open by
default when there was nothing to show yet. Splitting it into its own route
gives the one thing a person does first — paste two URLs — a page with
nothing else competing for it; finishing a run there hands off to `/results`
rather than trying to be a launcher and a report on one screen.

`/missing` is not in the original design brief, which predates the pipeline's
discovery step. It earns its place: a page that no longer exists anywhere has
nothing to compare against, so it appears in no row of the main table. Without
this screen the dashboard would render a confident report that silently omits
the worst outcome a migration can have. The main view links to it in a banner
for the same reason.

## The review screen

Built verdict-first, then the concrete losses, then the two pages rendered as
documents, side by side. It went through two earlier designs, both wrong in
their own way:

1. One page-wide word diff in two columns. Fails exactly where it matters: on
   a page that really changed, every word is marked, both panels come out
   solid red and solid green, and the aligner begins matching coincidental
   words between unrelated sentences — the few unmarked fragments are noise.
2. A flat list of passage cards, one per word-budget chunk. Better, but a
   section with twenty paragraphs slices into a handful of ~80-word blobs that
   all carry the same heading label, which reads as repetition rather than as
   the section it actually was.

So the page is a document now: real headings, paragraphs, lists and tables, in
each side's own order, each block coloured by what happened to it (kept /
reworded / dropped / added). A list that only dropped its third bullet shows
as that list, with that one bullet struck through — not as one vague
"reworded" card. Word-level marking still appears on a reworded paragraph,
**only when it tracks a real edit**: above a change ratio of 0.7 the
highlighting is suppressed and the page says why. A "Dim what didn't change"
toggle fades the kept content on both sides without hiding it, so headings
and surrounding context are never lost while scanning for what actually
changed.

## What was added to the design

The brief was written before several of the pipeline's findings existed, so the
wiring added surfaces for them rather than only swapping in real numbers:

- **Coverage beside similarity**, on both the table and the detail header.
  Similarity is the number that hides loss — a page can read as 86% similar
  with 41% of its text unaccounted for. Coverage is the one that says so.
- **Which headings went**, under the structural counts. Counts alone are the
  wrong unit: a page can hold ten headings before and after with nine of them
  different, and read as unchanged.
- **Lists and tables as themselves**, not flattened into prose. A dropped
  bullet or a changed table row is shown struck through inside the list or
  table it belongs to, rather than buried in an 80-word blob of running text.
- **Caveats**, in the explanation panel. The brief put a confidence note on
  Clean rows only; the reasons not to trust a verdict matter most on the rows
  that are not clean.
- **Documents as their own structural row.** A PDF is not part of a page's
  text, so nothing else in the pipeline notices one vanishing.

Two things from the brief were changed deliberately. The copy panels said
"Sitecore" and "WordPress"; they now name the hosts actually loaded, because
the tool compares any two sites. And the loading state's fake progress bar was
removed — the load is a JSON fetch, not a pipeline run, and a progress bar that
cannot progress is a lie.

## Checking it works

```bash
npm run build
python -m src.server --port 8012        # from the repo root
BASE_URL=http://127.0.0.1:8012 npm run smoke
BASE_URL=http://127.0.0.1:8012 node run-e2e.mjs
```

`smoke.mjs` loads every route headlessly, fails on any console or page error,
**and asserts something specific rendered** — a row count, a percentage. A build
that compiles tells you nothing about whether the app runs, and an error-free
blank screen passed an earlier length-only check: the main table rendered
"Showing 0 of 3" for a while because a `useMemo` was missing its data
dependency.

`run-e2e.mjs` goes further: it fills the two URL fields, clicks Run, and waits
for the dashboard to show that run's own results. The point of the form is that
nobody has to touch a terminal, so the check drives it the way a person would.
It earned its keep immediately — the first attempt never submitted, because the
page-cap input carried `step="10"` and HTML5 validation silently rejects any
number that is not a multiple of ten. Typing 25 produced "the two nearest valid
values are 20 and 30" and no run.

## Structure

```
src/
  main.jsx            entry: Router → ThemeProvider → DataProvider → App
  App.jsx             routes
  ThemeContext.jsx    light/dark, persisted, defaults to OS preference
  theme.css           all styling — CSS custom properties
  data/
    useData.jsx       loads /api/data, falls back to public/data.json
    tierMeta.js       risk-tier labels + colours
  components/
    Icons.jsx         inline SVG set
    Header.jsx        brand, nav, theme toggle
    RiskBadge.jsx     tier pill: coloured icon + tint, label in ink
    RunForm.jsx       two URLs -> a run, with progress and a stop button
  pages/
    MainView.jsx      ranked table + summary
    NotMigrated.jsx   pages with no counterpart
    PageDetail.jsx    old vs new, structural diff, what changed
    RedirectMap.jsx   old → new map
```

`RiskBadge` is worth noting: the colour rides on an icon and a background tint,
never on the label text. That is what lets it use a status palette validated for
both light and dark surfaces without the text ever failing contrast.
