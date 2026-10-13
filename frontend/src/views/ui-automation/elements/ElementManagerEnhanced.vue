<template>
  <div class="element-manager">
    <div class="element-layout">
      <!-- 宸︿晶椤甸潰鏍?-->
      <div class="sidebar">
        <div class="sidebar-header">
          <el-select v-model="selectedProject" :placeholder="$t('common.selectProject')" @change="onProjectChange">
            <el-option
              v-for="project in projects"
              :key="project.id"
              :label="project.name"
              :value="project.id"
            />
          </el-select>
          <div class="header-actions">
            <el-button type="primary" size="small" @click="showCreatePageDialog = true" :title="$t('uiAutomation.element.createPage')">
              <el-icon><Folder /></el-icon>
            </el-button>
            <el-button type="success" size="small" @click="createEmptyElement" :title="$t('uiAutomation.element.addElement')">
              <el-icon><Plus /></el-icon>
            </el-button>
          </div>
        </div>

        <div class="page-tree">
          <el-tree
            ref="treeRef"
            :key="treeKey"
            :data="treeData"
            :props="treeProps"
            node-key="id"
            :expand-on-click-node="false"
            :default-expanded-keys="expandedKeys"
            @node-click="onNodeClick"
            @node-contextmenu="onNodeRightClick"
            @node-expand="onNodeExpand"
            @node-collapse="onNodeCollapse"
          >
            <template #default="{ node, data }">
              <div class="tree-node">
                <el-icon v-if="data.type === 'page'">
                  <Folder />
                </el-icon>
                <el-icon v-else>
                  <Document />
                </el-icon>

                <!-- 椤甸潰鍚嶇О缂栬緫 -->
                <div v-if="data.type === 'page' && editingNodeId === data.id" class="node-edit">
                  <el-input
                    v-model="editingNodeName"
                    size="small"
                    @blur="savePageName"
                    @keyup.enter="savePageName"
                    @keyup.esc="cancelEdit"
                    ref="editInputRef"
                  />
                </div>

                <!-- 鏅€氭樉绀烘ā寮?-->
                <span v-else class="node-label">{{ node.label }}</span>

                <span v-if="data.type === 'element'" class="element-type-tag" :class="data.element_type?.toLowerCase()">
                  {{ getElementTypeLabel(data.element_type) }}
                </span>
              </div>
            </template>
          </el-tree>
        </div>
      </div>

      <!-- 鍙充晶鍏冪礌璇︽儏 -->
      <div class="main-content">
        <div v-if="!selectedElement" class="empty-state">
          <el-empty :description="$t('uiAutomation.element.emptyElementTip')">
            <el-button type="primary" @click="createEmptyElement">{{ $t('uiAutomation.element.createNewElement') }}</el-button>
          </el-empty>
        </div>

        <div v-else class="element-detail">
          <!-- 鍏冪礌鍩烘湰淇℃伅 -->
          <div class="element-header">
            <div class="element-info">
              <el-form ref="elementHeaderFormRef" :model="selectedElement" :rules="elementHeaderRules" inline>
                <el-form-item prop="name" :label="$t('uiAutomation.element.elementName')" required>
                  <el-input
                    v-model="selectedElement.name"
                    :placeholder="$t('uiAutomation.element.elementNamePlaceholder')"
                    style="width: 300px"
                    @blur="validateHeaderField('name')"
                  />
                </el-form-item>
                <el-form-item :label="$t('uiAutomation.element.elementType')">
                  <el-select v-model="selectedElement.element_type" :placeholder="$t('uiAutomation.element.elementType')" style="width: 120px;">
                    <el-option :label="$t('uiAutomation.element.elementTypes.button')" value="BUTTON" />
                    <el-option :label="$t('uiAutomation.element.elementTypes.input')" value="INPUT" />
                    <el-option :label="$t('uiAutomation.element.elementTypes.link')" value="LINK" />
                    <el-option :label="$t('uiAutomation.element.elementTypes.dropdown')" value="DROPDOWN" />
                    <el-option :label="$t('uiAutomation.element.elementTypes.checkbox')" value="CHECKBOX" />
                    <el-option :label="$t('uiAutomation.element.elementTypes.radio')" value="RADIO" />
                    <el-option :label="$t('uiAutomation.element.elementTypes.text')" value="TEXT" />
                    <el-option :label="$t('uiAutomation.element.elementTypes.image')" value="IMAGE" />
                    <el-option :label="$t('uiAutomation.element.elementTypes.table')" value="TABLE" />
                    <el-option :label="$t('uiAutomation.element.elementTypes.form')" value="FORM" />
                    <el-option :label="$t('uiAutomation.element.elementTypes.modal')" value="MODAL" />
                  </el-select>
                </el-form-item>
                <el-form-item>
                  <el-button type="primary" @click="saveElement" :loading="saving" ref="saveButtonRef">
                    {{ $t('uiAutomation.common.save') }}
                  </el-button>
                </el-form-item>
              </el-form>
            </div>
          </div>

          <!-- 鍏冪礌閰嶇疆 -->
          <div class="element-form">
            <el-form ref="elementFormRef" :key="formKey" :model="selectedElement" :rules="elementRules" label-width="100px">
              <el-row :gutter="20">
                <el-col :span="12">
                  <el-form-item :label="$t('uiAutomation.element.page')">
                    <el-select v-model="selectedElement.page" :placeholder="$t('uiAutomation.element.selectPage')">
                      <el-option
                        v-for="page in pages"
                        :key="page.id"
                        :label="page.name"
                        :value="page.name"
                      />
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item :label="$t('uiAutomation.element.componentName')">
                    <el-input v-model="selectedElement.component_name" :placeholder="$t('uiAutomation.element.componentNamePlaceholder')" />
                  </el-form-item>
                </el-col>
              </el-row>

              <el-row :gutter="20">
                <el-col :span="12">
                  <el-form-item :label="$t('uiAutomation.element.locatorStrategy')" prop="locator_strategy_id" required>
                    <el-select
                      v-model="selectedElement.locator_strategy_id"
                      :key="`strategy-${formKey}-${selectedElement.locator_strategy_id || 'null'}`"
                      :placeholder="$t('uiAutomation.element.rules.strategyRequired')"
                      value-key="id"
                      @blur="validateField('locator_strategy_id')"
                    >
                      <el-option
                        v-for="strategy in locatorStrategies"
                        :key="strategy.id"
                        :label="strategy.name"
                        :value="strategy.id"
                      />
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item :label="$t('uiAutomation.element.waitTimeout') + '(' + $t('uiAutomation.element.waitTimeoutUnit') + ')'">
                    <el-input-number v-model="selectedElement.wait_timeout" :min="1" :max="60" style="width: 100%" />
                  </el-form-item>
                </el-col>
              </el-row>

              <el-row :gutter="20">
                <el-col :span="12">
                  <el-form-item :label="$t('uiAutomation.element.forceAction')">
                    <el-switch
                      v-model="selectedElement.force_action"
                      :active-text="$t('uiAutomation.element.forceActionEnabled')"
                      :inactive-text="$t('uiAutomation.element.forceActionDisabled')"
                    />
                    <div class="form-help-text" style="margin-top: 5px;">
                      {{ $t('uiAutomation.element.forceActionTip') }}
                    </div>
                  </el-form-item>
                </el-col>
              </el-row>

              <el-form-item :label="$t('uiAutomation.element.locatorExpression')" prop="locator_value" required>
                <el-input v-model="selectedElement.locator_value" :placeholder="$t('uiAutomation.element.locatorExpressionPlaceholder')" @blur="validateField('locator_value')" />
                <div class="form-help-text">
                  {{ $t('uiAutomation.element.locatorTip.title') }}<br>
                  - {{ $t('uiAutomation.element.locatorTip.id') }}<br>
                  - {{ $t('uiAutomation.element.locatorTip.css') }}<br>
                  - {{ $t('uiAutomation.element.locatorTip.xpath') }}<br>
                  - {{ $t('uiAutomation.element.locatorTip.other') }}
                </div>
              </el-form-item>

              <el-form-item :label="$t('uiAutomation.common.description')">
                <el-input v-model="selectedElement.description" type="textarea" :rows="3" :placeholder="$t('uiAutomation.element.descriptionPlaceholder')" />
              </el-form-item>
            </el-form>
          </div>
        </div>
      </div>
    </div>

    <!-- 鍒涘缓椤甸潰瀵硅瘽妗?-->
    <el-dialog v-model="showCreatePageDialog" :title="$t('uiAutomation.element.createPageTitle')" width="500px" :close-on-click-modal="false">
      <el-form ref="pageFormRef" :model="pageForm" :rules="pageRules" label-width="100px">
        <el-form-item :label="$t('uiAutomation.element.pageName')" prop="name">
          <el-input v-model="pageForm.name" :placeholder="$t('uiAutomation.element.pageNamePlaceholder')" />
        </el-form-item>
        <el-form-item :label="$t('uiAutomation.element.parentPage')">
          <el-select v-model="pageForm.parent_page" :placeholder="$t('uiAutomation.element.selectParentPage')" clearable>
            <el-option
              v-for="page in getAllPages()"
              :key="page.id"
              :label="page.name"
              :value="page.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="$t('uiAutomation.common.description')" prop="description">
          <el-input v-model="pageForm.description" type="textarea" :rows="3" :placeholder="$t('uiAutomation.element.descriptionPlaceholder')" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showCreatePageDialog = false">{{ $t('uiAutomation.common.cancel') }}</el-button>
        <el-button type="primary" @click="createPage">{{ $t('uiAutomation.common.confirm') }}</el-button>
      </template>
    </el-dialog>

    <!-- 鍙抽敭鑿滃崟 -->
    <ul v-show="showContextMenu" class="context-menu" :style="{ left: contextMenuX + 'px', top: contextMenuY + 'px' }">
      <li @click="addContextElement">{{ $t('uiAutomation.element.contextMenu.addElement') }}</li>
      <!-- 鍙湁鍦ㄦ櫘閫氶〉闈㈣妭鐐逛笅鎵嶆樉绀?鏂板瀛愰〉闈?閫夐」 -->
      <li v-if="rightClickedNode && rightClickedNode.type === 'page' && rightClickedNode.id !== 'unassigned'" @click="addSubPage">
        {{ $t('uiAutomation.element.contextMenu.addSubPage') }}
      </li>
      <!-- "鏈叧鑱旈〉闈?鑺傜偣涓嶆樉绀虹紪杈戝拰鍒犻櫎閫夐」 -->
      <li v-if="rightClickedNode && rightClickedNode.id !== 'unassigned'" @click="editNode">
        {{ $t('uiAutomation.element.contextMenu.edit') }}
      </li>
      <li v-if="rightClickedNode && rightClickedNode.id !== 'unassigned'" @click="deleteNode">
        {{ $t('uiAutomation.element.contextMenu.delete') }}
      </li>
    </ul>

    <!-- 缂栬緫椤甸潰瀵硅瘽妗?-->
    <el-dialog v-model="showEditPageDialog" :title="$t('uiAutomation.element.editPageTitle')" width="500px" :close-on-click-modal="false">
      <el-form ref="editPageFormRef" :model="editPageForm" :rules="pageRules" label-width="100px">
        <el-form-item :label="$t('uiAutomation.element.pageName')" prop="name">
          <el-input v-model="editPageForm.name" :placeholder="$t('uiAutomation.element.pageNamePlaceholder')" />
        </el-form-item>
        <el-form-item :label="$t('uiAutomation.element.parentPage')">
          <el-select v-model="editPageForm.parent_page" :placeholder="$t('uiAutomation.element.selectParentPage')" clearable>
            <el-option
              v-for="page in getAllPagesExceptCurrent(editPageForm.id)"
              :key="page.id"
              :label="page.name"
              :value="page.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="$t('uiAutomation.common.description')" prop="description">
          <el-input v-model="editPageForm.description" type="textarea" :rows="3" :placeholder="$t('uiAutomation.element.descriptionPlaceholder')" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showEditPageDialog = false">{{ $t('uiAutomation.common.cancel') }}</el-button>
        <el-button type="primary" @click="updatePage">{{ $t('uiAutomation.common.save') }}</el-button>
      </template>
    </el-dialog>

  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus, FolderAdd, Document, Search, Edit, Delete,
  Folder, Document as DocumentIcon, Operation, DocumentCopy, ArrowDown
} from '@element-plus/icons-vue'
import {
  getUiProjects,
  getElements,
  createElement,
  getElementDetail,
  updateElement,
  deleteElement,
  getElementTree,
  getElementGroupTree,
  getElementGroups,
  createElementGroup,
  updateElementGroup,
  deleteElementGroup,
  getLocatorStrategies,
  validateElementLocator,
  generateElementSuggestions
} from '@/api/ui_automation'

