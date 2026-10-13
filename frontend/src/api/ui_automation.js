import request from '@/utils/api'

// 浠〃鐩樼浉鍏矨PI
export function getDashboardStats() {
  return request({
    url: '/ui-automation/dashboard/stats/',
    method: 'get'
  })
}

// 鑾峰彇椤圭洰鍒楄〃 (alias for getUiProjects)
export const getProjects = getUiProjects

// UI椤圭洰鐩稿叧API

// 鑾峰彇UI椤圭洰鍒楄〃
export function getUiProjects(params) {
  return request({
    url: '/ui-automation/projects/',
    method: 'get',
    params
  })
}

// 鍒涘缓UI椤圭洰
export function createUiProject(data) {
  return request({
    url: '/ui-automation/projects/',
    method: 'post',
    data
  })
}

// 鑾峰彇UI椤圭洰璇︽儏
export function getUiProjectDetail(id) {
  return request({
    url: `/ui-automation/projects/${id}/`,
    method: 'get'
  })
}

// 鏇存柊UI椤圭洰
export function updateUiProject(id, data) {
  return request({
    url: `/ui-automation/projects/${id}/`,
    method: 'patch',
    data
  })
}

// 鍒犻櫎UI椤圭洰
export function deleteUiProject(id) {
  return request({
    url: `/ui-automation/projects/${id}/`,
    method: 'delete'
  })
}

// 瀹氫綅绛栫暐鐩稿叧API

// 鑾峰彇瀹氫綅绛栫暐鍒楄〃
export function getLocatorStrategies(params) {
  return request({
    url: '/ui-automation/locator-strategies/',
    method: 'get',
    params
  })
}

// 鍒涘缓瀹氫綅绛栫暐
export function createLocatorStrategy(data) {
  return request({
    url: '/ui-automation/locator-strategies/',
    method: 'post',
    data
  })
}

// UI鍏冪礌鐩稿叧API

// 鑾峰彇UI鍏冪礌鍒楄〃
export function getElements(params) {
  return request({
    url: '/ui-automation/elements/',
    method: 'get',
    params
  })
}

// 鍒涘缓UI鍏冪礌
export function createElement(data) {
  return request({
    url: '/ui-automation/elements/',
    method: 'post',
    data
  })
}

// 鑾峰彇UI鍏冪礌璇︽儏
export function getElementDetail(id) {
  return request({
    url: `/ui-automation/elements/${id}/`,
    method: 'get'
  })
}

// 鏇存柊UI鍏冪礌
export function updateElement(id, data) {
  return request({
    url: `/ui-automation/elements/${id}/`,
    method: 'patch',
    data
  })
}

// 鍒犻櫎UI鍏冪礌
export function deleteElement(id) {
  return request({
    url: `/ui-automation/elements/${id}/`,
    method: 'delete'
  })
}

// 娴嬭瘯鑴氭湰鐩稿叧API

// 鑾峰彇娴嬭瘯鑴氭湰鍒楄〃
export function getTestScripts(params) {
  return request({
    url: '/ui-automation/test-scripts/',
    method: 'get',
    params
  })
}

// 鍒涘缓娴嬭瘯鑴氭湰
export function createTestScript(data) {
  return request({
    url: '/ui-automation/test-scripts/',
    method: 'post',
    data
  })
}

// 鑾峰彇娴嬭瘯鑴氭湰璇︽儏
export function getTestScriptDetail(id) {
  return request({
    url: `/ui-automation/test-scripts/${id}/`,
    method: 'get'
  })
}

// 鏇存柊娴嬭瘯鑴氭湰
export function updateTestScript(id, data) {
  return request({
    url: `/ui-automation/test-scripts/${id}/`,
    method: 'patch',
    data
  })
}

// 鍒犻櫎娴嬭瘯鑴氭湰
export function deleteTestScript(id) {
  return request({
    url: `/ui-automation/test-scripts/${id}/`,
    method: 'delete'
  })
}

// 娴嬭瘯濂椾欢鐩稿叧API

// 鑾峰彇娴嬭瘯濂椾欢鍒楄〃
export function getTestSuites(params) {
  return request({
    url: '/ui-automation/test-suites/',
    method: 'get',
    params
  })
}

