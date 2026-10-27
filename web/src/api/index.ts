import type { Api } from './api'
import { httpApi } from './http'
import { mockApi } from './mock/mockApi'

export const USE_MOCKS = (import.meta.env.VITE_USE_MOCKS ?? 'true') !== 'false'

export const api: Api = USE_MOCKS ? mockApi : httpApi

export { ApiError } from './client'
export type * from './types'
