import {
  ActionIcon,
  AppShell,
  Badge,
  Burger,
  Group,
  Menu,
  NavLink,
  SegmentedControl,
  Text,
  Title,
  useMantineColorScheme,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import {
  IconBell,
  IconDeviceDesktop,
  IconFileSettings,
  IconMap2,
  IconMoon,
  IconRadar,
  IconServer,
  IconSun,
  IconTopologyStar3,
} from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'
import { NavLink as RouterNavLink, Outlet } from 'react-router'

import { HealthIndicator } from '../components/HealthIndicator'
import { LANGUAGES } from '../i18n'

const LINKS = [
  { to: '/topology', label: 'nav.map', icon: IconMap2 },
  { to: '/devices', label: 'nav.devices', icon: IconServer },
  { to: '/discovery', label: 'nav.discovery', icon: IconRadar },
] as const

const LATER = [
  { label: 'nav.alarms', icon: IconBell },
  { label: 'nav.config', icon: IconFileSettings },
] as const

function ThemeMenu() {
  const { t } = useTranslation()
  const { colorScheme, setColorScheme } = useMantineColorScheme()
  const icons = { light: IconSun, dark: IconMoon, auto: IconDeviceDesktop }
  const Current = icons[colorScheme]
  return (
    <Menu position="bottom-end">
      <Menu.Target>
        <ActionIcon variant="default" size="lg" aria-label={t('header.theme.label')}>
          <Current size={18} aria-hidden />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        {(['light', 'dark', 'auto'] as const).map((scheme) => {
          const IconComponent = icons[scheme]
          return (
            <Menu.Item
              key={scheme}
              leftSection={<IconComponent size={16} aria-hidden />}
              onClick={() => {
                setColorScheme(scheme)
              }}
              aria-checked={colorScheme === scheme}
              role="menuitemradio"
            >
              {t(`header.theme.${scheme}`)}
            </Menu.Item>
          )
        })}
      </Menu.Dropdown>
    </Menu>
  )
}

export function Layout() {
  const { t, i18n } = useTranslation()
  const [opened, { toggle, close }] = useDisclosure()
  return (
    <AppShell
      header={{ height: 60 }}
      navbar={{ width: 220, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger
              opened={opened}
              onClick={toggle}
              hiddenFrom="sm"
              size="sm"
              aria-label={t('nav.toggle')}
            />
            <IconTopologyStar3 size={26} aria-hidden />
            <div>
              <Title order={1} size="h4" lh={1.1}>
                {t('app.title')}
              </Title>
              <Text size="xs" c="dimmed" visibleFrom="xs">
                {t('app.subtitle')}
              </Text>
            </div>
          </Group>
          <Group gap="sm" wrap="nowrap">
            <HealthIndicator />
            <SegmentedControl
              size="xs"
              aria-label={t('header.language')}
              value={i18n.language}
              onChange={(language) => void i18n.changeLanguage(language)}
              data={LANGUAGES.map((language) => ({
                value: language,
                label: language.toUpperCase(),
              }))}
            />
            <ThemeMenu />
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs" aria-label={t('nav.main')}>
        {LINKS.map(({ to, label, icon: IconComponent }) => (
          <NavLink
            key={to}
            component={RouterNavLink}
            to={to}
            label={t(label)}
            leftSection={<IconComponent size={18} aria-hidden />}
            onClick={close}
          />
        ))}
        {LATER.map(({ label, icon: IconComponent }) => (
          <NavLink
            key={label}
            label={t(label)}
            leftSection={<IconComponent size={18} aria-hidden />}
            rightSection={
              <Badge size="xs" variant="light" color="gray">
                {t('nav.soon')}
              </Badge>
            }
            disabled
          />
        ))}
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  )
}
