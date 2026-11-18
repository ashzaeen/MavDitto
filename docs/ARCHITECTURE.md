# Architecture and diagrams

Every diagram is [Mermaid](https://mermaid.js.org/), which GitHub renders natively in light and dark. They are drawn from the code in [`src/`](../src) and [`dashboard-react/`](../dashboard-react), and the design reasoning behind them lives in [`docs/design/`](design).

**Contents**

1. [System overview](#1-system-overview)
2. [Dashboard routes](#2-dashboard-routes)
3. [Server API](#3-server-api)
4. [A comparison run, in the background](#4-a-comparison-run-in-the-background)
5. [Migration QA pipeline](#5-migration-qa-pipeline)
6. [How pages get paired](#6-how-pages-get-paired)
7. [Fetching a page](#7-fetching-a-page)
8. [Risk scoring](#8-risk-scoring)
9. [The LLM judge](#9-the-llm-judge)
10. [Broken Link Inspector](#10-broken-link-inspector)
11. [Alt Text](#11-alt-text)
12. [Content Writer](#12-content-writer)
13. [Web Builder](#13-web-builder)
14. [Setup Wizard](#14-setup-wizard)
15. [LLM provider layer and budget](#15-llm-provider-layer-and-budget)
16. [Local files and what is committed](#16-local-files-and-what-is-committed)

---

## 1. System overview

One browser app, one small standard-library HTTP server, and a set of tools that share the same fetching, extraction and LLM plumbing.

```mermaid
flowchart LR
    subgraph FE["Browser: React dashboard (Vite)"]
        UI["Migration QA / Alt Text / Broken Links<br/>Content Writer / Web Builder / Setup / Settings"]
    end

    subgraph SRV["src/server.py (stdlib http.server, 127.0.0.1 only)"]
        API["JSON API + static bundle"]
    end

    subgraph TOOLS["Tools"]
        MQA["Migration QA<br/>discover, pair, diff, score"]
        LC["link_checker"]
        AT["alt_text"]
        CW["content_writer"]
        WB["web_builder"]
        SE["setup_engine"]
    end

    subgraph SHARED["Shared plumbing"]
        FETCH["fetch.py<br/>polite fetcher + cache"]
        EXT["extract.py<br/>text, headings, images, links, blocks"]
        LLM["llm_provider.py<br/>+ llm_config.py + llm_cost.py"]
    end

    subgraph EXTERNAL["Outside"]
        WEB[("Websites<br/>live or Wayback")]
        PROV[("Claude / OpenAI / Gemini")]
    end

    subgraph DISK["Local disk (git-ignored)"]
        DATA[("data/<br/>run results, cache, llm_config.json")]
        CONF[("config/<br/>brand voice, knowledge base, components")]
    end

    UI <--> API
    API --> MQA & LC & AT & CW & WB & SE
    MQA & LC & AT & CW --> FETCH
    FETCH --> WEB
    FETCH --> EXT
    MQA & AT & CW & WB & SE --> LLM
    LLM --> PROV
    MQA --> DATA
    CW & WB & SE --> CONF
    LLM --> DATA
```

Design choices that shape the rest of this document:

- **The dashboard never fetches a page or loads a model.** The pipeline writes results to disk and the dashboard only reads them.
- **The server is localhost-only** because the run endpoints fetch arbitrary URLs on request.
- **Every LLM feature goes through one entry point**, so the active provider and the spend cap apply everywhere.

---

## 2. Dashboard routes

```mermaid
flowchart TD
    Home["/ Home"] --> All["/all-tools"]
    Home --> Mig["/migration"]
    Home --> Alt["/alt-text"]
    Home --> BL["/broken-links"]
    Home --> CWp["/content-writer"]
    Home --> WBp["/web-builder"]
    Home --> Setup["/setup"]
    Home --> Set["/settings"]

    Mig --> Res["/migration/results<br/>ranked table"]
    Res --> Det["/migration/pages/:id<br/>side-by-side detail"]
    Mig --> Miss["/migration/missing<br/>old pages with no counterpart"]
    Mig --> Red["/migration/redirects<br/>old to new map"]
```

A persistent left icon rail has one icon per tool, never per view, so moving between tools does not change the shell. `/broken-links/*` redirects to `/broken-links`.

---

## 3. Server API

[`src/server.py`](../src/server.py) uses only the standard library. Endpoints, grouped by what they serve:

```mermaid
mindmap
  root((server.py))
    Migration QA
      GET /api/data
      GET and POST /api/run
      POST /api/run/cancel
      POST /api/judge
    Alt Text
      POST /api/alt-text/image
      POST /api/alt-text/images
      POST /api/alt-text/page
    Broken Links
      POST /api/link-check/page
      GET and POST /api/link-check/site
      POST /api/link-check/site/cancel
    Content Writer
      GET /api/content-writer/templates
      GET /api/content-writer/history
      POST rewrite
      POST generate
      POST refine
      POST review
      POST regenerate-section
      POST regenerate-block
      POST export
      POST history/delete
    Web Builder
      GET /api/web-builder/catalog
      POST extract
      POST plan
      POST populate
      POST regenerate-component
    Setup and config
      GET and POST /api/config/llm
      POST /api/config/llm/test
      GET /api/config/status
      GET and POST /api/config/knowledge-base
      GET /api/config/brand-voice
      POST /api/setup/ingest-brand-voice
      POST /api/setup/ingest-components
      POST /api/setup/save
```

---

## 4. A comparison run, in the background

A run is minutes of network work, so it never blocks a request thread. The server starts it on its own thread, the page polls for progress, and the user can cancel. Site scans for broken links use the same shape.

```mermaid
sequenceDiagram
    autonumber
    actor U as Reviewer
    participant D as Dashboard
    participant S as server.py
    participant B as BackgroundRun thread
    participant P as run_pipeline
    participant R as data/run

    U->>D: Compare two sites (old URL, new URL, options)
    D->>S: POST /api/run
    S->>B: start thread
    S-->>D: accepted
    B->>P: run(old, new, out, progress callback)
    loop until finished
        D->>S: GET /api/run
        S-->>D: stage, done / total, message
    end
    opt user cancels
        D->>S: POST /api/run/cancel
        S->>B: set cancel flag
        B-->>P: stop at the next checkpoint
    end
    P->>R: per-pair JSON, url_pairs.csv, unmatched_pages.csv, inventories, discovery.json
    D->>S: GET /api/data
    S-->>D: results for the dashboard
```

---

## 5. Migration QA pipeline

Two root URLs in, a ranked and explained list of pages out. The headline answer, which old pages have no counterpart at all, arrives **before** any content is compared, because a missing page cannot be diffed against a replacement it does not have.

```mermaid
flowchart TD
    IN(["Old root URL + new root URL"]) --> EN["Enumerate both sites<br/>sitemap first, bounded crawl as fallback"]
    EN --> PR["Pair old pages to new pages<br/>4 passes, most confident first"]
    PR --> UN[/"unmatched_pages.csv<br/>pages needing a decision"/]
    PR --> UP[/"url_pairs.csv<br/>doubles as a redirect map"/]
    PR --> LV{"--check-live?"}
    LV -- yes --> CL["Confirm each page responds<br/>unfetchable pages are named and excluded"]
    LV -- no --> FE
    CL --> FE["Fetch both versions of each pair<br/>concurrent, rate-limited per host"]
    FE --> EX["Extract: text, headings, images, links,<br/>ordered structural blocks"]
    EX --> ST["Structural diff<br/>headings, images, links; deterministic"]
    EX --> SM["Semantic diff<br/>coverage of old passages by new ones"]
    SM -. "skipped with --no-semantic" .-> SC
    ST --> SC["Risk score<br/>loss axis + change axis -> one tier"]
    SM --> SC
    SC --> JG{"--judge?"}
    JG -- yes --> LJ["LLM judge<br/>only the passages embeddings cannot settle"]
    JG -- no --> SR
    LJ --> SR["Results store<br/>one JSON file per pair"]
    SR --> XP["export_web / GET /api/data"]
    XP --> DB(["Dashboard: ranked, explained, worst first"])
```

**Why two diffs.** The structural diff is cheap and blind to meaning; it sees a paragraph vanish only if a heading or link went with it. The semantic diff measures **coverage**: each old passage is matched to its best counterpart on the new page, and the passages with no good match are the finding. A whole-page similarity score would hide a dropped paragraph behind 90% unchanged text.

---

## 6. How pages get paired

Four passes, most confident first. Each pass claims what it is sure of before a looser one runs.

```mermaid
flowchart TD
    A(["Old page path"]) --> P1{"1. exact<br/>same site-relative path?"}
    P1 -- yes --> M(["Paired"])
    P1 -- no --> P2{"2. slug<br/>same final path segment?"}
    P2 -- yes --> M
    P2 -- no --> P3{"3. fuzzy-path<br/>best similarity above a floor?"}
    P3 -- yes --> AM{"Top two candidates<br/>within a hair of each other?"}
    AM -- yes --> U
    AM -- no --> M
    P3 -- no --> P4{"4. name (--match-titles)<br/>distinctive title or h1 match?"}
    P4 -- yes --> M
    P4 -- no --> U(["Left unmatched,<br/>listed for a human decision"])
```

- CMS extensions are stripped first, so Sitecore's `/About.aspx` lines up with WordPress's `/about/`.
- An ambiguous match is refused on purpose: picking one of two near-equal candidates is a coin flip presented as a finding.
- `--match-titles` only trusts a title if it is distinctive on that site. If titles repeat (common on single-page apps), it falls back to each page's first `<h1>`, and if neither is distinctive it declines and says so.

---

## 7. Fetching a page

```mermaid
flowchart TD
    S(["fetch(url, source)"]) --> C{"On-disk cache hit?"}
    C -- yes --> DONE(["Return cached page"])
    C -- no --> RB{"robots.txt allows it?"}
    RB -- no --> BLK(["Skipped"])
    RB -- yes --> SRC{"source"}
    SRC -- wayback --> WB["Resolve closest snapshot,<br/>fetch with id_ modifier<br/>(original bytes, no toolbar)"]
    SRC -- live --> RL["Per-host rate limiter"]
    RL --> H["httpx request<br/>backoff on 429 / 5xx"]
    H --> OK{"Responded?"}
    OK -- no --> UNR(["Recorded as unreachable,<br/>run moves on"])
    OK -- yes --> SH{"Text-density check:<br/>empty JavaScript shell?"}
    SH -- yes --> PW["Re-fetch with Playwright"]
    SH -- no --> DONE2
    PW --> DONE2
    WB --> DONE2["Store in cache"]
    DONE2 --> DONE
```

Concurrency overlaps *waiting*, not requests: every worker passes through the same per-host rate limiter. Bulk fetches use a tighter time budget than a single considered fetch, because in bulk a page that will not answer promptly *is* the finding.

---

## 8. Risk scoring

Each pair gets one tier from two separately scored axes. "Missing" is a different kind of evidence from "rewritten", not more of it: a page can be rewritten end to end and still say everything it used to.

```mermaid
flowchart LR
    subgraph IN["Evidence"]
        L["Loss<br/>passages with no counterpart,<br/>dropped headings, documents,<br/>images, links"]
        Ch["Change<br/>passages substantially rewritten,<br/>headings reworded,<br/>similarity down"]
    end
    L --> RU{{"Rules over both axes<br/>always explainable in words"}}
    Ch --> RU
    RU --> T1["Missing content<br/>specific content is gone"]
    RU --> T2["Major rewording<br/>heavily rewritten, or a small real loss"]
    RU --> T3["Minor rewording<br/>light rewording, cosmetic structure"]
    RU --> T4["Clean<br/>nothing meaningful changed"]
    RU --> T5["Unknown<br/>could not be compared; listed apart"]
    RU -. "0-100 score orders pages<br/>within a tier only" .-> ORD["Ranked list, worst first"]
```

Structural signals are proxies, so they are weighted down when the evidence is thin. Every verdict carries its reasons, including `Clean` ones, and caveats appear on the rows that are not clean.

---

## 9. The LLM judge

Embedding similarity cannot separate "reworded" from "reworded and lost a fact": calibration measured a faithful paraphrase at 0.734 and a rewrite that silently dropped a GPA requirement at 0.764. The judge reads only what the semantic stage could not vouch for.

```mermaid
sequenceDiagram
    autonumber
    participant Sc as Scored pair
    participant J as llm_judge
    participant Bu as Budget
    participant Ca as Disk cache
    participant Pv as llm_provider
    participant M as Model

    Sc->>J: flagged page
    J->>J: select passages between MATCH_WEAK and MATCH_STRONG,<br/>plus passages that vanished outright
    J->>Ca: lookup by content
    alt cached
        Ca-->>J: previous verdict (costs nothing)
    else not cached
        J->>Bu: estimate cost (provider token counter)
        alt over the cap
            Bu-->>J: BudgetExceeded, call refused
        else affordable
            J->>Pv: one request for the whole page
            Pv->>M: structured call
            M-->>Pv: did this rewrite keep the facts?
            Pv-->>J: result
            J->>Bu: record spend
            J->>Ca: save
        end
    end
    J-->>Sc: verdict attached to the pair
```

Cost control: only flagged pages and flagged passages are judged, one request per page rather than per passage, and a hard spend cap is checked **before** each call.

---

## 10. Broken Link Inspector

A link-health audit for one page or a whole subsite, independent of the migration pipeline. Both entry points share one extract, filter, dedupe, check pipeline; a site scan just crawls first.

```mermaid
flowchart TD
    ST(["Page scan or Site scan"]) --> Q{"Scope"}
    Q -- page --> F1["Fetch the page"]
    Q -- site --> CR["Discover pages under the path prefix<br/>(reuses discover.py: sitemap, then bounded crawl)"]
    CR --> F1
    F1 --> EL["Extract links"]
    EL --> RG["Region filter<br/>include or skip header / footer / nav"]
    RG --> DD["Deduplicate"]
    DD --> CT["Categorize"]
    CT --> CK["Check each link"]
    CK --> RS(["LinkScanResult"])

    subgraph CAT["Categories"]
        direction LR
        c1["internal in scope"]
        c2["internal other"]
        c3["external"]
        c4["document"]
        c5["image"]
        c6["media"]
        c7["anchor"]
        c8["email"]
        c9["phone"]
    end
    CT -.-> CAT
```

### How each link is checked

```mermaid
flowchart TD
    L(["Categorized link"]) --> K{"Kind"}
    K -- "email, phone" --> FMT["Format check only<br/>never touches the network"]
    K -- anchor --> GET["GET the page<br/>confirm the target id exists"]
    K -- "page, document, image, media, external" --> HEAD["HEAD request"]
    HEAD --> HS{"HEAD supported?"}
    HS -- no --> GET2["Fall back to GET"]
    HS -- yes --> ST
    GET --> ST
    GET2 --> ST
    FMT --> ST["Status"]
    ST --> S1["ok"]
    ST --> S2["redirected"]
    ST --> S3["broken"]
    ST --> S4["broken anchor"]
    ST --> S5["restricted"]
    ST --> S6["unreachable"]
    ST --> S7["format invalid"]
```

Order of categorization matters: a fragment marks an in-page jump regardless of the URL, and a file extension beats domain scoping, so a PDF hosted on the scanned domain is a Document, not an internal page. External hosts get their own longer per-host delay and a hard concurrency ceiling, independent of how many workers check internal links.

---

## 11. Alt Text

```mermaid
flowchart LR
    A1(["Uploaded image"]) --> G
    A2(["Page URL"]) --> SC["scan_page<br/>reuse extract.py's image extraction<br/>(real photo vs CSS background)"]
    SC --> F["Skip decorative images"]
    F --> G["AltTextGenerator.generate"]
    G --> CH{"Disk cache<br/>(keyed by the image's bytes)"}
    CH -- hit --> OUT
    CH -- miss --> BU["Budget check"] --> LLM["llm_provider vision call"] --> OUT(["Short, accurate description<br/>written for a screen reader"])
```

---

## 12. Content Writer

Rewrites a URL or uploaded file into a configured brand voice, or writes new copy from a template. A drafted variant is never shipped unreviewed: it is reviewed, redrafted against any blocking issue, and the final review always ships with it.

```mermaid
flowchart TD
    subgraph IN["Inputs"]
        i1["URL"]
        i2["Uploaded file<br/>PDF, DOCX, PPTX, XLSX, Markdown, image"]
        i3["Brief fields for a template"]
        i4["One free-form prompt (compose)"]
    end
    i1 & i2 --> EXT["extraction.py"]
    EXT --> SRC["Source material"]
    i3 & SRC --> DR
    i4 --> DR

    BV[("config/brand-voice.json<br/>+ knowledge-base.json")] --> DR
    VM["voice_method.py<br/>vendored writing-and-QA method"] --> DR
    TPL["templates.py<br/>15 templates, 3 groups"] --> DR

    DR["Draft<br/>brand voice + tone + length options"] --> RV["Review<br/>deterministic checks + LLM critic<br/>(includes the brand-appropriateness floor)"]
    RV --> PASS{"Any critical issue?"}
    PASS -- yes --> RT{"Retries left?<br/>max_review_retries"}
    RT -- yes --> DR
    RT -- no --> SH
    PASS -- no --> SH["Ship the draft<br/>with its review attached"]
    SH --> SC["StructuredContent<br/>typed sections or blocks"]
    SC --> RF["Refine in place<br/>shorten, expand, simplify, regenerate section or block"]
    RF --> RV
    SC --> EXP["Export"]
    EXP --> E1["md"] & E2["txt"] & E3["html"] & E4["docx"] & E5["pdf"]
    SC -.-> WB[["Web Builder"]]
```

**Templates** ([`templates.py`](../src/content_writer/templates.py)):

| Group | Templates |
| --- | --- |
| Web page copy | rewrite a page, new page from a brief, academic program page, landing or campaign page, department or about page, compose (free-form) |
| News and events | news story, event announcement, press release, spotlight |
| Micro-copy and SEO | headlines and page titles, meta descriptions, calls to action, FAQ set, summary |

**Review.** The deterministic half catches what a model is unreliable at noticing in its own output: a banned word, a 170-character meta description, a statistic that appears nowhere in the source. The LLM critic judges voice, tone fit and generic filler. Suggestions never block; only critical issues do.

**Placeholders.** Anything invented to fill out a compose request (a placeholder quote, an illustrative figure, a link target, an image) is marked `is_placeholder` with a note and stays visibly labelled through rendering and export.

---

## 13. Web Builder

Maps structured content onto a component library in two phases. A human approves the layout plan in between, and that step is UI-driven, not code.

```mermaid
flowchart TD
    subgraph P1["Phase 1: match and plan"]
        IN1(["StructuredContent from Content Writer<br/>or a raw URL / file"]) --> EX["extract"]
        EX --> MT["match: ONE LLM call over the whole page<br/>weighing every component's real affordances"]
        CAT[("config/components.json<br/>component catalog")] --> MT
        MT --> PL["LayoutPlan<br/>one row per section: component + reason"]
    end

    PL --> AP{"Human reviews and approves<br/>(UI step)"}
    AP -- adjust --> PL

    subgraph P2["Phase 2: populate and validate"]
        AP -- approved --> PO["populate: ONE LLM call per component"]
        CAT --> PO
        PO --> VC["validate_component<br/>deterministic, against that component's fields"]
        VC -- "violations, retries left" --> PO
        VC -- ok --> VP["validate_populated<br/>reviewer-facing problems list for the whole plan"]
        VP --> OUT(["Ready-to-paste fields"])
    end

    OUT -. "regenerate one component" .-> PO
```

Population is type-aware per the catalog's field definitions: rich text comes back formatted, a button comes back as label, colour and rationale and never an invented URL (always one of the section's real links), an image field comes back as a role note plus a handoff to the Alt Text tool, and an enum field is constrained to its allowed values. One call per component keeps "regenerate this component" cheap.

---

## 14. Setup Wizard

Turns freeform material into the local config the other tools read. Every result is a **draft** shown on a review screen first, because an inferred voice profile or an inferred field constraint is cheap to get wrong silently.

```mermaid
flowchart TD
    UP(["Upload docs, screenshots<br/>or a link to a live page"]) --> XT["content_writer.extraction<br/>same handlers Content Writer uses"]
    XT --> W{"Which config?"}
    W -- "brand voice" --> IB["ingest_brand_voice<br/>one LLM call: registers, shared principles,<br/>seed system prompt, guardrail floor"]
    W -- "component library" --> IC["ingest_components<br/>screenshot via vision extraction,<br/>link via URL extraction"]
    IB --> DRF["Draft"]
    IC --> DRF
    DRF --> RV{"Review screen:<br/>edit and confirm"}
    RV -- confirmed --> SV["POST /api/setup/save"]
    SV --> F1[("config/brand-voice.json")]
    SV --> F2[("config/components.json")]
    SV --> F3[("config/knowledge-base.json")]
```

A v1 brand profile is normalized to the v2 shape on load, so older profiles keep working and no deployment inherits content it never configured.

---

## 15. LLM provider layer and budget

Every feature that calls a model goes through `llm_provider.call_structured`, so the active provider and the spend cap apply uniformly.

```mermaid
flowchart LR
    subgraph FEAT["Features"]
        f1["LLM judge"]
        f2["Alt Text"]
        f3["Content Writer<br/>rewrite, generate, refine, review"]
        f4["Web Builder<br/>match, populate"]
        f5["Setup ingestion"]
    end
    f1 & f2 & f3 & f4 & f5 --> CS["llm_provider.call_structured"]
    CFG[("data/llm_config.json<br/>+ ANTHROPIC / OPENAI / GEMINI keys<br/>kept in sync with the environment")] --> CS
    CS --> BU{"Budget<br/>check before the call"}
    BU -- "over the cap" --> X(["BudgetExceeded"])
    BU -- ok --> RT{"Active provider"}
    RT --> C["Claude"]
    RT --> O["OpenAI"]
    RT --> G["Gemini"]
    C & O & G --> RES["Structured result"]
    RES --> REC["Record spend"]
    CS -. "SDK clients imported lazily,<br/>only the active one loads" .-> RT
```

The provider is chosen in Settings. SDK exceptions are translated by `llm_cost.py` into messages a reviewer can act on. Nothing in the migration pipeline needs credentials unless `--judge` is used.

---

## 16. Local files and what is committed

```mermaid
flowchart LR
    classDef committed fill:#e8f1ff,stroke:#3b6fd4,color:#0b1b3a
    classDef ignored fill:#f4f4f4,stroke:#888,color:#333,stroke-dasharray:4 3

    subgraph REPO["In the repository"]
        src["src/ (Python)"]:::committed
        dash["dashboard-react/ (source)"]:::committed
        tests["tests/ (offline)"]:::committed
        vend["vendor/anthropic_brand_voice/<br/>(Apache-2.0, with NOTICE)"]:::committed
        docs["docs/ and docs/design/"]:::committed
        cfgreadme["config/README.md"]:::committed
    end

    subgraph LOCAL["Generated locally, git-ignored"]
        d1["data/run/<br/>per-pair JSON, CSVs, discovery.json"]:::ignored
        d2["data/cache/<br/>fetch cache"]:::ignored
        d3["data/llm_config.json<br/>API keys"]:::ignored
        d4["data/content_writer_history/"]:::ignored
        c1["config/brand-voice.json"]:::ignored
        c2["config/knowledge-base.json"]:::ignored
        c3["config/components.json"]:::ignored
        n1["dashboard-react/dist/<br/>dashboard-react/public/data.json"]:::ignored
    end
```

No university data, brand material or credentials ship in the repository. Crawl output, caches and the three config files are produced on your own machine, and the repository's disclaimer asks that it only be pointed at sites you are authorized to scan.
