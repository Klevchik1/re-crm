<template>
  <!--
    Виджет автозаполнения карточки объекта данными с realty.yandex.ru.

    Сценарий: после того как сотрудник выбрал адрес в DaData (передаётся
    через prop :address), он жмёт «Найти на Яндекс.Недвижимости» —
    мы дёргаем POST /api/yandex-realty/search/, показываем список
    кандидатов, по клику на «Заполнить» отдаём наверх событие "apply"
    с полным разбором объявления (цена, площади, описание, фото и т.д.).

    Поскольку Яндекс может ловить капчу/блок — выводим понятную ошибку
    и подсказываем варианты обхода (попробовать позже / проверить
    интернет / включить прокси).
  -->
  <section class="panel panel--soft stack" style="gap: 12px">
    <header class="row" style="justify-content: space-between; flex-wrap: wrap; gap: 8px">
      <div>
        <h3 class="h4" style="margin: 0">Автозаполнение с Яндекс.Недвижимости</h3>
        <p class="muted" style="margin: 4px 0 0">
          После выбора адреса в подсказках можно подтянуть цену, площадь,
          описание и фотографии из похожего объявления на realty.yandex.ru.
          Между запросами выдерживается пауза, чтобы не получить капчу.
        </p>
      </div>
    </header>

    <div class="row" style="flex-wrap: wrap; gap: 8px; align-items: flex-end">
      <div class="field" style="flex: 1; min-width: 180px">
        <label>Тип сделки</label>
        <select class="select" v-model="dealType">
          <option value="kupit">Продажа</option>
          <option value="snyat">Аренда</option>
        </select>
      </div>
      <div class="field" style="flex: 1; min-width: 180px">
        <label>Тип объекта</label>
        <select class="select" v-model="propertyType">
          <option value="kvartira">Квартира</option>
          <option value="komnata">Комната</option>
          <option value="dom">Дом</option>
          <option value="uchastok">Участок</option>
        </select>
      </div>
      <button
        class="btn btn--accent"
        type="button"
        :disabled="!canSearch || searching"
        @click="search"
      >
        {{ searching ? 'Ищем…' : 'Найти на Яндекс.Недвижимости' }}
      </button>
    </div>

    <div class="row" style="gap: 8px; align-items: flex-end">
      <div class="field" style="flex: 1; min-width: 240px">
        <label>Или вставьте ссылку на объявление</label>
        <input
          class="input"
          v-model="manualUrl"
          placeholder="https://realty.yandex.ru/offer/..."
        />
      </div>
      <button
        class="btn"
        type="button"
        :disabled="!manualUrl || importing"
        @click="importByUrl(manualUrl)"
      >
        {{ importing ? 'Загружаем…' : 'Заполнить по ссылке' }}
      </button>
    </div>

    <p v-if="!canSearch" class="muted">
      Сначала выберите адрес из подсказок DaData выше — тогда поиск
      будет точнее.
    </p>

    <div v-if="error" class="error">{{ error }}</div>

    <div v-if="results.length" class="stack" style="gap: 8px">
      <div
        v-for="(r, i) in results"
        :key="r.url || r.raw_id || i"
        class="yandex-card"
      >
        <div class="yandex-card__photo">
          <img
            v-if="r.photos && r.photos[0]"
            :src="r.photos[0]"
            alt="Фото объявления"
            loading="lazy"
            referrerpolicy="no-referrer"
            @error="onImgError($event)"
          />
          <div v-else class="yandex-card__photo-stub">Нет фото</div>
        </div>
        <div class="yandex-card__body">
          <div class="yandex-card__title">
            {{ r.title || r.address || 'Без названия' }}
          </div>
          <div class="yandex-card__meta">
            <span v-if="r.price">{{ formatPrice(r.price) }}</span>
            <span v-if="r.area_total">{{ r.area_total }} м²</span>
            <span v-if="r.rooms_count">{{ r.rooms_count }}-комн.</span>
            <span v-if="r.floor_number && r.total_floors">
              {{ r.floor_number }}/{{ r.total_floors }} эт.
            </span>
          </div>
          <div v-if="r.address" class="muted">{{ r.address }}</div>
          <div class="row" style="gap: 8px; margin-top: 6px">
            <a
              v-if="r.url"
              :href="r.url"
              target="_blank"
              rel="noopener noreferrer"
              class="btn btn--sm"
            >Открыть на Яндексе</a>
            <button
              v-if="r.url"
              class="btn btn--sm btn--accent"
              type="button"
              :disabled="importing"
              @click="importByUrl(r.url)"
            >
              {{ importingUrl === r.url ? 'Загружаем…' : 'Заполнить' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-else-if="searched && !searching && !error" class="muted">
      Похожих объявлений на Яндекс.Недвижимости не найдено. Попробуйте
      изменить тип сделки/объекта или вставить ссылку вручную.
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import api from '../api'
import { formatMoney } from '../utils/formatters'

function formatPrice(value) {
  if (!value) return ''
  return formatMoney(value, '') + ' ₽'
}

const props = defineProps({
  // address — словарь, возвращённый событием pick из AddressAutocomplete.
  address: { type: Object, default: null },
})
const emit = defineEmits(['apply'])

const dealType = ref('kupit')
const propertyType = ref('kvartira')

const results = ref([])
const searched = ref(false)
const searching = ref(false)
const importing = ref(false)
const importingUrl = ref('')
const manualUrl = ref('')
const error = ref('')

const canSearch = computed(() => {
  if (!props.address) return false
  return Boolean(
    props.address.value
    || props.address.unrestricted_value
    || props.address.street
    || props.address.house
  )
})

async function search() {
  if (!canSearch.value || searching.value) return
  searching.value = true
  error.value = ''
  results.value = []
  try {
    const { data } = await api.post('/yandex-realty/search/', {
      address: props.address,
      deal_type: dealType.value,
      property_type: propertyType.value,
      limit: 10,
    })
    results.value = data.results || []
    searched.value = true
  } catch (e) {
    error.value = extractErrorMessage(e,
      'Не удалось получить данные от Яндекс.Недвижимости.')
  } finally {
    searching.value = false
  }
}

async function importByUrl(url) {
  if (!url || importing.value) return
  importing.value = true
  importingUrl.value = url
  error.value = ''
  try {
    const { data } = await api.post('/yandex-realty/import/', { url })
    if (data.offer) {
      emit('apply', data.offer)
    }
  } catch (e) {
    error.value = extractErrorMessage(e,
      'Не удалось разобрать объявление с Яндекса.')
  } finally {
    importing.value = false
    importingUrl.value = ''
  }
}

function extractErrorMessage(e, fallback) {
  const data = e?.response?.data
  if (data?.detail) {
    return data.error ? `${data.detail} (${data.error})` : data.detail
  }
  return e?.message || fallback
}

function onImgError(event) {
  // Если Яндекс заблокировал hot-linking — просто скрываем картинку.
  event.target.style.display = 'none'
}
</script>

<style scoped>
.yandex-card {
  display: grid; grid-template-columns: 160px 1fr; gap: 12px;
  background: var(--c-paper);
  border-radius: var(--r-sm);
  padding: 8px; box-shadow: var(--shadow-1);
}
.yandex-card__photo {
  aspect-ratio: 4/3; overflow: hidden;
  border-radius: var(--r-sm); background: var(--c-paper-2);
  display: flex; align-items: center; justify-content: center;
}
.yandex-card__photo img {
  width: 100%; height: 100%; object-fit: cover;
}
.yandex-card__photo-stub {
  font-size: 12px; color: var(--c-ink-soft);
}
.yandex-card__body { display: flex; flex-direction: column; gap: 4px; }
.yandex-card__title { font-weight: 600; color: var(--c-ink); }
.yandex-card__meta {
  display: flex; flex-wrap: wrap; gap: 8px; font-size: 13px;
  color: var(--c-ink-soft);
}
@media (max-width: 600px) {
  .yandex-card { grid-template-columns: 1fr; }
  .yandex-card__photo { aspect-ratio: 16/9; }
}
</style>
