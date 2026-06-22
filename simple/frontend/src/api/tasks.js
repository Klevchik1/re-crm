/**
 * Тонкий фасад над REST-эндпоинтами задач и заявок.
 *
 * Зачем отдельный модуль:
 *   1. Единая точка входа — все представления (Tasks.vue, RequestDetail.vue,
 *      CurrentTaskWidget.vue) дергают одни и те же функции и не дублируют
 *      URL-ы и хедеры.
 *   2. После КАЖДОЙ мутации (start/pause/complete/create/take/accept_match)
 *      автоматически дергается workload.bumpAfterAction() — это убирает
 *      главную причину рассинхрона виджета и страниц (данные были
 *      «устаревшими», потому что в одном из экранов забывали вызвать
 *      workload.refresh()).
 *   3. Унифицированная обработка ошибок: все методы возвращают
 *      { ok, data, error } — view-шки не бьются на try/catch.
 *
 * Если когда-нибудь перейдём на WebSocket (Django Channels) — достаточно
 * подменить внутренности bumpAfterAction(), всё остальное кода не касается.
 */

import api from '@/api'
import { useWorkloadStore } from '@/store/workload'

/**
 * Внутренний хелпер: выполняет запрос и дергает bump у workload-стора.
 * Возвращает дискриминированный объект — так вью-код проще писать без
 * вложенных try/catch.
 *
 * @param {() => Promise<import('axios').AxiosResponse>} fn
 * @param {{ bump?: boolean, bumpDelayMs?: number }} [opts]
 */
async function call(fn, opts = {}) {
  const { bump = true, bumpDelayMs = 1500 } = opts
  try {
    const response = await fn()
    if (bump) {
      try {
        const workload = useWorkloadStore()
        workload.bumpAfterAction({ delayMs: bumpDelayMs })
      } catch (_err) {
        // Pinia ещё не смонтирована (например, в юнит-тестах) — не критично.
      }
    }
    return { ok: true, data: response.data, error: null }
  } catch (error) {
    const detail = error?.response?.data?.detail
      || error?.response?.data?.non_field_errors?.[0]
      || error?.message
      || 'Не удалось выполнить запрос'
    return { ok: false, data: null, error: detail, raw: error }
  }
}

// ---------------------------------------------------------------------------
// Задачи
// ---------------------------------------------------------------------------

export function listTasks(params = {}) {
  return call(() => api.get('/tasks/', { params }), { bump: false })
}

export function getTask(id) {
  return call(() => api.get(`/tasks/${id}/`), { bump: false })
}

export function createTask(payload) {
  return call(() => api.post('/tasks/', payload))
}

export function patchTask(id, payload) {
  return call(() => api.patch(`/tasks/${id}/`, payload))
}

export function deleteTask(id) {
  return call(() => api.delete(`/tasks/${id}/`))
}

export function startTask(id) {
  return call(() => api.post(`/tasks/${id}/start/`))
}

export function pauseTask(id) {
  return call(() => api.post(`/tasks/${id}/pause/`))
}

/**
 * Сменить статус задачи через action `change_status`.
 * Бэкенд ожидает числовой `status_id` (pk из /task-statuses/).
 */
export function changeTaskStatus(id, statusId) {
  return call(() => api.post(`/tasks/${id}/change_status/`, {
    status_id: Number(statusId),
  }))
}

/**
 * Завершить задачу. `result` — произвольный объект, в котором агент
 * фиксирует что именно сделано («позвонил», «провёл показ», «подобрал
 * объекты N, M»). Попадает в Task.result и используется в истории и
 * отчётах.
 */
export function completeTask(id, result = {}) {
  return call(() => api.post(`/tasks/${id}/complete/`, { result }))
}

/**
 * Зафиксировать этап выполнения задачи (звонок/сообщение/подбор).
 * Не переводит задачу в другой статус и не снимает её с сотрудника —
 * только добавляет запись в ``Task.steps_log``. Используется экраном
 * TaskWorkflow.vue как «шаги мастера».
 *
 * @param {number} id
 * @param {{ step: string, outcome?: string, note?: string }} payload
 */
export function recordTaskStep(id, payload) {
  return call(() => api.post(`/tasks/${id}/record_step/`, payload), {
    // bump не нужен: шаги не меняют загрузку сотрудника.
    bump: false,
  })
}

// ---------------------------------------------------------------------------
// Заявки клиентов
// ---------------------------------------------------------------------------

export function takeRequest(id) {
  return call(() => api.post(`/requests/${id}/take/`))
}

/**
 * Подтвердить клиентский подбор: сервер запускает цепочку
 * «автозакрытие задач → KPI → письмо клиенту».
 */
export function acceptRequestMatch(requestId, matchId) {
  return call(() => api.post(`/requests/${requestId}/accept_match/`, {
    match_id: matchId,
  }))
}

// ---------------------------------------------------------------------------
// SmartPay — оплата просмотра объекта
// ---------------------------------------------------------------------------

/**
 * Создать счёт SmartPay для просмотра (POST /viewings/{id}/initiate_payment/).
 * Идемпотентен: повторный вызов вернёт уже созданный invoice_id.
 *
 * @param {number} viewingId — PK записи PropertyViewing
 * @returns {{ ok, data: { invoice_id, status, amount, description }, error }}
 */
export function initiateViewingPayment(viewingId) {
  return call(
    () => api.post(`/viewings/${viewingId}/initiate_payment/`),
    { bump: false },
  )
}

/**
 * Проверить статус счёта SmartPay (GET /viewings/{id}/payment_status/).
 *
 * @param {number} viewingId — PK записи PropertyViewing
 * @returns {{ ok, data: { invoice_id, status }, error }}
 */
export function getViewingPaymentStatus(viewingId) {
  return call(
    () => api.get(`/viewings/${viewingId}/payment_status/`),
    { bump: false },
  )
}

// ---------------------------------------------------------------------------
// Журнал исходящих писем
// ---------------------------------------------------------------------------

export function listOutgoingEmails(params = {}) {
  return call(() => api.get('/outgoing-emails/', { params }), { bump: false })
}

export function retryOutgoingEmail(id) {
  return call(() => api.post(`/outgoing-emails/${id}/retry/`), { bump: false })
}