// 鍥介檯鍖?
const { t } = useI18n()

// 鍝嶅簲寮忔暟鎹?
const projects = ref([])
const selectedProject = ref('')
const pages = ref([])
const locatorStrategies = ref([])
const treeData = ref([])
const selectedElement = ref(null)
const expandedKeys = ref([])
const treeKey = ref(0) // 鐢ㄤ簬寮哄埗閲嶆柊娓叉煋鏍戠粍浠?
const formKey = ref(0) // 鐢ㄤ簬寮哄埗閲嶆柊娓叉煋琛ㄥ崟缁勪欢

// 琛ㄥ崟寮曠敤
const treeRef = ref(null)
const pageFormRef = ref(null)
const editPageFormRef = ref(null)
const elementFormRef = ref(null)
const elementHeaderFormRef = ref(null)

// 瀵硅瘽妗嗘帶鍒?
const showCreatePageDialog = ref(false)
const showEditPageDialog = ref(false)

// 鍙抽敭鑿滃崟
const showContextMenu = ref(false)
const contextMenuX = ref(0)
const contextMenuY = ref(0)
const rightClickedNode = ref(null)

// 琛ㄥ崟鏁版嵁
const pageForm = reactive({
  name: '',
  description: '',
  parent_page: null
})

const editPageForm = reactive({
  id: null,
  name: '',
  description: '',
  parent_page: null
})

