import { describe, expect, it } from 'vitest'

import {
  ipv4InCidr,
  isCidr,
  isIpAddress,
  isIpv4,
  isIpv6,
  normalizeTags,
  validateDiscoveryForm,
} from './ip'

describe('IP addresses', () => {
  it.each(['10.0.0.1', '192.0.2.255', '0.0.0.0'])('accepts IPv4 %s', (value) => {
    expect(isIpv4(value)).toBe(true)
  })
  it.each(['10.0.0', '256.1.1.1', '10.0.0.01', '10.0.0.1 ', 'a.b.c.d', ''])(
    'rejects IPv4 %s',
    (value) => {
      expect(isIpv4(value)).toBe(false)
    },
  )
  it.each(['2001:db8::1', '::1', 'fe80::1:2:3:4', '2001:db8:0:0:0:0:0:1', '::ffff:192.0.2.1'])(
    'accepts IPv6 %s',
    (value) => {
      expect(isIpv6(value)).toBe(true)
    },
  )
  it.each(['2001:db8:::1', '2001:db8::1::2', '12345::', '1:2:3:4:5:6:7:8:9', 'gggg::1'])(
    'rejects IPv6 %s',
    (value) => {
      expect(isIpv6(value)).toBe(false)
    },
  )
  it('checks any family', () => {
    expect(isIpAddress('10.0.0.1')).toBe(true)
    expect(isIpAddress('2001:db8::1')).toBe(true)
    expect(isIpAddress('core1')).toBe(false)
  })
})

describe('CIDR', () => {
  it.each(['10.0.0.0/16', '10.255.0.0/24', '0.0.0.0/0', '10.0.0.1/32', '2001:db8::/32'])(
    'accepts %s',
    (value) => {
      expect(isCidr(value)).toBe(true)
    },
  )
  it.each(['10.0.0.0', '10.0.0.0/33', '10.0.0.0/', '/24', '10.0.0.0/24/1', '2001:db8::/129'])(
    'rejects %s',
    (value) => {
      expect(isCidr(value)).toBe(false)
    },
  )
  it('tells whether an IPv4 address is in a network', () => {
    expect(ipv4InCidr('10.255.0.2', '10.255.0.0/24')).toBe(true)
    expect(ipv4InCidr('10.255.1.2', '10.255.0.0/24')).toBe(false)
    expect(ipv4InCidr('10.1.2.3', '10.1.2.0/31')).toBe(false)
    expect(ipv4InCidr('2001:db8::1', '2001:db8::/32')).toBeNull()
  })
})

describe('discovery form validation', () => {
  const valid = {
    seeds: ['10.255.0.2'],
    allowedSubnets: ['10.255.0.0/24'],
    credentialProfileIds: ['5e0c7a1d-0000-4000-8000-000000008001'],
  }

  it('accepts a complete form', () => {
    expect(validateDiscoveryForm(valid)).toEqual({})
  })

  it('reports every missing field', () => {
    expect(
      validateDiscoveryForm({ seeds: [], allowedSubnets: [], credentialProfileIds: [] }),
    ).toEqual({
      seeds: 'discovery.validation.seedsRequired',
      allowedSubnets: 'discovery.validation.subnetsRequired',
      credentialProfileIds: 'discovery.validation.profilesRequired',
    })
  })

  it('rejects malformed addresses and networks', () => {
    expect(validateDiscoveryForm({ ...valid, seeds: ['10.255.0.300'] }).seeds).toBe(
      'discovery.validation.seedInvalid',
    )
    expect(validateDiscoveryForm({ ...valid, allowedSubnets: ['10.255.0.0'] }).allowedSubnets).toBe(
      'discovery.validation.subnetInvalid',
    )
  })

  it('rejects a seed outside every allowed subnet', () => {
    expect(validateDiscoveryForm({ ...valid, seeds: ['192.0.2.1'] }).seeds).toBe(
      'discovery.validation.seedOutsideSubnets',
    )
    expect(
      validateDiscoveryForm({ ...valid, allowedSubnets: ['192.0.2.0/24', '10.255.0.0/24'] }),
    ).toEqual({})
  })
})

describe('tags', () => {
  it('splits pasted lists and drops duplicates', () => {
    expect(normalizeTags(['10.0.0.1, 10.0.0.2', '10.0.0.1,', ' 10.0.0.3 '])).toEqual([
      '10.0.0.1',
      '10.0.0.2',
      '10.0.0.3',
    ])
  })
})
