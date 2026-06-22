<!--
  TaskWorkflow — пошаговый экран выполнения задачи сотрудником.

  Открывается кнопкой «Открыть задачу» из таблицы /tasks и виджета
  CurrentTaskWidget. Идея — провести сотрудника по понятному пути:

    1) Контакт      — позвонил / написал / не дозвонился
    2) Заявка       — подтвердить существующую заявку клиента
                      или быстро создать новую, если её нет
    3) Подбор       — для задач подбора: подобрал объект /
                      назначил показ / подтвердил вариант
                      (для остальных задач шаг автоматически «пропускается»)
    4) Завершение   — зафиксировать результат и закрыть задачу

  Каждое действие, которое сотрудник выполняет внутри шага, уходит
  на бэкенд как POST /tasks/:id/record_step/. Это пишет запись в
  Task.steps_log — будущий лог удобно показывать в истории.
-->
<template>
  <section class="stack" v-if="task">
    <!-- Шапка с контекстом -->
    <div class="hero" style="padding: 24px 28px">
      <div class="row row--between" style="flex-wrap: wrap; gap: 12px">
        <div>
          <div class="hero__eyebrow">ВЫПОЛНЕНИЕ ЗАДАЧИ №{{ task.id }}</div>
          <h1 class="h2" style="color: #fff; margin-top: 8px">{{ task.title }}</h1>
          <div style="color: rgba(255,255,255,.8); font-size: 14px; margin-top: 6px">
            <span class="tag tag--type" style="margin-right: 6px">
              {{ task.task_type_display || task.task_type }}
            </span>
            <span>{{ task.client_username ? 'Клиент: ' + task.client_username : 'Клиент не указан' }}</span>
            <span v-if="task.due_date"> · Срок: {{ formatDate(task.due_date) }}</span>
          </div>
        </div>
        <div class="row" style="gap: 8px; flex-wrap: wrap">
          <router-link to="/tasks" class="btn">← К списку задач</router-link>
        </div>
      </div>
    </div>

    <!-- Тосты -->
    <Transition name="toast">
      <div v-if="toast.show" class="toast" :class="'toast--' + toast.type">
        {{ toast.message }}
      </div>
    </Transition>

    <!-- Прогресс-бар этапов -->
    <div class="panel panel--light">
      <ol class="steps">
        <li v-for="(s, i) in steps" :key="s.id"
            class="step"
            :class="{
              'step--done': i < currentStepIdx,
              'step--active': i === currentStepIdx,
              'step--skipped': s.skipped,
            }">
          <span class="step__num">{{ i + 1 }}</span>
          <span class="step__label">{{ s.label }}</span>
          <span v-if="s.skipped" class="step__hint">пропущено</span>
        </li>
      </ol>
    </div>

    <!-- Тело текущего шага -->
    <div class="panel panel--light workflow-body">

      <!-- ШАГ 1 — Контакт -->
      <template v-if="currentStep.id === 'contact'">
        <h2 class="h3">Шаг 1. Связаться с клиентом</h2>
        <p class="muted" style="margin-top: 4px">
          Зафиксируйте факт связи. После — перейдёте к работе с заявкой.
        </p>

        <div v-if="clientContacts" class="contact-card">
          <div v-if="clientContacts.phone">
            <span class="muted">Телефон: </span>
            <a :href="`tel:${clientContacts.phone}`" class="link">{{ clientContacts.phone }}</a>
          </div>
          <div v-if="clientContacts.email">
            <span class="muted">Email: </span>
            <a :href="`mailto:${clientContacts.email}`" class="link">{{ clientContacts.email }}</a>
          </div>
        </div>

        <div class="field" style="margin-top: 14px">
          <label>Комментарий (опционально)</label>
          <textarea class="textarea" v-model="contactNote" rows="2"
                    placeholder="Например: согласовали встречу на среду"></textarea>
        </div>

        <div class="row" style="gap: 8px; flex-wrap: wrap; margin-top: 12px">
          <button class="btn btn--accent" :disabled="busy"
                  @click="submitContact('called')">
            Позвонил
          </button>
          <button class="btn btn--accent" :disabled="busy"
                  @click="submitContact('messaged')">
            Написал
          </button>
          <button class="btn" :disabled="busy"
                  @click="submitContact('missed')">
            Не дозвонился
          </button>
        </div>
      </template>

      <!-- ШАГ 2 — Заявка -->
      <template v-else-if="currentStep.id === 'request'">
        <h2 class="h3">Шаг 2. Заявка клиента</h2>

        <!-- Сценарий А: к задаче уже привязана заявка -->
        <div v-if="task.request">
          <p class="muted" style="margin-top: 4px">
            Задача связана с заявкой. Откройте её, чтобы обсудить подбор.
          </p>
          <div class="linked-request">
            <div>
              <b>Заявка №{{ task.request }}</b>
              <div class="muted" style="font-size: 13px">
                {{ linkedRequest?.status_name || '—' }} ·
                {{ linkedRequest?.operation_type_name || '—' }}
              </div>
            </div>
            <div class="row" style="gap: 6px">
              <router-link :to="`/requests/${task.request}`"
                           class="btn btn--sm btn--primary">
                Перейти к заявке
              </router-link>
              <button class="btn btn--sm btn--accent" :disabled="busy"
                      @click="submitRequestStep('linked')">
                Далее
              </button>
            </div>
          </div>
        </div>

        <!-- Сценарий Б: у клиента есть активная заявка, но она не привязана -->
        <div v-else-if="clientActiveRequest">
          <p class="muted" style="margin-top: 4px">
            У клиента есть активная заявка — можно продолжить работу по ней.
          </p>
          <div class="linked-request">
            <div>
              <b>Заявка №{{ clientActiveRequest.id }}</b>
              <div class="muted" style="font-size: 13px">
                {{ clientActiveRequest.status_name }} ·
                {{ clientActiveRequest.operation_type_name }}
              </div>
            </div>
            <div class="row" style="gap: 6px">
              <router-link :to="`/requests/${clientActiveRequest.id}`"
                           class="btn btn--sm btn--primary">
                Перейти к заявке
              </router-link>
              <button class="btn btn--sm btn--accent" :disabled="busy"
                      @click="submitRequestStep('exists', clientActiveRequest.id)">
                Далее
              </button>
            </div>
          </div>
        </div>

        <!-- Сценарий В: заявки нет — форма быстрого создания -->
        <div v-else>
          <p class="muted" style="margin-top: 4px">
            У клиента нет активной заявки. Создайте её из разговора.
          </p>
          <div v-if="!task.client" class="warn">
            У задачи не указан клиент — создать заявку из этого экрана
            нельзя. Укажите клиента на странице задачи.
          </div>
          <form v-else class="grid grid--2" style="margin-top: 12px"
                @submit.prevent="createRequest">
            <div class="field">
              <label>Тип операции</label>
              <select class="select" v-model.number="newRequest.operation_type" required>
                <option :value="null" disabled>— выберите —</option>
                <option v-for="o in operationTypes" :key="o.id" :value="o.id">
                  {{ o.name }}
                </option>
              </select>
            </div>
            <div class="field">
              <label>Тип недвижимости</label>
              <input class="input" v-model="newRequest.property_type"
                     placeholder="Квартира / дом / коммерция…" />
            </div>
            <div class="field">
              <label>Цена от</label>
              <input class="input" type="number" v-model.number="newRequest.min_price" />
            </div>
            <div class="field">
              <label>Цена до</label>
              <input class="input" type="number" v-model.number="newRequest.max_price" />
            </div>
            <div class="field">
              <label>Комнат</label>
              <input class="input" type="number" v-model.number="newRequest.rooms_count" />
            </div>
            <div class="field">
              <label>Район / адрес</label>
              <input class="input" v-model="newRequest.address_preferences" />
            </div>
            <div class="field" style="grid-column: 1 / -1">
              <label>Пожелания</label>
              <textarea class="textarea" v-model="newRequest.description" rows="2"></textarea>
            </div>
            <div class="row" style="grid-column: 1 / -1; justify-content: flex-end">
              <button type="submit" class="btn btn--accent" :disabled="busy">
                Создать заявку и продолжить
              </button>
            </div>
          </form>
        </div>
      </template>

      <!-- ШАГ 3 — Подбор/выполнение (только для подборных задач) -->
      <template v-else-if="currentStep.id === 'match'">
        <h2 class="h3">Шаг 3. Подбор объекта</h2>
        <p class="muted" style="margin-top: 4px">
          Подберите объекты для клиента в заявке, затем зафиксируйте,
          какой вариант он подтвердил.
        </p>

        <div v-if="activeRequestId" class="linked-request">
          <div>
            <b>Заявка №{{ activeRequestId }}</b>
            <div class="muted" style="font-size: 13px">
              Работа с подборкой ведётся на странице заявки.
            </div>
          </div>
          <div class="row" style="gap: 6px">
            <router-link :to="`/requests/${activeRequestId}`"
                         class="btn btn--sm btn--primary">
              Открыть подборку
            </router-link>
          </div>
        </div>

        <div class="row" style="gap: 8px; flex-wrap: wrap; margin-top: 14px">
          <button class="btn btn--accent" :disabled="busy"
                  @click="submitMatchStep('proposed')">
            Предложил варианты
          </button>
          <button class="btn btn--accent" :disabled="busy"
                  @click="submitMatchStep('showing_scheduled')">
            Назначил показ
          </button>
          <button class="btn btn--accent" :disabled="busy"
                  @click="submitMatchStep('confirmed')">
            Клиент подтвердил вариант
          </button>
        </div>

        <!-- SmartPay: оплата просмотра (только для задач типа «Показ объекта») -->
        <div v-if="task.task_type === 'showing'" class="payment-block" style="margin-top: 20px">
          <div style="font-weight: 600; font-size: 14px; margin-bottom: 8px">
            Оплата просмотра через SmartPay
          </div>

          <!-- Просмотр ещё не найден/загружается -->
          <div v-if="payment.loadingViewing" class="muted" style="font-size: 13px">
            Ищем запись просмотра…
          </div>

          <!-- Просмотр не найден -->
          <div v-else-if="!payment.viewingId" class="warn">
            Запись просмотра не найдена. Убедитесь, что просмотр создан в системе для этого клиента и объекта.
          </div>

          <!-- Просмотр найден — блок оплаты -->
          <template v-else>
            <!-- Ещё не инициировали -->
            <div v-if="!payment.invoiceId">
              <p class="muted" style="font-size: 13px; margin-bottom: 10px">
                Создайте счёт SmartPay для просмотра №{{ payment.viewingId }}.
                Тестовый токен: сумма 1 ₽, реальная карта, возврат за месяц.
              </p>
              <button class="btn btn--primary" :disabled="payment.busy"
                      @click="initiatePayment(payment.viewingId)">
                {{ payment.busy ? 'Создаём счёт…' : 'Выставить счёт SmartPay' }}
              </button>
              <div v-if="payment.error" class="warn" style="margin-top: 8px">
                {{ payment.error }}
              </div>
            </div>

            <!-- Счёт создан — показываем статус -->
            <div v-else class="payment-status-card">
              <div class="row" style="gap: 12px; flex-wrap: wrap; align-items: center">
                <div>
                  <div style="font-size: 12px; color: #6a7a77; margin-bottom: 2px">Invoice ID</div>
                  <code style="font-size: 12px">{{ payment.invoiceId }}</code>
                </div>
                <div>
                  <div style="font-size: 12px; color: #6a7a77; margin-bottom: 2px">Статус</div>
                  <span class="payment-badge" :class="`payment-badge--${(payment.status || '').toLowerCase()}`">
                    {{ paymentStatusLabel(payment.status) }}
                  </span>
                </div>
                <button class="btn btn--sm" :disabled="payment.busy"
                        @click="checkPaymentStatus(payment.viewingId)">
                  {{ payment.busy ? '…' : 'Обновить статус' }}
                </button>
              </div>
              <div v-if="payment.error" class="warn" style="margin-top: 8px">
                {{ payment.error }}
              </div>
            </div>
          </template>
        </div>
      </template>

      <!-- ШАГ 4 — Завершение -->
      <template v-else-if="currentStep.id === 'complete'">
        <h2 class="h3">Шаг 4. Завершить задачу</h2>
        <p class="muted" style="margin-top: 4px">
          Опишите итог — это попадёт в историю и в отчёты.
        </p>

        <!-- Краткая сводка по шагам, чтобы сотрудник видел, что он
             только что сделал, и не дублировал в итог. -->
        <div v-if="task.steps_log?.length" class="steps-log">
          <div v-for="(entry, i) in task.steps_log" :key="i" class="steps-log__row">
            <span class="steps-log__time">{{ formatDate(entry.at) }}</span>
            <span class="steps-log__body">
              <b>{{ stepLabel(entry.step) }}</b>
              <span v-if="entry.outcome"> — {{ outcomeLabel(entry.outcome) }}</span>
              <span v-if="entry.note" class="muted"> · {{ entry.note }}</span>
            </span>
          </div>
        </div>

        <div class="field" style="margin-top: 14px">
          <label>Результат</label>
          <textarea class="textarea" v-model="completionSummary" rows="4"
                    placeholder="Например: клиент согласился на объект №12, договорились подписать договор 20 мая"></textarea>
        </div>
        <div class="row" style="gap: 8px; justify-content: flex-end">
          <button class="btn btn--accent" :disabled="busy" @click="submitComplete">
            Завершить задачу
          </button>
        </div>
      </template>

      <!-- После финального шага (редиректит вверх), ничего не показываем. -->
    </div>
  </section>
  <div v-else class="empty">Загрузка задачи…</div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../api'
