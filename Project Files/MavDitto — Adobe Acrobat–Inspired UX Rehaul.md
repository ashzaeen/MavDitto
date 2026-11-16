# MavDitto — Adobe Acrobat–Inspired UX Rehaul

Sep 24, 2026 · @Ashzaeen

## Where MavDitto stands today

From the current build: a flat top navigation bar carries six items side by side — **Home, Migrated pages, Not migrated, Redirect map, Alt text, Broken links** — with no visual distinction between "a whole tool" (Alt Text Generator, Broken Link Inspector) and "one view inside a tool's results" (Migrated pages / Not migrated / Redirect map are all outputs of the same migration-validation run). Home is effectively the Migration Validator's landing page — a headline, explanatory copy, and a single old-root/new-root input form — rather than a hub for the whole suite. Alt Text and Broken Links each have their own clean input screen (upload-vs-scan, page-vs-site toggle), but there's no shared entry point tying all three tools together, no history of past runs, and no way to discover a tool other than clicking through the top nav.

This works as three independent tools bolted together. The rehaul below is about making it feel like one coherent app.

## Why Adobe Acrobat is a good reference model

Acrobat solved almost exactly this problem: it's a suite of many distinct capabilities (edit, comment, fill & sign, compress, convert, organize pages) that has to feel like one product rather than a pile of tools. Its UX answer is consistent across the app:

- **Minimal, stable global chrome** — the top bar and left rail barely change no matter what you're doing, so the app never feels like it's re-skinning itself between tasks
- **A Home screen built around files and recent activity**, not a single form — you see what you were working on and jump back in, or start something new from a small set of clear entry points
- **Context lives on the right, navigation lives on the left** — selecting something (a page, an object, a comment) opens relevant detail and actions in a side panel instead of navigating you away from what you were looking at
- **One searchable "All tools" surface** so the breadth of the product is discoverable without memorizing where everything lives

MavDitto has the same shape of problem at a smaller scale: multiple distinct tools, each producing multiple views of results, all needing to feel like one product. The patterns below map Acrobat's answers onto MavDitto's specific screens.

## Structural shift: left icon rail, minimal top chrome

Replace today's flat six-item top nav with a slim, persistent **left icon rail** — one icon per top-level tool, not per view:

- Home
- Migration Validator
- Alt Text Generator
- Broken Link Inspector
- All Tools (a grid/discovery icon, see below)

This alone cuts today's six top-nav items down to five stable, tool-level icons — the sub-views that currently clutter the top bar (Migrated pages, Not migrated, Redirect map) move inside the Migration Validator itself (see the Contextual in-tool sub-navigation section).

**Decided**: the three main tools — Migration Validator, Alt Text Generator, and Broken Link Inspector — each get their own icon in the rail *and* their own tile (icon + name + one-line description) on Home's quick-start row and in the All Tools grid. They're never collapsed into a single generic "tools" entry or nested behind a menu — this mirrors how Acrobat gives each major capability (Edit, Comment, Fill & Sign) its own icon and tile rather than hiding it behind a dropdown.

The top bar becomes minimal and consistent across every screen: a breadcrumb on the left (e.g. "Migration Validator / Migrated pages"), a global search box in the center, and the theme toggle plus a contextual primary action (Export, Run Scan, etc.) on the right. This is the same top-bar discipline Acrobat keeps: it barely changes shape no matter which tool you're in, so switching tools never feels like landing in a different app.

## Home reimagined as a true hub

Today's Home is the Migration Validator's landing screen wearing a "Home" label. For now, Home is rebuilt around clear starting points rather than one form — a persisted "recent scans" history (reopening a past run from Home) is a good later feature, but out of scope for this pass:

**Start something new** — three (or more, as the suite grows) clear action cards: "Check a migration," "Scan for broken links," "Generate alt text." Each opens straight into that tool's setup screen. This replaces today's single big form with a starting point for the whole suite, not just one tool.

**Global search** — a persistent search box (in the top bar, see above) that searches across tools and the All Tools grid — typing "broken" or "alt text" jumps straight to the right tool without hunting through the rail.

Today's explanatory copy ("A page can read as 86% similar with 41% of its text unaccounted for...") is good content, but it reads as landing-page prose ahead of any action. Move it behind a small help/info icon next to the relevant input, the way Acrobat keeps its screens action-first and pushes explanation into tooltips and info panels rather than paragraphs above the fold.

## Contextual in-tool sub-navigation

Migrated pages, Not migrated, and Redirect map are three views of one Migration Validator run — they shouldn't sit at the same global nav level as Alt Text Generator or Broken Link Inspector, which are entirely separate tools. Acrobat handles exactly this with a secondary, contextual layer inside whatever you have open (page thumbnails, bookmarks, comments — all local to the current file, not global nav items).

For MavDitto: once inside the Migration Validator for a given run, a secondary tab strip (directly under the breadcrumb, above the content) switches between **Migrated pages / Not migrated / Redirect map**. This tab strip only appears when you're inside the Migration Validator — it disappears entirely when you switch to Alt Text or Broken Links in the left rail. The same pattern applies as more views get added to any tool (e.g. if Broken Links later gets a separate "By category" view alongside its main results table).