// 鏍戝舰缁勪欢閰嶇疆
const treeProps = {
  children: 'children',
  label: 'name'
}

// 琛ㄥ崟楠岃瘉瑙勫垯
const pageRules = computed(() => ({
  name: [
    { required: true, message: t('uiAutomation.element.rules.pageNameRequired'), trigger: 'blur' }
  ]
}))

// 鍏冪礌琛ㄥ崟澶撮儴楠岃瘉瑙勫垯锛堝厓绱犲悕绉帮級
const elementHeaderRules = computed(() => ({
  name: [
    { required: true, message: t('uiAutomation.element.rules.nameRequired'), trigger: 'blur' },
    { min: 1, max: 200, message: t('uiAutomation.element.rules.nameLength'), trigger: 'blur' }
  ]
}))

// 鍏冪礌琛ㄥ崟楠岃瘉瑙勫垯
const elementRules = computed(() => ({
  locator_strategy_id: [
    { required: true, message: t('uiAutomation.element.rules.strategyRequired'), trigger: 'change' }
  ],
  locator_value: [
    { required: true, message: t('uiAutomation.element.rules.locatorRequired'), trigger: 'blur' },
    { min: 1, max: 500, message: t('uiAutomation.element.rules.locatorLength'), trigger: 'blur' }
  ]
}))

// 鑾峰彇鍏冪礌绫诲瀷鏍囩
const getElementTypeLabel = (type) => {
  const typeKey = type?.toLowerCase()
  const typeMap = {
    'button': t('uiAutomation.element.elementTypes.button'),
    'input': t('uiAutomation.element.elementTypes.input'),
    'link': t('uiAutomation.element.elementTypes.link'),
    'dropdown': t('uiAutomation.element.elementTypes.dropdown'),
    'checkbox': t('uiAutomation.element.elementTypes.checkbox'),
    'radio': t('uiAutomation.element.elementTypes.radio'),
    'text': t('uiAutomation.element.elementTypes.text'),
    'image': t('uiAutomation.element.elementTypes.image'),
    'table': t('uiAutomation.element.elementTypes.table'),
    'form': t('uiAutomation.element.elementTypes.form'),
    'modal': t('uiAutomation.element.elementTypes.modal')
  }
  return typeMap[typeKey] || type
}

// 鑾峰彇鎵€鏈夐〉闈?
const getAllPages = () => {
  const allPages = []

  const traverse = (nodes) => {
    nodes.forEach(node => {
      if (node.type === 'page') {
        allPages.push({
          id: node.id,
          name: node.name
        })
      }
      if (node.children) {
        traverse(node.children)
      }
    })
  }

  traverse(treeData.value)
  return allPages
}

// 鑾峰彇鎵€鏈夐〉闈紙闄や簡鎸囧畾ID鐨勯〉闈級
const getAllPagesExceptCurrent = (currentId) => {
  const allPages = []

  const traverse = (nodes) => {
    nodes.forEach(node => {
      if (node.type === 'page' && node.id !== currentId) {
        allPages.push({
          id: node.id,
          name: node.name
        })
      }
      if (node.children) {
        traverse(node.children)
      }
    })
  }

  traverse(treeData.value)
  return allPages
}

