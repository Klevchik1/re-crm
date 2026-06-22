<template>
  <section class="stack">
    <div class="hero" style="padding: 24px 28px">
      <div class="row row--between" style="flex-wrap: wrap; gap: 12px">
        <div>
          <div class="hero__eyebrow">ЗАЯВКИ</div>
          <h1 class="h2" style="color: #fff; margin-top: 8px">
            {{ auth.isStaff ? 'Заявки клиентов' : 'Мои заявки' }}
          </h1>
          <div style="color: rgba(255,255,255,.75); font-size: 14px; margin-top: 6px">
            {{ auth.isStaff
              ? 'Распределяйте заявки между агентами и ведите подборки объектов'
              : 'Здесь отображаются все ваши обращения к агентству' }}
          </div>
        </div>
        <button class="btn btn--accent" @click="toggleForm">
          {{ showForm ? 'Скрыть форму' : '+ Новая заявка' }}
        </button>
      </div>
    </div>

    <!-- Вкладки + поиск для сотрудника -->
    <div v-if="auth.isStaff" class="panel panel--light">
      <div class="row row--between" style="flex-wrap: wrap; gap: 12px; align-items: center">
        <div class="row" style="gap: 8px; flex-wrap: wrap">
          <button v-for="t in staffTabs" :key="t.value"
                  class="btn btn--sm"
                  :class="{ 'btn--primary': scope === t.value }"
                  @click="scope = t.value">
            {{ t.label }} ({{ t.count }})
          </button>
        </div>
        <div class="search-box">
          <svg class="search-box__icon" viewBox="0 0 20 20" fill="none"
               xmlns="http://www.w3.org/2000/svg" width="16" height="16">
            <circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" stroke-width="1.6"/>
            <path d="M13 13l3.5 3.5" stroke="currentColor" stroke-width="1.6"
                  stroke-linecap="round"/>
          </svg>
          <input class="search-box__input" v-model="clientSearch"
                 placeholder="Поиск по ФИО клиента…" />
          <button v-if="clientSearch" class="search-box__clear"
                  @click="clientSearch = ''">&times;</button>
        </div>
      </div>
    </div>

    <!-- Форма создания -->
    <form v-if="showForm" class="panel panel--light stack"
          @submit.prevent="createRequest">
      <div class="grid grid--3">
        <div v-if="auth.isStaff" class="field">
          <label>Клиент</label>
          <select class="select" v-model.number="form.client" required>
            <option :value="null" disabled>— выберите —</option>
            <option v-for="c in clients" :key="c.id" :value="c.id">
              {{ c.username }}
            </option>
          </select>
        </div>
        <div v-if="auth.isStaff" class="field">
          <label>Агент (опционально)</label>
          <select class="select" v-model.number="form.agent">
            <option :value="null">— не назначен —</option>
            <option v-for="a in agents" :key="a.id" :value="a.id">
              {{ a.username }}
            </option>
          </select>
        </div>
        <div class="field">
          <label>Операция</label>
          <select class="select" v-model.number="form.operation_type" required>
            <option v-for="o in operations" :key="o.id" :value="o.id">
              {{ o.name }}
            </option>
          </select>
        </div>
        <div class="field">
          <label>Конкретный объект (опционально)</label>
          <select class="select" v-model.number="form.property">
            <option :value="null">— подбор по критериям —</option>
            <option v-for="p in properties" :key="p.id" :value="p.id">
              {{ p.title || 'Объект №' + p.id }} · {{ formatMoney(p.price) }} ₽
            </option>
          </select>
        </div>
        <div class="field">
          <label>Тип недвижимости</label>
          <input class="input" v-model="form.property_type"
                 placeholder="Квартира, дом, коммерч." />
        </div>
        <div class="field">
          <label>Комнат</label>
          <input class="input" type="number" v-model.number="form.rooms_count" />
        </div>
        <div class="field">
          <label>Цена от / до</label>
          <div class="row">
            <input class="input" type="number" v-model.number="form.min_price" />
            <input class="input" type="number" v-model.number="form.max_price" />
          </div>
        </div>
      </div>
      <div class="field">
        <label>Пожелания</label>
        <textarea class="textarea" v-model="form.description" rows="3"></textarea>
      </div>
      <div v-if="formError" class="error">{{ formError }}</div>
      <div class="row" style="justify-content: flex-end">
        <button class="btn btn--accent" type="submit">Создать заявку</button>
      </div>
    </form>

    <!-- Список -->
    <div class="panel panel--light">
      <table class="table">
        <thead>
          <tr>
            <th>Клиент</th>
            <th>Агент</th>
            <th>Объект</th>
            <th>Операция</th>
            <th>Бюджет</th>
            <th>Статус</th>
            <th>Создана</th>
            <th v-if="auth.isStaff"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in visibleRequests" :key="r.id">
            <!-- Колонка клиент / ссылка на заявку -->
            <td>
              <router-link :to="`/requests/${r.id}`" class="link client-link">
                {{ r.client_username || 'Клиент' }}
              </router-link>
            </td>
            <td>
              <span v-if="r.agent_username">{{ r.agent_username }}</span>
              <span v-else class="tag">не назначен</span>
            </td>
            <td>
              <router-link v-if="r.property"
                           :to="`/properties/${r.property}`" class="link">
                {{ r.property_title || 'Объект №' + r.property }}
              </router-link>
              <span v-else class="muted">подбор</span>
            </td>
            <td>{{ r.operation_type_name }}</td>
            <td style="white-space: nowrap">
              {{ formatMoney(r.min_price) }}–{{ formatMoney(r.max_price) }} ₽
            </td>
            <td>
              <span class="tag" :class="statusClass(r)">{{ r.status_name }}</span>
            </td>
            <td class="muted" style="white-space: nowrap">
              {{ new Date(r.created_at).toLocaleDateString('ru-RU') }}
            </td>
            <!-- Выпадающий список действий — только сотрудникам -->
            <td v-if="auth.isStaff">
              <select class="select select--sm actions-select"
                      :disabled="!hasActions(r)"
                      @change="handleAction(r, $event.target.value); $event.target.value = ''">
                <option value="" disabled selected>Действия</option>
                <option v-if="!r.agent" value="take"
                        :disabled="takeDisabled"
                        :title="takeDisabled
                          ? 'Лимит: ' + workload.activeRequestsLabel
                          : undefined">
                  {{ takeDisabled ? 'Взять (лимит)' : 'Взять в работу' }}
                </option>
                <option v-if="r.can_close" value="close">Закрыть заявку</option>
              </select>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!visibleRequests.length" class="empty">
        {{ emptyLabel }}
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import api from '../api'
import { useAuthStore } from '../store/auth'
import { useWorkloadStore } from '../store/workload'
import { formatMoney } from '@/utils/formatters'