// 鍒涘缓娴嬭瘯濂椾欢
export function createTestSuite(data) {
  return request({
    url: '/ui-automation/test-suites/',
    method: 'post',
    data
  })
}

// 鑾峰彇娴嬭瘯濂椾欢璇︽儏
export function getTestSuiteDetail(id) {
  return request({
    url: `/ui-automation/test-suites/${id}/`,
    method: 'get'
  })
}

// 鏇存柊娴嬭瘯濂椾欢
export function updateTestSuite(id, data) {
  return request({
    url: `/ui-automation/test-suites/${id}/`,
    method: 'patch',
    data
  })
}

// 鍒犻櫎娴嬭瘯濂椾欢
export function deleteTestSuite(id) {
  return request({
    url: `/ui-automation/test-suites/${id}/`,
    method: 'delete'
  })
}

// 鑾峰彇娴嬭瘯濂椾欢涓殑娴嬭瘯鐢ㄤ緥
export function getTestSuiteTestCases(id) {
  return request({
    url: `/ui-automation/test-suites/${id}/test_cases/`,
    method: 'get'
  })
}

// 鍚戞祴璇曞浠舵坊鍔犳祴璇曠敤渚?
export function addTestCaseToTestSuite(id, data) {
  return request({
    url: `/ui-automation/test-suites/${id}/add_test_case/`,
    method: 'post',
    data
  })
}

// 浠庢祴璇曞浠剁Щ闄ゆ祴璇曠敤渚?
export function removeTestCaseFromTestSuite(suiteId, testCaseId) {
  return request({
    url: `/ui-automation/test-suites/${suiteId}/remove_test_case/`,
    method: 'delete',
    data: { test_case_id: testCaseId }
  })
}

// 鏇存柊娴嬭瘯濂椾欢涓祴璇曠敤渚嬬殑椤哄簭
export function updateTestCaseOrder(suiteId, testCaseOrders) {
  return request({
    url: `/ui-automation/test-suites/${suiteId}/update_test_case_order/`,
    method: 'post',
    data: { test_case_orders: testCaseOrders }
  })
}

// 杩愯娴嬭瘯濂椾欢
export function runTestSuite(suiteId, data) {
  return request({
    url: `/ui-automation/test-suites/${suiteId}/run_suite/`,
    method: 'post',
    data,
    timeout: 600000  // 10鍒嗛挓瓒呮椂锛屽洜涓哄浠跺彲鑳藉寘鍚涓祴璇曠敤渚?
  })
}

// 娴嬭瘯鎵ц鐩稿叧API

// 鑾峰彇娴嬭瘯鎵ц鍒楄〃
export function getTestExecutions(params) {
  return request({
    url: '/ui-automation/test-executions/',
    method: 'get',
    params
  })
}

// 鍒涘缓娴嬭瘯鎵ц
export function createTestExecution(data) {
  return request({
    url: '/ui-automation/test-executions/',
    method: 'post',
    data
  })
}

// 鑾峰彇娴嬭瘯鎵ц璇︽儏
export function getTestExecutionDetail(id) {
  return request({
    url: `/ui-automation/test-executions/${id}/`,
    method: 'get'
  })
}

// 鍒犻櫎娴嬭瘯鎵ц璁板綍
export function deleteTestExecution(id) {
  return request({
    url: `/ui-automation/test-executions/${id}/`,
    method: 'delete'
  })
}

// 杩愯娴嬭瘯鎵ц
export function runTestExecution(id) {
  return request({
    url: `/ui-automation/test-executions/${id}/run/`,
    method: 'post'
  })
}

// 涓娴嬭瘯鎵ц
export function abortTestExecution(id) {
  return request({
    url: `/ui-automation/test-executions/${id}/abort/`,
    method: 'post'
  })
}

// 娴嬭瘯鐜鐩稿叧API

// 鑾峰彇娴嬭瘯鐜鍒楄〃
export function getTestEnvironments(params) {
  return request({
    url: '/ui-automation/test-environments/',
    method: 'get',
    params
  })
}

// 鍒涘缓娴嬭瘯鐜
export function createTestEnvironment(data) {
  return request({
    url: '/ui-automation/test-environments/',
    method: 'post',
    data
  })
}