// 椤甸潰鍚嶇О缂栬緫鐩稿叧
const editingNodeId = ref(null)
const editingNodeName = ref('')
const editInputRef = ref(null)

// 鐘舵€?
const saving = ref(false)
const validating = ref(false)
const generating = ref(false)
const suggestions = ref([])


// 灏嗗叧閿彉閲忔毚闇插埌window瀵硅薄锛屾柟渚垮湪鎺у埗鍙拌皟璇?
const exposeToWindow = () => {
  if (typeof window !== 'undefined') {
    window.ELEMENTS_DEBUG = {
      treeData,
      projects,
      selectedElement,
      loadElementTree,
      treeRef: typeof treeRef !== 'undefined' ? treeRef : null,
      expandedKeys,
      pages,
      $vm: { // 褰撳墠缁勪欢瀹炰緥
        treeData: treeData.value,
        projects: projects.value,
        pages: pages.value,
        expandedKeys: expandedKeys.value
      }
    }
  }
}

// 缁勪欢鎸傝浇
onMounted(async () => {

  await loadProjects()
  await loadLocatorStrategies()


  if (projects.value.length > 0) {
    selectedProject.value = projects.value[0].id
    await onProjectChange()
  }

  // 鏆撮湶璋冭瘯淇℃伅
  exposeToWindow()

})

// 鍔犺浇椤圭洰鍒楄〃
const loadProjects = async () => {
  try {
    const response = await getUiProjects()
    projects.value = response.data?.results || response.data || []
  } catch (error) {
    console.error('鑾峰彇椤圭洰鍒楄〃澶辫触:', error)
  }
}

// 鎻愪緵鎺у埗鍙拌皟璇曞府鍔╁嚱鏁?
const debugTree = () => {
  if (typeof window !== 'undefined') {
      treeData.value.map(p => ({
        id: p.id,
        name: p.name,
        type: p.type,
        children: p.children?.length || 0,
        elementChildren: p.children?.filter(c => c.type === 'element').map(e => e.name) || []
      }))

    // 鎵惧嚭鎵€鏈夊厓绱?
    const allElements = []
    const findElements = (nodes, parent) => {
      nodes.forEach(node => {
        if (node.type === 'element') {
          allElements.push({
            name: node.name,
            id: node.id,
            parent: parent
          })
        } else if (node.type === 'page' && node.children) {
          findElements(node.children, node.name)
        }
      })
    }
    findElements(treeData.value, null)

    // 鏆撮湶鍒皐indow
    window.debugTreeData = debugTree
  }
}

// 鍔犺浇瀹氫綅绛栫暐
const loadLocatorStrategies = async () => {
  try {
    const response = await getLocatorStrategies()
    locatorStrategies.value = response.data?.results || response.data || []
  } catch (error) {
    console.error('鑾峰彇瀹氫綅绛栫暐澶辫触:', error)
  }
}

// 鍔犺浇椤甸潰锛堝垎缁勶級
const loadPages = async () => {
  if (!selectedProject.value) return

  try {
    const response = await getElementGroups({ project: selectedProject.value })
    pages.value = response.data?.results || response.data || []
  } catch (error) {
    console.error('鑾峰彇椤甸潰澶辫触:', error)
  }
}

// 鍔犺浇椤甸潰鏍戠粨鏋?
const loadPageTree = async () => {
  if (!selectedProject.value) return

  try {
    const response = await getElementGroupTree({ project: selectedProject.value })
    // 鏋勫缓瀹屾暣鐨勬爲褰㈢粨鏋?
    const buildTree = (groups) => {
      return groups.map(group => ({
        ...group,
        type: 'page',
        children: group.children ? buildTree(group.children) : []
      }))
    }

    treeData.value = buildTree(response.data || [])
  } catch (error) {
    console.error('鑾峰彇椤甸潰鏍戝け璐?', error)
    treeData.value = []
  }
}

