import type { Credentials } from './client'
import type {
  AuthMe,
  ConfigId,
  DocumentDetail,
  DocumentRow,
  DrillDown,
  EvalRun,
  FeedbackRequest,
  FinTable,
  Health,
  Job,
  LibraryDocument,
  LibraryPage,
  MetricMapRow,
  MetricsFilters,
  MetricsSummary,
  Page,
  PageDetail,
  QueryListRow,
  QueryRequest,
  QueryResponse,
  ReviewDecision,
  StreamEvent,
  ToolInfo,
  ToolTryResult,
  UploadMetadata,
} from './types'

/** One method per endpoint of contract 05. The real and the mock version both implement it. */
export interface Api {
  health(): Promise<Health>
  /** GET /auth/me. With `creds`, checks them; without, uses the saved login. 401 when a login is needed. */
  authMe(creds?: Credentials): Promise<AuthMe>

  query(req: QueryRequest, signal?: AbortSignal): Promise<QueryResponse>
  /** Calls onEvent for each SSE event. Resolves with the final QueryResponse from the done event. */
  queryStream(req: QueryRequest, onEvent: (e: StreamEvent) => void, signal?: AbortSignal): Promise<QueryResponse>
  feedback(req: FeedbackRequest): Promise<void>
  reviewQuery(queryId: string, comment: string): Promise<void>

  metricsSummary(filters: MetricsFilters): Promise<MetricsSummary>
  listQueries(filters: MetricsFilters & { page?: number }): Promise<Page<QueryListRow>>
  getQuery(queryId: string): Promise<DrillDown>

  startEvalRun(configId: ConfigId, caseIds?: string[]): Promise<{ run_id: string }>
  listEvalRuns(): Promise<EvalRun[]>
  getEvalRun(runId: string): Promise<EvalRun>

  uploadDocument(file: File, meta: UploadMetadata): Promise<{ document_id: string; job_id: string; status: string }>
  listDocuments(filters?: { category?: string; status?: string }): Promise<DocumentRow[]>
  getDocument(documentId: string): Promise<DocumentDetail>
  getPage(documentId: string, page: number): Promise<PageDetail>
  pageImageUrl(documentId: string, page: number): string
  reviewPage(documentId: string, page: number, decision: ReviewDecision, comment?: string): Promise<PageDetail>
  reindexDocument(documentId: string): Promise<void>
  deleteDocument(documentId: string): Promise<void>
  listJobs(): Promise<Job[]>

  listTables(documentId: string): Promise<FinTable[]>
  reviewTable(tableId: string, decision: ReviewDecision, comment?: string): Promise<FinTable>
  listMetricMap(pending?: boolean): Promise<MetricMapRow[]>
  approveMapping(lineLabel: string, metric: string): Promise<MetricMapRow>

  listLibrary(category?: string): Promise<LibraryDocument[]>
  /** 404 when the page is not in the library, for example while it waits for review. */
  getLibraryPage(documentId: string, page: number): Promise<LibraryPage>

  listTools(): Promise<ToolInfo[]>
  tryTool(name: string, args: Record<string, unknown>): Promise<ToolTryResult>
}