// 鑾峰彇娴嬭瘯鐜璇︽儏
export function getTestEnvironmentDetail(id) {
  return request({
    url: `/ui-automation/test-environments/${id}/`,
    method: 'get'
  })
}

// 鏇存柊娴嬭瘯鐜
export function updateTestEnvironment(id, data) {
  return request({
    url: `/ui-automation/test-environments/${id}/`,
    method: 'patch',
    data
  })
}

// 鍒犻櫎娴嬭瘯鐜
export function deleteTestEnvironment(id) {
  return request({
    url: `/ui-automation/test-environments/${id}/`,
    method: 'delete'
  })
}

// 鎴浘鐩稿叧API

// 鑾峰彇鎴浘鍒楄〃
export function getScreenshots(params) {
  return request({
    url: '/ui-automation/screenshots/',
    method: 'get',
    params
  })
}

// 鍒涘缓鎴浘
export function createScreenshot(data) {
  return request({
    url: '/ui-automation/screenshots/',
    method: 'post',
    data
  })
}

// 鑾峰彇鎴浘璇︽儏
export function getScreenshotDetail(id) {
  return request({
    url: `/ui-automation/screenshots/${id}/`,
    method: 'get'
  })
}

// 鍒犻櫎鎴浘
export function deleteScreenshot(id) {
  return request({
    url: `/ui-automation/screenshots/${id}/`,
    method: 'delete'
  })
}

// ============ 鏂板鍔熻兘API ============

// 鍏冪礌鍒嗙粍鐩稿叧API
export function getElementGroups(params) {
  return request({
    url: '/ui-automation/element-groups/',
    method: 'get',
    params
  })
}

export function createElementGroup(data) {
  return request({
    url: '/ui-automation/element-groups/',
    method: 'post',
    data
  })
}

export function getElementGroupDetail(id) {
  return request({
    url: `/ui-automation/element-groups/${id}/`,
    method: 'get'
  })
}

export function updateElementGroup(id, data) {
  return request({
    url: `/ui-automation/element-groups/${id}/`,
    method: 'patch',
    data
  })
}

export function deleteElementGroup(id) {
  return request({
    url: `/ui-automation/element-groups/${id}/`,
    method: 'delete'
  })
}

export function getElementGroupTree(params) {
  return request({
    url: '/ui-automation/element-groups/tree/',
    method: 'get',
    params
  })
}

// 鍏冪礌澧炲己鍔熻兘API
export function validateElementLocator(id) {
  return request({
    url: `/ui-automation/elements/${id}/validate_locator/`,
    method: 'post'
  })
}

export function getElementUsages(id) {
  return request({
    url: `/ui-automation/elements/${id}/usages/`,
    method: 'get'
  })
}

export function getElementTree(params) {
  return request({
    url: '/ui-automation/elements/tree/',
    method: 'get',
    params
  })
}

export function addBackupLocator(id, data) {
  return request({
    url: `/ui-automation/elements/${id}/add_backup_locator/`,
    method: 'post',
    data
  })
}

export function generateElementSuggestions(id) {
  return request({
    url: `/ui-automation/elements/${id}/generate_suggestions/`,
    method: 'post'
  })
}

// 椤甸潰瀵硅薄鐩稿叧API
export function getPageObjects(params) {
  return request({
    url: '/ui-automation/page-objects/',
    method: 'get',
    params
  })
}

export function createPageObject(data) {
  return request({
    url: '/ui-automation/page-objects/',
    method: 'post',
    data
  })
}

export function getPageObjectDetail(id) {
  return request({
    url: `/ui-automation/page-objects/${id}/`,
    method: 'get'
  })
}

export function updatePageObject(id, data) {
  return request({
    url: `/ui-automation/page-objects/${id}/`,
    method: 'patch',
    data
  })
}

export function deletePageObject(id) {
  return request({
    url: `/ui-automation/page-objects/${id}/`,
    method: 'delete'
  })
}

export function generatePageObjectCode(id, data) {
  return request({
    url: `/ui-automation/page-objects/${id}/generate_code/`,
    method: 'post',
    data
  })
}

