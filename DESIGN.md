---
name: Hivemind
description: The team's shared agent memory, specified like a graphics standards manual.
colors:
  sheet: "#ffffff"
  paper: "#f6f5f2"
  paper-2: "#eeede8"
  ink: "#141414"
  ink-2: "#3b3b38"
  muted: "#64645e"
  faint: "#8c8c85"
  rule: "#e0dfd9"
  rule-2: "#c9c8c1"
  bar: "#141414"
  bar-ink: "#ffffff"
  bar-muted: "#b4b3ad"
  bar-line: "#3d3d3a"
  signal: "#d22f17"
  signal-hover: "#b52711"
  signal-ink: "#c42b13"
  signal-wash: "rgba(210, 47, 23, 0.09)"
  blue: "#2560cf"
  blue-wash: "rgba(37, 96, 207, 0.09)"
  green: "#18744a"
  green-wash: "rgba(24, 116, 74, 0.1)"
  amber: "#9a5306"
  amber-wash: "rgba(214, 133, 22, 0.13)"
  t-agent: "#141414"
  t-fact: "#2560cf"
  t-procedure: "#18744a"
  t-episode: "#8a8a83"
  t-error: "#d22f17"
  t-task: "#9a5306"
  t-handoff: "#0f7d8c"
  t-topic: "#6d4fc2"
  t-entity: "#b0afa8"
  t-session: "#c9c8c1"
  t-user: "#a3417a"
  link: "#d4d3cc"
  client-claude-code: "#b4532d"
  client-cursor: "#2d68ab"
  client-codex: "#0b7458"
  client-hivemind: "#5f5f59"
  client-unknown: "#6447b8"
typography:
  display:
    fontFamily: "Archivo, ui-sans-serif, system-ui, Segoe UI, sans-serif"
    fontSize: "28px"
    fontWeight: 600
    lineHeight: 1.12
    letterSpacing: "-0.02em"
    fontVariation: "'wdth' 86"
    fontFeature: "'tnum' 1"
  numeral:
    fontFamily: "Archivo, ui-sans-serif, system-ui, Segoe UI, sans-serif"
    fontSize: "24px"
    fontWeight: 700
    lineHeight: 1
    fontVariation: "'wdth' 78"
    fontFeature: "'tnum' 1"
  headline:
    fontFamily: "Archivo, ui-sans-serif, system-ui, Segoe UI, sans-serif"
    fontSize: "21px"
    fontWeight: 600
    lineHeight: 1.22
    letterSpacing: "-0.012em"
    fontVariation: "'wdth' 92"
  brand:
    fontFamily: "Archivo, ui-sans-serif, system-ui, Segoe UI, sans-serif"
    fontSize: "17px"
    fontWeight: 700
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Archivo, ui-sans-serif, system-ui, Segoe UI, sans-serif"
    fontSize: "15px"
    fontWeight: 500
    lineHeight: 1.4
  body:
    fontFamily: "Archivo, ui-sans-serif, system-ui, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.45
    fontFeature: "'tnum' 1"
  section:
    fontFamily: "Archivo, ui-sans-serif, system-ui, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    letterSpacing: "0"
  label:
    fontFamily: "Archivo, ui-sans-serif, system-ui, Segoe UI, sans-serif"
    fontSize: "12.5px"
    fontWeight: 500
    lineHeight: 1.5
  mono:
    fontFamily: "JetBrains Mono, ui-monospace, Cascadia Mono, Consolas, monospace"
    fontSize: "11.5px"
    fontWeight: 500
    fontFeature: "'liga' 0, 'calt' 0"
rounded:
  none: "0px"
  r: "2px"
  pulse: "50%"
spacing:
  hair: "4px"
  xs: "6px"
  sm: "8px"
  row: "10px"
  md: "14px"
  rail: "18px"
  gutter: "20px"
  canvas: "24px"
  section: "24px"
  lane-gap: "28px"
  column-gap: "36px"
  rail-w: "280px"
  insp-w: "384px"
  bar-h: "56px"
