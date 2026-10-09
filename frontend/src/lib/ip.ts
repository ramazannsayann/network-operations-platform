/** IP address and CIDR checks for forms (the API validates again). */

const IPV4_OCTET = '(25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)'
const IPV4 = new RegExp(`^${IPV4_OCTET}(\\.${IPV4_OCTET}){3}$`)

export function isIpv4(value: string): boolean {
  return IPV4.test(value)
}

/** IPv6 in any of its textual forms (full, compressed, with an embedded IPv4 tail). */
export function isIpv6(value: string): boolean {
  if (!value.includes(':') || value.includes(':::')) return false
  let text = value
  let groups = 8
  const lastColon = text.lastIndexOf(':')
  const tail = text.slice(lastColon + 1)
  if (tail.includes('.')) {
    if (!isIpv4(tail)) return false
    text = `${text.slice(0, lastColon + 1)}0`
    groups = 7
  }
  const halves = text.split('::')
  if (halves.length > 2) return false
  const parts = halves.flatMap((half) => (half === '' ? [] : half.split(':')))
  if (!parts.every((part) => /^[0-9a-f]{1,4}$/i.test(part))) return false
  return halves.length === 2 ? parts.length < groups : parts.length === groups
}

export function isIpAddress(value: string): boolean {
  return isIpv4(value) || isIpv6(value)
}

/** A network in CIDR notation, e.g. 10.0.0.0/16 or 2001:db8::/32. Host bits may be set. */
export function isCidr(value: string): boolean {
  const [address, length, ...rest] = value.split('/')
  if (address === undefined || length === undefined || rest.length > 0) return false
  if (!/^\d{1,3}$/.test(length)) return false
  const bits = Number(length)
  if (isIpv4(address)) return bits <= 32
  if (isIpv6(address)) return bits <= 128
  return false
}

function ipv4ToNumber(address: string): number {
  return address.split('.').reduce((total, octet) => total * 256 + Number(octet), 0)
}

/** Whether an IPv4 address lies in an IPv4 CIDR network; null for IPv6 (not checked here). */
export function ipv4InCidr(address: string, cidr: string): boolean | null {
  const [network = '', length = ''] = cidr.split('/')
  if (!isIpv4(address) || !isIpv4(network)) return null
  const bits = Number(length)
  const size = 2 ** (32 - bits)
  const start = Math.floor(ipv4ToNumber(network) / size) * size
  const value = ipv4ToNumber(address)
  return value >= start && value < start + size
}

/** Tags typed or pasted as "10.0.0.1, 10.0.0.2": split on separators, trimmed, unique. */
export function normalizeTags(values: string[]): string[] {
  return [...new Set(values.flatMap((value) => value.split(/[\s,;]+/)).filter(Boolean))]
}

export interface DiscoveryFormValues {
  seeds: string[]
  allowedSubnets: string[]
  credentialProfileIds: string[]
}

/** i18n keys of the problems, per field; an empty object means the form is valid. */
export interface DiscoveryFormErrors {
  seeds?: string
  allowedSubnets?: string
  credentialProfileIds?: string
}

export function validateDiscoveryForm(values: DiscoveryFormValues): DiscoveryFormErrors {
  const errors: DiscoveryFormErrors = {}
  if (values.seeds.length === 0) errors.seeds = 'discovery.validation.seedsRequired'
  else if (!values.seeds.every(isIpAddress)) errors.seeds = 'discovery.validation.seedInvalid'

  if (values.allowedSubnets.length === 0)
    errors.allowedSubnets = 'discovery.validation.subnetsRequired'
  else if (!values.allowedSubnets.every(isCidr))
    errors.allowedSubnets = 'discovery.validation.subnetInvalid'

  if (!errors.seeds && !errors.allowedSubnets) {
    // A seed outside every allowed subnet would only be recorded as out of scope.
    const outside = values.seeds.filter((seed) =>
      values.allowedSubnets.every((subnet) => ipv4InCidr(seed, subnet) === false),
    )
    if (outside.length > 0) errors.seeds = 'discovery.validation.seedOutsideSubnets'
  }

  if (values.credentialProfileIds.length === 0)
    errors.credentialProfileIds = 'discovery.validation.profilesRequired'
  return errors
}
