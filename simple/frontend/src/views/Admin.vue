<template>
  <!--
    Административная панель.
    Доступ ограничен на двух уровнях:
      * route meta.manager + router.beforeEach (проверка isManager);
      * страница дополнительно рендерится через v-if="auth.isManager"
        — запасной контроль на случай прямого рендера компонента.
    В секции редактирования (назначение должностей, роли, сотрудники)
    все мутирующие действия защищены: кнопки активны только для менеджеров,
    запрос к API всё равно отсечёт попытку со стороны обычного сотрудника
    на бэкенде (permission IsAdminOrManager).
  -->
  <section v-if="auth.isManager" class="stack">
    <!-- Заголовок админ-панели -->
    <div class="hero admin-hero">
      <div class="row row--between" style="flex-wrap: wrap; gap: 12px">
        <div>
          <div class="hero__eyebrow">АДМИНИСТРИРОВАНИЕ</div>
          <h1 class="h2" style="color: #fff; margin-top: 8px">
            Панель администратора
          </h1>
          <div style="color: rgba(255,255,255,.75); font-size: 14px; margin-top: 6px">
            Управление сотрудниками, ролями и справочниками системы.
            Доступ разрешён только администраторам и менеджерам.
          </div>
        </div>
        <div class="admin-role-badge">
          <span class="tag tag--accent" style="font-size: 13px; padding: 6px 14px">
            {{ auth.roleLabel }}
          </span>
        </div>
      </div>
    </div>

    <!-- KPI кратко -->
    <div class="grid grid--stats">
      <StatCard label="Сотрудников" :value="counters.employees" accent />
      <StatCard label="Клиентов"    :value="counters.clients" />
      <StatCard label="Ролей"       :value="roles.length" />
      <StatCard label="Супер-админов" :value="counters.superusers" />
    </div>

    <!-- Две «управляющие» плитки -->
    <div class="grid grid--2">
      <!-- Пользователи -->
      <div class="panel panel--light admin-panel">
        <div class="row row--between">
          <span class="tag tag--accent">Пользователи</span>
          <span class="muted">всего: {{ users.length }}</span>
        </div>
        <h2 class="h2" style="margin-top: 8px">Назначение должностей</h2>
        <p class="muted" style="margin: 4px 0 12px">
          Открывает полный список пользователей с возможностью менять тип
          учётной записи и должность.
        </p>
        <div class="row" style="gap: 8px">
          <button class="btn btn--primary" @click="openAssign()">
            Назначить должность
          </button>
          <router-link to="/clients" class="btn">
            Открыть список →
          </router-link>
        </div>
      </div>

      <!-- Django Admin -->
      <div class="panel admin-panel" v-if="auth.isSuperuser || auth.isAdmin">
        <span class="tag tag--panel">Система</span>
        <h2 class="h2" style="color: #fff; margin-top: 8px">
          Django Admin
        </h2>
        <p style="color: rgba(255,255,255,.75); margin: 4px 0 12px">
          Прямой доступ к административной панели Django без повторной авторизации.
        </p>
        <button class="btn btn--accent" @click="openDjangoAdmin">
          Открыть Django Admin →
        </button>
      </div>

      <!-- Справочник должностей -->
      <div class="panel admin-panel">
        <span class="tag tag--panel">Справочник</span>
        <h2 class="h2" style="color: #fff; margin-top: 8px">
          Должности сотрудников
        </h2>
        <p style="color: rgba(255,255,255,.75); margin: 4px 0 12px">
          Создавайте и редактируйте роли — администратор, менеджер, агент.
          Роли управляют правами доступа в системе.
        </p>
        <button class="btn btn--accent" @click="rolesOpen = true">
          Управлять ролями
        </button>
      </div>
    </div>

    <!-- Быстрый список сотрудников -->
    <div class="panel panel--light">
      <div class="row row--between" style="margin-bottom: 12px">
        <h2 class="h2">Сотрудники агентства</h2>
        <router-link to="/clients" class="btn btn--sm">Все →</router-link>
      </div>
      <table class="table">
        <thead>
          <tr>
            <th>Логин</th>
            <th>Почта</th>
            <th>Должность</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in employees.slice(0, 8)" :key="u.id">
            <td><b>{{ u.username }}</b></td>
            <td>{{ u.email || '—' }}</td>
            <td>{{ u.role_name || '—' }}</td>
            <td style="text-align: right">
              <button class="btn btn--sm" @click="openAssign(u)">
                Редактировать
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!employees.length" class="empty">Сотрудники ещё не назначены.</div>
    </div>

    <!-- Модалка: назначение должности -->
    <div v-if="assignOpen" class="modal" @click.self="assignOpen = false">
      <div class="panel panel--light modal__card stack">
        <div class="row row--between">
          <h2 class="h3">Назначение должности</h2>
          <button class="btn btn--sm" @click="assignOpen = false">×</button>
        </div>
        <div v-if="!assignUser" class="field">
          <label>Пользователь</label>
          <select class="select" v-model.number="assignUserId">
            <option :value="null" disabled>— выберите пользователя —</option>
            <option v-for="u in users" :key="u.id" :value="u.id">
              {{ u.username }} — {{ u.email || 'без почты' }}
            </option>
          </select>
        </div>
        <div v-else class="muted">
          Пользователь <b>{{ assignUser.username }}</b>.
        </div>
        <div class="field">
          <label>Тип учётной записи</label>
          <select class="select" v-model="assignForm.user_type">
            <option value="client">Клиент</option>
            <option value="employee">Сотрудник</option>
          </select>
        </div>
        <div class="field" v-if="assignForm.user_type === 'employee'">
          <label>Должность</label>
          <select class="select" v-model.number="assignForm.role_id">
            <option :value="null">— без должности —</option>
            <option v-for="r in roles" :key="r.id" :value="r.id">
              {{ r.name }}
            </option>
          </select>
        </div>
        <div v-if="assignError" class="error">{{ assignError }}</div>
        <div class="row" style="justify-content: flex-end; gap: 8px">
          <button class="btn btn--sm" @click="assignOpen = false">Отмена</button>
          <button class="btn btn--primary btn--sm"
                  :disabled="assignLoading || (!assignUser && !assignUserId)"
                  @click="saveAssign">
            {{ assignLoading ? 'Сохранение…' : 'С��хранить' }}
          </button>
        </div>
      </div>
    </div>

    <!-- Модалка: справочник ролей -->
    <div v-if="rolesOpen" class="modal" @click.self="rolesOpen = false">
      <div class="panel panel--light modal__card stack">
        <div class="row row--between">
          <h2 class="h3">Справочник должностей</h2>
          <button class="btn btn--sm" @click="rolesOpen = false">×</button>
        </div>
        <table class="table">
          <thead>
            <tr><th>Код</th><th>Название</th><th></th></tr>
          </thead>
          <tbody>
            <tr v-for="r in roles" :key="r.id">
              <td><code>{{ r.code }}</code></td>
              <td>{{ r.name }}</td>
              <td style="text-align: right">
                <button class="btn btn--sm btn--danger"
                        @click="removeRole(r)">
                  Удалить
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <form class="row" style="gap: 8px" @submit.prevent="createRole">
          <input class="input" v-model="newRole.code" placeholder="код (agent)"
                 style="flex: 0 0 140px" required />
          <input class="input" v-model="newRole.name" placeholder="название (Агент)"
                 style="flex: 1" required />
          <button class="btn btn--accent btn--sm" type="submit">Добавить</button>
        </form>
        <div v-if="rolesError" class="error">{{ rolesError }}</div>
      </div>
    </div>
  </section>

  <!-- Если каким-то образом роут пробили — отказ -->
  <section v-else class="panel panel--light empty">
    <h2 class="h2">Доступ ограничен</h2>
    <p class="muted">
      Этот раздел доступен только администраторам и менеджерам агентства.
    </p>
    <router-link to="/" class="btn">На главную</router-link>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import api from '../api'