// 鍔犺浇鍏冪礌鏍?
const loadElementTree = async () => {
  if (!selectedProject.value) {
    treeData.value = []
    return
  }

  try {
    // 骞惰鍔犺浇椤甸潰鏍戝拰鍏冪礌
    const [pageTreeResponse, elementsResponse] = await Promise.all([
      getElementGroupTree({ project: selectedProject.value }),
      getElementTree({ project: selectedProject.value })
    ])

    // 鏋勫缓瀹屾暣鐨勬爲褰㈢粨鏋?
    const buildTree = (groups) => {
      return groups.map(group => ({
        ...group,
        type: 'page',
        children: group.children ? buildTree(group.children) : []
      }))
    }

    const pageNodes = buildTree(pageTreeResponse.data || [])

    // 璋冭瘯淇℃伅 - 妫€鏌PI杩斿洖鐨勫畬鏁村搷搴旂粨鏋?

    // 鎵撳嵃鍘熷鏁版嵁杩涜鍒嗘瀽

    const elements = elementsResponse.data?.results || elementsResponse.data || []

    // 鑾峰彇鎵€鏈夐〉闈㈢殑ID锛岀敤浜庤皟璇?
    const pageIds = pageNodes.map(page => page.id)

    // 灏嗗厓绱犳坊鍔犲埌瀵瑰簲椤甸潰涓?
    const attachedElementIds = new Set()

    const attachElementsToPages = (pages) => {
      pages.forEach(page => {
        // 鎵惧埌灞炰簬褰撳墠椤甸潰鐨勫厓绱?
        const pageElements = elements.filter(element => element.group_id === page.id)

        const elementNodes = pageElements.map(element => {
          attachedElementIds.add(element.id)
          return {
            ...element,
            type: 'element'
          }
        })

        // 灏嗗厓绱犳坊鍔犲埌椤甸潰鐨勫瓙鑺傜偣涓?
        page.children = page.children ? [...page.children, ...elementNodes] : [...elementNodes]

        // 閫掑綊澶勭悊瀛愰〉闈?
        if (page.children) {
          attachElementsToPages(page.children.filter(child => child.type === 'page'))
        }
      })
    }

    attachElementsToPages(pageNodes)

    // 娣诲姞鏈叧鑱旈〉闈㈢殑鍏冪礌鍒?鏈叧鑱旈〉闈?鑺傜偣
    // 鍖呮嫭锛?. group_id 涓?null/undefined 鐨勫厓绱?
    //       2. group_id 鎸囧悜鐨勯〉闈笉瀛樺湪鐨勫厓绱?
    const unassignedElements = elements.filter(element => {
      // 濡傛灉娌℃湁group_id锛岃偗瀹氭槸鏈叧鑱旂殑
      if (!element.group_id) {
        return true
      }
      // 濡傛灉鏈塯roup_id浣嗘病鏈夎娣诲姞鍒颁换浣曢〉闈紙椤甸潰涓嶅瓨鍦級锛屼篃绠楁湭鍏宠仈
      return !attachedElementIds.has(element.id)
    })


    if (unassignedElements.length > 0) {
      const unassignedPage = {
        id: 'unassigned',
        name: '未关联页面',
        type: 'page',
        children: unassignedElements.map(element => ({
          ...element,
          type: 'element'
        }))
      }
      pageNodes.unshift(unassignedPage) // 娣诲姞鍒板垪琛ㄦ渶鍓嶉潰
      // 榛樿灞曞紑鏈叧鑱旈〉闈㈣妭鐐?
      expandedKeys.value.push('unassigned')
    }

    treeData.value = pageNodes

    // 灏唗reeData鏆撮湶鍒皐indow锛屾柟渚垮湪鎺у埗鍙拌皟璇?
    if (typeof window !== 'undefined') {
      window.vue_treeData = treeData.value
    }
  } catch (error) {
    console.error('鑾峰彇鍏冪礌鏍戝け璐?', error)
    treeData.value = []
  }
}

// 椤圭洰鍒囨崲
const onProjectChange = async () => {
  selectedElement.value = null
  suggestions.value = []


  await Promise.all([
    loadPages(),
    loadElementTree()
  ])

  if (treeData.value.length > 0) {
    // 默认选中第一个节点
  }

  // 椤圭洰鍒囨崲鏃跺己鍒跺埛鏂版爲
  treeKey.value += 1
}

// 鍒涘缓绌哄厓绱?
const createEmptyElement = () => {
  selectedElement.value = {
    name: '',
    element_type: 'BUTTON',
    page: '',
    component_name: '',
    locator_strategy_id: null, // 浣跨敤null鑰屼笉鏄┖瀛楃涓?
    locator_value: '',
    wait_timeout: 5,
    force_action: false,  // 寮哄埗鎿嶄綔閫夐」锛岄粯璁ょ鐢?
    description: ''
  }
}

// 楠岃瘉鍗曚釜瀛楁锛堢敤浜庡け鐒﹂獙璇侊級
const validateField = async (field) => {
  if (!elementFormRef.value) return
  try {
    await elementFormRef.value.validateField(field)
  } catch (error) {
    // 楠岃瘉澶辫触锛屼笉闇€瑕佸仛浠讳綍澶勭悊锛岄敊璇細鑷姩鏄剧ず
  }
}

// 楠岃瘉澶撮儴琛ㄥ崟瀛楁锛堝厓绱犲悕绉帮級
const validateHeaderField = async (field) => {
  if (!elementHeaderFormRef.value) return
  try {
    await elementHeaderFormRef.value.validateField(field)
  } catch (error) {
    // 楠岃瘉澶辫触锛屼笉闇€瑕佸仛浠讳綍澶勭悊锛岄敊璇細鑷姩鏄剧ず
  }
}

// 楠岃瘉鏁翠釜鍏冪礌琛ㄥ崟
const validateElementForm = async () => {
  const results = await Promise.allSettled([
    elementHeaderFormRef.value?.validate() ?? Promise.resolve(),
    elementFormRef.value?.validate() ?? Promise.resolve()
  ])

  // 妫€鏌ユ槸鍚︽湁楠岃瘉澶辫触鐨勬儏鍐?
  const hasFailed = results.some(result => result.status === 'rejected')
  return !hasFailed
}

// 鍒涘缓椤甸潰
const createPage = async () => {
  const validate = await pageFormRef.value.validate()
  if (!validate) return

  try {
    // 鏋勫缓鍒涘缓椤甸潰鐨勫弬鏁帮紝姝ｇ‘澶勭悊鐖堕〉闈㈠弬鏁?
    const pageData = {
      name: pageForm.name,
      description: pageForm.description,
      project: selectedProject.value
    }

    // 鍙湁褰撶埗椤甸潰ID瀛樺湪涓斾笉涓虹┖鏃舵墠娣诲姞parent_group瀛楁
    if (pageForm.parent_page) {
      pageData.parent_group = pageForm.parent_page
    }

    await createElementGroup(pageData)

    ElMessage.success(t('uiAutomation.element.messages.pageCreateSuccess'))
    showCreatePageDialog.value = false

    // 閲嶇疆琛ㄥ崟
    Object.assign(pageForm, {
      name: '',
      description: '',
      parent_page: null
    })

    // 閲嶆柊鍔犺浇椤甸潰鍜屾爲
    await Promise.all([
      loadPages(),
      loadElementTree()
    ])

    // 寮哄埗鍒锋柊鏍戠粍浠?
    treeKey.value += 1
  } catch (error) {
    console.error('鍒涘缓椤甸潰澶辫触:', error)
    ElMessage.error(t('uiAutomation.element.messages.pageCreateFailed'))
  }
}

