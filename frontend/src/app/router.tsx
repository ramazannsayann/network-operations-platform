import { createBrowserRouter, Navigate } from 'react-router'

import { DeviceDetailPage } from '../features/devices/DeviceDetailPage'
import { DevicesPage } from '../features/devices/DevicesPage'
import { DiscoveryPage } from '../features/discovery/DiscoveryPage'
import { DiscoveryRunPage } from '../features/discovery/DiscoveryRunPage'
import { Layout } from './Layout'
import { NotFound } from './NotFound'

export const routes = [
  {
    element: <Layout />,
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
      { path: '*', element: <NotFound /> },
    ],
  },
]

export const router = createBrowserRouter(routes)
