import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { api, ApiError } from '../api'

type Choice = 'helpful' | 'not_helpful'

/** Helpful / not helpful with an optional comment (FR-11). One feedback per answer: 409 FEEDBACK_EXISTS. */
export function FeedbackBar({ queryId }: { queryId: string }) {
  const [choice, setChoice] = useState<Choice | null>(null)
  const [comment, setComment] = useState('')
  const [sent, setSent] = useState(false)

  const mutation = useMutation({
    mutationFn: (c: Choice) => api.feedback({ query_id: queryId, helpful: c === 'helpful', comment: comment.trim() || undefined }),
    onSuccess: () => setSent(true),
    onError: (err) => {
      if (err instanceof ApiError && err.code === 'FEEDBACK_EXISTS') setSent(true)
    },
  })

  if (sent) {
    const already = mutation.error instanceof ApiError && mutation.error.code === 'FEEDBACK_EXISTS'
    return <p className="text-xs text-slate-500">{already ? 'Feedback for this answer is already saved.' : 'Thank you. Your feedback is saved.'}</p>
  }

  return (
    <div className="flex flex-col gap-2 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-slate-500">Was this helpful?</span>
        {(['helpful', 'not_helpful'] as Choice[]).map((c) => (
          <button
            key={c}
            type="button"
            aria-pressed={choice === c}
            onClick={() => setChoice(c)}
            className={`btn !px-2 !py-0.5 border ${
              choice === c ? 'border-indigo-500 bg-indigo-50 text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-200' : 'border-slate-300 dark:border-slate-700'
            }`}
          >
            {c === 'helpful' ? '👍 Helpful' : '👎 Not helpful'}
          </button>
        ))}
      </div>
      {choice ? (
        <form
          className="flex flex-wrap items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            mutation.mutate(choice)
          }}
        >
          <input
            className="input min-w-0 flex-1 !py-1 text-xs"
            placeholder="Comment (optional)"
            aria-label="Feedback comment"
            maxLength={1000}
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <button type="submit" className="btn-primary !py-1 text-xs" disabled={mutation.isLoading}>
            {mutation.isLoading ? 'Sending' : 'Send feedback'}
          </button>
        </form>
      ) : null}
      {mutation.isError && !(mutation.error instanceof ApiError && mutation.error.code === 'FEEDBACK_EXISTS') ? (
        <p role="alert" className="text-rose-600">
          {(mutation.error as Error).message}
        </p>
      ) : null}
    </div>
  )
}
