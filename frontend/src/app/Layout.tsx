import {
  ActionIcon,
  AppShell,
  Avatar,
  Badge,
  Burger,
  Group,
  Menu,
  NavLink,
  SegmentedControl,
  Stack,
  Text,
  Title,
  UnstyledButton,
  useMantineColorScheme,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import {
  IconBell,
  IconDeviceDesktop,
  IconFileSettings,
  IconHistory,
  IconLogout,
  IconMap2,
  IconMessages,
  IconMoon,
  IconRadar,
  IconServer,
  IconSun,
  IconTopologyStar3,
  IconUser,
} from '@tabler/icons-react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, NavLink as RouterNavLink, Outlet } from 'react-router'

import { useAuth, useMe } from '../auth/context'
import { HealthIndicator } from '../components/HealthIndicator'
import { LANGUAGES } from '../i18n'

const LINKS = [
  { to: '/topology', label: 'nav.map', icon: IconMap2, permission: 'topology:read' },
  { to: '/devices', label: 'nav.devices', icon: IconServer, permission: 'devices:read' },
  { to: '/discovery', label: 'nav.discovery', icon: IconRadar, permission: 'discovery:read' },
  { to: '/configs', label: 'nav.config', icon: IconFileSettings, permission: 'configs:read' },
  {
    to: '/config-changes',
    label: 'nav.configChanges',
    icon: IconHistory,
    permission: 'configs:read',
  },
  { to: '/events', label: 'nav.events', icon: IconMessages, permission: 'events:read' },
] as const

const LATER = [{ label: 'nav.alarms', icon: IconBell }] as const

function UserMenu() {
  const { t } = useTranslation()
  const { logout } = useAuth()
  const me = useMe()
  return (
    <Menu position="bottom-end">
      <Menu.Target>
        <UnstyledButton aria-label={t('header.account')}>
          <Group gap={6} wrap="nowrap">
            <Avatar size="sm" radius="xl" color="indigo">
              {me.display_name.slice(0, 1).toUpperCase()}
            </Avatar>
            <Stack gap={0} visibleFrom="md">
              <Text size="sm" fw={500} lh={1.1}>
                {me.display_name}
              </Text>
              <Text size="xs" c="dimmed" lh={1.1}>
                {t(`enums.userRole.${me.role}`)}
              </Text>
            </Stack>
          </Group>
        </UnstyledButton>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>{me.username}</Menu.Label>
        <Menu.Item component={RouterLink} to="/profile" leftSection={<IconUser size={16} />}>
          {t('nav.profile')}
        </Menu.Item>
        <Menu.Item
          leftSection={<IconLogout size={16} />}
          onClick={() => {
            void logout()
          }}
        >
          {t('auth.logout')}
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  )
}

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
  const { permissions } = useMe()
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
            <UserMenu />
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs" aria-label={t('nav.main')}>
        {LINKS.filter((link) => permissions.includes(link.permission)).map(
          ({ to, label, icon: IconComponent }) => (
            <NavLink
              key={to}
              component={RouterNavLink}
              to={to}
              label={t(label)}
              leftSection={<IconComponent size={18} aria-hidden />}
              onClick={close}
            />
          ),
        )}
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
