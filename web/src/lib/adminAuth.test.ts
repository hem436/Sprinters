import { createHash } from 'node:crypto'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { checkLogin, currentSession, endSession, loginRequired, resetLoginLimits, usingDefaultPassword } from './adminAuth'
import { sha256Hex } from './sha256'

const hash = (s: string) => createHash('sha256').update(s).digest('hex')

describe('sha256Hex', () => {
  it.each(['', 'abc', 'admin', 'pässwörd ₹ 日本', 'x'.repeat(55), 'y'.repeat(64), 'z'.repeat(1000)])('matches Node for %j', (text) => {
    expect(sha256Hex(text)).toBe(hash(text))
  })
})

describe('adminAuth', () => {
  beforeEach(() => {
    resetLoginLimits()
    sessionStorage.clear()
  })
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('uses the demo password when no hash is set, and no login with "off"', () => {
    expect(loginRequired()).toBe(true)
    expect(usingDefaultPassword()).toBe(true)
    expect(checkLogin({ username: 'admin', password: 'demo' })).toBe(true)
    vi.stubEnv('VITE_ADMIN_PASSWORD_SHA256', 'off')
    expect(loginRequired()).toBe(false)
  })

  it('a real hash replaces the demo password', () => {
    vi.stubEnv('VITE_ADMIN_PASSWORD_SHA256', hash('long-real-password'))
    expect(usingDefaultPassword()).toBe(false)
    expect(checkLogin({ username: 'admin', password: 'demo' })).toBe(false)
  })

  it('accepts only the right user name and password, and saves no password', () => {
    vi.stubEnv('VITE_ADMIN_USERNAME', 'ops')
    vi.stubEnv('VITE_ADMIN_PASSWORD_SHA256', hash('right'))
    expect(checkLogin({ username: 'admin', password: 'right' })).toBe(false)
    expect(checkLogin({ username: 'ops', password: 'wrong' })).toBe(false)
    expect(checkLogin({ username: 'ops', password: 'right' })).toBe(true)
    expect(currentSession()).toBe('ops')
    expect(sessionStorage.getItem('ka.admin')).not.toContain('right')
    endSession()
    expect(currentSession()).toBeNull()
  })

  it('ends a session after 8 hours, or when the password changes', () => {
    vi.stubEnv('VITE_ADMIN_PASSWORD_SHA256', hash('one'))
    const now = Date.now()
    expect(checkLogin({ username: 'admin', password: 'one' }, now)).toBe(true)
    expect(currentSession(now + 7 * 3600 * 1000)).toBe('admin')
    expect(currentSession(now + 9 * 3600 * 1000)).toBeNull()
    expect(checkLogin({ username: 'admin', password: 'one' }, now)).toBe(true)
    vi.stubEnv('VITE_ADMIN_PASSWORD_SHA256', hash('two'))
    expect(currentSession(now)).toBeNull()
  })

  it('locks for 30 seconds after 5 wrong tries, even for the right password', () => {
    vi.stubEnv('VITE_ADMIN_PASSWORD_SHA256', hash('ok'))
    const now = Date.now()
    for (let i = 0; i < 5; i++) checkLogin({ username: 'admin', password: 'bad' }, now)
    expect(checkLogin({ username: 'admin', password: 'ok' }, now + 1000)).toBe(false)
    expect(checkLogin({ username: 'admin', password: 'ok' }, now + 31_000)).toBe(true)
  })
})
