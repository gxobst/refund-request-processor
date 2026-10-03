import { apiClient } from './apiClient'
import type {
  ExportSchedule,
  CreateExportSchedulePayload,
  UpdateExportSchedulePayload,
  ExportTriggerResponse,
} from '../types/api'

/**
 * Fetches all recurring export schedules.
 */
export async function fetchExportSchedules(): Promise<ExportSchedule[]> {
  return apiClient.get<ExportSchedule[]>('/v1/refunds/export/schedules')
}

/**
 * Creates a new recurring export schedule.
 */
export async function createExportSchedule(
  payload: CreateExportSchedulePayload
): Promise<ExportSchedule> {
  return apiClient.post<ExportSchedule>('/v1/refunds/export/schedules', payload)
}

/**
 * Updates an existing export schedule.
 */
export async function updateExportSchedule(
  scheduleId: string,
  payload: UpdateExportSchedulePayload
): Promise<ExportSchedule> {
  return apiClient.put<ExportSchedule>(`/v1/refunds/export/schedules/${scheduleId}`, payload)
}

/**
 * Deletes an export schedule.
 */
export async function deleteExportSchedule(scheduleId: string): Promise<void> {
  return apiClient.delete<void>(`/v1/refunds/export/schedules/${scheduleId}`)
}

/**
 * Manually triggers immediate execution and email delivery for an export schedule.
 */
export async function triggerExportSchedule(
  scheduleId: string
): Promise<ExportTriggerResponse> {
  return apiClient.post<ExportTriggerResponse>(
    `/v1/refunds/export/schedules/${scheduleId}/trigger`
  )
}

export const scheduleExportService = {
  fetchExportSchedules,
  createExportSchedule,
  updateExportSchedule,
  deleteExportSchedule,
  triggerExportSchedule,
}