import StatCard from '../components/StatCard.vue'
import { useAuthStore } from '../store/auth'

const auth = useAuthStore()
const users = ref([])
const roles = ref([])

const employees = computed(() =>
  users.value.filter((u) => u.user_type === 'employee')
)
const counters = computed(() => ({
  employees: employees.value.length,
  clients: users.value.filter((u) => u.user_type === 'client').length,
  superusers: users.value.filter((u) => u.is_superuser).length,
}))

// --- Назначение должности -------------------------------------------------
const assignOpen = ref(false)
const assignUser = ref(null)
const assignUserId = ref(null)
const assignLoading = ref(false)
const assignError = ref('')
const assignForm = reactive({ user_type: 'client', role_id: null })

function openAssign (u) {
  assignUser.value = u || null
  assignUserId.value = u?.id ?? null
  assignForm.user_type = u?.user_type || 'client'
  assignForm.role_id = u?.role ?? null
  assignError.value = ''
  assignOpen.value = true
}

async function saveAssign () {
  assignLoading.value = true
  assignError.value = ''
  try {
    const id = assignUser.value?.id || assignUserId.value
    await api.post(`/users/${id}/assign_role/`, {
      user_type: assignForm.user_type,
      role_id: assignForm.user_type === 'employee'
        ? assignForm.role_id : null,
    })
    assignOpen.value = false
    await loadUsers()
  } catch (e) {
    assignError.value = e.response?.data?.detail
      || 'Не удалось сохранить. Проверьте права доступа.'
  } finally {
    assignLoading.value = false
  }
}

