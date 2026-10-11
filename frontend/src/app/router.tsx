import { createBrowserRouter, Navigate } from 'react-router'

import { RequireAuth, RequirePermission } from '../auth/guards'
import { LoginPage } from '../features/account/LoginPage'
import { ProfilePage } from '../features/account/ProfilePage'
import { SetupMfaPage, SetupPasswordPage } from '../features/account/SetupPages'
import { AuditPage } from '../features/admin/AuditPage'
import { CredentialsPage } from '../features/admin/CredentialsPage'
import { UsersPage } from '../features/admin/UsersPage'
import { ConfigChangesPage } from '../features/configs/ConfigChangesPage'
import { ConfigsPage } from '../features/configs/ConfigsPage'
import { DeviceDetailPage } from '../features/devices/DeviceDetailPage'
import { DevicesPage } from '../features/devices/DevicesPage'
import { DiscoveryPage } from '../features/discovery/DiscoveryPage'
import { DiscoveryRunPage } from '../features/discovery/DiscoveryRunPage'
import { EventsPage } from '../features/events/EventsPage'
import { Layout } from './Layout'
import { NotFound } from './NotFound'

export const routes = [
  { path: 'login', element: <LoginPage /> },
  {
    path: 'setup/password',
    element: (
      <RequireAuth>
        <SetupPasswordPage />
      </RequireAuth>
    ),
  },
  {
    path: 'setup/mfa',
    element: (
      <RequireAuth>
        <SetupMfaPage />
      </RequireAuth>
    ),
  },
  {
    element: (
      <RequireAuth>
        <Layout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to="/topology" replace /> },
      {
        path: 'topology',
        // Cytoscape is large; the map loads it on first visit.
        lazy: async () => ({
          Component: (await import('../features/topology/TopologyPage')).TopologyPage,
        }),
      },
      { path: 'devices', element: <DevicesPage /> },
      { path: 'devices/:deviceId', element: <DeviceDetailPage /> },
      { path: 'discovery', element: <DiscoveryPage /> },
      { path: 'discovery/runs/:runId', element: <DiscoveryRunPage /> },
      { path: 'configs', element: <ConfigsPage /> },
      { path: 'config-changes', element: <ConfigChangesPage /> },
      { path: 'events', element: <EventsPage /> },
      { path: 'profile', element: <ProfilePage /> },
      {
        path: 'admin/users',
        element: (
          <RequirePermission permission="users:manage">
            <UsersPage />
          </RequirePermission>
        ),
      },
      {
        path: 'admin/credentials',
        element: (
          <RequirePermission permission="credentials:manage">
            <CredentialsPage />
          </RequirePermission>
        ),
      },
      {
        path: 'admin/audit',
        element: (
          <RequirePermission permission="audit:read">
            <AuditPage />
          </RequirePermission>
        ),
      },
      { path: '*', element: <NotFound /> },
    ],
  },
]

export const router = createBrowserRouter(routes)
