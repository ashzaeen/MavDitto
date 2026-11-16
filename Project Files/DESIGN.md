# MavDitto Design System

Adapted from the public [Notion DESIGN.md](https://github.com/VoltAgent/awesome-design-md/blob/main/design-md/notion/DESIGN.md) (warm minimalism, whisper borders, soft multi-layer shadows). The structure, spacing rhythm, and component logic are kept close to that original — what changes is the palette: **light mode is recolored to UTA's official brand colors**, and **dark mode is deliberately left brand-neutral** (a standard, well-built dark dev-tool theme, not a "UTA site with a dark filter").

This file drives the whole MavDitto app: the migration-validation dashboard, the Broken Link Inspector tab, and the alt-text generator tab all draw from the same tokens below.

## 1. Visual Theme & Atmosphere

MavDitto keeps Notion's core instinct — a blank canvas that gets out of the way, ultra-thin whisper borders instead of heavy lines, and shadows that are felt rather than seen — because it suits a data-dense internal tool as well as it suits a workspace app. What changes is who the palette belongs to.

**Light mode is UTA's.** UTA Blue (`#0064B1`) is the single accent that carries every primary action, link, and focus state, the same restrained way Notion Blue does in the original system. UTA Orange (`#F58025`) is kept strictly decorative — a small icon, a flourish — per UTA's own brand rules, which explicitly forbid orange as text or as a background with white text on it. Headings sit in UTA Web Blue (`#003865`), a deep navy that reads as unmistakably UTA without ever touching the orange restrictions.

**Dark mode is nobody's.** Rather than force UTA orange/blue into a dark shell (which usually looks like a brand accent fighting a black background), dark mode uses a clean, standard blue accent and a neutral charcoal canvas — the kind of dark theme any well-built dev tool would ship. This is a deliberate choice, not an oversight: a reviewer working at night should get a normal, comfortable dark UI, not a muted version of the university's colors.

**Key characteristics:**
- Whisper borders throughout: `1px solid rgba(0,56,101,0.12)` in light mode, `1px solid rgba(255,255,255,0.08)` in dark mode
- Single-accent discipline: one blue does all primary/interactive work per theme; orange never carries function, only decoration
- Status color (green/amber/red for Clean/Warning/Broken) is entirely separate from brand color, so meaning is never confused with branding
- 8px base spacing unit, tightened from Notion's marketing-page rhythm to a dashboard-appropriate density
- Dark mode uses surface-lightening for elevation instead of drop shadows, since shadows barely read on dark canvases

## 2. Color Palette & Roles

### Light Mode — UTA Brand

| Name | Hex | Role |
| --- | --- | --- |
| Canvas | `#ffffff` | Page background |
| Surface Alt | `#f7f5f3` | Section tint, alternating backgrounds, subtle card fill |
| Heading Text | `#003865` (UTA Web Blue) | All headings — deep navy, unmistakably UTA |
| Body Text | `rgba(0,0,0,0.87)` | Standard reading text, near-black for readability |
| Secondary Text | `#746661` | Descriptions, muted labels |
| Placeholder / Disabled Text | `#978c87` | Placeholder, disabled states, captions |
| Primary Accent | `#0064b1` (UTA Blue) | Primary CTA, links, active tab, focus ring |
| Accent Hover / Active | `#003865` (UTA Web Blue) | Pressed/hover state — darker than the base accent |
| Decorative Accent | `#f58025` (UTA Orange) | **Decorative only** — icons, small flourishes. Never text, never a background with white text on it |
| Text-safe Orange | `#c45517` (UTA Web Orange) | The only acceptable orange for text, and only for small, non-essential labels |
| Cool Tint Surface | `#bdd6e6` | Info banners, default badge background |
| Cool Tint Text | `#527a8a` | Text on cool tint surfaces |
| Border | `1px solid rgba(0,56,101,0.12)` | Whisper border — cards, dividers, table rows |
| Focus Ring | `#0064b1` | 2px solid, all interactive elements |
| Badge Background (info) | `#eaf3fb` | Pill badge surface, default/info state |
| Badge Text (info) | `#003865` | Pill badge text on the badge background above |

### Dark Mode — Neutral (not UTA-branded)

| Name | Hex | Role |
| --- | --- | --- |
| Canvas | `#15171a` | Page background |
| Surface (Level 1) | `#1b1e22` | Cards, panels |
| Surface (Level 2) | `#22262b` | Raised elements, hovered cards |
| Surface (Level 3) | `#2a2f35` | Modals, popovers |
| Heading / Body Text | `rgba(255,255,255,0.92)` | All text, single near-white value |
| Secondary Text | `#9aa1a9` | Descriptions, muted labels |
| Placeholder / Disabled Text | `#6b7280` | Placeholder, disabled states, captions |
| Primary Accent | `#3b82f6` | Primary CTA, links, active tab, focus ring |
| Accent Hover | `#5b9eff` | Hover state — lighter than the base accent |
| Accent Active / Pressed | `#2563eb` | Pressed state — darker than the base accent |
| Secondary Decorative Accent | `#2dd4bf` | Used sparingly for variety (e.g. a "New" tag) — never load-bearing |
| Border | `1px solid rgba(255,255,255,0.08)` | Whisper border — cards, dividers, table rows |
| Focus Ring | `#5b9eff` | 2px solid, all interactive elements |
| Badge Background (info) | `rgba(59,130,246,0.14)` | Pill badge surface, default/info state |
| Badge Text (info) | `#8fc1ff` | Pill badge text on the badge background above |

### Semantic Status Colors (both themes — product function, not brand)

These drive every risk/status tier across MavDitto: migration risk (Clean/Minor/Major/Missing), Broken Link Inspector status (OK/Redirected/Broken/Restricted/Unreachable), and anything similar. They are intentionally separate from the brand accent above so status meaning is never mistaken for a branding choice.

| Meaning | Light Text | Light Background | Dark Text | Dark Background |
| --- | --- | --- | --- | --- |
| Success / OK / Clean | `#1a8f4c` | `#e7f6ec` | `#34d399` | `rgba(52,211,153,0.12)` |
| Warning / Redirected / Restricted / Minor | `#b45309` | `#fdf1e3` | `#f5a524` | `rgba(245,165,36,0.12)` |
| Danger / Broken / Unreachable / Missing | `#c0392b` | `#fbeae8` | `#f87171` | `rgba(248,113,113,0.12)` |

Note: the warning tier's amber is deliberately its own hue, not a reuse of UTA Orange — this keeps "this needs attention" (status) visually distinct from "this is a UTA decorative touch" (brand), even though both are in the orange family.

## 3. Typography Rules

Keep Notion's hierarchy, weight system, and letter-spacing logic — it's a well-built, professional scale that doesn't need reinventing for a dashboard. The one change: use plain **Inter** (system fallback: `-apple-system, system-ui, Segoe UI, Helvetica, Arial, sans-serif`) rather than a custom modified font, since this is an internal tool being built from scratch, not a brand-locked marketing site.

| Role | Size | Weight | Line Height | Letter Spacing | Use |
| --- | --- | --- | --- | --- | --- |
| Display | 40px | 700 | 1.10 | -1.25px | Page-level titles ("MavDitto") |
| Section Heading | 28px | 700 | 1.15 | -0.75px | Tab titles, major section headers |
| Sub-heading | 20px | 700 | 1.25 | -0.25px | Card titles, panel headers |
| Body Large | 16px | 600 | 1.45 | normal | Summary stats, emphasized copy |
| Body | 15px | 400 | 1.5 | normal | Standard reading text, table cells |
| Body Medium | 15px | 500 | 1.5 | normal | Navigation, emphasized UI text |
| Nav / Button | 14px | 600 | 1.3 | normal | Buttons, tab labels, nav links |
| Caption | 13px | 500 | 1.4 | normal | Metadata, timestamps, found-on counts |
| Badge | 12px | 600 | 1.3 | 0.125px | Status pills, tags |

**Principles carried over from Notion:** four-weight system (400 read / 500 interact / 600 emphasize / 700 announce); letter-spacing tightens at larger sizes and relaxes to normal by body size; line-height tightens as size increases. Scaled down overall from Notion's marketing-page sizes since a dashboard needs more information density per screen.

## 4. Component Stylings

### Buttons

**Primary**
- Light: bg `#0064b1`, text `#ffffff`, hover/active bg `#003865`
- Dark: bg `#3b82f6`, text `#ffffff`, hover bg `#5b9eff`, active bg `#2563eb`
- Padding: 8px 16px · Radius: 6px · Focus: 2px solid focus ring + subtle shadow

**Secondary**
- Light: bg `rgba(0,56,101,0.06)`, text `#003865`
- Dark: bg `rgba(255,255,255,0.06)`, text `rgba(255,255,255,0.85)`
- Same padding/radius as Primary

**Ghost / Link**
- Transparent background, text in the accent color, underline on hover

**Pill Badge (status tiers)**
- Colors come from the Semantic Status table, never the brand accent
- Radius: 9999px · Padding: 4px 8px · Font: Badge role above

### Cards & Panels
- Light: bg `#ffffff`, border `1px solid rgba(0,56,101,0.12)`, radius 12px, Notion-style soft shadow (`rgba(0,0,0,0.04) 0px 4px 18px, rgba(0,0,0,0.027) 0px 2px 8px, rgba(0,0,0,0.02) 0px 1px 3px`)
- Dark: bg `#1b1e22`, border `1px solid rgba(255,255,255,0.08)`, **no drop shadow** — elevation comes from the surface-lightening levels instead (see Depth & Elevation)

### Inputs & Forms
- Light: bg `#ffffff`, border `1px solid #bdd6e6`, focus ring `#0064b1`, placeholder `#978c87`
- Dark: bg `#1b1e22`, border `1px solid rgba(255,255,255,0.12)`, focus ring `#5b9eff`, placeholder `#6b7280`

### Navigation / Tabs
- App shell header: light mode may carry an optional 4px UTA Blue hairline at the very top of the page as a brand touch — restrained, not a full color block. Dark mode has no such hairline; it stays plain and neutral.
- Tabs (Migration Validation / Broken Links / Alt Text, etc.): active tab uses the accent color for text + an underline; inactive tabs use secondary text color, no underline.

### Risk / Status Rows (dashboard-specific)
- Each status pill uses the Semantic Status colors, sorted worst-first by default
- A row's left edge can carry a 3px color bar in the same semantic color for fast left-to-right scanning in dense tables

## 5. Layout Principles

### Spacing Scale

Base unit: 8px. Every gap, padding, and margin in the app should come from this table — no one-off pixel values.

| Token | Value | Use |
| --- | --- | --- |
| `space-1` | 4px | Icon-to-label gaps, tight inline spacing |
| `space-2` | 8px | Button padding (vertical), badge padding, gap between related inline elements |
| `space-3` | 12px | Table cell padding, input padding |
| `space-4` | 16px | Card padding, gap between form fields, button padding (horizontal) |
| `space-5` | 24px | Gap between related cards/panels within one section |
| `space-6` | 32px | Gap between distinct dashboard sections (summary header → results table) |
| `space-7` | 48px | Top-level page padding, gap around the setup panel |

**Density note**: this is a dashboard, not a marketing page — Notion's original 64–120px section rhythm is landing-page scale. `space-6`/`space-7` above are the dashboard-appropriate equivalent; don't reach past 48px for any normal layout gap.

### Border Radius Scale

| Token | Value | Use |
| --- | --- | --- |
| `radius-xs` | 4px | Inputs, checkboxes |
| `radius-sm` | 6px | Buttons |
| `radius-md` | 8px | Small elements, dropdowns, menus |
| `radius-lg` | 12px | Cards, panels |
| `radius-xl` | 16px | Featured/hero cards (rare in a dashboard — used sparingly, e.g. the summary header card) |
| `radius-pill` | 9999px | Status badges, pills |
| `radius-round` | 50% | Avatars, icon-only circular buttons |

### Grid & Containers

- Max content width: dashboard views can run full-width within the app shell; card grids cap around 1200px for readability on very wide monitors
- Data tables scroll horizontally within their own container (`overflow-x: auto`) rather than the whole page shifting

## 6. Depth & Elevation

**Light mode** — same philosophy as Notion: whisper borders plus soft, multi-layer shadows with very low individual opacity, so elevation is felt rather than seen.

| Level | Treatment |
| --- | --- |
| Flat | No border, no shadow — page background |
| Whisper | `1px solid rgba(0,56,101,0.12)` — standard card/divider border |
| Card | Soft 3-layer shadow, max opacity 0.04 |
| Modal | Deeper shadow, max opacity 0.06, larger blur radius |

**Dark mode** — shadows barely read against a dark canvas, so elevation instead comes from lightening the surface itself:

| Level | Treatment |
| --- | --- |
| Canvas | `#15171a` — page background |
| Level 1 | `#1b1e22` — cards, panels |
| Level 2 | `#22262b` — raised/hovered elements |
| Level 3 | `#2a2f35` + thin light border — modals, popovers |

## 7. Responsive Behavior

Desktop-first, since this is an internal reviewer tool (per the Dashboard Design Brief, full mobile optimization is explicitly out of scope) — but it should degrade gracefully rather than break:

- **>1080px**: full multi-column dashboard layout, sidebar/tab nav visible
- **768–1080px**: tab nav may collapse into a compact bar; tables keep their columns but scroll horizontally within their container
- **<768px**: sidebar/tab nav collapses into a simple top bar or hamburger; data tables switch to a stacked card-per-row layout rather than horizontal-scroll-only, so the tool stays usable on a tablet even though it isn't the primary target

## 8. Accessibility & States

- Focus is always visible: 2px solid focus ring (accent color per theme) on every interactive element, no exceptions
- **UTA Orange (`#f58025`) is never used as text color, and never as a background with white text on it** — this is a hard UTA brand-accessibility rule, not a style preference. When orange text is genuinely needed, use UTA Web Orange (`#c45517`) instead, and only for small, non-essential labels — never for buttons, links, or anything status-related
- Status meaning always comes from the Semantic Status palette, never from the brand accent or the decorative orange — this keeps color-blind-safe redundancy possible (pair color with an icon/label, not color alone) and keeps brand and function visually distinct
- Standard interactive states apply per theme: default (whisper border) → hover (accent color shift / slight surface lift) → active/pressed (darker accent in light, darker accent in dark) → focus (ring) → disabled (placeholder-tier color, reduced opacity)

## 9. Agent Prompt Guide

### Quick reference — Light Mode
- Primary CTA / links: `#0064b1`
- Heading text: `#003865`
- Body text: `rgba(0,0,0,0.87)`
- Decorative-only accent: `#f58025` (never text, never bg-with-white-text)
- Border: `1px solid rgba(0,56,101,0.12)`

### Quick reference — Dark Mode
- Primary CTA / links: `#3b82f6`
- Text: `rgba(255,255,255,0.92)`
- Border: `1px solid rgba(255,255,255,0.08)`
- Elevation: lighten the surface (`#1b1e22` → `#22262b` → `#2a2f35`), don't add shadows

### Example prompts
- "Build the Broken Links summary header on a white canvas. Title at 28px weight 700, color #003865. Status pills use the semantic status colors (green/amber/red), never the blue accent. Primary 'Run Scan' button: #0064b1 background, white text, 6px radius, 8px 16px padding, hover darkens to #003865."
- "Build the same header for dark mode: canvas #15171a, card surface #1b1e22, text rgba(255,255,255,0.92). Primary button: #3b82f6 background, white text, hover #5b9eff. No drop shadows — use the lighter surface level instead for any raised element."
- "Design a risk-tier pill badge: use the semantic status table only. Clean = #1a8f4c text on #e7f6ec background (light) or #34d399 on rgba(52,211,153,0.12) (dark). 9999px radius, 4px 8px padding, 12px weight 600 text."

### Do / Don't
- **Do** use UTA Blue (`#0064b1`) for every primary action and link in light mode.
- **Do** keep UTA Orange strictly decorative — a small icon or flourish, never a button fill with white text, never body or link text.
- **Do** keep dark mode's accent brand-neutral — it should read as a normal, well-built dark dev tool, not a dimmed UTA skin.
- **Do** use the semantic status palette — not brand colors — for every risk/status indicator across MavDitto.
- **Don't** reach for generic Tailwind grays in light mode — use UTA's own secondary palette (`#746661`, `#978c87`, `#bdd6e6`, `#527a8a`) for the neutral scale instead.
- **Don't** carry light mode's shadow-based elevation into dark mode as-is — use the surface-lightening model there instead.
