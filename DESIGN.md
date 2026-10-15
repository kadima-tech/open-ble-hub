# Design

The design language of the Bathroom Hub web UI (`apps/bathroom-hub/src/bathroom_hub/web.py`, `static/app.css`, `static/app.js`), called **Mineral**. It is the only UI in the repository; a new hub under `apps/` starts from these tokens and components. It was chosen from the "Flow Directions" design explorations (onboarding → dashboard → device hub).

## Character

Calm, light and sage: a health tool for a household, read on a phone in the bathroom. Large, quiet numbers; white cards on a stone-green ground; one deep green accent. Nothing loads from the internet: the font is bundled, pages are server-rendered, and `app.js` only adds conveniences.

## Flow

1. **Onboarding** (`/welcome`, shown while there are no people): step 1 creates the first profile, step 2 connects Google Health (or points to the one-time OAuth setup in Settings), step 3 pairs the scale. Steps 2 and 3 can be skipped. A three-segment progress bar shows the step.
2. **Dashboard** (`/`): one person at a time, chosen with the profile switcher (remembered in a cookie; defaults to whoever weighed last). A "Who was this?" card leads when a weigh could not be matched. Then the weight card with chart and 7d/30d/90d/1y range, body-fat and lean-mass cards with sparklines, Google Health and Device hub rows, and recent weighs.
3. **Device hub** (`/devices`): the hub's own status, devices needing attention pinned first, then devices grouped by room (or type). Search and filter chips appear once there are more than five devices; groups show four devices and fold the rest. A sticky "Add device" button.
4. **Add device** (`/devices/add`): "Found nearby" first (devices in pairing mode get a Pair button), live pairing steps with a countdown, then a catalogue to search or browse by type with a support badge per model.

Supporting pages: device detail (`/devices/{id}`), weighs (`/history`), people (`/profiles`), Google linking (`/profiles/{id}/google`), settings (`/settings`).

## Colour

Tokens live on `:root` in `app.css`; dark mode follows `prefers-color-scheme`.

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `--bg` | `#eef1ec` | `#111613` | page ground |
| `--surface` | `#ffffff` | `#1a211d` | cards, inputs, icon buttons |
| `--surface-2` | `#f5f7f4` | `#212923` | icon tiles, fact tiles, inactive step numbers |
| `--sunken` | `#dde3de` | `#0c100e` | segmented-control track |
| `--text` / `--text-2` / `--muted` | `#18221e` / `#34413b` / `#56635d` | `#e6ece8` / `#c5cfc9` / `#9aa6a0` | body, secondary, labels and hints |
| `--border` / `--divider` | `#d3dad5` / `#eef1ec` | `#2c3530` / `#242c27` | input borders / row dividers, chart grid |
| `--accent` (+ `-hover`, `-soft`) | `#1f5e4f` | `#6fbfa6` | primary buttons, links, hub card, weight chart, "ok" badges |
| `--warn-*` | text `#6b4a00`, bg `#fff4de`, border `#f0d9a8` | `#f2c063`, `#2e2510`, `#5a4618` | "Who was this?", needs attention, pairing countdown |
| `--error` / `--error-bg` | `#b42318` / `#fde8e6` | `#ff8a80` / `#3d1f1d` | failures, destructive links, form errors |
| `--tone-weight` / `--tone-fat` / `--tone-lean` | `#1f5e4f` / `#b86b2e` / `#3e6f9e` | `#6fbfa6` / `#e09a5e` / `#7fa9d6` | chart line per measure |

Person avatars use a fixed five-colour palette (`.av-0`…`.av-4`, by profile id) with white initials. Status is always written out (badge text, row note, `aria-label` on dots), never colour alone.

## Typography

- **Instrument Sans** (variable, 400–700), bundled as `static/fonts/instrument-sans-latin-wght-normal.woff2` (OFL; licence beside it), falling back to `system-ui`.
- Base 15px / 1.45. Page titles 24px/600; onboarding titles 32px/600 with −0.02em tracking; card titles 17px/600; eyebrows and labels 13px/500 muted; small print 12px.
- Numbers: the main weight 56px/600 (−0.03em), secondary figures 26px/600, units in muted text beside them. Tabular figures throughout.

## Spacing, shape and layout

- 4px-based scale (`--space-1`…`--space-7` = 4, 8, 12, 16, 20, 24, 32px).
- Radii: cards 22px (`--r-lg`), small cards and tiles 16–20px, inputs and buttons 14px, chips and badges fully round.
- Cards have no border; the white surface on the stone ground separates them. Shadows only on floating things (menus, the sticky button).
- Content column 560px (480px for onboarding and Google linking); the dashboard widens to 1040px and splits into two columns from 900px.

## Components

- **Top bar:** a 44px square back button, title with a muted sub-line, optional icon buttons on the right. On the dashboard the profile switcher (a `<details>` menu) takes the title's place.
- **Cards:** `.card` with `.card-head` (title left, badge or link right); `.notice` in warn colours; `.ok-card` and `.error-card` for outcomes.
- **Rows:** `.row-item` with a 36px `.icon-tile`, two-line text and a trailing badge, dot or chevron; divided by `--divider` lines inside a `.list-card`.
- **Buttons:** primary (accent fill, 48px; 56px when sticky), secondary (white with border), ghost (accent text), `btn-link` (text only; `.danger` red).
- **Segmented control:** `.seg` for range tabs (links) and `.seg-input` for radio choices such as sex.
- **Chips:** filter links; the selected chip is filled with `--text`.
- **Forms:** labels above inputs, 52px fields, units inside the field on the right (`.with-unit`), errors in one block at the top.
- **Numbered steps:** `.numbered` with round counters; `.is-done` shows a check on the accent, `.is-now` a warn ring.
- **Charts:** server-rendered SVG (`bathroom_hub/charts.py`): one line with a 9% area, three grid lines, a dot on the latest value, min and max to the right, start date and "Today" beneath. Sparklines on the small cards.

## Interaction

- Every action is a form POST then a redirect (with an optional same-site `next`), confirmed by a green flash. Destructive forms carry `data-confirm`.
- Pages with live state poll `/api/status` every 4s and reload when it changes, but not while someone is typing or has a menu open. The pairing countdown ticks each second.
- Motion: only the "Searching" spinner, which stops under `prefers-reduced-motion`.
- Touch targets at least 44px.

## Voice

Short, direct and friendly. Say what happens and what to do next ("Hold the unit button on the scale for 3 seconds"). "Weigh" for one measurement, "person" in the UI and "profile" in setup, "device hub" for the device list. Body-fat values are labelled as estimates with their ± range.