import * as tasksApi from '../api/tasks'
import { useAuthStore } from '../store/auth'
import { useWorkloadStore } from '../store/workload'
// Общий форматтер «DD.MM HH:MM» вынесен в utils/formatters.
import { formatDateShort as formatDate } from '@/utils/formatters'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const workload = useWorkloadStore()

const task = ref(null)
const linkedRequest = ref(null)
const clientActiveRequest = ref(null)
const operationTypes = ref([])
const busy = ref(false)
const contactNote = ref('')
const completionSummary = ref('')

// SmartPay — состояние оплаты просмотра
const payment = reactive({
  viewingId: null,       // PK PropertyViewing, для которого создан счёт
  invoiceId: null,       // invoice_id от SmartPay
  status: null,          // CREATED | PAID | CANCELLED | EXPIRED | UNKNOWN
  busy: false,           // идёт запрос к SmartPay
  error: null,           // текст последней ошибки
  pollTimer: null,       // id setInterval для автопроверки статуса
  loadingViewing: false, // идёт поиск записи PropertyViewing
})

// Форма быстрой заявки
const newRequest = reactive({
  operation_type: null,
  property_type: '',
  min_price: null,
  max_price: null,
  rooms_count: null,
  address_preferences: '',
  description: '',
})

// Тосты
const toast = reactive({ show: false, message: '', type: 'success' })
function showToast (message, type = 'success') {
  toast.message = message
  toast.type = type
  toast.show = true
  setTimeout(() => { toast.show = false }, 4000)
}