export function addElementToPageObject(id, data) {
  return request({
    url: `/ui-automation/page-objects/${id}/add_element/`,
    method: 'post',
    data
  })
}

export function getPageObjectElements(id) {
  return request({
    url: `/ui-automation/page-objects/${id}/elements/`,
    method: 'get'
  })
}

// 椤甸潰瀵硅薄鍏冪礌鍏宠仈API
export function getPageObjectElementDetails(params) {
  return request({
    url: '/ui-automation/page-object-elements/',
    method: 'get',
    params
  })
}

export function createPageObjectElement(data) {
  return request({
    url: '/ui-automation/page-object-elements/',
    method: 'post',
    data
  })
}

export function updatePageObjectElement(id, data) {
  return request({
    url: `/ui-automation/page-object-elements/${id}/`,
    method: 'patch',
    data
  })
}

export function deletePageObjectElement(id) {
  return request({
    url: `/ui-automation/page-object-elements/${id}/`,
    method: 'delete'
  })
}

// 鑴氭湰姝ラ鐩稿叧API
export function getScriptSteps(params) {
  return request({
    url: '/ui-automation/script-steps/',
    method: 'get',
    params
  })
}

export function createScriptStep(data) {
  return request({
    url: '/ui-automation/script-steps/',
    method: 'post',
    data
  })
}

export function batchCreateScriptSteps(data) {
  return request({
    url: '/ui-automation/script-steps/batch_create/',
    method: 'post',
    data
  })
}

export function updateScriptStep(id, data) {
  return request({
    url: `/ui-automation/script-steps/${id}/`,
    method: 'patch',
    data
  })
}

export function deleteScriptStep(id) {
  return request({
    url: `/ui-automation/script-steps/${id}/`,
    method: 'delete'
  })
}

// 鑴氭湰鍏冪礌浣跨敤鎯呭喌API
export function getScriptElementUsages(params) {
  return request({
    url: '/ui-automation/script-element-usages/',
    method: 'get',
    params
  })
}

export function analyzeScriptElements(data) {
  return request({
    url: '/ui-automation/script-element-usages/analyze_script/',
    method: 'post',
    data
  })
}

export function createScriptElementUsage(data) {
  return request({
    url: '/ui-automation/script-element-usages/',
    method: 'post',
    data
  })
}

export function updateScriptElementUsage(id, data) {
  return request({
    url: `/ui-automation/script-element-usages/${id}/`,
    method: 'patch',
    data
  })
}

export function deleteScriptElementUsage(id) {
  return request({
    url: `/ui-automation/script-element-usages/${id}/`,
    method: 'delete'
  })
}

// 娴嬭瘯鐢ㄤ緥鐩稿叧API

// 鑾峰彇娴嬭瘯鐢ㄤ緥鍒楄〃
export function getTestCases(params) {
  return request({
    url: '/ui-automation/test-cases/',
    method: 'get',
    params
  })
}

// 鍒涘缓娴嬭瘯鐢ㄤ緥
export function createTestCase(data) {
  return request({
    url: '/ui-automation/test-cases/',
    method: 'post',
    data
  })
}

// 鑾峰彇娴嬭瘯鐢ㄤ緥璇︽儏
export function getTestCaseDetail(id) {
  return request({
    url: `/ui-automation/test-cases/${id}/`,
    method: 'get'
  })
}

// 鏇存柊娴嬭瘯鐢ㄤ緥
export function updateTestCase(id, data) {
  return request({
    url: `/ui-automation/test-cases/${id}/`,
    method: 'patch',
    data
  })
}

// 鍒犻櫎娴嬭瘯鐢ㄤ緥
export function deleteTestCase(id) {
  return request({
    url: `/ui-automation/test-cases/${id}/`,
    method: 'delete'
  })
}

// 杩愯娴嬭瘯鐢ㄤ緥
export function runTestCase(testCaseId, data) {
  return request({
    url: `/ui-automation/test-cases/${testCaseId}/run/`,
    method: 'post',
    data,
    timeout: 300000  // 5鍒嗛挓瓒呮椂锛屽洜涓烘祴璇曟墽琛岄渶瑕佸惎鍔ㄦ祻瑙堝櫒鍜屾墽琛屽涓楠?
  })
}