// 鑺傜偣鐐瑰嚮
const onNodeClick = async (data) => {
  if (data.type === 'element') {
    try {
      const response = await getElementDetail(data.id)
      selectedElement.value = response.data

      // 寮哄埗鍒锋柊琛ㄥ崟锛岀‘淇濅笅鎷夋姝ｇ‘鏄剧ず
      formKey.value += 1
    } catch (error) {
      console.error('鑾峰彇鍏冪礌璇︽儏澶辫触:', error)
    }
  }
}

// 鑺傜偣鍙抽敭鐐瑰嚮
const onNodeRightClick = (event, data) => {
  event.preventDefault()

  // 闅愯棌鐜版湁鑿滃崟
  showContextMenu.value = false

  // 璁剧疆鍙抽敭鐐瑰嚮鐨勮妭鐐?
  rightClickedNode.value = data

  // 璁剧疆鑿滃崟浣嶇疆
  contextMenuX.value = event.clientX
  contextMenuY.value = event.clientY

  // 鏄剧ず鑿滃崟
  showContextMenu.value = true

  // 娣诲姞鍏ㄥ眬鐐瑰嚮鐩戝惉鍣ㄤ互闅愯棌鑿滃崟
  const hideMenu = () => {
    showContextMenu.value = false
    document.removeEventListener('click', hideMenu)
  }

  // 寤惰繜娣诲姞鐩戝惉鍣紝閬垮厤绔嬪嵆瑙﹀彂
  setTimeout(() => {
    document.addEventListener('click', hideMenu)
  }, 100)
}

// 鑺傜偣灞曞紑
const onNodeExpand = (data) => {
  if (!expandedKeys.value.includes(data.id)) {
    expandedKeys.value.push(data.id)
  }
}

// 鑺傜偣鏀惰捣
const onNodeCollapse = (data) => {
  const index = expandedKeys.value.indexOf(data.id)
  if (index > -1) {
    expandedKeys.value.splice(index, 1)
  }
}

// 淇濆瓨鍏冪礌
const saveElement = async () => {
  if (!selectedElement.value) return

  // 楠岃瘉琛ㄥ崟
  const isValid = await validateElementForm()
  if (!isValid) {
    ElMessage.error(t('uiAutomation.element.messages.saveFailed'))
    return
  }

  try {
    saving.value = true

    if (selectedElement.value.id) {
      // 鏇存柊鍏冪礌 - 鏋勫缓姝ｇ‘鐨凙PI鏁版嵁鏍煎紡
      const elementUpdateData = {
        name: selectedElement.value.name,
        element_type: selectedElement.value.element_type,
        page: selectedElement.value.page,
        component_name: selectedElement.value.component_name,
        description: selectedElement.value.description,
        locator_strategy_id: selectedElement.value.locator_strategy_id,
        locator_value: selectedElement.value.locator_value,
        wait_timeout: selectedElement.value.wait_timeout,
        force_action: selectedElement.value.force_action,
        project_id: selectedProject.value
      }

      // 濡傛灉鍏冪礌鏈夊垎缁勶紙椤甸潰锛夛紝纭繚浼犻€掓纭殑 group_id
      if (selectedElement.value.page) {

        // 閫氳繃閬嶅巻鏍戝舰缁撴瀯鏌ユ壘瀵瑰簲鐨勯〉闈D
        const findPageIdByName = (nodes, pageName) => {
          for (const node of nodes) {
            if (node.type === 'page' && node.name === pageName) {
              return node.id
            }
            if (node.children) {
              const foundId = findPageIdByName(node.children, pageName)
              if (foundId) return foundId
            }
          }
          return null
        }

        const pageId = findPageIdByName(treeData.value, selectedElement.value.page)
        if (pageId) {
          elementUpdateData.group_id = pageId
        }
      }

      await updateElement(selectedElement.value.id, elementUpdateData)

      // 閲嶆柊鑾峰彇瀹屾暣鐨勫厓绱犺鎯呬互纭繚鎵€鏈夊叧鑱斿瓧娈垫纭樉绀?
      const detailResponse = await getElementDetail(selectedElement.value.id)
      selectedElement.value = detailResponse.data

      // 寮哄埗鍒锋柊琛ㄥ崟锛岀‘淇濅笅鎷夋姝ｇ‘鏄剧ず
      formKey.value += 1

      // 浣跨敤nextTick纭繚DOM鏇存柊
      await nextTick()

      ElMessage.success(t('uiAutomation.element.messages.saveSuccess'))
    } else {
      // 鍒涘缓鍏冪礌
      // 纭繚浼犻€掓纭殑瀛楁鍚?project_id 鑰屼笉鏄?project
      const elementData = {
        ...selectedElement.value,
        project_id: selectedProject.value
      }

      // 濡傛灉鍏冪礌鏈夊垎缁勶紙椤甸潰锛夛紝纭繚浼犻€?group_id
      if (selectedElement.value.page) {

        // 閫氳繃閬嶅巻鏍戝舰缁撴瀯鏌ユ壘瀵瑰簲鐨勯〉闈D
        const findPageIdByName = (nodes, pageName) => {
          for (const node of nodes) {
            if (node.type === 'page' && node.name === pageName) {
              return node.id
            }
            if (node.children) {
              const foundId = findPageIdByName(node.children, pageName)
              if (foundId) return foundId
            }
          }
          return null
        }

        const pageId = findPageIdByName(treeData.value, selectedElement.value.page)

        if (pageId) {
          elementData.group_id = pageId
        }
      }

      const response = await createElement(elementData)

      // 閲嶆柊鑾峰彇瀹屾暣鐨勫厓绱犺鎯呬互纭繚鎵€鏈夊叧鑱斿瓧娈垫纭樉绀?
      const detailResponse = await getElementDetail(response.data.id)
      selectedElement.value = detailResponse.data

      // 寮哄埗鍒锋柊琛ㄥ崟锛岀‘淇濅笅鎷夋姝ｇ‘鏄剧ず
      formKey.value += 1

      // 浣跨敤nextTick纭繚DOM鏇存柊
      await nextTick()

      ElMessage.success(t('uiAutomation.element.messages.createSuccess'))
    }

    // 閲嶆柊鍔犺浇鏍?
    await loadElementTree()

    // 寮哄埗閲嶆柊娓叉煋鏍戠粍浠?
    treeKey.value += 1

    // 寮哄埗瑙﹀彂Vue鏇存柊鍜屾爲缁勪欢鍒锋柊
    nextTick(() => {

      // 灞曞紑鏂板垱寤哄厓绱犳墍鍦ㄧ殑椤甸潰鑺傜偣
      if (selectedElement.value && selectedElement.value.group_id) {
        if (!expandedKeys.value.includes(selectedElement.value.group_id)) {
          expandedKeys.value.push(selectedElement.value.group_id)
        }
      }

    })
  } catch (error) {
    console.error('淇濆瓨鍏冪礌澶辫触:', error)
    ElMessage.error(t('uiAutomation.element.messages.saveFailed') + ': ' + (error.response?.data?.message || error.message || t('uiAutomation.messages.error.unknown')))
  } finally {
    saving.value = false
  }
}