// ---------------------------------------------------------------------------
// Шаги мастера
// ---------------------------------------------------------------------------
// Шаг «match» нужен только задачам подбора/показа, для звонков/документов
// он лишний — помечаем его как skipped и не выв��дим как активный.
const MATCH_TASK_TYPES = ['property_search', 'showing']

const steps = computed(() => {
  const isMatchRelevant = MATCH_TASK_TYPES.includes(task.value?.task_type)
  return [
    { id: 'contact',  label: 'Контакт с клиентом', skipped: false },
    { id: 'request',  label: 'Заявка',             skipped: false },
    { id: 'match',    label: 'Подбор/выполнение',  skipped: !isMatchRelevant },
    { id: 'complete', label: 'Завершение',         skipped: false },
  ]
})

// Какие шаги уже пройдены (есть запись в steps_log).
const doneStepIds = computed(() => {
  const ids = new Set()
  for (const entry of task.value?.steps_log || []) {
    if (entry?.step) ids.add(entry.step)
  }
  return ids
})

// Индекс «активного» шага: первый, который не пропущен и не сделан.
const currentStepIdx = computed(() => {
  const list = steps.value
  for (let i = 0; i < list.length; i += 1) {
    const s = list[i]
    if (s.skipped) continue
    if (!doneStepIds.value.has(s.id)) return i
  }
  return list.length - 1
})
const currentStep = computed(() => steps.value[currentStepIdx.value])