// AI鎅鸿兘鎵ц屸祴璇曠敤渚?
export function runAITestCase(testCaseId, data) {
  return request({
    url: `/ui-automation/test-cases/${testCaseId}/run_ai/`,
    method: 'post',
    data: data || {},
    timeout: 600000
  })
}

// 审核AI执行结果
export function acceptAILocators(executionId) {
  return request({
    url: `/ui-automation/test-cases/accept_ai_locators/`,
    method: 'post',
    data: { execution_id: executionId }
  })
}

// 澶嶅埗娴嬭瘯鐢ㄤ緥
export function copyTestCase(id) {
  return request({
    url: `/ui-automation/test-cases/${id}/copy_case/`,
    method: 'post'
  })
}

// 鑾峰彇娴嬭瘯鐢ㄤ緥鎵ц鍘嗗彶
export function getTestCaseExecutions(params) {
  return request({
    url: '/ui-automation/test-case-executions/',
    method: 'get',
    params
  })
}

// 鍒犻櫎娴嬭瘯鐢ㄤ緥鎵ц璁板綍
export function deleteTestCaseExecution(id) {
  return request({
    url: `/ui-automation/test-case-executions/${id}/`,
    method: 'delete'
  })
}

// 鎵归噺鍒犻櫎娴嬭瘯鐢ㄤ緥鎵ц璁板綍
export function batchDeleteTestCaseExecutions(ids) {
  return request({
    url: '/ui-automation/test-case-executions/batch-delete/',
    method: 'post',
    data: { ids }
  })
}

// 鎵归噺杩愯娴嬭瘯鐢ㄤ緥
export function batchRunTestCases(data) {
  return request({
    url: '/ui-automation/test-cases/batch-run/',
    method: 'post',
    data
  })
}

// 鎿嶄綔璁板綍鐩稿叧API

// 鑾峰彇鎿嶄綔璁板綍鍒楄〃
export function getOperationRecords(params) {
  return request({
    url: '/ui-automation/operation-records/',
    method: 'get',
    params
  })
}

// 鍒涘缓鎿嶄綔璁板綍
export function createOperationRecord(data) {
  return request({
    url: '/ui-automation/operation-records/',
    method: 'post',
    data
  })
}

// ==================== 瀹氭椂浠诲姟鐩稿叧API ====================

// 鑾峰彇瀹氭椂浠诲姟鍒楄〃
export function getScheduledTasks(params) {
  return request({
    url: '/ui-automation/scheduled-tasks/',
    method: 'get',
    params
  })
}

// 鍒涘缓瀹氭椂浠诲姟
export function createScheduledTask(data) {
  return request({
    url: '/ui-automation/scheduled-tasks/',
    method: 'post',
    data
  })
}

// 鑾峰彇瀹氭椂浠诲姟璇︽儏
export function getScheduledTaskDetail(id) {
  return request({
    url: `/ui-automation/scheduled-tasks/${id}/`,
    method: 'get'
  })
}

// 鏇存柊瀹氭椂浠诲姟
export function updateScheduledTask(id, data) {
  return request({
    url: `/ui-automation/scheduled-tasks/${id}/`,
    method: 'patch',
    data
  })
}

// 鍒犻櫎瀹氭椂浠诲姟
export function deleteScheduledTask(id) {
  return request({
    url: `/ui-automation/scheduled-tasks/${id}/`,
    method: 'delete'
  })
}

// 鏆傚仠瀹氭椂浠诲姟
export function pauseScheduledTask(id) {
  return request({
    url: `/ui-automation/scheduled-tasks/${id}/pause/`,
    method: 'post'
  })
}

// 鎭㈠瀹氭椂浠诲姟
export function resumeScheduledTask(id) {
  return request({
    url: `/ui-automation/scheduled-tasks/${id}/resume/`,
    method: 'post'
  })
}

// 绔嬪嵆杩愯浠诲姟
export function runScheduledTask(id) {
  return request({
    url: `/ui-automation/scheduled-tasks/${id}/run_now/`,
    method: 'post'
  })
}

// ==================== 閫氱煡閰嶇疆鐩稿叧API ====================