// 楠岃瘉鍏冪礌
const validateElement = async () => {
  if (!selectedElement.value) return

  try {
    validating.value = true
    const response = await validateElementLocator(selectedElement.value.id)
    const result = response.data

    if (result.is_valid) {
      ElMessage.success(t('uiAutomation.element.messages.validateSuccess'))
    } else {
      ElMessage.error(`${t('uiAutomation.element.messages.validateFailed')}: ${result.validation_message}`)
    }
  } catch (error) {
    ElMessage.error(t('uiAutomation.element.messages.validateFailed'))
    console.error('楠岃瘉鍏冪礌澶辫触:', error)
  } finally {
    validating.value = false
  }
}

// 鐢熸垚寤鸿
const generateSuggestions = async () => {
  if (!selectedElement.value) return

  try {
    generating.value = true
    const response = await generateElementSuggestions(selectedElement.value.id)
    suggestions.value = response.data.suggestions
  } catch (error) {
    console.error('鐢熸垚寤鸿澶辫触:', error)
  } finally {
    generating.value = false
  }
}

// 淇濆瓨椤甸潰鍚嶇О
const savePageName = () => {
  // TODO: 瀹炵幇椤甸潰鍚嶇О淇濆瓨
  editingNodeId.value = null
}

// 鍙栨秷缂栬緫
const cancelEdit = () => {
  editingNodeId.value = null
}

// 鍙抽敭鑿滃崟鎿嶄綔鍑芥暟
// 鏂板鍏冪礌
const addContextElement = () => {
  showContextMenu.value = false
  createEmptyElement()

  // 濡傛灉鍙抽敭鐐瑰嚮鐨勬槸椤甸潰鑺傜偣锛岃缃厓绱犵殑椤甸潰
  if (rightClickedNode.value && rightClickedNode.value.type === 'page') {
    // 鐗规畩澶勭悊锛氬鏋滄槸"鏈叧鑱旈〉闈?鑺傜偣锛屼笉璁剧疆page鍜実roup_id
    if (rightClickedNode.value.id === 'unassigned') {
      return
    }

    if (selectedElement.value) {
      selectedElement.value.page = rightClickedNode.value.name
      // 鍚屾椂璁剧疆group_id锛岀‘淇濆厓绱犺兘姝ｇ‘鍏宠仈鍒伴〉闈?
      selectedElement.value.group_id = rightClickedNode.value.id
    }
  }
}

// 鏂板瀛愰〉闈?
const addSubPage = () => {
  showContextMenu.value = false

  // 绂佹鍦?鏈叧鑱旈〉闈?鑺傜偣涓嬪垱寤哄瓙椤甸潰
  if (rightClickedNode.value && rightClickedNode.value.id === 'unassigned') {
    ElMessage.warning('鏈叧鑱旈〉闈㈣妭鐐逛笅涓嶈兘鍒涘缓瀛愰〉闈?')
    return
  }

  showCreatePageDialog.value = true

  // 濡傛灉鍙抽敭鐐瑰嚮鐨勬槸椤甸潰鑺傜偣锛岃缃埗椤甸潰
  if (rightClickedNode.value && rightClickedNode.value.type === 'page') {
    pageForm.parent_page = rightClickedNode.value.id
  }
}

// 缂栬緫鑺傜偣
const editNode = async () => {
  showContextMenu.value = false

  if (!rightClickedNode.value) {
    return
  }


  // 绂佹缂栬緫"鏈叧鑱旈〉闈?鑺傜偣
  if (rightClickedNode.value.id === 'unassigned') {
    ElMessage.warning('鏈叧鑱旈〉闈㈣妭鐐逛笉鑳界紪杈?')
    return
  }

  if (rightClickedNode.value.type === 'page') {
    // 缂栬緫椤甸潰
    editPageForm.id = rightClickedNode.value.id
    editPageForm.name = rightClickedNode.value.name
    editPageForm.description = rightClickedNode.value.description || ''
    editPageForm.parent_page = rightClickedNode.value.parent_group || null
    showEditPageDialog.value = true
  } else if (rightClickedNode.value.type === 'element') {
    // 缂栬緫鍏冪礌 - 閫氳繃API鑾峰彇瀹屾暣鐨勫厓绱犺鎯咃紝閬垮厤浣跨敤鏍戣妭鐐圭殑澶嶆潅鏁版嵁
    try {
      const response = await getElementDetail(rightClickedNode.value.id)
      selectedElement.value = response.data

      // 寮哄埗鍒锋柊琛ㄥ崟锛岀‘淇濅笅鎷夋姝ｇ‘鏄剧ず
      formKey.value += 1
    } catch (error) {
      console.error('鑾峰彇鍏冪礌璇︽儏澶辫触:', error)
      ElMessage.error(t('uiAutomation.element.messages.getDetailFailed'))
    }
  } else {
  }
}

