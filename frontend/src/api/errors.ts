import type { Schemas } from './client'

export type Problem = Schemas['Problem']

/** An API error with its RFC 9457 problem details, when the API sent them. */
export class ApiError extends Error {
  readonly status: number
  readonly problem: Problem | null

  constructor(status: number, problem: Problem | null) {
    super(problem?.detail ?? problem?.title ?? `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.problem = problem
  }
}

function isProblem(value: unknown): value is Problem {
  return typeof value === 'object' && value !== null && 'title' in value && 'status' in value
}

/** The data of an openapi-fetch result, or an ApiError. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call
  if (response.ok && data !== undefined) return data
  throw new ApiError(response.status, isProblem(error) ? error : null)
}