// 鑾峰彇閫氱煡閰嶇疆鍒楄〃
export function getNotificationConfigs(params) {
  return request({
    url: '/ui-automation/notification-configs/',
    method: 'get',
    params
  })
}

// 鍒涘缓閫氱煡閰嶇疆
export function createNotificationConfig(data) {
  return request({
    url: '/ui-automation/notification-configs/',
    method: 'post',
    data
  })
}

// 鑾峰彇閫氱煡閰嶇疆璇︽儏
export function getNotificationConfigDetail(id) {
  return request({
    url: `/ui-automation/notification-configs/${id}/`,
    method: 'get'
  })
}

// 鏇存柊閫氱煡閰嶇疆
export function updateNotificationConfig(id, data) {
  return request({
    url: `/ui-automation/notification-configs/${id}/`,
    method: 'patch',
    data
  })
}

// 鍒犻櫎閫氱煡閰嶇疆
export function deleteNotificationConfig(id) {
  return request({
    url: `/ui-automation/notification-configs/${id}/`,
    method: 'delete'
  })
}

// 璁剧疆涓洪粯璁ら厤缃?
export function setDefaultNotificationConfig(id) {
  return request({
    url: `/ui-automation/notification-configs/${id}/set_default/`,
    method: 'post'
  })
}

// ==================== 閫氱煡鏃ュ織鐩稿叧API ====================

// 鑾峰彇閫氱煡鏃ュ織鍒楄〃
export function getNotificationLogs(params) {
  return request({
    url: '/ui-automation/notification-logs/',
    method: 'get',
    params
  })
}

// 閲嶈瘯鍙戦€侀€氱煡
export function retryNotification(id) {
  return request({
    url: `/ui-automation/notification-logs/${id}/retry/`,
    method: 'post'
  })
}

// ==================== 浠诲姟閫氱煡璁剧疆鐩稿叧API ====================

// 鑾峰彇浠诲姟閫氱煡璁剧疆
export function getTaskNotificationSettings(params) {
  return request({
    url: '/ui-automation/task-notification-settings/',
    method: 'get',
    params
  })
}

// 鍒涘缓浠诲姟閫氱煡璁剧疆
export function createTaskNotificationSetting(data) {
  return request({
    url: '/ui-automation/task-notification-settings/',
    method: 'post',
    data
  })
}

// 鏇存柊浠诲姟閫氱煡璁剧疆
export function updateTaskNotificationSetting(id, data) {
  return request({
    url: `/ui-automation/task-notification-settings/${id}/`,
    method: 'patch',
    data
  })
}

// 鑾峰彇鐢ㄦ埛鍒楄〃锛堝鐢ㄦ帴鍙ｆ祴璇曠殑鐢ㄦ埛鎺ュ彛锛?
export function getUiUsers(params) {
  return request({
    url: '/api-testing/users/',
    method: 'get',
    params
  })
}

// ==================== AI 鏅鸿兘妯″紡鐩稿叧API ====================

// 鑾峰彇 AI 鐢ㄤ緥鍒楄〃
export function getAICases(params) {
  return request({
    url: '/ui-automation/ai-cases/',
    method: 'get',
    params
  })
}

export function getAICaseCategories(params) {
  return request({
    url: '/ui-automation/ai-case-categories/',
    method: 'get',
    params
  })
}

export function getDesktopAppProfiles(params) {
  return request({
    url: '/ui-automation/desktop-app-profiles/',
    method: 'get',
    params
  })
}

export function createDesktopAppProfile(data) {
  return request({
    url: '/ui-automation/desktop-app-profiles/',
    method: 'post',
    data
  })
}

export function updateDesktopAppProfile(id, data) {
  return request({
    url: `/ui-automation/desktop-app-profiles/${id}/`,
    method: 'patch',
    data
  })
}

export function deleteDesktopAppProfile(id) {
  return request({
    url: `/ui-automation/desktop-app-profiles/${id}/`,
    method: 'delete'
  })
}

export function createAICaseCategory(data) {
  return request({
    url: '/ui-automation/ai-case-categories/',
    method: 'post',
    data
  })
}

export function updateAICaseCategory(id, data) {
  return request({
    url: `/ui-automation/ai-case-categories/${id}/`,
    method: 'patch',
    data
  })
}

