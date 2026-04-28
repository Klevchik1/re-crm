<template>
  <section class="stack">
    <div class="hero" style="padding: 24px 28px">
      <div class="hero__eyebrow">{{ isEdit ? 'РЕДАКТИРОВАНИЕ' : 'НОВЫЙ ОБЪЕКТ' }}</div>
      <h1 class="h2" style="color: #fff; margin-top: 8px">
        {{ isEdit ? 'Изменить объект' : 'Создать объект' }}
      </h1>
    </div>

    <form class="panel panel--light stack" @submit.prevent="submit">
      <!-- Основные параметры -->
      <h2 class="h3">Основные параметры</h2>
      <div class="grid grid--2">
        <div class="field">
          <label>Заголовок</label>
          <input class="input" v-model="form.title" required
                 placeholder="Например: 2-комнатная на Ленина" />
        </div>
        <div class="field">
          <label>Тип операции</label>
          <select class="select" v-model.number="form.operation_type" required>
            <option v-for="o in dict.operations" :key="o.id" :value="o.id">
              {{ o.name }}
            </option>
          </select>
        </div>

        <div class="field">
          <label>Цена, ₽</label>
          <input class="input" type="number" step="0.01"
                 v-model.number="form.price" required />
        </div>
        <div class="field">
          <label>Цена за м²</label>
          <input class="input" type="number" step="0.01"
                 v-model.number="form.price_per_sqm" />
        </div>

        <div class="field">
          <label>Количество комнат</label>
          <input class="input" type="number" v-model.number="form.rooms_count" />
        </div>
        <div class="field">
          <label>Этаж / всего этажей</label>
          <div class="row">
            <input class="input" type="number" v-model.number="form.floor_number" />
            <input class="input" type="number" v-model.number="form.total_floors" />
          </div>
        </div>

        <div class="field">
          <label>Общая площадь, м²</label>
          <input class="input" type="number" step="0.01"
                 v-model.number="form.area_total" />
        </div>
        <div class="field">
          <label>Жилая площадь, м²</label>
          <input class="input" type="number" step="0.01"
                 v-model.number="form.area_living" />
        </div>
      </div>

      <!-- Адрес через DaData -->
      <h2 class="h3" style="margin-top: 8px">Адрес</h2>
      <p class="muted">
        Начните вводить адрес — подсказки подгружаются из сервиса DaData.
        Выберите нужную строку, и поля будут заполнены автоматически.
      </p>
      <AddressAutocomplete
        v-model="addressQuery"
        label="Поиск по адресу"
        placeholder="Город, улица, дом, квартира…"
        @pick="onAddressPick"
      />
      <div v-if="addressPicked" class="row" style="gap: 12px; flex-wrap: wrap">
        <span class="tag tag--accent">{{ addressPicked.value }}</span>
        <span v-if="addressPicked.postal_code" class="tag">
          Индекс: {{ addressPicked.postal_code }}
        </span>
        <span v-if="addressPicked.geo_lat && addressPicked.geo_lon" class="tag">
          {{ addressPicked.geo_lat.toFixed(4) }}, {{ addressPicked.geo_lon.toFixed(4) }}
        </span>
      </div>
      <div v-else-if="existingAddress" class="muted">
        Текущий адрес: {{ existingAddress }}
      </div>

      <!-- Парсер realty.yandex.ru: автозаполнение карточки по адресу. -->
      <YandexRealtyImport
        :address="addressPicked"
        @apply="onYandexApply"
      />
      <div v-if="lastImportNote" class="muted">{{ lastImportNote }}</div>

      <!-- Характеристики -->
      <h2 class="h3" style="margin-top: 8px">Характеристики</h2>
      <div class="row" style="flex-wrap: wrap; gap: 8px">
        <label v-for="f in dict.features" :key="f.id" class="chip-check">
          <input type="checkbox" :value="f.id" v-model="form.feature_ids" />
          <span>{{ f.name }}</span>
        </label>
        <span v-if="!dict.features.length" class="muted">
          Справочник характеристик пуст. Запустите команду
          <code>seed_dictionaries</code>.
        </span>
      </div>

      <!-- Фотографии -->
      <h2 class="h3" style="margin-top: 8px">Фотографии</h2>
      <p class="muted">
        Сервис подсказок адресов не предоставляет изображения, поэтому
        фото и описание добавляются сотрудником вручную. Можно загрузить
        файлы или указать ссылки на внешние изображения.
      </p>
      <div class="grid grid--3" v-if="photos.length">
        <div v-for="(p, i) in photos" :key="p.id || ('new-' + i)"
             class="photo-tile">
          <img :src="p.image_url || p.preview || p.url" alt="Фото объекта" />
          <div class="photo-tile__overlay">
            <label class="tag tag--panel" style="cursor: pointer">
              <input type="checkbox" v-model="p.is_cover"
                     @change="setCover(p)" style="display: none" />
              {{ p.is_cover ? 'Обложка' : 'Сделать обложкой' }}
            </label>
            <button class="btn btn--danger btn--sm" type="button"
                    @click="removePhoto(p, i)">
              Удалить
            </button>
          </div>
        </div>
      </div>
      <div class="row" style="gap: 12px; flex-wrap: wrap">
        <label class="btn btn--sm" style="cursor: pointer">
          Загрузить файл
          <input type="file" accept="image/*" multiple
                 style="display: none" @change="onFilesSelected" />
        </label>
        <div class="row" style="gap: 8px; flex: 1; min-width: 240px">
          <input class="input" v-model="newPhotoUrl"
                 placeholder="или вставьте ссылку на изображение" />
          <button class="btn btn--sm" type="button" @click="addPhotoByUrl">
            Добавить ссылку
          </button>
        </div>
      </div>

      <!-- Описание -->
      <h2 class="h3" style="margin-top: 8px">Описание</h2>
      <div class="field">
        <label>Описание объекта</label>
        <textarea class="textarea" v-model="form.description" rows="5"
                  placeholder="Расскажите об объекте: состояние, инфраструктура, транспорт…">
        </textarea>
      </div>

      <div v-if="error" class="error">{{ error }}</div>
      <div class="row" style="justify-content: flex-end; gap: 8px">
        <button class="btn" type="button" @click="$router.back()">Отмена</button>
        <button class="btn btn--accent" :disabled="loading" type="submit">
          {{ loading ? 'Сохранение…' : (isEdit ? 'Сохранить' : 'Создать') }}
        </button>
      </div>
    </form>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../api'
