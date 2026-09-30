import { createTheme, type CSSVariablesResolver, type MantineColorsTuple } from '@mantine/core'

// Brand accent: a violet that leans toward magenta, the "glass" look's anchor. Shade 6 is the filled colour in light
// mode (white text on it is ~5.9:1), shade 5 in dark mode (~4.6:1), so labels on filled buttons stay readable.
const brand: MantineColorsTuple = [
  '#F6F0FF', '#EBDDFF', '#D6BBFF', '#BE94FF', '#A56DFA',
  '#9150EF', '#7E3BDB', '#6A2DBE', '#55239A', '#401A75',
]

// Dark mode is painted from this scale (7 = page, 6 = cards, 5 = hover, 4 = borders, 2 = dimmed, 0 = text).
// Tinted toward violet so the dark glass reads as the same family as the light one, not a generic grey.
const dark: MantineColorsTuple = [
  '#EEEBF7', '#CFC9E0', '#A9A2C0', '#716A8C', '#3B3554',
  '#2B2642', '#1F1B33', '#161229', '#0E0B1C', '#08060F',
]

// Plus Jakarta Sans: rounded, open letterforms that stay legible at small sizes, with a system-font fallback.
const FONT = '"Plus Jakarta Sans", -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif'

export const theme = createTheme({
  primaryColor: 'brand',
  primaryShade: { light: 6, dark: 5 },
  colors: { brand, dark },
  fontFamily: FONT,
  fontFamilyMonospace: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
  defaultRadius: 'md',
  focusRing: 'auto',
  cursorType: 'pointer',
  // One step larger than Mantine's defaults: every screen is comfortable to read without zooming.
  fontSizes: { xs: '13px', sm: '15px', md: '16px', lg: '18px', xl: '21px' },
  lineHeights: { xs: '1.45', sm: '1.5', md: '1.55', lg: '1.55', xl: '1.5' },
  radius: { xs: '8px', sm: '10px', md: '14px', lg: '20px', xl: '28px' },
  shadows: {
    xs: '0 1px 2px rgba(40, 20, 80, 0.06)',
    sm: '0 1px 2px rgba(40, 20, 80, 0.05), 0 6px 16px -8px rgba(60, 30, 120, 0.18)',
    md: '0 2px 4px rgba(40, 20, 80, 0.05), 0 14px 32px -12px rgba(60, 30, 120, 0.25)',
    lg: '0 4px 8px rgba(40, 20, 80, 0.06), 0 24px 56px -18px rgba(60, 30, 120, 0.32)',
    xl: '0 8px 16px rgba(40, 20, 80, 0.08), 0 36px 80px -24px rgba(60, 30, 120, 0.4)',
  },
  headings: {
    fontFamily: FONT,
    fontWeight: '700',
    sizes: {
      h1: { fontSize: '36px', lineHeight: '1.2', fontWeight: '800' },
      h2: { fontSize: '30px', lineHeight: '1.25', fontWeight: '800' }, // page title
      h3: { fontSize: '20px', lineHeight: '1.35' }, // section
      h4: { fontSize: '17px', lineHeight: '1.4' }, // card header
    },
  },
  components: {
    Button: {
      defaultProps: { size: 'md', radius: 'md' },
      // The primary filled button gets the violet-to-pink glass gradient; coloured (red, teal…) buttons keep their
      // meaning and only get the sheen from glass.css.
      classNames: (_theme: unknown, props: { color?: string; variant?: string }) => ({
        root: (!props.color || props.color === 'brand') && (!props.variant || props.variant === 'filled') ? 'ng-btn-primary' : '',
      }),
    },
    ActionIcon: { defaultProps: { variant: 'subtle', color: 'gray', size: 'lg', radius: 'md' } },
    TextInput: { defaultProps: { size: 'md' } },
    PasswordInput: { defaultProps: { size: 'md' } },
    NumberInput: { defaultProps: { size: 'md' } },
    Textarea: { defaultProps: { size: 'md' } },
    Select: { defaultProps: { size: 'md', comboboxProps: { shadow: 'lg', radius: 'md' } } },
    MultiSelect: { defaultProps: { size: 'md', comboboxProps: { shadow: 'lg', radius: 'md' } } },
    Checkbox: { defaultProps: { size: 'md', radius: 'sm' } },
    Switch: { defaultProps: { size: 'md' } },
    Badge: { defaultProps: { variant: 'light', radius: 'xl', size: 'md' } },
    Paper: { defaultProps: { withBorder: true, radius: 'lg' } },
    Card: { defaultProps: { withBorder: true, radius: 'lg' } },
    Table: { defaultProps: { highlightOnHover: true, verticalSpacing: 'md', horizontalSpacing: 'md' } },
    NavLink: { defaultProps: { variant: 'light' } },
    // Always underlined, so a link inside a sentence is recognisable without relying on colour alone.
    Anchor: { defaultProps: { underline: 'always', fw: 600 } },
    Tabs: { defaultProps: { variant: 'pills', radius: 'xl' } },
    SegmentedControl: { defaultProps: { radius: 'xl', size: 'md' } },
    Tooltip: { defaultProps: { withArrow: true, openDelay: 250, radius: 'md' } },
    Modal: {
      defaultProps: {
        radius: 'lg',
        centered: true,
        overlayProps: { backgroundOpacity: 0.3, blur: 8 },
        transitionProps: { transition: 'pop', duration: 220 },
      },
    },
    Alert: { defaultProps: { radius: 'md' } },
    Notification: { defaultProps: { radius: 'lg' } },
    Skeleton: { defaultProps: { radius: 'md' } },
  },
})

// Page colours for the glass look. Text and "dimmed" text are darker than Mantine's defaults so secondary text still
// passes contrast on a translucent card (Mantine's grey dimmed is ~3.3:1; this one is ~6.5:1).
export const cssVariablesResolver: CSSVariablesResolver = () => ({
  variables: {},
  light: {
    '--mantine-color-body': '#F3EEFA',
    '--mantine-color-text': '#1D1530',
    '--mantine-color-dimmed': '#5C5572',
    '--mantine-color-default': 'rgba(255, 255, 255, 0.72)',
    '--mantine-color-default-hover': 'rgba(255, 255, 255, 0.92)',
    '--mantine-color-default-border': 'rgba(110, 80, 160, 0.16)',
    '--mantine-color-placeholder': '#8A83A0',
    // Text on "light" badges, alerts and buttons: Mantine's defaults (e.g. yellow #e67700 on pale yellow, 2.7:1) are
    // too faint to read; these deeper tones clear 4.5:1 on their tinted backgrounds.
    '--mantine-color-yellow-light-color': '#7A4F00',
    '--mantine-color-orange-light-color': '#9E360A',
    '--mantine-color-teal-light-color': '#05614A',
    '--mantine-color-green-light-color': '#1D6A2E',
    '--mantine-color-red-light-color': '#B0241C',
    '--mantine-color-cyan-light-color': '#0A5E73',
    '--mantine-color-blue-light-color': '#1B57B0',
    '--mantine-color-lime-light-color': '#3F6212',
  },
  dark: {
    '--mantine-color-body': '#0E0B1C',
    '--mantine-color-text': '#EEEBF7',
    '--mantine-color-dimmed': '#B2ABC8',
    '--mantine-color-default': 'rgba(255, 255, 255, 0.06)',
    '--mantine-color-default-hover': 'rgba(255, 255, 255, 0.1)',
    '--mantine-color-default-border': 'rgba(255, 255, 255, 0.12)',
    '--mantine-color-placeholder': '#8C86A3',
  },
})