// 鍒犻櫎鑺傜偣
const deleteNode = async () => {
  showContextMenu.value = false

  if (!rightClickedNode.value) return

  // 绂佹鍒犻櫎"鏈叧鑱旈〉闈?鑺傜偣
  if (rightClickedNode.value.id === 'unassigned') {
    ElMessage.warning('鏈叧鑱旈〉闈㈣妭鐐逛笉鑳藉垹闄?')
    return
  }

  try {
    await ElMessageBox.confirm(
      t('uiAutomation.element.messages.confirmDeleteNode', { name: rightClickedNode.value.name }),
      t('uiAutomation.common.confirmDelete'),
      {
        type: 'warning',
        confirmButtonText: t('uiAutomation.common.confirm'),
        cancelButtonText: t('uiAutomation.common.cancel')
      }
    )


    if (rightClickedNode.value.type === 'page') {
      // 鍒犻櫎椤甸潰锛堝垎缁勶級
      await deleteElementGroup(rightClickedNode.value.id)
      ElMessage.success(t('uiAutomation.element.messages.pageDeleteSuccess'))
    } else if (rightClickedNode.value.type === 'element') {
      // 鍒犻櫎鍏冪礌
      await deleteElement(rightClickedNode.value.id)
      ElMessage.success(t('uiAutomation.element.messages.deleteSuccess'))
      // 濡傛灉褰撳墠閫変腑鐨勬槸琚垹闄ょ殑鍏冪礌锛屾竻绌洪€変腑
      if (selectedElement.value && selectedElement.value.id === rightClickedNode.value.id) {
        selectedElement.value = null
      }
    }


    // 閲嶆柊鍔犺浇鏁版嵁
    await Promise.all([
      loadPages(),
      loadElementTree()
    ])

    // 寮哄埗鍒锋柊鏍戠粍浠?
    treeKey.value += 1
  } catch (error) {
    if (error !== 'cancel') {
      console.error('鍒犻櫎澶辫触:', error)
      ElMessage.error(t('uiAutomation.element.messages.deleteFailed'))
    }
  }
}

// 鏇存柊椤甸潰
const updatePage = async () => {

  if (!editPageFormRef.value) {
    return
  }

  const validate = await editPageFormRef.value.validate()
  if (!validate) {
    return
  }


  try {
    // 鏋勫缓鏇存柊椤甸潰鐨勫弬鏁帮紝姝ｇ‘澶勭悊鐖堕〉闈㈠弬鏁?
    const pageData = {
      name: editPageForm.name,
      description: editPageForm.description,
      project: selectedProject.value
    }

    // 鍙湁褰撶埗椤甸潰ID瀛樺湪涓斾笉涓虹┖鏃舵墠娣诲姞parent_group瀛楁
    // 濡傛灉鐖堕〉闈D涓簄ull锛岃〃绀哄彇娑堢埗椤甸潰鍏宠仈
    if (editPageForm.parent_page !== undefined) {
      pageData.parent_group = editPageForm.parent_page
    }

    await updateElementGroup(editPageForm.id, pageData)

    ElMessage.success(t('uiAutomation.element.messages.pageUpdateSuccess'))
    showEditPageDialog.value = false

    // 閲嶆柊鍔犺浇椤甸潰鍜屾爲
    await Promise.all([
      loadPages(),
      loadElementTree()
    ])

    // 寮哄埗鍒锋柊鏍戠粍浠?
    treeKey.value += 1
  } catch (error) {
    console.error('鏇存柊椤甸潰澶辫触:', error)
    ElMessage.error(t('uiAutomation.element.messages.pageUpdateFailed'))
  }
}
</script>

<style scoped>
.element-manager {
  height: 100vh;
  display: flex;
  flex-direction: column;
}

.element-layout {
  display: flex;
  flex: 1;
  overflow: hidden;
}

.sidebar {
  width: 300px;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
  background: #f5f7fa;
}

.sidebar-header {
  padding: 15px;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-actions {
  display: flex;
  gap: 5px;
  margin-left: auto;
}

.page-tree {
  flex: 1;
  overflow-y: auto;
  padding: 10px;
}

.tree-node {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 5px 0;
}

.node-label {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.element-type-tag {
  font-size: 12px;
  padding: 2px 6px;
  border-radius: 4px;
  background-color: #ecf5ff;
  color: #409eff;
}

.main-content {
  flex: 1;
  overflow: auto;
  padding: 20px;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
}

.element-header {
  margin-bottom: 20px;
  padding-bottom: 20px;
  border-bottom: 1px solid #e4e7ed;
}

.element-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.element-form {
  margin-top: 20px;
}

.form-help-text {
  font-size: 12px;
  color: #909399;
  margin-top: 5px;
}

/* 鍙抽敭鑿滃崟鏍峰紡 */
.context-menu {
  position: fixed;
  z-index: 9999;
  background: white;
  border: 1px solid #e4e7ed;
  border-radius: 4px;
  box-shadow: 0 2px 12px 0 rgba(0, 0, 0, 0.1);
  padding: 5px 0;
  margin: 0;
  list-style: none;
  min-width: 120px;
}

.context-menu li {
  padding: 8px 15px;
  cursor: pointer;
  font-size: 14px;
  color: #606266;
}

.context-menu li:hover {
  background-color: #f5f7fa;
  color: #409eff;
}
</style>
