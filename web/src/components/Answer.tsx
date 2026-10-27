import ReactMarkdown from 'react-markdown'

/** Renders answer markdown. Citation markers like [E1] or [T1] become small labels. */
export function Answer({ markdown }: { markdown: string }) {
  const withMarkers = markdown.replace(/\[((?:E|T)\d+)\](?!\()/g, '[$1](#cite-$1)')
  return (
    <div className="prose-answer text-sm leading-relaxed">
      <ReactMarkdown
        skipHtml
        components={{
          a: ({ href, children }) =>
            href?.startsWith('#cite-') ? (
              <sup className="mx-0.5 rounded bg-slate-200 px-1 text-[10px] font-semibold text-slate-700 dark:bg-slate-700 dark:text-slate-200">{children}</sup>
            ) : (
              <a href={href} target="_blank" rel="noreferrer" className="text-indigo-600 underline">
                {children}
              </a>
            ),
        }}
      >
        {withMarkers}
      </ReactMarkdown>
    </div>
  )
}