import AddressAutocomplete from '../components/AddressAutocomplete.vue'
import YandexRealtyImport from '../components/YandexRealtyImport.vue'

const route = useRoute()
const router = useRouter()
const isEdit = computed(() => !!route.params.id)

const form = reactive({
  title: '', operation_type: 1, status: 1,
  address: null,
  price: null, price_per_sqm: null,
  area_total: null, area_living: null, area_kitchen: null,
  rooms_count: null, floor_number: null, total_floors: null,
  description: '',
  feature_ids: [],
})

const dict = reactive({ operations: [], features: [] })
const addressQuery = ref('')
const addressPicked = ref(null)
const existingAddress = ref('')
const photos = ref([])
const pendingFiles = ref([])  // новые файлы, ожидающие загрузки после создания
const removedPhotoIds = ref([])
const newPhotoUrl = ref('')
const loading = ref(false)
const error = ref('')
const lastImportNote = ref('')

function onAddressPick(r) {
  addressPicked.value = r
}

/**
 * Обработчик автозаполнения формы данными из realty.yandex.ru.
 *
 * Подставляем только пустые поля — чтобы не затирать ручной ввод
 * сотрудника. Фотографии добавляем как внешние URL (отдельный массив
 * pendingFiles не трогаем): при отправке формы они уйдут в
 * /property-photos/ через ветку _fromUrl.
 */
function onYandexApply(offer) {
  if (!offer) return
  const fields = {
    title:         offer.title,
    description:   offer.description,
    price:         offer.price,
    price_per_sqm: offer.price_per_sqm,
    area_total:    offer.area_total,
    area_living:   offer.area_living,
    area_kitchen:  offer.area_kitchen,
    rooms_count:   offer.rooms_count,
    floor_number:  offer.floor_number,
    total_floors:  offer.total_floors,
  }
  const filled = []
  for (const [key, value] of Object.entries(fields)) {
    if (value === null || value === undefined || value === '') continue
    const current = form[key]
    if (current === null || current === undefined || current === '' || current === 0) {
      form[key] = value
      filled.push(key)
    }
  }
  // Фотографии: добавляем только новые URL, без дубликатов.
  const existingUrls = new Set(
    photos.value.map(p => p.url || p.image_url).filter(Boolean)
  )
  let added = 0
  for (const url of (offer.photos || [])) {
    if (!url || existingUrls.has(url)) continue
    existingUrls.add(url)
    photos.value.push({
      url,
      image_url: url,
      is_cover: photos.value.length === 0,
      _new: true,
      _fromUrl: true,
    })
    added += 1
  }
  lastImportNote.value =
    `Подставлено полей: ${filled.length}, добавлено фото: ${added}. `
    + 'Проверьте значения и при необходимости отредактируйте.'
}

function onFilesSelected(e) {
  const files = Array.from(e.target.files || [])
  for (const file of files) {
    const preview = URL.createObjectURL(file)
    const photo = { file, preview, is_cover: false, _new: true }
    photos.value.push(photo)
    pendingFiles.value.push(photo)
  }
  e.target.value = ''
}