components:
  button:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.r}"
    padding: "0 14px"
    height: "34px"
  button-hover:
    backgroundColor: "{colors.paper}"
  button-primary:
    backgroundColor: "{colors.signal}"
    textColor: "{colors.bar-ink}"
    rounded: "{rounded.r}"
    padding: "0 14px"
    height: "34px"
  button-primary-hover:
    backgroundColor: "{colors.signal-hover}"
  button-ink:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
    rounded: "{rounded.r}"
    padding: "0 14px"
    height: "34px"
  button-ink-hover:
    backgroundColor: "{colors.ink-2}"
  button-small:
    rounded: "{rounded.r}"
    padding: "0 11px"
    height: "30px"
  icon-button:
    textColor: "{colors.ink}"
    rounded: "{rounded.r}"
    size: "34px"
  tag:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.ink-2}"
    typography: "{typography.label}"
    rounded: "{rounded.r}"
    padding: "0 7px"
    height: "20px"
  tag-ink:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
  tag-signal:
    backgroundColor: "{colors.signal-wash}"
    textColor: "{colors.signal-ink}"
  tag-green:
    backgroundColor: "{colors.green-wash}"
    textColor: "{colors.green}"
  tag-blue:
    backgroundColor: "{colors.blue-wash}"
    textColor: "{colors.blue}"
  tag-amber:
    backgroundColor: "{colors.amber-wash}"
    textColor: "{colors.amber}"
  chip:
    backgroundColor: "{colors.paper-2}"
    textColor: "{colors.ink-2}"
    typography: "{typography.mono}"
    rounded: "{rounded.r}"
    padding: "1px 6px"
  avatar:
    textColor: "{colors.bar-ink}"
    rounded: "{rounded.r}"
    size: "30px"
  row:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    padding: "10px 8px"
  row-hover:
    backgroundColor: "{colors.paper}"
  row-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
  stat:
    textColor: "{colors.ink}"
    typography: "{typography.display}"
    padding: "9px 18px 10px"
  stat-key:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.sheet}"
  search-field:
    backgroundColor: "{colors.sheet}"
    textColor: "{colors.ink}"
    rounded: "{rounded.r}"
    padding: "0 12px"
    height: "42px"
  topbar:
    backgroundColor: "{colors.bar}"
    textColor: "{colors.bar-ink}"
    padding: "0 20px"
    height: "56px"
  narration-band:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    typography: "{typography.title}"
    padding: "9px 20px"
---

# Design System: Hivemind

## Overview

**Creative North Star: "The Standards Manual"**

Hivemind's dashboard presents a team's shared agent memory the way a 1970s corporate graphics standards manual presents an identity: a white sheet, ink type, hairline rules and a grid in which every item has a designation. Agents are A1, A2, work items W1, procedures P1, facts F1, topics T1, and those designations are cross-referenced wherever the memory is explained, above all in the provenance trail. The interface reads as a specification sheet, not a marketing dashboard.

Density is high but calm. Content sits in rows on hairlines instead of boxed cards, section heads hang under a 2px ink rule, and values change in fixed cells so nothing reflows while the demo plays or while time travel scrubs the past. One colour, signal red, is reserved for things that need attention now; everything else is ink, warm grey and a small set of quiet semantic hues. Selection inverts to solid ink, as a manual would reverse a cell out of black.

The confirmed anti-reference is the soft-card indigo SaaS dashboard: cards on a dot grid, rounded tiles with drop shadows, and an accent colour spread everywhere.

**Key Characteristics:**
- White sheet, ink type, warm-grey hairlines; a black top bar closed by a 3px signal-red rule.
- One signal colour with a narrow job; all status is a square mark plus a word.
- Designations (A, W, P, F, T plus a number) in mono, cross-referenced between map, inspector and provenance.
- Rows on hairlines, 2px ink rules over section heads, square corners (2px at most).
- Flat sheet: shadows only on things that float above it.
- Narrowed Archivo for numerals and headings; JetBrains Mono for designations, IDs and commands.
- Light by default; dark theme inverts the sheet to ink with the same rules.

