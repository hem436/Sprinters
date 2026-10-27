import { useCallback, useState } from 'react'

const KEY = 'ka.session_id'

function newSessionId(): string {
  return `s-${Math.random().toString(36).slice(2, 10)}`
}

function read(): string {
  try {
    const existing = localStorage.getItem(KEY)
    if (existing) return existing
    const id = newSessionId()
    localStorage.setItem(KEY, id)
    return id
  } catch {
    return newSessionId()
  }
}

/** The chat has no login. A session id groups the turns of one conversation (contract 01 section 6). */
export function useSession(): { sessionId: string; reset: () => void } {
  const [sessionId, setSessionId] = useState(read)
  const reset = useCallback(() => {
    const id = newSessionId()
    try {
      localStorage.setItem(KEY, id)
    } catch {
      // Storage blocked: the new id lives only in memory.
    }
    setSessionId(id)
  }, [])
  return { sessionId, reset }
}