function addPhotoByUrl() {
  const u = newPhotoUrl.value.trim()
  if (!u) return
  photos.value.push({ url: u, image_url: u, is_cover: false, _new: true, _fromUrl: true })
  newPhotoUrl.value = ''
}

function setCover(target) {
  photos.value.forEach(p => { p.is_cover = (p === target) })
}

function removePhoto(p, index) {
  if (p.id) removedPhotoIds.value.push(p.id)
  photos.value.splice(index, 1)
}

async function uploadPhotos(propertyId) {
  // 1) загружаем файлы
  for (const p of pendingFiles.value) {
    const fd = new FormData()
    fd.append('property', propertyId)
    fd.append('image', p.file)
    fd.append('is_cover', p.is_cover ? 'true' : 'false')
    await api.post('/property-photos/', fd,
      { headers: { 'Content-Type': 'multipart/form-data' } })
  }
  pendingFiles.value = []

  // 2) прикрепляем ссылки, добавленные через URL
  for (const p of photos.value.filter(x => x._new && x._fromUrl)) {
    await api.post('/property-photos/', {
      property: propertyId,
      url: p.url,
      is_cover: p.is_cover,
    })
  }

  // 3) удаляем отмеченные на удаление
  for (const id of removedPhotoIds.value) {
    await api.delete(`/property-photos/${id}/`)
  }
  removedPhotoIds.value = []
}

async function submit() {
  loading.value = true; error.value = ''
  try {
    const payload = {
      title: form.title,
      operation_type: form.operation_type,
      status: form.status,
      price: form.price,
      price_per_sqm: form.price_per_sqm,
      area_total: form.area_total,
      area_living: form.area_living,
      area_kitchen: form.area_kitchen,
      rooms_count: form.rooms_count,
      floor_number: form.floor_number,
      total_floors: form.total_floors,
      description: form.description,
      feature_ids: form.feature_ids,
    }
    if (addressPicked.value) {
      payload.address_data = addressPicked.value
    } else if (form.address) {
      payload.address = form.address
    } else if (!isEdit.value) {
      throw new Error('Выберите адрес из подсказок.')
    }

    const url = isEdit.value
      ? `/properties/${route.params.id}/` : '/properties/'
    const method = isEdit.value ? 'put' : 'post'
    const { data } = await api[method](url, payload)

    await uploadPhotos(data.id)

    router.push(`/properties/${data.id}`)
  } catch (e) {
    const data = e.response?.data
    if (typeof data === 'object' && data) {
      error.value = Object.entries(data)
        .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : v}`)
        .join('; ')
    } else {
      error.value = e.message || 'Не удалось сохранить объект.'
    }
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  const [o, f] = await Promise.all([
    api.get('/operation-types/'),
    api.get('/property-features/'),
  ])
  dict.operations = o.data.results || o.data
  dict.features = f.data.results || f.data

  if (isEdit.value) {
    const { data } = await api.get(`/properties/${route.params.id}/`)
    Object.assign(form, {
      title: data.title,
      operation_type: data.operation_type,
      status: data.status,
      address: data.address,
      price: data.price,
      price_per_sqm: data.price_per_sqm,
      area_total: data.area_total,
      area_living: data.area_living,
      area_kitchen: data.area_kitchen,
      rooms_count: data.rooms_count,
      floor_number: data.floor_number,
      total_floors: data.total_floors,
      description: data.description,
      feature_ids: (data.feature_values || []).map(fv => fv.feature),
    })
    existingAddress.value = data.full_address || ''
    photos.value = (data.photos || []).map(p => ({ ...p }))
  }
})
</script>

<style scoped>
.chip-check {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 12px; border-radius: var(--r-pill);
  background: var(--c-paper-2); color: var(--c-ink-soft);
  font-size: 13px; cursor: pointer;
  border: 1px solid transparent;
}
.chip-check input { accent-color: var(--c-accent); }
.chip-check:has(input:checked) {
  background: rgba(31,163,154,.14);
  color: var(--c-accent);
  border-color: rgba(31,163,154,.4);
}
.photo-tile {
  position: relative; border-radius: var(--r-sm); overflow: hidden;
  background: var(--c-paper-2); aspect-ratio: 4/3;
}
.photo-tile img { width: 100%; height: 100%; object-fit: cover; }
.photo-tile__overlay {
  position: absolute; inset: auto 0 0 0;
  display: flex; align-items: center; justify-content: space-between;
  gap: 8px; padding: 8px;
  background: linear-gradient(to top, rgba(14,58,56,.85), transparent);
}
</style>
