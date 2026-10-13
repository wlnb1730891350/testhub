import request from '@/utils/api'

export const getOcrConfigs = () => request.get('/ocr/configs/')
export const createOcrConfig = (data) => request.post('/ocr/configs/', data)
export const updateOcrConfig = (id, data) => request.patch(`/ocr/configs/${id}/`, data)
export const deleteOcrConfig = (id) => request.delete(`/ocr/configs/${id}/`)
export const setDefaultOcrConfig = (id) => request.post(`/ocr/configs/${id}/set_default/`)
export const testOcrConfig = (id) => request.post(`/ocr/configs/${id}/test/`)
export const getOcrInstallation = () => request.get('/ocr/check-installation/')
