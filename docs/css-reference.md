# CSS Reference

This file documents every CSS variable, design token, font face, animation, responsive breakpoint, and recurring styling pattern used in [style.css](../static/style.css).

---

## 1. CSS Custom Properties

All variables live inside `:root` (the document-level scope), so they cascade to every descendant.

### 1.1 Layout & spacing

| Variable | Value | Purpose |
|---|---|---|
| `--radius` | `10px` | Default `border-radius` applied to panels |

### 1.2 Background

| Variable | Value | Purpose |
|---|---|---|
| `--bg` | `#10141a` | Page/body background (overrides the dark gradient behind `body`) |
| `--panel` | `#171d26` | Panel / card background |
| `--panel-raised` | `#1c232e` | Slightly lighter panel variant used for buttons, state badges, and hover surfaces |

### 1.3 Borders

| Variable | Value | Purpose |
|---|---|---|
| `--border` | `#4e4e4e` | Default border colour for panels, header separators, buttons, state badges |

### 1.4 Text

| Variable | Value | Purpose |
|---|---|---|
| `--text` | `#e7eaf0` | Primary text colour (page title, specs, button text) |
| `--text-dim` | `#8892a3` | Secondary / muted text (spec values, body text) |
| `--text-faint` | `#8892a3` | Alias of `--text-dim`; used for eyebrow labels, spec labels, footer |

### 1.5 LED colours

| Variable | Value | Purpose |
|---|---|---|
| `--led-active` | `rgb(82, 215, 113)` | Green — service **running / stopped** |
| `--led-active-glow` | `rgba(82, 215, 113, 0.45)` | Glow intensity for an active LED |
| `--led-inactive` | `#6b7686` | Grey — service **idle / default** state |
| `--led-failed` | `rgb(232, 79, 79)` | Red — service **failed** |
| `--led-failed-glow` | `rgba(232, 79, 79, 0.4)` | Glow intensity for a failed LED |
| `--led-warn` | `#e3ab4a` | Amber — warning state (declared but not currently applied to any rule) |

LED state is controlled at render time by two shadow custom properties on the `.led` element:

```css
.led {
  --led-color: var(--led-inactive);   /* swap to --led-active or --led-failed as needed */
  --led-glow: transparent;            /* swap to --led-active-glow / --led-failed-glow */
}
```

### 1.6 Focus / accent (used outside `:root`)

| Custom property | Value (when active) | Purpose |
|---|---|---|
| `.btn-primary.action-start` → background | `--led-active` | Green CTA |
| `.btn-primary.action-stop` → border | `--led-failed` | Red-outlined destructive button |
| `.error-banner` | hard-coded `rgba(232, 102, 79, …)` | Red error surface |
| `button:focus-visible` outline | `var(--led-active)` | Green focus ring |

---

## 2. Typography

### 2.1 Font faces

| Variable | Value | Loaded from |
|---|---|---|
| `--font-mono` | `'IBM Plex Mono', ui-monospace, 'SF Mono', monospace` | Google Fonts `https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap` |
| `--font-ui` | `'Inter', -apple-system, sans-serif` | Google Fonts `https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap` |

**Usage patterns:**

| Font | Where applied |
|---|---|
| `--font-mono` | Page title, eyebrow labels, unit names, spec labels/values, state badges, buttons, footer, error banner |
| `--font-ui` | `<body>` fallback, buttons |

### 2.2 Common text sizes

| Value | Where used |
|---|---|
| `11px` | Eyebrow label, footer timestamp / `last-run` |
| `12px` | Error banner |
| `13px` | State badge text, spec labels & values |
| `14px` | Button text |
| `15px` | Unit name (in panel header) |
| `19px` | Page title |

Weights: `500` for titles, `600` for state badge / button text, `400` is not explicitly declared.

### 2.3 Letter spacing

| Variable | Where used |
|---|---|
| `0.08em` | Eyebrow (uppercase) |
| `0.04em` | State badge |
| `0.02em` | Spec label |

---

## 3. Animation

### 3.1 LED breathing — `.led.pulse`

Purpose: simulate a softly pulsing / "breathing" service LED when the status panel is not currently updating.

```css
@keyframes breathe {
  0%, 100% { opacity: 1;    }
  50%      { opacity: 0.55; }
}

.led.pulse {
  animation: breathe 2.6s ease-in-out infinite;
}
```

