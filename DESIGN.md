# Design

The design language of the Philips BLE Hub configuration UI (`ble_hub/web.py`, `ble_hub/static/app.css`) as it exists in the code.

## Character

A quiet utility on the home network: plain, calm and readable on a phone held in the bathroom. There are no images, web fonts or CDNs, because the Pi may have no internet and is slow. Pages are server-rendered HTML with a small inline script for live status.

## Color

Tokens live on `:root` in `app.css`. Dark mode follows `prefers-color-scheme`.

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `--bg` | `#f5f6f4` | `#121514` | page background |
| `--surface` | `#ffffff` | `#1b1f1d` | cards, header, inputs |
| `--surface-2` | `#eef0ec` | `#232826` | secondary buttons, active nav, muted badges |
| `--text` | `#1c211f` | `#e7ebe8` | body text |
| `--muted` | `#5d6662` | `#9aa49f` | labels, hints, timestamps |
| `--border` | `#dde1dc` | `#2e3431` | card and table borders |
| `--accent` | `#1f7a68` | `#4fb39d` | primary buttons, links, focus ring, "Getting started" card |
| `--ok` / `--ok-bg` | `#1f7a4a` / `#e3f2e9` | `#6fcf97` / `#1d3327` | "Paired", "Sent", flash messages |
| `--warn` / `--warn-bg` | `#8a5a00` / `#fbf0d9` | `#f2c063` / `#3a2f17` | "Pairing", "Queued", unmatched weigh rows |
| `--error` / `--error-bg` | `#b42318` / `#fde8e6` | `#ff8a80` / `#3d1f1d` | failures, destructive links, form errors |

There is a single accent (teal-green). Status is always shown with a text badge, never with color alone.

## Typography

- System UI stack (`--font`), base 16px with line height 1.5.
- `h1` 1.5rem, `h2` 1.05rem, both semi-bold. The brand in the header is 650 weight.
- Numbers in tables use tabular figures and are right-aligned.
- `--mono` for addresses and code fragments.

## Spacing and layout

- 4px scale: `--space-1`…`--space-6` = 4, 8, 12, 16, 24, 32px.
- Content is at most 1040px wide with a 16px side gutter.
- Cards have a 10px radius (`--radius`), a 1px border and no shadow.
- The overview puts Scale and Activity in an auto-fit grid (min 300px per column) and the Weighs table below at full width.
- Below 640px, two-column form rows and fact lists stack into one column, and tables scroll horizontally inside `.table-wrap`.

## Components

- **Header:** brand plus text nav; the active item has a `--surface-2` pill.
- **Card:** a `.card-head` row holds the title and a badge on the right.
- **Badge:** a pill in four tones: `ok`, `warn`, `error`, `muted`.
- **Buttons:** `.primary` (accent fill), `.secondary` (surface with border), and `button.link` (text only; `.danger` for destructive).
- **Forms:** labels wrap their inputs, with `.hint` text underneath. Validation errors appear in a single `.errors` block at the top. Inputs are at least 40px tall.
- **Weighs table:** rows needing a person get the `--warn-bg` fill. The person select submits as soon as it changes, with a `<noscript>` save button as fallback.
- **Flash:** a green banner after redirects (POST, then redirect, then GET).

## Interaction

- Every action is a plain form POST followed by a redirect. Destructive actions ask for confirmation with `confirm()`.
- The overview polls `/api/status` every 4s and reloads when something changes. The pairing countdown ticks each second.
- No animation.

## Voice

Short, direct sentences that say what happens and what to do next ("Hold the unit button on the scale for 3 seconds"). Use "weigh" for a single measurement and "person" or "profile" for users.
