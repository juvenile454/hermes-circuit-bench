// Theme "Bench Phosphor" (THEMES_AREA): colours + typography only, no customCSS, no fontUrl.
// Listed in Settings → Appearance → Theme; never selected automatically.

const BENCH_THEME = {
  name: 'bench-phosphor',
  label: 'Bench Phosphor',
  description: 'Phosphor green on near-black — circuit bench',
  colors: {
    background: PHOSPHOR.bg,
    foreground: PHOSPHOR.fg,
    card: PHOSPHOR.panel,
    cardForeground: PHOSPHOR.fg,
    muted: PHOSPHOR.raised,
    // between fg and fg-dim: app icons and the status bar must not look dimmed
    mutedForeground: THEME_MUTED,
    popover: PHOSPHOR.panel,
    popoverForeground: PHOSPHOR.fg,
    primary: PHOSPHOR.ok,
    primaryForeground: PHOSPHOR.ink,
    secondary: '#0f2418',
    secondaryForeground: PHOSPHOR.fg,
    accent: '#0f2418',
    accentForeground: PHOSPHOR.ok,
    border: PHOSPHOR['stroke-strong'],
    input: PHOSPHOR['stroke-strong'],
    ring: PHOSPHOR.ok,
    midground: PHOSPHOR.ok,
    destructive: PHOSPHOR.bad,
    destructiveForeground: PHOSPHOR.ink,
    sidebarBackground: '#030604',
    sidebarBorder: PHOSPHOR.stroke,
    userBubble: PHOSPHOR.raised,
    userBubbleBorder: PHOSPHOR['stroke-strong']
  },
  typography: {
    fontSans: 'system-ui, "Segoe UI", "Helvetica Neue", Arial, sans-serif',
    fontMono: MONO.replace('var(--dt-font-mono), ', '')
  }
}