*Cycle length:* **2.6 s**, ease-in-out, infinite, opacity oscillates between `1` and `0.55`.

### 3.2 Reduced motion guard

```css
@media (prefers-reduced-motion: reduce) {
  .led.pulse { animation: none; }
  * { transition-duration: 0.01ms !important;
      animation-duration: 0.01ms !important; }
}
```

When the user's OS requests reduced motion:

- `.led.pulse` animation is disabled (`animation: none`).
- **Every** `transition` and `animation` on **every element** is collapsed to ~0 ms via `!important`. This is a brute-force accessibility override — it will disable the 0.08 s button `transform`, the 0.2 s colour transitions, the 2.6 s LED pulse, and the 0.4 s LED `box-shadow` transition.

### 3.3 Button hover / active animations

```css
button {
  transition: transform 0.08s ease,
              background-color 0.2s ease,
              border-color 0.2s ease,
              opacity 0.2s ease;
}
button:hover:not(:disabled) { border-color: #3a4657; }
button:active:not(:disabled) { transform: scale(0.97); }
```

- Hover brightens the border to `#3a4657` (200 ms).
- Active presses shrink slightly to `scale(0.97)` (80 ms).

---

## 4. Responsive breakpoints

### 4.1 Small viewport — `@media (max-width: 400px)`

Only one override exists for very narrow screens (small phones held portrait):

```css
@media (max-width: 400px) {
  .panel-header  { flex-wrap: wrap; }
  .state-word    { margin-left: 50px; }
}
```

- **`.panel-header`** switches to `flex-wrap: wrap`, allowing the eye-brow / unit name / state-badge to stack vertically when needed.
- **`.state-word`** gets a large left margin to visually separate itself from the LED + name cluster when the header has wrapped.

### 4.2 No other breakpoints

The grid itself is already fluid:

```css
.rack {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: 16px;
}
```

- `minmax(380px, 1fr)` — each panel is at least 380 px wide; the grid reflows from 1-column → 2-column → 3-column as `--viewport-width` grows, with no explicit media query needed.
- `max-width: 1480px` on `.page` caps the layout on very wide screens.

---

## 5. The `.panel:focus-within` highlight pattern

`focus-within` is **not used** in style.css. There is no `.panel:focus-within` rule anywhere in the stylesheet.

The actual focus-highlight system is implemented at the button level:

```css
button:focus-visible {
  outline: 2px solid var(--led-active);
  outline-offset: 2px;
}
```

- Uses `outline` (not `box-shadow`), so browsers may still paint a default focus ring *under* the custom one in some cases.
- Colour: `--led-active` (green, `rgb(82, 215, 113)`).
- Offset: `2px` gap between the button edge and the outline.
- Only fires for keyboard navigation (`:focus-visible`), not mouse clicks.

For context, the full panel structure is layered on top of the focused element:

```
.panel (rounded corners, drop shadow)
 ├── .panel-header (LE + eye-brow, unit-name, .led, .state-word)
 ├── .specs (label/value grid)
 ├── .actions (flex row of buttons)
 └── .footer  (small muted text + last-run)
```

When focus reaches a button inside an action row, only that button draws the green outline — the parent panel remains untouched.

---

## 6. Error banner

Although the banner uses hard-coded colours rather than CSS variables, it is worth noting here because it is the only semantic coloured surface beyond the LED palette:

```css
.error-banner {
  background: rgba(232, 102, 79, 0.12);
  border:      1px solid rgba(232, 102, 79, 0.35);
  color:       #f2a596;
  font-family: var(--font-mono);
  font-size:   12px;
  display:     none;            /* toggled to block via .show */
}
```

The red (`rgb(232, 79, 79)`) is the same hue as `--led-failed`, reused for visual consistency between the warning LED and the error banner.

---

## 7. Summary table — everything in one place

| Category | Count |
|---|---|
| CSS variables (`--*`) declared in `:root` | 16 |
| Font families (Google Fonts imports) | 2 |
| `@media` rules | 2 (reduced-motion + small viewport) |
| `@keyframes` definitions | 1 (`breathe`) |
| Focus highlight rules | 1 (`button:focus-visible`) |
| Hard-coded accent surfaces (non-variable) | error-banner, button-hover border |
