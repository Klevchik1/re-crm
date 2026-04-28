<template>
  <section class="stack">
    <div class="hero" style="padding: 24px 28px">
      <div class="row row--between" style="flex-wrap: wrap; gap: 12px">
        <div>
          <div class="hero__eyebrow">ЗАДАЧИ</div>
          <h1 class="h2" style="color: #fff; margin-top: 8px">Рабочие задачи</h1>
          <div style="color: rgba(255,255,255,.75); font-size: 14px; margin-top: 6px">
            Поручения сотрудникам: звонки, показы, документы
          </div>
          <!-- Индикатор личной нагрузки сотрудника — сразу под заголовком. -->
          <div v-if="!auth.isManager"
               class="workload-banner"
               :class="{ 'is-limit': workload.isOverloaded }">
            <span>Моя загрузка:</span>
            <b>{{ workload.activeTasksLabel }}</b> задач ·
            <b>{{ workload.activeRequestsLabel }}</b> заявок ·
            <b>{{ workload.workload.in_progress_tasks }}/{{ workload.workload.max_in_progress_tasks }}</b>
            в работе
          </div>
        </div>
        <div class="row" style="gap: 8px; flex-wrap: wrap">
          <button class="btn btn--accent" @click="toggleForm">
            {{ showForm ? 'Скрыть форму' : '+ Новая задача' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Уведомления (тосты) -->
    <Transition name="toast">
      <div v-if="toast.show" class="toast" :class="'toast--' + toast.type">
        {{ toast.message }}
      </div>
    </Transition>

    <!-- Форма создания -->
    <form v-if="showForm" class="panel panel--light stack" @submit.prevent="create">
      <div class="grid grid--3">
        <div class="field">
          <label>Заголовок</label>
          <input class="input" v-model="form.title" required />
        </div>
        <div class="field">
          <label>Исполнитель</label>
          <select class="select" v-model.number="form.assignee" required>
            <option :value="null" disabled>— выберите —</option>
            <option v-for="a in employees" :key="a.id" :value="a.id">
              {{ a.username }}
            </option>
          </select>
        </div>
        <div class="field">
          <label>Тип задачи</label>
          <select class="select" v-model="form.task_type">
            <option v-for="tt in taskTypes" :key="tt.code" :value="tt.code">
              {{ tt.name }}
            </option>
          </select>
        </div>
        <div class="field">
          <label>Приоритет</label>
          <select class="select" v-model="form.priority">
            <option value="low">Низкий</option>
            <option value="normal">Обычный</option>
            <option value="high">Высокий</option>
          </select>
        </div>
        <div class="field">
          <label>Срок</label>
          <input class="input" type="datetime-local" v-model="form.due_date" />
        </div>
        <div class="field">
          <label>Связанная заявка</label>
          <select class="select" v-model.number="form.request">
            <option :value="null">— не выбрана —</option>
            <option v-for="r in requests" :key="r.id" :value="r.id">
              №{{ r.id }} — {{ r.client_username }}
            </option>
          </select>
        </div>
        <div class="field">
          <label>Клиент</label>
          <select class="select" v-model.number="form.client">
            <option :value="null">— не выбран —</option>
            <option v-for="c in clients" :key="c.id" :value="c.id">
              {{ c.username }}
            </option>
          </select>
        </div>
        <div class="field">
          <label>Связанный объект</label>
          <select class="select" v-model.number="form.property">
            <option :value="null">— не выбран —</option>
            <option v-for="p in properties" :key="p.id" :value="p.id">
              {{ p.title || 'Объект №' + p.id }}
            </option>
          </select>
        </div>
      </div>
      <div class="field">
        <label>Описание</label>
        <textarea class="textarea" v-model="form.description" rows="3"></textarea>
      </div>
      <div class="row" style="justify-content: flex-end">
        <button class="btn btn--accent" type="submit">Создать задачу</button>
      </div>
    </form>

    <!-- Вкладки «Активные / История». Для менеджера история показывает
         все завершённые задачи, для сотрудника — только его собственные. -->
    <div class="panel panel--light">
      <div class="tabs">
        <button class="tab"
                :class="{ 'tab--active': viewMode === 'active' }"
                @click="setViewMode('active')">
          Активные <span class="tab__count">{{ activeCount }}</span>
        </button>
        <button class="tab"
                :class="{ 'tab--active': viewMode === 'history' }"
                @click="setViewMode('history')">
          История <span class="tab__count">{{ historyCount }}</span>
        </button>
      </div>

      <!-- Фильтры видны только в «Активных», в истории они не нужны:
           там и так показываются только завершённые. -->
      <div v-if="viewMode === 'active'" class="filter-row">
        <div class="filter-group">
          <span class="filter-label">Статус:</span>
          <div class="row" style="gap: 6px; flex-wrap: wrap">
            <button class="btn btn--sm"
                    :class="{ 'btn--primary': statusFilter === '' }"
                    @click="statusFilter = ''">
              Все ({{ activeCount }})
            </button>
            <button v-for="s in activeStatuses" :key="s.id"
                    class="btn btn--sm"
                    :class="{ 'btn--primary': statusFilter === s.id }"
                    @click="statusFilter = s.id">
              {{ s.name }} ({{ countByStatus(s.id) }})
            </button>
          </div>
        </div>
        <div class="filter-group">
          <span class="filter-label">Тип:</span>
          <select class="select select--sm" v-model="typeFilter">
            <option value="">Все типы</option>
            <option v-for="tt in taskTypes" :key="tt.code" :value="tt.code">
              {{ tt.name }}
            </option>
          </select>
        </div>
      </div>
    </div>

    <!-- Таблица задач: активные -->
    <div v-if="viewMode === 'active'" class="panel panel--light">
      <table class="table">
        <thead>
          <tr>
            <th></th>
            <th>Заголовок</th>
            <th>Тип</th>
            <th>Исполнитель</th>
            <th>Заявка</th>
            <th>Приоритет</th>
            <th>Срок</th>
            <th>Статус</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in filtered" :key="t.id"
              :class="{ 'row--mine': isMine(t), 'row--active': isMyActive(t) }">
            <td class="mine-cell">
              <TaskMineBadge :task="t" :user-id="auth.user?.id" mode="dot" />
            </td>
            <td>
              <b>{{ t.title }}</b>
              <div class="muted" style="font-size: 12px" v-if="t.property_title">
                Объект: {{ t.property_title }}
              </div>
            </td>
            <td>
              <span class="tag tag--type">{{ t.task_type_display || taskTypeLabel(t.task_type) }}</span>
            </td>
            <td>
              <div class="assignee-cell">
                <span>{{ t.assignee_username }}</span>
                <TaskMineBadge :task="t" :user-id="auth.user?.id" mode="full" />
              </div>
            </td>
            <td>
              <router-link v-if="t.request" :to="`/requests/${t.request}`"
                           class="link">
                №{{ t.request }}
              </router-link>
              <span v-else class="muted">—</span>
            </td>
            <td>
              <span class="tag" :class="priorityClass(t.priority)">
                {{ priorityLabel(t.priority) }}
              </span>
            </td>
            <td class="muted" style="white-space: nowrap">
              {{ t.due_date ? formatDate(t.due_date) : '—' }}
              <span v-if="t.is_overdue" class="tag overdue">просрочено</span>
            </td>
            <td>
              <span class="tag tag--accent">{{ t.status_name }}</span>
              <div v-if="t.is_auto_closed"
                   class="auto-closed-badge" title="Задача закрыта автоматически">
                авто
              </div>
            </td>
            <td class="task-actions">
              <!-- Открыть пошаговый экран работы с клиентом.
                   Показываем только тем, кому эта задача назначена,
                   и только пока она не завершена. -->
              <button v-if="canOpenWorkflow(t)"
                      class="btn btn--sm btn--primary"
                      @click="openWorkflow(t)">
                Открыть
              </button>
              <button v-if="canStart(t)"
                      class="btn btn--sm btn--accent"
                      :disabled="!canStartBtn(t) || busyId === t.id"
                      :title="!canStartBtn(t) ? 'У сотрудника уже есть задача в работе' : 'Взять в работу'"
                      @click="startTask(t)">
                Старт
              </button>
              <button v-if="canPause(t)"
                      class="btn btn--sm"
                      :disabled="busyId === t.id"
                      @click="pauseTask(t)">
                Пауза
              </button>
              <button v-if="canComplete(t)"
                      class="btn btn--sm btn--ghost"
                      :disabled="busyId === t.id"
                      @click="openCompleteModal(t)">
                Завершить
              </button>
              <select class="select select--sm"
                      :value="t.status"
                      @change="changeStatus(t, $event.target.value)">
                <option disabled value="">Статус…</option>
                <option v-for="s in statuses" :key="s.id" :value="s.id">
                  {{ s.name }}
                </option>
              </select>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!filtered.length" class="empty">Задач нет.</div>
    </div>

    <!-- Таблица задач: история. Акцент на длительности и результате —
         это то, что сотруднику / менеджеру нужно видеть первым. -->
    <div v-else class="panel panel--light">
      <table class="table">
        <thead>
          <tr>
            <th>Задача</th>
            <th>Тип</th>
            <th>Исполнитель</th>
            <th>Заявка</th>
            <th>Завершена</th>
            <th>Длительность</th>
            <th>Результат</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in history" :key="t.id">
            <td>
              <b>{{ t.title }}</b>
              <div class="muted" style="font-size: 12px" v-if="t.property_title">
                Объект: {{ t.property_title }}
              </div>
            </td>
            <td>
              <span class="tag tag--type">{{ t.task_type_display || taskTypeLabel(t.task_type) }}</span>
            </td>
            <td>{{ t.assignee_username }}</td>
            <td>
              <router-link v-if="t.request" :to="`/requests/${t.request}`" class="link">
                №{{ t.request }}
              </router-link>
              <span v-else class="muted">—</span>
            </td>
            <td class="muted" style="white-space: nowrap">
              {{ t.completed_at ? formatDate(t.completed_at) : '—' }}
            </td>
            <td class="muted" style="white-space: nowrap">
              {{ humanDuration(t) }}
            </td>
            <td class="history-result">
              <div class="tag tag--accent" v-if="t.status_code === 'done'">выполнена</div>
              <div class="tag" v-else-if="t.status_code === 'cancelled'" style="background:#fde7e4;color:#c2554a">отменена</div>
              <div class="muted" style="font-size: 12px; margin-top: 4px" v-if="resultSummary(t)">
                {{ resultSummary(t) }}
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!history.length" class="empty">Выполненных задач пока нет.</div>
    </div>

    <!-- Модалка завершения задачи -->
    <Teleport to="body">
      <div v-if="completeModal.show" class="modal-overlay" @click.self="closeCompleteModal">
        <div class="modal">
          <h3 class="h3">Завершение задачи</h3>
          <p class="muted" style="margin-top: 8px">
            {{ completeModal.task?.title }}
          </p>
          <div class="field" style="margin-top: 16px">
            <label>Результат выполнения (опционально)</label>
            <textarea class="textarea" v-model="completeModal.result"
                      rows="4" placeholder="Опишите результат..."></textarea>
          </div>
          <div class="row" style="gap: 10px; justify-content: flex-end; margin-top: 20px">
            <button class="btn" @click="closeCompleteModal">Отмена</button>
            <button class="btn btn--accent" @click="confirmComplete"
                    :disabled="busyId === completeModal.task?.id">
              Завершить
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import api from '../api'
import * as tasksApi from '../api/tasks'
import { useAuthStore } from '../store/auth'
import { useWorkloadStore } from '../store/workload'
import TaskMineBadge from '../components/TaskMineBadge.vue'
// Общий форматтер «DD.MM HH:MM» вынесен в utils/formatters.
import { formatDateShort as formatDate } from '@/utils/formatters'

const auth = useAuthStore()
const workload = useWorkloadStore()
const router = useRouter()

const tasks = ref([])
const history = ref([])
const statuses = ref([])
const employees = ref([])
const clients = ref([])
const requests = ref([])
const properties = ref([])

const statusFilter = ref('')
const typeFilter = ref('')
const showForm = ref(false)
const busyId = ref(null)
const viewMode = ref('active')

// Типы задач (соответствуют TASK_TYPE_CHOICES в модели)
const taskTypes = [
  { code: 'contact_client', name: 'Связаться с клиентом' },
  { code: 'property_search', name: 'Подбор объектов' },
  { code: 'showing', name: 'Показ объекта' },
  { code: 'documents', name: 'Подготовка документов' },
  { code: 'call', name: 'Звонок' },
  { code: 'other', name: 'Прочее' },
]

// Тост-уведомления
const toast = reactive({ show: false, message: '', type: 'success' })
function showToast(message, type = 'success') {
  toast.message = message
  toast.type = type
  toast.show = true
  setTimeout(() => { toast.show = false }, 4000)
}

// Модалка завершения
const completeModal = reactive({ show: false, task: null, result: '' })
function openCompleteModal(task) {
  completeModal.task = task
  completeModal.result = ''
  completeModal.show = true
}
function closeCompleteModal() {
  completeModal.show = false
  completeModal.task = null
}

const form = reactive(defaultForm())

function defaultForm () {
  return {
    title: '', description: '',
    assignee: null, priority: 'normal', task_type: 'other',
    due_date: '', request: null, client: null, property: null,
  }
}

// ---- Списки «активные / история» -----------------------------------------
// «Активные» — это всё, кроме done/cancelled. Фильтр локальный —
// сортируем в памяти, т.к. массив уже загружен в tasks.
const TERMINAL_CODES = ['done', 'cancelled']
const activeTasks = computed(() => (
  tasks.value.filter(t => !TERMINAL_CODES.includes(t.status_code))
))
const activeStatuses = computed(() => (
  statuses.value.filter(s => !TERMINAL_CODES.includes(s.code))
))

const filtered = computed(() => {
  let result = activeTasks.value
  if (statusFilter.value) {
    result = result.filter((t) => t.status === statusFilter.value)
  }
  if (typeFilter.value) {
    result = result.filter((t) => t.task_type === typeFilter.value)
  }
  return result
})

const activeCount = computed(() => activeTasks.value.length)
const historyCount = computed(() => history.value.length)

function countByStatus (id) {
  return activeTasks.value.filter((t) => t.status === id).length
}

function taskTypeLabel (code) {
  return taskTypes.find(t => t.code === code)?.name || code
}

function priorityLabel (p) {
  return ({ low: 'Низкий', normal: 'Обычный', high: 'Высокий' })[p] || p
}
function priorityClass (p) {
  if (p === 'high') return 'tag--accent'
  if (p === 'low') return 'tag--panel'
  return ''
}

/**
 * Пытаемся вывести длительность задачи: если на клиенте есть хотя бы
 * created_at и completed_at — считаем разницу; иначе «—».
 */
function humanDuration (t) {
  if (!t.created_at || !t.completed_at) return '—'
  const ms = new Date(t.completed_at) - new Date(t.created_at)
  if (!Number.isFinite(ms) || ms < 0) return '—'
  const min = Math.round(ms / 60000)
  if (min < 60) return `${min} мин`
  const hours = Math.floor(min / 60)
  const rest = min % 60
  if (hours < 24) return rest ? `${hours} ч ${rest} мин` : `${hours} ч`
  const days = Math.floor(hours / 24)
  return `${days} дн ${hours % 24} ч`
}

/**
 * Результат может храниться как строка или как объект {summary, ...}.
 * Пользователю показываем summary (первым), либо текст целиком.
 */
function resultSummary (t) {
  if (!t.result) return ''
  if (typeof t.result === 'string') return t.result
  return t.result.summary || ''
}

function toggleForm () {
  showForm.value = !showForm.value
  if (showForm.value) Object.assign(form, defaultForm())
}

function isMine (t) { return t.assignee === auth.user?.id }
function isMyActive (t) {
  return isMine(t) && t.status_code === 'in_progress'
}

async function load () {
  const [t, s, e, c, r, p] = await Promise.all([
    api.get('/tasks/'),
    api.get('/task-statuses/'),
    api.get('/users/', { params: { user_type: 'employee' } }),
    api.get('/users/', { params: { user_type: 'client' } }),
    api.get('/requests/'),
    api.get('/properties/'),
  ])
  tasks.value = t.data.results || t.data
  statuses.value = s.data.results || s.data
  employees.value = e.data.results || e.data
  clients.value = c.data.results || c.data
  requests.value = r.data.results || r.data
  properties.value = p.data.results || p.data
}

/**
 * Загрузка истории: запрос уходит напрямую на /tasks/ с фильтром
 * по статусам done/cancelled, а для сотрудника — дополнительно
 * assignee=me (алиас, который понимает TaskViewSet.get_queryset).
 */
async function loadHistory () {
  const params = {
    status_code: 'done,cancelled',
    ordering: '-completed_at',
    page_size: 100,
  }
  if (!auth.isManager) params.assignee = 'me'
  const { data } = await api.get('/tasks/', { params })
  history.value = data.results || data
}

function setViewMode (mode) {
  viewMode.value = mode
  if (mode === 'history') loadHistory()
}

async function create () {
  const payload = { ...form }
  if (!payload.due_date) delete payload.due_date
  if (!payload.request) delete payload.request
  if (!payload.client) delete payload.client
  if (!payload.property) delete payload.property
  try {
    await api.post('/tasks/', payload)
    showForm.value = false
    Object.assign(form, defaultForm())
    showToast('Задача создана')
    await load()
  } catch (err) {
    showToast(err.response?.data?.detail || 'Не удалось создать задачу', 'error')
  }
}

async function changeStatus (task, statusId) {
  if (!statusId) return
  const { ok, data, error } = await tasksApi.changeTaskStatus(task.id, statusId)
  if (ok) {
    // Применяем свежий объект к строке таблицы без full reload.
    applyTaskPatch(data)
    showToast('Статус изменён')
  } else {
    showToast(error, 'error')
  }
}

// --- права на быстрые действия --------------------------------------------
function isOwnOrManaged (task) {
  return auth.isManager || task.assignee === auth.user?.id
}
function canStart (task) {
  return isOwnOrManaged(task)
    && ['new', 'waiting'].includes(task.status_code)
}
function canPause (task) {
  return isOwnOrManaged(task) && task.status_code === 'in_progress'
}
function canComplete (task) {
  return isOwnOrManaged(task)
    && ['new', 'in_progress', 'waiting'].includes(task.status_code)
}
function canOpenWorkflow (task) {
  // «Открыть» показываем только владельцу задачи — менеджер смотрит
  // задачу через обычный просмотр, не мешая пошаговой работе.
  return task.assignee === auth.user?.id
    && !TERMINAL_CODES.includes(task.status_code)
}
function canStartBtn (task) {
  if (auth.isManager) return true
  if (task.assignee !== auth.user?.id) return false
  return workload.workload.in_progress_tasks
      < workload.workload.max_in_progress_tasks
}

/**
 * Встраиваем обновлённый объект задачи в массив tasks. Это позволяет
 * не гонять лишний GET /tasks/ после каждого действия и делает UI
 * мгновенно отзывчивым.
 */
function applyTaskPatch (task) {
  if (!task || !task.id) return
  const idx = tasks.value.findIndex(t => t.id === task.id)
  if (idx >= 0) tasks.value.splice(idx, 1, task)
  else tasks.value.push(task)
}

async function startTask (task) {
  busyId.value = task.id
  // Оптимистичный апдейт: сразу ставим статус in_progress и
  // занимаем слот нагрузки. Если API вернёт ошибку — откатим.
  const prevStatusCode = task.status_code
  const prevStatus = task.status
  const inProgress = statuses.value.find(s => s.code === 'in_progress')
  if (inProgress) {
    applyTaskPatch({
      ...task,
      status_code: 'in_progress',
      status: inProgress.id,
      status_name: inProgress.name,
    })
  }
  workload.optimisticStartTask({ ...task, status_code: 'in_progress' })

  const { ok, data, error } = await tasksApi.startTask(task.id)
  if (ok) {
    applyTaskPatch(data)
    showToast('Задача взята в работу')
  } else {
    // Откат: возвращаем исходный статус.
    applyTaskPatch({
      ...task,
      status_code: prevStatusCode,
      status: prevStatus,
    })
    workload.refresh()
    showToast(error || 'Нельзя стартовать задачу: превышен лимит', 'error')
  }
  busyId.value = null
}

async function pauseTask (task) {
  busyId.value = task.id
  const { ok, data, error } = await tasksApi.pauseTask(task.id)
  if (ok) {
    applyTaskPatch(data)
    showToast('Задача приостановлена')
  } else {
    showToast(error || 'Не удалось приостановить задачу', 'error')
  }
  busyId.value = null
}

async function confirmComplete () {
  const task = completeModal.task
  if (!task) return
  busyId.value = task.id

  // Оптимистично: сразу освобождаем слот, чтобы сотрудник видел,
  // что может взять следующую задачу, и переносим задачу в «историю».
  workload.optimisticCompleteTask(task.id)

  const payload = completeModal.result
    ? { summary: completeModal.result }
    : {}
  const { ok, data, error } = await tasksApi.completeTask(task.id, payload)
  if (ok) {
    applyTaskPatch(data)
    // Если открыта вкладка истории — подгрузим свежий срез.
    if (viewMode.value === 'history') loadHistory()
    showToast('Задача завершена')
    closeCompleteModal()
  } else {
    // Откат нагрузки и возврат статуса.
    workload.refresh()
    showToast(error || 'Не удалось завершить задачу', 'error')
  }
  busyId.value = null
}

function openWorkflow (task) {
  router.push({ name: 'task-workflow', params: { id: task.id } })
}

onMounted(async () => {
  await load()
  if (auth.isStaff) workload.refresh()
})
</script>

<style scoped>
.link { color: var(--c-accent); font-weight: 500; }
.link:hover { text-decoration: underline; }
.overdue { background: #fee; color: #c2554a; margin-left: 6px; }
.select--sm { padding: 6px 10px; font-size: 13px; }

.task-actions {
  display: flex; gap: 6px; flex-wrap: wrap;
  align-items: center;
}

.workload-banner {
  margin-top: 10px;
  background: rgba(255,255,255,.12);
  color: #fff; font-size: 13px;
  padding: 6px 12px; border-radius: 999px;
  display: inline-flex; gap: 6px; align-items: center;
}
.workload-banner.is-limit {
  background: rgba(194, 85, 74, .9);
}

/* Вкладки «Активные / История» */
.tabs {
  display: flex;
  gap: 4px;
  padding: 4px;
  background: #f1f1ec;
  border-radius: 10px;
  margin-bottom: 16px;
  width: fit-content;
}
.tab {
  background: transparent;
  border: 0;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 600;
  color: var(--c-text-muted);
  border-radius: 8px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  transition: background .15s, color .15s;
}
.tab:hover { color: var(--c-text); }
.tab--active {
  background: #fff;
  color: var(--c-text);
  box-shadow: 0 1px 2px rgba(0,0,0,.06);
}
.tab__count {
  background: rgba(15,58,51,.1);
  color: var(--c-text-muted);
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
}
.tab--active .tab__count {
  background: rgba(15,58,51,.14);
  color: #0f3a33;
}

/* Фильтры */
.filter-row {
  display: flex; flex-wrap: wrap; gap: 16px; align-items: center;
}
.filter-group {
  display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
}
.filter-label {
  font-size: 13px; font-weight: 600; color: var(--c-text-muted);
}

/* Типы задач */
.tag--type {
  background: #e8f4f3; color: #1a5a52; font-size: 11px;
}

/* Индикатор автозакрытия */
.auto-closed-badge {
  display: inline-block;
  font-size: 10px; font-weight: 700;
  text-transform: uppercase;
  background: #e3f2fd; color: #1565c0;
  padding: 2px 6px; border-radius: 4px;
  margin-left: 6px;
}

/* «Моя задача» — подсветка строк */
.mine-cell { width: 18px; padding-left: 14px !important; }
.row--mine > td:first-child {
  box-shadow: inset 3px 0 0 rgba(15, 58, 51, .25);
}
.row--active > td:first-child {
  box-shadow: inset 3px 0 0 #0f3a33;
}
.row--active { background: rgba(15, 58, 51, .03); }

.assignee-cell {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.history-result { min-width: 160px; }

/* Тосты */
.toast {
  position: fixed;
  top: 20px; right: 20px;
  z-index: 1000;
  padding: 14px 20px;
  border-radius: 8px;
  font-size: 14px; font-weight: 500;
  box-shadow: 0 4px 16px rgba(0,0,0,.15);
}
.toast--success { background: #0f3a33; color: #fff; }
.toast--error { background: #c2554a; color: #fff; }
.toast-enter-active, .toast-leave-active {
  transition: all .3s ease;
}
.toast-enter-from, .toast-leave-to {
  opacity: 0; transform: translateX(30px);
}

/* Модалка */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,.5);
  display: flex; align-items: center; justify-content: center;
  z-index: 100;
}
.modal {
  background: #fff;
  border-radius: 12px;
  padding: 24px 28px;
  width: 100%; max-width: 480px;
  box-shadow: 0 20px 50px rgba(0,0,0,.2);
}
</style>
