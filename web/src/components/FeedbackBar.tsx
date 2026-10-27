import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '../api'

/** One-click feedback (FR-11). "Not helpful" opens an optional comment. One feedback per answer: 409 FEEDBACK_EXISTS. */
export function FeedbackBar({ queryId }: { queryId: string }) {
  const [asking, setAsking] = useState(false)
  const [comment, setComment] = useState('')
  const [sent, setSent] = useState<'saved' | 'exists' | null>(null)

  const mutation = useMutation({
    mutationFn: (helpful: boolean) => api.feedback({ query_id: queryId, helpful, comment: comment.trim() || undefined }),
    onSuccess: () => setSent('saved'),
    onError: (err) => {
      if (err instanceof ApiError && err.code === 'FEEDBACK_EXISTS') setSent('exists')
    },
  })

  if (sent) {
    return <p className="text-xs text-slate-500">{sent === 'exists' ? 'Feedback for this answer is already saved.' : 'Thank you. Your feedback is saved.'}</p>
  }

  const iconBtn =
    'inline-flex h-9 w-9 items-center justify-center rounded-full border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 disabled:opacity-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800'

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-1.5">
        <button type="button" className={iconBtn} aria-label="Helpful" title="Helpful" disabled={mutation.isLoading} onClick={() => mutation.mutate(true)}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M7 10v11H3V10h4zM7 10l4-8a3 3 0 0 1 3 3v4h6a2 2 0 0 1 2 2.3l-1.4 8A2 2 0 0 1 18.6 21H7" />
          </svg>
        </button>
        <button
          type="button"
          className={`${iconBtn} ${asking ? '!border-indigo-500 !text-indigo-600' : ''}`}
          aria-label="Not helpful"
          aria-expanded={asking}
          title="Not helpful"
          onClick={() => setAsking((a) => !a)}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M17 14V3h4v11h-4zM17 14l-4 8a3 3 0 0 1-3-3v-4H4a2 2 0 0 1-2-2.3l1.4-8A2 2 0 0 1 5.4 3H17" />
          </svg>
        </button>
      </div>
      {asking ? (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            mutation.mutate(false)
          }}
        >
          <input
            className="input min-w-0 flex-1 !rounded-full !py-1.5 text-xs"
            placeholder="What was missing? (optional)"
            aria-label="Feedback comment"
            maxLength={1000}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <button type="submit" className="btn-primary !rounded-full text-xs" disabled={mutation.isLoading}>
            {mutation.isLoading ? 'Sending' : 'Send feedback'}
          </button>
        </form>
      ) : null}
      {mutation.isError && !(mutation.error instanceof ApiError && mutation.error.code === 'FEEDBACK_EXISTS') ? (
        <p role="alert" className="text-xs text-rose-600">
          {(mutation.error as Error).message}
        </p>
      ) : null}
    </div>
  )
}
