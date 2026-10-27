import type { StreamEvent } from './types'

// Server-sent events parser. EventSource cannot POST, so the stream is read with fetch and parsed here.

export interface SseParser {
  push(chunk: string): StreamEvent[]
}

export function createSseParser(): SseParser {
  let buffer = ''
  return {
    push(chunk: string) {
      buffer += chunk.replace(/\r\n/g, '\n')
      const events: StreamEvent[] = []
      let sep = buffer.indexOf('\n\n')
      while (sep !== -1) {
        const block = buffer.slice(0, sep)
        buffer = buffer.slice(sep + 2)
        const parsed = parseBlock(block)
        if (parsed) events.push(parsed)
        sep = buffer.indexOf('\n\n')
      }
      return events
    },
  }
}

function parseBlock(block: string): StreamEvent | null {
  let event = 'message'
  const data: string[] = []
  for (const line of block.split('\n')) {
    if (line.startsWith(':')) continue
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''))
  }
  if (data.length === 0) return null
  try {
    return { event, data: JSON.parse(data.join('\n')) } as StreamEvent
  } catch {
    return null
  }
}
