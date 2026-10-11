import { ApiError } from '../../api/errors'

/** The field errors of a problem (422), keyed by the body field they belong to. */
export function fieldErrors(error: unknown): Record<string, string[]> {
  if (!(error instanceof ApiError)) return {}
  const issues = (error.problem as { errors?: { loc: (string | number)[]; type: string }[] } | null)
    ?.errors
  const result: Record<string, string[]> = {}
  for (const issue of issues ?? []) {
    const field = String(issue.loc[issue.loc.length - 1] ?? '')
    ;(result[field] ??= []).push(issue.type)
  }
  return result
}

/** "password.common" -> the i18n key of its message. */
export function passwordMessageKey(type: string): string {
  const known = [
    'too_short',
    'too_long',
    'common',
    'repetitive',
    'sequence',
    'contains_name',
    'unchanged',
    'wrong',
  ]
  const code = type.replace(/^password\./, '')
  return known.includes(code) ? `account.password.errors.${code}` : 'account.password.errors.other'
}