// id заявки, по которой ведётся работа: приоритетно — привязанная
// к задаче, иначе — активная заявка клиента, если мы её нашли.
const activeRequestId = computed(() => (
  task.value?.request || clientActiveRequest.value?.id || null
))

// Контакты клиента для шага 1 — берём из связанной заявки,
// если клиент засветил их в заявке.
const clientContacts = ref(null)

// ---------------------------------------------------------------------------
// Загрузка данных
// ---------------------------------------------------------------------------
async function load () {
  const taskId = route.params.id
  const { data } = await api.get(`/tasks/${taskId}/`)
  task.value = data

  // Безопасность на клиенте: если задача не моя и я не менеджер —
  // возвращаем на /tasks, чтобы экран пошаговой работы не вводил в
  // заблуждение (API всё равно запретит действия, но лучше не
  // рендерить экран вообще).
  if (task.value.assignee !== auth.user?.id && !auth.isManager) {
    router.replace('/tasks')
    return
  }

  // Если задача завершена — нет смысла «работать» здесь, отправляем
  // пользователя в историю.
  if (['done', 'cancelled'].includes(task.value.status_code)) {
    router.replace('/tasks')
    return
  }

  const extra = []
  // 1) Справочник типов операций — нужен форме «создать заявку».
  extra.push(api.get('/operation-types/').then((r) => {
    operationTypes.value = r.data.results || r.data
  }).catch(() => { /* справочник может быть на другом пути */ }))

  // 2) Если у задачи уже есть заявка — подгружаем её для контекста.
  if (task.value.request) {
    extra.push(api.get(`/requests/${task.value.request}/`).then((r) => {
      linkedRequest.value = r.data
      clientContacts.value = {
        phone: r.data.client_phone || null,
        email: r.data.client_email || null,
      }
    }).catch(() => {}))
  } else if (task.value.client) {
    // 3) Иначе ищем у клиента активную заявку (не закрытую).
    extra.push(api.get('/requests/', {
      params: { client: task.value.client, page_size: 5 },
    }).then((r) => {
      const list = r.data.results || r.data
      const open = list.find(x => x.status_code !== 'closed')
      clientActiveRequest.value = open || null
    }).catch(() => {}))
  }

  await Promise.all(extra)

  // Для задач типа «Показ объекта» — подгружаем запись PropertyViewing,
  // чтобы блок оплаты SmartPay мог использовать её ID.
  loadViewingForTask()
}