const auth = useAuthStore()
const workload = useWorkloadStore()

const requests = ref([])
const clients = ref([])
const agents = ref([])
const operations = ref([])
const properties = ref([])

const showForm = ref(false)
const formError = ref('')
const scope = ref('all')  // all | unassigned | mine
const clientSearch = ref('')

const form = reactive(defaultForm())

function defaultForm () {
  return {
    client: null, agent: null, operation_type: null,
    property: null, property_type: '', rooms_count: null,
    min_price: null, max_price: null, description: '',
  }
}

const staffTabs = computed(() => [
  { value: 'all', label: 'Все', count: requests.value.length },
  { value: 'unassigned', label: 'Неразобранное',
    count: requests.value.filter(r => !r.agent).length },
  { value: 'mine', label: 'Мои',
    count: requests.value.filter(r => r.agent === auth.user?.id).length },
])

const visibleRequests = computed(() => {
  let list = requests.value

  // Фильтр по вкладке (только для сотрудника)
  if (auth.isStaff) {
    if (scope.value === 'unassigned') list = list.filter(r => !r.agent)
    else if (scope.value === 'mine') list = list.filter(r => r.agent === auth.user?.id)
  }

  // Поиск по ФИО клиента
  const q = clientSearch.value.trim().toLowerCase()
  if (q) {
    list = list.filter(r =>
      (r.client_username || '').toLowerCase().includes(q)
    )
  }

  return list
})

const emptyLabel = computed(() => {
  if (clientSearch.value.trim()) return 'Клиент не найден.'
  if (!auth.isStaff) return 'Вы пока не подавали заявок.'
  if (scope.value === 'unassigned') return 'Нет нераспределённых заявок.'
  if (scope.value === 'mine') return 'У вас нет активных заявок.'
  return 'Заявок ещё не создано.'
})

const takeDisabled = computed(() =>
  !auth.isManager && !workload.workload.can_take_request,
)

function hasActions (r) {
  return (!r.agent) || r.can_close
}

