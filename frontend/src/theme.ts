import { createTheme, type CSSVariablesResolver, type MantineColorsTuple } from '@mantine/core'

// Brand accent. Shade 6 in light mode, shade 5 in dark (primaryShade below) so it keeps contrast on both.
const brand: MantineColorsTuple = [
  '#EEF3FF', '#DCE6FF', '#B9CDFF', '#94B2FF', '#6F97FF',
  '#4F7CFF', '#3A63E6', '#2B4EC2', '#1F3B99', '#162B73',
]

// Mantine paints dark mode from this scale: 7 = page, 6 = cards/paper, 5 = hover/raised, 4 = borders,
// 2 = dimmed text, 0 = text. Layered surfaces with 1px borders instead of shadows.
const dark: MantineColorsTuple = [
  '#E6E8EC', '#C4C9D2', '#9AA3B2', '#5B6473', '#2A2F3A',
  '#1E222B', '#171A21', '#0F1115', '#0B0D10', '#07080A',
]

const FONT = 'Inter, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'

export const theme = createTheme({
  primaryColor: 'brand',
  primaryShade: { light: 6, dark: 5 },
  colors: { brand, dark },
  fontFamily: FONT,
  defaultRadius: 'md',
  focusRing: 'auto',
  headings: {
    fontFamily: FONT,
    fontWeight: '600',
    sizes: {
      h1: { fontSize: '32px', lineHeight: '1.25', fontWeight: '700' },
      h2: { fontSize: '24px', lineHeight: '1.3', fontWeight: '700' }, // page title
      h3: { fontSize: '18px', lineHeight: '1.35' }, // section
      h4: { fontSize: '16px', lineHeight: '1.4' }, // card header
    },
  },
  components: {
    Badge: { defaultProps: { variant: 'light' } },
    ActionIcon: { defaultProps: { variant: 'subtle', color: 'gray' } },
    Paper: { defaultProps: { withBorder: true } },
    Card: { defaultProps: { withBorder: true } },
    Table: { defaultProps: { highlightOnHover: true, verticalSpacing: 'sm' } },
    NavLink: { defaultProps: { variant: 'light' } },
  },
})

// Light mode gets a soft grey page under white cards; dark mode is fully driven by the `dark` scale above.
export const cssVariablesResolver: CSSVariablesResolver = () => ({
  variables: {},
  light: { '--mantine-color-body': '#F6F7F9' },
  dark: {},
})