export function deleteAICaseCategory(id) {
  return request({
    url: `/ui-automation/ai-case-categories/${id}/`,
    method: 'delete'
  })
}

export function batchConfigureAICaseCategory(data) {
  return request({
    url: '/ui-automation/ai-cases/batch-category/',
    method: 'post',
    data
  })
}

// 鍒涘缓 AI 鐢ㄤ緥
export function createAICase(data) {
  return request({
    url: '/ui-automation/ai-cases/',
    method: 'post',
    data
  })
}

// 鑾峰彇 AI 鐢ㄤ緥璇︽儏
export function getAICaseDetail(id) {
  return request({
    url: `/ui-automation/ai-cases/${id}/`,
    method: 'get'
  })
}

// 鏇存柊 AI 鐢ㄤ緥
export function updateAICase(id, data) {
  return request({
    url: `/ui-automation/ai-cases/${id}/`,
    method: 'patch',
    data
  })
}

// 鍒犻櫎 AI 鐢ㄤ緥
export function deleteAICase(id) {
  return request({
    url: `/ui-automation/ai-cases/${id}/`,
    method: 'delete'
  })
}

// 杩愯 AI 鐢ㄤ緥
export function runAICase(id, data = {}) {
  return request({
    url: `/ui-automation/ai-cases/${id}/run/`,
    method: 'post',
    data
  })
}

// 鑾峰彇 AI 鎵ц璁板綍鍒楄〃
export function getAIExecutionRecords(params) {
  return request({
    url: '/ui-automation/ai-execution-records/',
    method: 'get',
    params
  })
}

export function getAIExecutionReportList(params) {
  return request({
    url: '/ui-automation/ai-execution-records/report-list/',
    method: 'get',
    params
  })
}

// 鑾峰彇 AI 鎵ц璁板綍璇︽儏
export function getAIExecutionRecordDetail(id) {
  return request({
    url: `/ui-automation/ai-execution-records/${id}/`,
    method: 'get'
  })
}

// 鎵ц涓存椂 AI 浠诲姟
export function runAdhocAITask(data) {
  return request({
    url: '/ui-automation/ai-execution-records/run_adhoc/',
    method: 'post',
    data
  })
}

// 鍋滄 AI 浠诲姟
export function stopAITask(id) {
  return request({
    url: `/ui-automation/ai-execution-records/${id}/stop/`,
    method: 'post'
  })
}

// 鎵归噺鍒犻櫎 AI 鎵ц璁板綍
export function batchDeleteAIExecutionRecords(ids, batchIds = []) {
  return request({
    url: '/ui-automation/ai-execution-records/batch_delete/',
    method: 'post',
    data: { ids, batch_ids: batchIds }
  })
}

// 鑾峰彇 AI 鎵ц鎶ュ憡
export function getAIExecutionReport(id, params = {}) {
  return request({
    url: `/ui-automation/ai-execution-records/${id}/report/`,
    method: 'get',
    params
  })
}

// 获取批量执行汇总报告
export function getAIBatchExecutionReport(batchId) {
  return request({
    url: '/ui-automation/ai-execution-records/batch-report/',
    method: 'get',
    params: { batch_id: batchId }
  })
}

// 瀵煎嚭 AI 鎵ц鎶ュ憡涓?PDF
export function exportAIExecutionReportPDF(id, params = {}) {
  return request({
    url: `/ui-automation/ai-execution-records/${id}/export-pdf/`,
    method: 'get',
    params,
    responseType: 'blob'
  })
}


// ===== ???? API =====

// ??????
export function startRecording(data) {
  return request({
    url: '/ui-automation/recording/',
    method: 'post',
    data
  })
}

// ????
export function stopRecording(sessionId) {
  return request({
    url: `/ui-automation/recording/${sessionId}/stop/`,
    method: 'post'
  })
}

// ??????
export function getRecordingActions(sessionId) {
  return request({
    url: '/ui-automation/recording/actions/',
    method: 'get',
    params: { session_id: sessionId }
  })
}

// ???????????????
export function sendRecordingActions(data) {
  return request({
    url: '/ui-automation/recording/actions/',
    method: 'post',
    data
  })
}