function statusClass (r) {
  const code = r.status_code
  if (code === 'closed') return 'tag--panel'
  if (code === 'cancelled') return ''
  if (code === 'processing') return 'tag--accent'
  return 'tag--accent'
}

function toggleForm () {
  showForm.value = !showForm.value
  if (showForm.value) {
    formError.value = ''
    Object.assign(form, defaultForm())
    if (operations.value.length) {
      form.operation_type = operations.value[0].id
    }
  }
}

async function handleAction (r, action) {
  if (action === 'take') await takeRequest(r)
  if (action === 'close') await closeRequest(r)
}

async function load () {
  const requests_req = api.get('/requests/')
  const operations_req = api.get('/operation-types/')
  const properties_req = api.get('/properties/')
  const clients_req = auth.isStaff
    ? api.get('/users/', { params: { user_type: 'client' } })
    : Promise.resolve({ data: [] })
  const agents_req = auth.isStaff
    ? api.get('/users/', { params: { user_type: 'employee' } })
    : Promise.resolve({ data: [] })

  const [r, c, a, o, p] = await Promise.all([
    requests_req, clients_req, agents_req, operations_req, properties_req,
  ])
  requests.value = r.data.results || r.data
  clients.value = c.data.results || c.data
  agents.value = a.data.results || a.data
  operations.value = o.data.results || o.data
  properties.value = p.data.results || p.data
  if (operations.value.length && !form.operation_type) {
    form.operation_type = operations.value[0].id
  }
}

async function createRequest () {
  formError.value = ''
  try {
    const payload = { ...form }
    if (!auth.isStaff) {
      delete payload.client
      delete payload.agent
    }
    if (!payload.property) delete payload.property
    await api.post('/requests/', payload)
    showForm.value = false
    Object.assign(form, defaultForm())
    if (operations.value.length) form.operation_type = operations.value[0].id
    await load()
  } catch (err) {
    formError.value = err.response?.data
      ? Object.values(err.response.data).flat().join(' ')
      : 'Не удалось создать заявку.'
  }
}

async function takeRequest (r) {
  if (!auth.isManager && !workload.workload.can_take_request) {
    alert(`Нельзя взять заявку: уже ${workload.workload.active_requests} в работе `
      + `из ${workload.workload.max_active_requests}. Закройте текущую.`)
    return
  }
  try {
    await api.post(`/requests/${r.id}/take/`)
  } catch (err) {
    alert(err.response?.data?.detail
      || 'Не удалось взять заявку. Возможно, превышен лимит.')
  }
  await Promise.all([load(), workload.refresh()])
}

async function closeRequest (r) {
  if (!confirm('Закрыть заявку?')) return
  const res = await api.post(`/requests/${r.id}/close/`)
  if (res?.data?.deal?.deal_number) {
    const d = res.data.deal
    alert(
      `Заявка закрыта. На её основе создана сделка ${d.deal_number} `
      + `в разделе «Сделки». PDF-договор готов к скачиванию.`,
    )
  }
  await Promise.all([load(), workload.refresh()])
}

onMounted(async () => {
  await load()
  if (auth.isStaff) workload.refresh()
})
</script>

<style scoped>
.link { color: var(--c-accent); font-weight: 500; }
.link:hover { text-decoration: underline; }

.client-link {
  font-weight: 600;
  font-size: 14px;
}

/* Поисковая строка */
.search-box {
  position: relative;
  display: flex;
  align-items: center;
  min-width: 220px;
}
.search-box__icon {
  position: absolute;
  left: 10px;
  color: var(--c-muted);
  pointer-events: none;
  flex-shrink: 0;
}
.search-box__input {
  width: 100%;
  padding: 7px 32px 7px 32px;
  border: 1.5px solid #d2dedd;
  border-radius: var(--r-pill);
  background: var(--c-paper-2);
  color: var(--c-ink);
  font-size: 13px;
  outline: none;
  transition: border-color .15s;
}
.search-box__input:focus { border-color: var(--c-accent); }
.search-box__clear {
  position: absolute;
  right: 10px;
  font-size: 16px;
  color: var(--c-muted);
  line-height: 1;
  cursor: pointer;
}
.search-box__clear:hover { color: var(--c-ink); }

/* Компактный select действий */
.actions-select {
  min-width: 120px;
  cursor: pointer;
}
.actions-select:disabled {
  opacity: 0.4;
  cursor: default;
}
</style>