// --- Справочник ролей ------------------------------------------------------
const rolesOpen = ref(false)
const rolesError = ref('')
const newRole = reactive({ code: '', name: '' })

async function createRole () {
  rolesError.value = ''
  try {
    await api.post('/user-roles/', {
      code: newRole.code, name: newRole.name,
    })
    newRole.code = ''; newRole.name = ''
    await loadRoles()
  } catch (e) {
    rolesError.value = e.response?.data
      ? Object.values(e.response.data).flat().join(' ')
      : 'Не удалось создать роль.'
  }
}

async function removeRole (r) {
  if (!confirm(`Удалить должность «${r.name}»?`)) return
  try {
    await api.delete(`/user-roles/${r.id}/`)
    await loadRoles()
  } catch (e) {
    rolesError.value = e.response?.data?.detail
      || 'Не удалось удалить.'
  }
}

// --- Django Admin авто-логин -----------------------------------------------
function openDjangoAdmin () {
  const token = localStorage.getItem('access')
  if (!token) {
    alert('Не найден токен авторизации. Войдите в систему заново.')
    return
  }
  // Передаём JWT-токен на бэкенд, который создаст Django-сессию и
  // перенаправит браузер прямо в /admin/ без формы входа.
  window.open(`/api/auth/admin-login/?token=${encodeURIComponent(token)}`, '_blank')
}

// --- Загрузка --------------------------------------------------------------
async function loadUsers () {
  const { data } = await api.get('/users/')
  users.value = data.results || data
}
async function loadRoles () {
  try {
    const { data } = await api.get('/user-roles/')
    roles.value = data.results || data
  } catch {
    roles.value = []
  }
}

onMounted(async () => {
  await Promise.all([loadUsers(), loadRoles()])
})
</script>

<style scoped>
.admin-hero {
  background: linear-gradient(135deg, var(--c-panel) 0%, var(--c-panel-2) 100%);
  padding: 24px 28px;
}
.admin-role-badge { align-self: flex-start; }
.admin-panel { min-height: 180px; display: flex; flex-direction: column; }

.modal {
  position: fixed; inset: 0; z-index: 80;
  background: rgba(11, 37, 36, 0.55);
  display: grid; place-items: center;
  padding: 16px;
}
.modal__card {
  width: 100%; max-width: 560px;
  max-height: calc(100vh - 32px); overflow: auto;
}
code {
  background: var(--c-paper-2); padding: 2px 8px;
  border-radius: var(--r-xs); font-size: 12px;
}
</style>