## Colors

An ink-on-white palette with warm-grey neutrals, one signal red, and three muted semantic hues that only ever appear as text or a faint wash.

### Primary
- **Signal Red** (signal): the single accent. The Play the demo button, the "Why do we know this?" action, the top bar's closing rule, the logo tile, the live pulse, the live time-ruler thumb, the newest provenance station, the leading progress tick and the best benchmark bar. Darkens to **Signal Red Deep** (signal-hover) on hover; the same deep value (signal-ink) is used when signal must be read as text on white. **Signal Wash** (signal-wash) tints the row that just arrived and the offline banner.

### Secondary
- **Handoff Blue** (blue): focus rings, handoff routes and the dashed handoff connector, the Handed off and Promoted tags, the Recall field's focus state. Pairs with **Blue Wash** (blue-wash) for tag grounds.

### Tertiary
- **Verified Green** (green): Done, Active, Accepted and Verified how-to tags; positive stat deltas. Ground: **Green Wash** (green-wash).
- **Archive Amber** (amber): the past. Pending tags, revision counters, and the whole time-ruler band when the view is set to a moment in the past. Ground: **Amber Wash** (amber-wash).

### Neutral
- **Sheet White** (sheet): the page, panels, rows at rest, popovers.
- **Paper** (paper): the second layer. Hover on rows and buttons, the narration band.
- **Paper Deep** (paper-2): tag and chip grounds, inline code, skeleton and bar tracks.
- **Ink** (ink): type, 2px section rules, 1px pane borders, selected rows, the key stat cell, the default button outline.
- **Ink Soft** (ink-2): secondary reading text such as feed lines, trail steps and chips.
- **Muted Grey** (muted): metadata, counts, designations, timestamps, placeholder text.
- **Faint Grey** (faint): decorative numerals only, never text that must be read.
- **Hairline** (rule) and **Hairline Strong** (rule-2): row dividers and quiet control borders, respectively; rule-2 also draws resting map connectors and scrollbar thumbs.
- **Bar Black** (bar), **Bar Ink** (bar-ink), **Bar Muted** (bar-muted), **Bar Line** (bar-line): the top bar's own ground, text, secondary text and control borders.

### Identity and category colours
- **Client squares**: Claude Code (client-claude-code), Cursor (client-cursor), Codex (client-codex), Hivemind (client-hivemind) and any other client (client-unknown) appear only as solid square avatars carrying white initials, and as agent nodes in the graph explorer. They identify, they never decorate.
- **Graph categories** (t-agent through t-user, plus link for edges): one restrained hue per node type, used only in the force-graph explorer and its legend. Error episodes take t-error, which is signal red by design.

### Dark theme
`[data-theme="dark"]` redefines every token rather than adding new ones: the sheet becomes near-black ink (paper and paper-2 step up from it), ink becomes warm off-white, hairlines darken, the bar goes deeper than the sheet, and blue, green, amber and signal-ink lighten so they hold up as text on the dark sheet. The solid signal stays #d22f17 in both themes so white button text keeps 5:1 and live marks keep 3.6:1 against the dark sheet. Exact dark values live in `src/hivemind/web/styles.css` and in the sidecar's `colorMeta.*.dark`. Structure, rules and inversions are identical in both themes.

### Named Rules
**The One Signal Rule.** Signal red means "attention now": live, act, just arrived, or failed. It is never decoration, never a section colour, never a chart series except the best result. If a screen shows red that does not mean one of those four things, it is wrong.

**The Mark-Plus-Word Rule.** Colour never carries status alone. Every status tag is a 7px square mark (solid, outlined for Open, absent for Superseded) followed by a word.

**The Ink Inversion Rule.** Selection is solid ink with sheet-coloured type, never a tint. The one stat that proves the product (Known fixes served) is inverted the same way.

## Typography

