import { describe, expect, it } from 'vitest'
import { createSseParser } from './sse'

describe('SSE parser', () => {
  it('parses events split across chunks', () => {
    const p = createSseParser()
    expect(p.push('event: status\ndata: {"stage":"rer')).toEqual([])
    const events = p.push('ank"}\n\nevent: token\ndata: {"text":"Hi "}\n\n: keep-alive\n\nevent: done\r\ndata: {"query_id":"Q1"}\r\n\r\n')
    expect(events).toEqual([
      { event: 'status', data: { stage: 'rerank' } },
      { event: 'token', data: { text: 'Hi ' } },
      { event: 'done', data: { query_id: 'Q1' } },
    ])
  })
  it('skips a block with bad JSON', () => {
    expect(createSseParser().push('event: token\ndata: {oops\n\n')).toEqual([])
  })
})
