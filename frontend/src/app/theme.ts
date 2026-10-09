import { Badge, createTheme } from '@mantine/core'

export const theme = createTheme({
  primaryColor: 'indigo',
  defaultRadius: 'md',
  fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
  fontFamilyMonospace: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
  components: {
    // No uppercase: CSS upper-casing follows the page language, and in Turkish "switch"
    // would become "SWİTCH". Status texts keep their case in every language.
    Badge: Badge.extend({ styles: { label: { textTransform: 'none' } } }),
  },
})
