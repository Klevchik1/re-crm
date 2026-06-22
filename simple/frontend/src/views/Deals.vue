<template>
  <section class="stack">
    <div class="hero" style="padding: 24px 28px">
      <div class="row row--between" style="flex-wrap: wrap; gap: 12px; align-items: center">
        <div>
          <div class="hero__eyebrow">СДЕЛКИ</div>
          <h1 class="h2" style="color: #fff; margin-top: 8px">Журнал сделок</h1>
          <div style="color: rgba(255,255,255,.75); font-size: 14px; margin-top: 6px">
            Воронка продаж: от первого контакта до завершения сделки
          </div>
        </div>
        <!-- Поиск -->
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

    <!-- Фильтр по статусам -->
    <div class="panel panel--light">
      <div class="row" style="gap: 8px; flex-wrap: wrap">
        <button class="btn btn--sm"
                :class="{ 'btn--primary': statusFilter === '' }"
                @click="statusFilter = ''">
          Все ({{ deals.length }})
        </button>
        <button v-for="s in statuses" :key="s.id"
                class="btn btn--sm"
                :class="{ 'btn--primary': statusFilter === s.id }"
                @click="statusFilter = s.id">
          {{ s.name }} ({{ countByStatus(s.id) }})
        </button>
      </div>
    </div>

    <div class="panel panel--light">
      <table class="table">
        <thead>
          <tr>
            <th>Номер / Клиент</th>
            <th>Объект</th>
            <th>Тип</th>
            <th>Стоимость, ₽</th>
            <th>Комиссия</th>
            <th>Статус</th>
            <th>Дата</th>
            <th style="width: 200px"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in filtered" :key="d.id">
            <!-- Номер сделки + ФИО клиента -->
            <td>
              <b style="font-size: 14px">{{ d.deal_number }}</b>
              <div v-if="d.client_username" class="muted" style="font-size: 12px; margin-top: 2px">
                {{ d.client_username }}
              </div>
            </td>
            <td>{{ d.property_title || 'Объект №' + d.property }}</td>
            <td><span class="tag tag--accent">{{ d.operation_type_name }}</span></td>
            <td style="white-space: nowrap">{{ formatMoney(d.price_final) }}</td>
            <td style="white-space: nowrap">
              {{ d.commission_percent || '—' }}%
              <span class="muted">
                ({{ d.commission_amount ? formatMoney(d.commission_amount) + ' ₽' : '—' }})
              </span>
            </td>
            <td>
              <span class="tag" :class="statusClass(d.status_name)">
                {{ d.status_name || '—' }}
              </span>
            </td>
            <td class="muted" style="white-space: nowrap">
              {{ new Date(d.deal_date).toLocaleDateString('ru-RU') }}
            </td>
            <!-- Выпадающий список: договор + смена статуса -->
            <td>
              <select class="select select--sm actions-select"
                      @change="handleAction(d, $event.target.value); $event.target.value = ''">
                <option value="" disabled selected>Действия</option>
                <optgroup label="Договор">
                  <option v-if="d.contract_url" value="download">Скачать PDF</option>
                  <option v-else value="regenerate">Сформировать PDF</option>
                </optgroup>
                <optgroup label="Изменить статус">
                  <option v-for="s in statuses" :key="s.id" :value="`status:${s.id}`">
                    {{ s.name }}
                  </option>
                </optgroup>
              </select>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!filtered.length" class="empty">
        {{ clientSearch.trim()
          ? 'Клиент не найден.'
          : 'Сделок по выбранному статусу нет.' }}
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import api from '../api'
import { formatMoney as fmtMoney } from '@/utils/formatters'

const deals = ref([])
const statuses = ref([])
const statusFilter = ref('')
const clientSearch = ref('')

function formatMoney (v) { return fmtMoney(v, '0') }

const filtered = computed(() => {
  let list = deals.value

  // Фильтр по статусу
  if (statusFilter.value) {
    list = list.filter((d) => d.status === statusFilter.value)
  }

  // Поиск по ФИО клиента
  const q = clientSearch.value.trim().toLowerCase()
  if (q) {
    list = list.filter(d =>
      (d.client_username || '').toLowerCase().includes(q)
    )
  }

  return list
})

function countByStatus(id) {
  return deals.value.filter((d) => d.status === id).length
}

function statusClass(name) {
  const n = (name || '').toLowerCase()
  if (n.includes('заверш')) return 'tag--accent'
  if (n.includes('отмен')) return 'tag--panel'
  return ''
}

async function handleAction(deal, action) {
  if (action === 'download') await downloadContract(deal)
  else if (action === 'regenerate') await regenerate(deal)
  else if (action.startsWith('status:')) {
    const statusId = action.split(':')[1]
    await changeStatus(deal, statusId)
  }
}

async function changeStatus(deal, statusId) {
  if (!statusId) return
  await api.post(`/deals/${deal.id}/change_status/`, { status_id: Number(statusId) })
  await load()
}

async function downloadContract(deal) {
  try {
    const res = await api.get(`/deals/${deal.id}/contract/`, { responseType: 'blob' })
    const blob = new Blob([res.data], { type: 'application/pdf' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `contract-${deal.deal_number}.pdf`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch (err) {
    alert('Не удалось скачать договор.')
  }
}

async function regenerate(deal) {
  try {
    await api.post(`/deals/${deal.id}/regenerate_contract/`)
    await load()
  } catch (err) {
    alert(err.response?.data?.detail || 'Не удалось сформировать договор.')
  }
}

async function load() {
  const [d, s] = await Promise.all([
    api.get('/deals/'),
    api.get('/deal-statuses/'),
  ])
  deals.value = d.data.results || d.data
  statuses.value = s.data.results || s.data
}

onMounted(load)
</script>

<style scoped>
/* Поисковая строка */
.search-box {
  position: relative;
  display: flex;
  align-items: center;
  min-width: 240px;
}
.search-box__icon {
  position: absolute;
  left: 10px;
  color: rgba(255,255,255,.6);
  pointer-events: none;
  flex-shrink: 0;
}
.search-box__input {
  width: 100%;
  padding: 8px 32px 8px 32px;
  border: 1.5px solid rgba(255,255,255,.2);
  border-radius: var(--r-pill);
  background: rgba(255,255,255,.08);
  color: #fff;
  font-size: 13px;
  outline: none;
  transition: background .15s, border-color .15s;
}
.search-box__input::placeholder {
  color: rgba(255,255,255,.5);
}
.search-box__input:focus {
  border-color: rgba(255,255,255,.4);
  background: rgba(255,255,255,.12);
}
.search-box__clear {
  position: absolute;
  right: 10px;
  font-size: 18px;
  color: rgba(255,255,255,.6);
  line-height: 1;
  cursor: pointer;
}
.search-box__clear:hover { color: #fff; }

/* Компактный select действий */
.actions-select {
  min-width: 100%;
  cursor: pointer;
  font-size: 13px;
}
</style>