This is the single highest-leverage change in this rehaul: it takes the global nav from six items down to a stable five, and makes it immediately clear which items are "a whole tool" versus "a view of one tool's results."

## Row detail: dedicated pages

Acrobat's usual move here is a right-hand side panel — select something, and its detail appears alongside without navigating away. MavDitto deliberately doesn't follow that one, by choice: row detail stays on its own dedicated page, not a panel.

This formalizes what today's "Review →" links in Migrated pages already imply: clicking a row navigates to a full detail page. What still carries over from Acrobat's philosophy is that the page should feel like a natural extension of the table, not a jump to a different part of the app — a consistent breadcrumb (e.g. "Migration Validator / Migrated pages / utatickets.com"), a clear back-to-results affordance, and prev/next navigation between flagged rows so a reviewer can move through many pages without returning to the table each time.

For Migrated pages, that page shows the old-vs-new content comparison, the structural diff, and the LLM's explanation of what changed — exactly what the existing Page detail view already describes. For Broken Links, the page shows the link's full detail and its "found on" page list. Full pages give both of these room to breathe as wide, two-column layouts, which a side panel would have cramped.

## All Tools hub

Acrobat's "All tools" page is a searchable, browsable grid of every capability — it's how people discover things they didn't know Acrobat could do. MavDitto's suite is clearly still growing (the brainstorm history in this project alone has covered a dozen possible additions), so this pays off early rather than later.

An **All Tools** entry in the left rail opens a grid of cards, one per capability: Migration Validator, Alt Text Generator, Broken Link Inspector, and anything added afterward. Each card has an icon, a one-line description, and a "Start" button that jumps straight into that tool's setup screen — identical in spirit to Home's "Start something new" cards, just exhaustive rather than curated to three. A search box at the top filters the grid by name or keyword.

This also solves a real near-term problem: once there are five or six tools, Home's "Start something new" section can't reasonably show all of them as big cards — Home keeps its top two or three most-used entry points, and "All Tools" is the overflow destination for the rest.

## Consistent affordances and empty states

**Export, standardized**: today's export buttons ("Export flagged pages," "Export list," "Export mapping") are already sensibly contextual to each view, which is good — formalize the pattern rather than change it: same top-right slot, same download icon, same button style everywhere, so it's muscle memory across every tool rather than something to relocate each time.

**Empty states, before any scan has run**: the current screenshots all show already-populated results. Every table view needs a designed "nothing here yet" state — Acrobat's blank-slate treatment (an icon, one line explaining what belongs here, and a button to go start the relevant scan) rather than an empty table with just headers. This matters most for Migrated pages / Not migrated / Redirect map, which only make sense after a Migration Validator run has happened.

**Consistent primary-action styling**: "Run comparison," "Run Scan," and any future primary action should share one visual treatment (the same button style and position) across every tool's setup screen — already close to true today, worth locking in explicitly as a rule rather than a coincidence.

## Phasing

Not all of this is equal effort. Roughly, cheapest to most involved:

| Phase | Change | Effort |
| --- | --- | --- |
| 1 | Left icon rail replacing the top nav; minimal top chrome (breadcrumb, search box, theme toggle) | Pure frontend restructuring — no new data needed |
| 2 | Contextual in-tool sub-navigation (Migrated pages / Not migrated / Redirect map move under the Migration Validator) | Pure frontend restructuring |
| 3 | Consistent affordances and empty states | Small, mostly styling and a handful of new empty-state components |
| 4 | Standardize row detail as dedicated pages (breadcrumb, back-to-results, prev/next) | Small — formalizes what today's "Review →" links already imply, mostly adding consistent breadcrumb/back/prev-next chrome |
| 5 | All Tools hub | Small once Phase 1's rail exists — mostly a new grid page |
| 6 | Home's "Recent scans" history and cross-scan search | **Deferred — out of scope for this pass.** Every scan would need to be persisted as a revisitable object with its own id, not just live in the current session, which touches the results-store design across all three tools. Worth revisiting as a later feature once the core rehaul is built. |

Phases 1–3 alone would already make the app read as far more like one coherent product; 4–6 are where it starts feeling genuinely Acrobat-like rather than just tidier.

## Open questions to discuss

- **How far to take the master-detail panel?** A right-hand panel works cleanly for a single selected row, but the current Migrated pages detail view (old vs. new content, side by side) is itself a two-column layout — does that comparison still fit comfortably in a side panel, or does it want to stay a dedicated full-screen view reached from the panel ("Open full comparison")? Worth deciding before Phase 4 gets built rather than after.
- **Left rail icon set**: five icons (Home, Migration Validator, Alt Text, Broken Links, All Tools) is clean now, but is there an appetite for grouping (e.g. an "Accessibility" group holding Alt Text alongside future accessibility tools) once the suite grows past five or six entries?