// ---------------------------------------------------------------------------
// Маппинг step'ов в человекочитаемые подписи (для журнала)
// ---------------------------------------------------------------------------
const STEP_LABELS = {
  contact:  'Контакт',
  request:  'Заявка',
  match:    'Подбор',
  complete: 'Завершение',
}
const OUTCOME_LABELS = {
  called:             'позвонил',
  messaged:           'написал',
  missed:             'не дозвонился',
  created:            'создана новая заявка',
  linked:             'связана с существующей заявкой',
  exists:             'использована активная заявка клиента',
  proposed:           'предложил варианты',
  showing_scheduled:  'назначил показ',
  confirmed:          'клиент подтвердил вариант',
}
function stepLabel (id) { return STEP_LABELS[id] || id }
function outcomeLabel (id) { return OUTCOME_LABELS[id] || id }

// ---------------------------------------------------------------------------
// Обработчики шагов
// ---------------------------------------------------------------------------
async function submitContact (outcome) {
  busy.value = true
  const { ok, data, error } = await tasksApi.recordTaskStep(task.value.id, {
    step: 'contact',
    outcome,
    note: contactNote.value || null,
  })
  if (ok) {
    task.value = data
    contactNote.value = ''
    showToast('Этап «Контакт» зафиксирован')
  } else {
    showToast(error, 'error')
  }
  busy.value = false
}

async function submitRequestStep (outcome, requestId = null) {
  busy.value = true
  // Если у задачи нет request, но мы её «привязываем» к существующей
  // заявке клиента — сначала обновляем связь через PATCH, чтобы в
  // RequestDetail, в истории и в фильтрах всё было согласовано.
  if (!task.value.request && requestId) {
    const patch = await tasksApi.patchTask(task.value.id, { request: requestId })
    if (!patch.ok) {
      showToast(patch.error || 'Не удалось привязать заявку', 'error')
      busy.value = false
      return
    }
    task.value = patch.data
  }
  const { ok, data, error } = await tasksApi.recordTaskStep(task.value.id, {
    step: 'request',
    outcome,
    note: null,
  })
  if (ok) {
    task.value = data
    showToast('Этап «Заявка» зафиксирован')
  } else {
    showToast(error, 'error')
  }
  busy.value = false
}