**Display Font:** Archivo (with ui-sans-serif, system-ui, Segoe UI, sans-serif), variable width axis 75 to 100.
**Body Font:** Archivo, same stack.
**Label/Mono Font:** JetBrains Mono (with ui-monospace, Cascadia Mono, Consolas, monospace).

**Character:** A sturdy grotesque that narrows for numerals and headings, the way a manual sets figures in a condensed cut, paired with a plain mono that marks anything machine-issued: designations, ticket IDs, file names, commands. Numerals are tabular everywhere so counts never jitter.

### Hierarchy
- **Display** (600, 28px, 1.12, narrowed to 86%): stat values in the stats line and benchmark pairs. Drops to 24px under 1200px and 22px on phones.
- **Numeral** (700, 24px, 1, narrowed to 78%): the narration step number.
- **Headline** (600, 21px, 1.22, narrowed to 92%): the selected item's title in the inspector.
- **Brand** (700, 17px, -0.01em): the wordmark beside the logo.
- **Title** (500, 15px, 1.4): narration text and empty-state titles.
- **Body** (400 to 600, 14px, 1.45): row titles, node text, results, buttons and tabs (600 for controls and tabs). Placeholder copy caps at 34ch.
- **Section** (700, 13px): section and column heads under the 2px ink rule; the time-travel label.
- **Label** (400 to 600, 12.5px): metadata, counts, deltas, tags, feed times, legend entries.
- **Mono** (500, 11.5px, ligatures off): designations, ticket IDs, chips, step numbers in lists, the `/` key hint. Mono at 12.5px for the as-of time and identifiers.

### Named Rules
**The Narrow Numeral Rule.** Numerals and the inspector headline are set in Archivo at narrowed widths (78 to 92%); running text stays at full width. Never fake narrowness with letter-spacing or a second family.

**The Machine Voice Rule.** Anything the system issued (A1, HM-D52C, test_ledger.py, `uv run ...`) is mono and usually muted. Anything a person would say is Archivo. Labels are sentence case.

## Layout

A full-height application frame with no page scroll: a 56px top bar, one stats line of eight equal fixed cells, an optional narration band, then three panes. The rail (280px) holds Team and Queue, the stage holds the active view (Map, Board or Graph) with the time ruler docked at its foot, and the inspector (384px) holds tabbed Details, Recall, Activity and Benchmarks. Panes are separated by 1px ink borders.

The relationship map is a four-column grid (Agents, Work, Knowledge, Topics; 36px column gap, 18px 24px padding, 760px minimum width) joined by right-angle connectors drawn in the gutters. The board is four lanes (28px gap) of rows. Horizontal padding is 20px in chrome and panels, 24px on the canvas; sections in the inspector are 24px apart, rail sections 26px.

Responsive behaviour:
- **At 1440px and below** the rail narrows to 256px, the inspector to 356px, and gutters tighten by 2 to 4px.
- **At 1199px and below** the inspector becomes a right-hand drawer (up to 400px) over the canvas, opened from the top bar.
- **At 1023px and below** the rail narrows to 232px and long button labels drop.
- **At 759px and below** the layout is one pane at a time behind a five-item bottom navigation (Map, Board, Graph, Team, Inspector). The top bar shrinks to 52px, view tabs disappear, the stats line becomes a horizontally snapping strip that leads with the inverted key stat, map columns stack, connectors hide, and the inspector becomes a bottom sheet (up to 82dvh) with a grab bar and scrim.

### Named Rules
**The Registered Cells Rule.** Values update inside fixed cells; nothing reflows when data changes or when time travel moves. A changed value ticks in place (signal red, then settles to ink) rather than moving the layout.

## Elevation & Depth

The sheet is flat. Depth comes from tone (sheet, paper, paper-2), from 1px hairlines and 1px ink pane borders, and from inversion, not from shadows. Exactly one shadow exists, and it is reserved for things that genuinely float over the sheet: the steps popover, toasts, and the inspector when it is a drawer or bottom sheet. Floating elements also take a 1px ink border, so they read as a pasted-up panel rather than a glowing card.

