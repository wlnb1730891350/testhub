import request from '@/utils/api'

export function getPerformanceStats() {
  return request.get('/performance-testing/dashboard/stats/')
}

export function getJMeterHealth() {
  return request.get('/performance-testing/dashboard/jmeter-health/')
}

export function getPerformanceProjects(params) {
  return request.get('/performance-testing/projects/', { params })
}

export function createPerformanceProject(data) {
  return request.post('/performance-testing/projects/', data)
}

export function updatePerformanceProject(id, data) {
  return request.patch(`/performance-testing/projects/${id}/`, data)
}

export function deletePerformanceProject(id) {
  return request.delete(`/performance-testing/projects/${id}/`)
}

export function createPerformanceDataset(data) {
  return request.post('/performance-testing/datasets/', data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function getPerformanceScripts(params) {
  return request.get('/performance-testing/scripts/', { params })
}

export function getPerformanceScript(id) {
  return request.get(`/performance-testing/scripts/${id}/`)
}

export function createPerformanceScript(data) {
  return request.post('/performance-testing/scripts/', data)
}

export function updatePerformanceScript(id, data) {
  return request.patch(`/performance-testing/scripts/${id}/`, data)
}

export function uploadScriptJmx(id, data) {
  return request.post(`/performance-testing/scripts/${id}/upload-jmx/`, data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function deletePerformanceScript(id) {
  return request.delete(`/performance-testing/scripts/${id}/`)
}

export function getDefaultPerformanceConfig(params) {
  return request.get('/performance-testing/scripts/default-config/', { params })
}

export function executePerformanceScript(id) {
  return request.post(`/performance-testing/scripts/${id}/execute/`)
}

export function importJmxPreview(data) {
  return request.post('/performance-testing/import/preview/', data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function importJmxConfirm(data) {
  return request.post('/performance-testing/import/confirm/', data, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function getPerformanceExecutions(params) {
  return request.get('/performance-testing/executions/', { params })
}

export function getPerformanceExecution(id) {
  return request.get(`/performance-testing/executions/${id}/`)
}

export function getExecutionRealtimeReport(id, params) {
  return request.get(`/performance-testing/executions/${id}/realtime-report/`, { params })
}

export function stopPerformanceExecution(id) {
  return request.post(`/performance-testing/executions/${id}/stop/`)
}

export function downloadExecutionJtl(id) {
  return request.get(`/performance-testing/executions/${id}/download-jtl/`, { responseType: 'blob' })
}

export function downloadExecutionJmx(id) {
  return request.get(`/performance-testing/executions/${id}/download-jmx/`, { responseType: 'blob' })
}

export function exportScriptJmx(id) {
  return request.get(`/performance-testing/scripts/${id}/export-jmx/`, { responseType: 'blob' })
}

export function exportCurrentScriptJmx(data) {
  return request.post('/performance-testing/scripts/export-jmx/', data, { responseType: 'blob' })
}

export function getSchedulerSchedules(params) {
  return request.get('/scheduler/schedules/', { params })
}

export function createSchedulerSchedule(data) {
  return request.post('/scheduler/schedules/', data)
}

export function executeSchedulerSchedule(id) {
  return request.post(`/scheduler/schedules/${id}/execute/`)
}

export function deleteSchedulerSchedule(id) {
  return request.delete(`/scheduler/schedules/${id}/`)
}