async function createRequest () {
  if (!task.value.client) return
  busy.value = true
  // Собираем payload с отбрасыванием пустых полей, чтобы бэкенд
  // не ругался валидаторами `Decimal/Integer` на строки.
  const payload = { client: task.value.client }
  for (const [k, v] of Object.entries(newRequest)) {
    if (v === null || v === '' || Number.isNaN(v)) continue
    payload[k] = v
  }
  try {
    const { data: req } = await api.post('/requests/', payload)
    // Привязываем новую заявку к задаче, чтобы в дальнейшем она
    // попала в /requests/{id}/ и в отчёты по задаче.
    await tasksApi.patchTask(task.value.id, { request: req.id })
    // И фиксируем шаг
    const res = await tasksApi.recordTaskStep(task.value.id, {
      step: 'request',
      outcome: 'created',
      note: `Создана заявка №${req.id}`,
    })
    if (res.ok) task.value = res.data
    clientActiveRequest.value = req
    showToast('Заявка создана')
  } catch (err) {
    showToast(err.response?.data?.detail || 'Не удалось создать заявку', 'error')
  }
  busy.value = false
}

async function submitMatchStep (outcome) {
  busy.value = true
  const { ok, data, error } = await tasksApi.recordTaskStep(task.value.id, {
    step: 'match',
    outcome,
    note: null,
  })
  if (ok) {
    task.value = data
    showToast('Этап «Подбор» зафиксирован')
  } else {
    showToast(error, 'error')
  }
  busy.value = false
}

async function submitComplete () {
  busy.value = true
  // Оптимистично освобождаем слот сотрудника, чтобы он сразу
  // мог взять следующую задачу из списка /tasks.
  workload.optimisticCompleteTask(task.value.id)
  const payload = completionSummary.value
    ? { summary: completionSummary.value }
    : { summary: 'Задача выполнена' }
  const { ok, error } = await tasksApi.completeTask(task.value.id, payload)
  busy.value = false
  if (ok) {
    showToast('Задача завершена')
    // Возвращаем пользователя в список — там он увидит её на
    // вкладке «История» и сможет взять следующую.
    router.push('/tasks')
  } else {
    // Откат нагрузки через server-truth.
    workload.refresh()
    showToast(error || 'Не удалось завершить задачу', 'error')
  }
}

// formatDate импортируется из utils/formatters (см. шапку script setup).

// ---------------------------------------------------------------------------
// SmartPay — загрузка записи просмотра для задачи типа showing
// ---------------------------------------------------------------------------

/**
 * Найти запись PropertyViewing, связанную с задачей типа «showing».
 * Ищем по клиенту + объекту. Результат сохраняется в payment.viewingId.
 */
async function loadViewingForTask() {
  const t = task.value
  if (!t || t.task_type !== 'showing') return
  if (!t.client || !t.property) return

  payment.loadingViewing = true
  try {
    const res = await api.get('/viewings/', {
      params: { client: t.client, property: t.property, page_size: 5 },
    })
    const list = (res.data.results || res.data || [])
    if (list.length > 0) {
      // Берём самый свежий просмотр (список отсортирован по -scheduled_date).
      payment.viewingId = list[0].id
    }
  } catch (_e) {
    // Не критично — просто не показываем блок оплаты.
  } finally {
    payment.loadingViewing = false
  }
}

// ---------------------------------------------------------------------------
// SmartPay — оплата просмотра
// ---------------------------------------------------------------------------

const PAYMENT_STATUS_LABELS = {
  CREATED:   'Ожидает оплаты',
  PAID:      'Оплачен',
  CANCELLED: 'Отменён',
  REFUNDED:  'Возврат',
  EXPIRED:   'Истёк',
  UNKNOWN:   'Неизвестно',
  ALREADY_CREATED: 'Ожидает оплаты',
}

function paymentStatusLabel(s) {
  return PAYMENT_STATUS_LABELS[s] || s || '—'
}

/**
 * Создать счёт SmartPay для просмотра.
 * viewingId — PK записи PropertyViewing.
 */
async function initiatePayment(viewingId) {
  if (!viewingId) {
    showToast('К задаче не привязан просмотр объекта', 'error')
    return
  }
  payment.busy = true
  payment.error = null
  const { ok, data, error } = await tasksApi.initiateViewingPayment(viewingId)
  payment.busy = false
  if (ok) {
    payment.viewingId = viewingId
    payment.invoiceId = data.invoice_id
    payment.status = data.status
    showToast('Счёт SmartPay создан')
    // Запускаем автопроверку статуса каждые 10 секунд (до 2 минут).
    _startPaymentPoll(viewingId)
  } else {
    payment.error = error || 'Не удалось создать счёт SmartPay'
    showToast(payment.error, 'error')
  }
}

/**
 * Вручную обновить статус счёта SmartPay.
 */
