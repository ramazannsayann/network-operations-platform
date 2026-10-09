import createClient from 'openapi-fetch'

import type { components, paths } from './schema'

/** Typed client for the NetOps API; paths, parameters and bodies come from the contract. */
export const api = createClient<paths>({ baseUrl: '/' })

export type Schemas = components['schemas']