// ??????
export function checkRecordingStatus(sessionId) {
  return request({
    url: `/ui-automation/recording/${sessionId}/status-check/`,
    method: 'get'
  })
}

// ?????????
export function saveRecordingAsTestCase(sessionId, name, targetTestCaseId = null, options = {}) {
  return request({
    url: `/ui-automation/recording/${sessionId}/save-as-test-case/`,
    method: 'post',
    data: {
      name,
      project_id: options.projectId,
      target_test_case_id: targetTestCaseId,
      selected_action_indexes: options.selectedActionIndexes || []
    }
  })
}
export function runAIAssertion(data) {
  return request({
    url: '/ui-automation/ai-assertion/',
    method: 'post',
    data,
    timeout: 120000  // AI鏂█鍙兘闇€瑕佽緝闀挎椂闂?
  })
}

// ==================== Setup Templates ====================

// 获取前置模板列表
export function getSetupTemplates(params = {}) {
  return request({
    url: '/ui-automation/setup-templates/',
    method: 'get',
    params
  })
}

// 获取单个前置模板
export function getSetupTemplate(id) {
  return request({
    url: `/ui-automation/setup-templates/${id}/`,
    method: 'get'
  })
}

// 创建前置模板
export function createSetupTemplate(data) {
  return request({
    url: '/ui-automation/setup-templates/',
    method: 'post',
    data
  })
}

// 更新前置模板
export function updateSetupTemplate(id, data) {
  return request({
    url: `/ui-automation/setup-templates/${id}/`,
    method: 'put',
    data
  })
}

// 删除前置模板
export function deleteSetupTemplate(id) {
  return request({
    url: `/ui-automation/setup-templates/${id}/`,
    method: 'delete'
  })
}

// ==================== 语音输入 / 自然语言 AI ====================

// 语音转文字
export function speechTranscribe(formData) {
  return request({
    url: '/ui-automation/speech/transcribe/',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// 自然语言解析为步骤
export function speechParse(data) {
  return request({
    url: '/ui-automation/speech/parse/',
    method: 'post',
    data
  })
}

// 基于自然语音描述的元素定位
export function speechElementLocate(data) {
  return request({
    url: '/ui-automation/speech/locate/',
    method: 'post',
    data,
    timeout: 120000
  })
}


// ==================== AI 用例批量/录制/导入 ====================

// 批量执行 AI 用例
export function batchRunAICases(data) {
  return request({
    url: '/ui-automation/ai-cases/batch-run/',
    method: 'post',
    data
  })
}

// 批量录制 AI 用例
export function batchRecordAICases(data) {
  return request({
    url: '/ui-automation/ai-cases/batch-record/',
    method: 'post',
    data
  })
}

// 获取 AI 录制动作
export function getAIRecordingActions(recordId) {
  return request({
    url: `/ui-automation/ai-execution-records/${recordId}/ai-recording-actions/`,
    method: 'get'
  })
}

// 保存 AI 录制
export function saveAIRecording(recordId, data) {
  return request({
    url: `/ui-automation/ai-execution-records/${recordId}/save-ai-recording/`,
    method: 'post',
    data
  })
}

// 导入 AI 用例
export function importAICases(formData) {
  return request({
    url: '/ui-automation/ai-cases/import-cases/',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// 在执行前编译并检查 AI 用例的断言计划
export function previewAICaseAssertions(id, data = {}) {
  return request({
    url: `/ui-automation/ai-cases/${id}/assertion-preview/`,
    method: 'post',
    data
  })
}

export function batchDeleteAICases(data) {
  return request({
    url: '/ui-automation/ai-cases/batch-delete/',
    method: 'post',
    data
  })
}

export function batchEnableAICaseDualMode(data) {
  return request({
    url: '/ui-automation/ai-cases/batch-enable-dual-mode/',
    method: 'post',
    data
  })
}

export function batchEnableAICaseBrowserMode(data) {
  return request({
    url: '/ui-automation/ai-cases/batch-enable-browser-mode/',
    method: 'post',
    data
  })
}

export function batchConfigureAICaseSetupTemplate(data) {
  return request({
    url: '/ui-automation/ai-cases/batch-setup-template/',
    method: 'post',
    data
  })
}