async function checkPaymentStatus(viewingId) {
  if (!viewingId) return
  payment.busy = true
  payment.error = null
  const { ok, data, error } = await tasksApi.getViewingPaymentStatus(viewingId)
  payment.busy = false
  if (ok) {
    payment.status = data.status
    if (data.status === 'PAID') {
      _stopPaymentPoll()
      showToast('Оплата прошла успешно')
    }
  } else {
    payment.error = error || 'Не удалось получить статус'
  }
}

/** Автопроверка статуса раз в 10 с, не дольше 2 минут. */
function _startPaymentPoll(viewingId) {
  _stopPaymentPoll()
  let attempts = 0
  payment.pollTimer = setInterval(async () => {
    attempts += 1
    if (attempts > 12) {        // 12 × 10 с = 2 мин
      _stopPaymentPoll()
      return
    }
    const { ok, data } = await tasksApi.getViewingPaymentStatus(viewingId)
    if (ok) {
      payment.status = data.status
      if (['PAID', 'CANCELLED', 'EXPIRED'].includes(data.status)) {
        _stopPaymentPoll()
        if (data.status === 'PAID') showToast('Оплата прошла успешно')
      }
    }
  }, 10_000)
}

function _stopPaymentPoll() {
  if (payment.pollTimer) {
    clearInterval(payment.pollTimer)
    payment.pollTimer = null
  }
}

onMounted(load)
</script>

<style scoped>
.link { color: var(--c-accent); font-weight: 500; }
.link:hover { text-decoration: underline; }

.tag--type { background: #e8f4f3; color: #1a5a52; font-size: 11px; }

/* Прогресс-бар шагов */
.steps {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  padding: 4px 0;
  list-style: none;
  counter-reset: step;
}
.step {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: 999px;
  background: #f1f4f3;
  color: #6a7a77;
  font-size: 13px;
  font-weight: 500;
}
.step__num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 22px;
  padding: 0 7px;
  border-radius: 999px;
  background: #dbe2e0;
  color: #546664;
  font-weight: 700;
  font-size: 12px;
}
.step__hint {
  font-size: 11px;
  color: #8a9a97;
  font-style: italic;
}
.step--done {
  background: #e0efe9;
  color: #0f3a33;
}
.step--done .step__num {
  background: #0f3a33;
  color: #fff;
}
.step--active {
  background: #0f3a33;
  color: #fff;
}
.step--active .step__num {
  background: #3ddbc7;
  color: #0f3a33;
}
.step--skipped {
  opacity: .55;
  text-decoration: line-through;
}

/* Тело этапа */
.workflow-body { min-height: 200px; }

.contact-card {
  margin-top: 14px;
  padding: 14px 16px;
  background: var(--c-paper-2, #f5f7f6);
  border-radius: 8px;
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 14px;
}

.linked-request {
  margin-top: 14px;
  padding: 14px 16px;
  background: var(--c-paper-2, #f5f7f6);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.warn {
  margin-top: 12px;
  background: #fdece9;
  color: #9a3b32;
  padding: 10px 14px;
  border-radius: 8px;
  font-size: 13px;
}

.payment-block {
  padding: 16px;
  background: var(--c-paper-2, #f5f7f6);
  border-radius: 10px;
  border: 1px solid #dbe6e4;
}

.payment-status-card {
  padding: 12px 14px;
  background: #fff;
  border-radius: 8px;
  border: 1px solid #dbe6e4;
}

.payment-badge {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: #e8f0ef;
  color: #4a6d68;
}
.payment-badge--paid      { background: #d4f5e9; color: #0a5c38; }
.payment-badge--cancelled { background: #fdece9; color: #9a3b32; }
.payment-badge--expired   { background: #fff3e0; color: #8a5700; }
.payment-badge--created   { background: #e3effe; color: #1a4b8c; }

.steps-log {
  margin-top: 12px;
  background: var(--c-paper-2, #f5f7f6);
  border-radius: 8px;
  padding: 10px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
.steps-log__row {
  display: flex;
  gap: 10px;
  align-items: baseline;
}
.steps-log__time {
  color: #8a9a97;
  font-size: 12px;
  flex: 0 0 auto;
  min-width: 90px;
}
.steps-log__body b { font-weight: 700; color: #0f3a33; }

/* Тосты (такие же, как в Tasks.vue) */
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
.toast-enter-active, .toast-leave-active { transition: all .3s ease; }
.toast-enter-from, .toast-leave-to {
  opacity: 0; transform: translateX(30px);
}
</style>