### Shadow Vocabulary
- **Pop** (shadow-pop in the sidecar; light `0 1px 2px rgba(20, 20, 20, 0.08), 0 12px 32px -8px rgba(20, 20, 20, 0.22)`): popovers, toasts, drawer and sheet only.
- **Signal rule** (`inset 0 -3px 0` signal): the top bar's closing red rule. A rule, not a shadow.
- **Focus** (`2px solid` blue outline, 2px offset; white inside the top bar): every focusable control. The Recall field instead takes a 1px blue border with a 3px blue-wash halo.

### Named Rules
**The Flat Sheet Rule.** Nothing that sits on the sheet casts a shadow. If it does not float over other content, it gets a hairline, not elevation.

## Shapes

Square. The shared radius is 2px (r) on buttons, tags, chips, avatars, inputs, toasts and cross-reference buttons; structural marks are fully square (0): the logo tile, scrollbar thumbs, the ruler thumb, provenance stations, progress ticks, connector terminals and score bars. Map connectors are orthogonal with no rounding at the bends, ending in 4px square terminals.

The only round shapes are the live pulse (and its expanding ping ring), the unread dot on the mobile Inspector tab, graph-explorer nodes and their legend swatches. Roundness therefore means "live signal" or "graph node", and nothing else.

### Named Rules
**The Square Corner Rule.** No radius above 2px anywhere. A circle is permitted only for a live indicator or a graph node.

## Components

### Buttons
Firm, outlined, plain: they look like the controls in a printed form.
- **Shape:** gently squared (2px), 34px high, 14px horizontal padding, 600 weight at 14px, icon and label 8px apart.
- **Default:** sheet ground, 1px ink border, ink text. Hover fills with paper.
- **Primary:** signal ground and border, white text. Hover deepens to signal-hover. One per region: Play the demo in the top bar, "Why do we know this?" in the inspector.
- **Ink:** solid ink with sheet-coloured text; hover softens to ink-2.
- **Quiet:** default with a rule-2 border instead of ink.
- **Small:** 30px high, 11px padding, 13px type.
- **Press:** every button scales to 0.97 (icon buttons 0.94) on press with the house ease. Disabled is 55% opacity with a progress cursor.
- **In the top bar:** non-primary buttons go transparent with bar-line borders and a faint white wash on hover; focus rings turn white.

### Icon buttons
34px square (32px in the top bar), transparent with a rule-2 border, 16px line icons at 1.75 stroke. Icons are inline SVG symbols, never an icon font.

### Status tags
- **Style:** 20px high, 7px padding, 12.5px at 600, with a 7px square mark in the current colour before the word.
- **Variants:** neutral (paper-2 on ink-2), ink (In progress, solid inverted), signal (Retracted), blue (Handed off, Promoted, Handoff), green (Done, Active, Verified how-to), amber (Pending, Rev n), open (outlined mark), struck (Superseded: transparent with a rule-2 inset outline and no mark; the item's text is also struck through). `plain` removes the mark when the word alone is enough.

### Chips
Mono 11.5px on paper-2, 2px radius, 1px 6px padding, truncated with an ellipsis. Used for entity names under topics. Inside a selected row they become a 16% sheet wash on ink.

### Rows (agents, tickets, map nodes, tasks, results)
- **Structure:** full-width buttons separated by 1px hairlines, no box, no shadow. Map nodes lead with a 26px designation column; agent rows lead with the square avatar stacked over the designation.
- **Hover:** paper fill; board tasks and recall results also ease 8px of side padding in.
- **Selected:** solid ink, sheet text, metadata at 70% sheet.
- **Dimmed:** when a selection or provenance trace is pinned, unrelated map nodes drop to 32% and unrelated connectors to 12%.
- **Fresh:** a newly arrived node flashes signal-wash and fades back over 1.6s; a new feed row flashes paper.
- **Superseded:** text muted and struck through with a rule-2 line.
- **Metadata lines** (designation, ticket ID, tag, owner, time) wrap between tokens with a 4px by 8px gap, never inside one; the time is pushed to the right edge.

### Section heads
A 2px ink rule over a 13px/700 name, with the count in muted 12.5px aligned right on the same baseline. Every list, column, lane and inspector section opens this way.

### Stats line
Eight equal cells divided by hairlines and closed by a 1px ink rule. Label in muted 12.5px, value in narrowed display numerals, delta in muted or green. The key cell (Known fixes served) is inverted to ink.

### Inputs / Fields
- **Recall search:** 42px, 1px ink border, 2px radius, leading search icon in muted, trailing `/` key hint in mono with a rule-2 outline. Focus switches the border to blue with a blue-wash halo. Caret is signal.
- **Select:** 34px, transparent, rule-2 border, 600 weight, a drawn chevron on the right.
- **Time ruler:** a range input drawn as a ruled scale (ticks every 10%), with a 4px square ink thumb that turns signal when live; the as-of label is mono, signal when live and amber in the past, where the whole band takes amber-wash.

### Navigation
- **Top bar:** bar-black ground with a 3px signal rule beneath. View tabs (Map, Board, Graph) are 600 weight in bar-muted, bar-ink when hovered or selected, with a 3px bar-ink underline that slides between tabs (0.28s, house ease).
- **Inspector tabs:** the same pattern on the sheet: muted to ink, 2px ink sliding underline, 48px tall.
- **Mobile bottom nav:** five equal items on the sheet, 20px icons over 11.5px labels; the current item is ink with a 3px ink bar along its top edge.

### Narration band
The demo's voice: a paper band under the stats line with the step number in narrowed signal numerals (ink when the story ends), the caption in 15px/500, a row of 6px by 4px ink progress ticks whose newest tick is signal, and an "All steps" popover listing the story so far. Captions swap with a short rise; the band reveals with a top-down clip.

### Provenance trail (signature)
A vertical 2px ink rule with 10px square stations, drawn downward on reveal with steps staggered in at 45ms. The first station (the memory itself) is solid signal and its line is ink and 600 weight; the rest are hollow ink squares. Below it, cross-reference buttons pair each map item's mono designation with its truncated title, and pressing "Why do we know this?" also traces the same path through the map's connectors.

### Map connectors (signature)
Orthogonal SVG paths out of the source row, down the gutter before the target column, into the target, with 4px square terminals. Resting stroke is 1px rule-2; handoffs are dashed blue; a highlighted path becomes 2px ink and draws itself on trace.

## Do's and Don'ts

### Do:
- **Do** set content in rows on 1px hairlines (rule) and open every group with a 2px ink rule and a 13px/700 head with a muted count.
- **Do** give every map item a mono designation (A, W, P, F, T plus a number) and reuse the same designation wherever that item is cross-referenced.
- **Do** keep signal red to live, action, just-arrived and failure states, and to one primary button per region.
- **Do** pair every status colour with a square mark and a word.
- **Do** invert selection to solid ink with sheet text.
- **Do** update values in place inside fixed cells; tick changes rather than reflowing.
- **Do** use narrowed Archivo (78 to 92% width) for numerals and the inspector headline, and tabular figures throughout.
- **Do** keep corners at 2px or square, and reserve circles for live pulses and graph nodes.
- **Do** give floating panels a 1px ink border plus the single pop shadow; nothing else gets elevation.
- **Do** redefine tokens under `[data-theme="dark"]` rather than adding theme-specific selectors.

### Don't:
- **Don't** build the soft-card indigo SaaS dashboard: cards on a dot grid, rounded shadowed tiles, an accent on everything.
- **Don't** introduce a second accent colour or use signal red as decoration, a section colour or a category.
- **Don't** convey status by colour alone.
- **Don't** put a shadow on anything that sits on the sheet.
- **Don't** round corners beyond 2px.
- **Don't** use faint grey for text that must be read; it is for decorative numerals only.
- **Don't** use client identity colours for anything but the agent's square avatar and its graph node.
