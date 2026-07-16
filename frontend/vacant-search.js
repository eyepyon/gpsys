(function () {
  'use strict';

  const view = document.body.dataset.searchView;
  if (!view) return;

  const apiBaseUrl = 'https://regional-revitalization-api-dev-804626259225.us-central1.run.app';
  const selectedTypes = new URLSearchParams(window.location.search).get('types') || '';
  const panel = document.createElement('section');
  panel.className = 'fixed left-1/2 -translate-x-1/2 top-20 z-[60] bg-white shadow-xl border border-gray-200 rounded-xl p-4';
  panel.style.width = 'min(920px, calc(100vw - 2rem))';
  panel.innerHTML = `
    <div class="flex justify-end mb-2">
      <button id="toggle-search-panel" type="button" class="px-3 py-1.5 border border-gray-300 text-gray-600 hover:bg-gray-50 rounded-lg text-xs font-medium flex items-center gap-1" aria-expanded="true">
        <i class="ri-subtract-line"></i><span>最小化</span>
      </button>
    </div>
    <form id="vacant-search-form" class="grid grid-cols-2 md:grid-cols-6 gap-3 items-end">
      <input id="search-api-url" type="hidden" value="${escapeHtml(apiBaseUrl)}">
      <label class="text-xs text-gray-600">緯度
        <input id="search-lat" type="number" required min="-90" max="90" step="any" value="35.68" class="mt-1 w-full px-3 py-2 border rounded-lg text-sm">
      </label>
      <label class="text-xs text-gray-600">経度
        <input id="search-lng" type="number" required min="-180" max="180" step="any" value="139.76" class="mt-1 w-full px-3 py-2 border rounded-lg text-sm">
      </label>
      <label class="text-xs text-gray-600">半径 (km)
        <input id="search-radius" type="number" required min="0.1" step="0.1" value="5" class="mt-1 w-full px-3 py-2 border rounded-lg text-sm">
      </label>
      <label class="text-xs text-gray-600">業種タグ（任意）
        <input id="search-types" type="text" value="${escapeHtml(selectedTypes)}" placeholder="restaurant,cafe" class="mt-1 w-full px-3 py-2 border rounded-lg text-sm">
      </label>
      <button id="get-current-location" type="button" class="col-span-2 md:col-span-2 px-5 py-2 bg-blue-600 hover:bg-blue-700 text-white font-bold rounded-lg flex items-center justify-center gap-2">
        <i class="ri-crosshair-2-line text-lg"></i><span>現在地を取得</span>
      </button>
      <button id="vacant-search-button" type="submit" class="col-span-2 md:col-span-4 px-5 py-2 bg-orange-500 hover:bg-orange-600 text-white font-bold rounded-lg">営業状態を問わず検索</button>
      <p id="vacant-search-message" class="col-span-2 md:col-span-6 text-sm text-gray-600" aria-live="polite"></p>
    </form>`;
  document.body.appendChild(panel);

  const form = document.getElementById('vacant-search-form');
  form.addEventListener('submit', search);
  document.getElementById('toggle-search-panel').addEventListener('click', toggleSearchPanel);
  document.getElementById('get-current-location').addEventListener('click', getCurrentLocation);
  if (view === 'map') setupPlaceTypeSelector();
  if (view === 'list') {
    const grid = document.getElementById('search-result-grid');
    const pagination = document.getElementById('search-pagination');
    if (pagination) pagination.classList.add('hidden');
    if (grid) grid.innerHTML = '<p class="col-span-3 py-12 text-center text-gray-500">DBから物件情報を読み込んでいます…</p>';
    form.requestSubmit();
  }

  function toggleSearchPanel() {
    const button = document.getElementById('toggle-search-panel');
    const label = button.querySelector('span');
    const icon = button.querySelector('i');
    const minimized = !form.classList.contains('hidden');
    form.classList.toggle('hidden', minimized);
    panel.style.width = minimized ? 'auto' : 'min(920px, calc(100vw - 2rem))';
    button.setAttribute('aria-expanded', String(!minimized));
    label.textContent = minimized ? '元に戻す' : '最小化';
    icon.className = minimized ? 'ri-expand-diagonal-line' : 'ri-subtract-line';
  }

  function setupPlaceTypeSelector() {
    const toggle = document.getElementById('toggle-place-types');
    const container = document.getElementById('additional-place-types');
    const typesInput = document.getElementById('search-types');
    if (!toggle || !container || !typesInput) return;

    const groups = {
      '飲食': ['bakery', 'bar', 'bar_and_grill', 'barbecue_restaurant', 'breakfast_restaurant', 'brunch_restaurant', 'cafe', 'cafeteria', 'coffee_shop', 'deli', 'dessert_shop', 'diner', 'fast_food_restaurant', 'fine_dining_restaurant', 'food_court', 'french_restaurant', 'hamburger_restaurant', 'ice_cream_shop', 'indian_restaurant', 'italian_restaurant', 'japanese_restaurant', 'korean_restaurant', 'meal_delivery', 'meal_takeaway', 'mexican_restaurant', 'pizza_restaurant', 'pub', 'ramen_restaurant', 'restaurant', 'seafood_restaurant', 'steak_house', 'sushi_restaurant', 'thai_restaurant'],
      '小売・店舗': ['auto_parts_store', 'bicycle_store', 'book_store', 'butcher_shop', 'cell_phone_store', 'clothing_store', 'convenience_store', 'cosmetics_store', 'department_store', 'discount_store', 'electronics_store', 'furniture_store', 'gift_shop', 'grocery_store', 'hardware_store', 'home_goods_store', 'jewelry_store', 'liquor_store', 'market', 'pet_store', 'shoe_store', 'shopping_mall', 'sporting_goods_store', 'store', 'supermarket', 'thrift_store', 'toy_store'],
      '美容・健康': ['beauty_salon', 'dentist', 'doctor', 'drugstore', 'fitness_center', 'gym', 'hair_care', 'hospital', 'massage', 'medical_center', 'medical_clinic', 'pharmacy', 'physiotherapist', 'skin_care_clinic', 'spa', 'veterinary_care', 'wellness_center'],
      '事業・サービス': ['accounting', 'business_center', 'corporate_office', 'coworking_space', 'electrician', 'insurance_agency', 'laundry', 'lawyer', 'locksmith', 'manufacturer', 'moving_company', 'painter', 'plumber', 'real_estate_agency', 'research_institute', 'roofing_contractor', 'storage', 'supplier', 'travel_agency'],
      '宿泊・施設': ['bed_and_breakfast', 'campground', 'extended_stay_hotel', 'guest_house', 'hostel', 'hotel', 'inn', 'lodging', 'motel', 'resort_hotel', 'banquet_hall', 'community_center', 'convention_center', 'event_venue', 'wedding_venue'],
      '文化・娯楽': ['art_gallery', 'art_museum', 'art_studio', 'bowling_alley', 'casino', 'cultural_center', 'karaoke', 'library', 'movie_theater', 'museum', 'night_club', 'performing_arts_theater', 'tourist_attraction', 'video_arcade'],
      '教育': ['educational_institution', 'preschool', 'primary_school', 'school', 'secondary_school', 'university'],
      '自動車・交通': ['car_dealer', 'car_rental', 'car_repair', 'car_wash', 'electric_vehicle_charging_station', 'gas_station', 'parking', 'tire_shop', 'bus_station', 'subway_station', 'taxi_service', 'train_station', 'transit_station']
    };
    const labels = {
      restaurant: 'レストラン', cafe: 'カフェ', bakery: 'パン屋', bar: 'バー', beauty_salon: '美容室',
      doctor: '医師', hospital: '病院', pharmacy: '薬局', store: '店舗', corporate_office: '企業オフィス',
      hotel: 'ホテル', school: '学校', gym: 'ジム', car_repair: '自動車修理', gas_station: 'ガソリンスタンド'
    };
    container.innerHTML = Object.entries(groups).map(([group, types]) => `
      <section><h4 class="text-xs font-bold text-gray-500 mb-2">${escapeHtml(group)}</h4>
      <div class="grid grid-cols-1 gap-2">${types.map(type => `
        <label class="flex items-center gap-2 cursor-pointer text-sm text-gray-700">
          <input type="checkbox" class="custom-checkbox place-type-checkbox" value="${escapeHtml(type)}">
          <span>${escapeHtml(labels[type] || type.replaceAll('_', ' '))}</span>
        </label>`).join('')}</div></section>`).join('');

    const syncInput = () => {
      const selected = [...document.querySelectorAll('.place-type-checkbox:checked')].map(input => input.value);
      typesInput.value = [...new Set(selected)].join(',');
    };
    const initialTypes = new Set(typesInput.value.split(',').map(value => value.trim()).filter(Boolean));
    document.querySelectorAll('.place-type-checkbox').forEach(input => {
      input.checked = initialTypes.has(input.value);
      input.addEventListener('change', event => {
        document.querySelectorAll('.place-type-checkbox').forEach(other => {
          if (other.value === event.currentTarget.value) other.checked = event.currentTarget.checked;
        });
        syncInput();
      });
    });
    toggle.addEventListener('click', () => {
      const opening = container.classList.contains('hidden');
      container.classList.toggle('hidden');
      toggle.textContent = opening ? '− 他の業種を閉じる' : '+ 他の業種を表示';
    });
  }

  function getCurrentLocation() {
    const message = document.getElementById('vacant-search-message');
    const button = document.getElementById('get-current-location');
    if (!navigator.geolocation) {
      message.textContent = 'このブラウザは現在地取得に対応していません。';
      return;
    }

    message.textContent = '現在地を取得しています…';
    button.disabled = true;
    button.classList.add('opacity-60');
    navigator.geolocation.getCurrentPosition(
      position => {
        document.getElementById('search-lat').value = position.coords.latitude.toFixed(6);
        document.getElementById('search-lng').value = position.coords.longitude.toFixed(6);
        message.textContent = `現在地を入力しました（精度: 約${Math.round(position.coords.accuracy)}m）`;
        button.disabled = false;
        button.classList.remove('opacity-60');
      },
      error => {
        const errorMessages = {
          1: '現在地の利用が許可されませんでした。ブラウザの位置情報設定をご確認ください。',
          2: '現在地を取得できませんでした。GPSや通信状態をご確認ください。',
          3: '現在地の取得がタイムアウトしました。もう一度お試しください。'
        };
        message.textContent = errorMessages[error.code] || '現在地の取得に失敗しました。';
        button.disabled = false;
        button.classList.remove('opacity-60');
      },
      {enableHighAccuracy: true, timeout: 10000, maximumAge: 60000}
    );
  }

  async function search(event) {
    event.preventDefault();
    const message = document.getElementById('vacant-search-message');
    const button = document.getElementById('vacant-search-button');
    const baseUrl = document.getElementById('search-api-url').value.trim().replace(/\/$/, '');
    const typesText = document.getElementById('search-types').value.trim();
    const body = {
      latitude: Number(document.getElementById('search-lat').value),
      longitude: Number(document.getElementById('search-lng').value),
      radius_km: Number(document.getElementById('search-radius').value),
      types: typesText ? typesText.split(',').map(value => value.trim()).filter(Boolean) : null,
      limit: 100
    };

    message.textContent = '検索中…';
    button.disabled = true;
    button.classList.add('opacity-60');
    try {
      const response = await fetch(`${baseUrl}/vacant-properties/search`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
      const candidates = Array.isArray(data.candidates) ? data.candidates : [];
      message.textContent = `${candidates.length}件見つかりました（営業状態による絞り込みなし）`;
      render(candidates);
    } catch (error) {
      console.error('物件情報の取得に失敗しました', error);
      message.textContent = '現在コスト対策のためAPIを一時停止しています';
      if (view === 'list') {
        const grid = document.getElementById('search-result-grid');
        const pagination = document.getElementById('search-pagination');
        if (pagination) pagination.classList.add('hidden');
        if (grid) grid.innerHTML = '<p class="col-span-3 py-12 text-center font-bold text-red-600">現在コスト対策のためAPIを一時停止しています</p>';
      }
    } finally {
      button.disabled = false;
      button.classList.remove('opacity-60');
    }
  }

  function render(candidates) {
    if (view === 'list') renderList(candidates);
    if (view === 'map') renderMap(candidates);
  }

  function renderList(candidates) {
    const count = document.getElementById('list-search-result-count');
    if (count) count.textContent = `${candidates.length} 件（営業状態による絞り込みなし）`;
    const grid = document.getElementById('search-result-grid');
    if (!grid) return;
    grid.innerHTML = candidates.length ? candidates.map(candidate => `
      <article class="bg-white rounded-2xl shadow-sm overflow-hidden property-card">
        <div class="p-5">
          <h3 class="text-lg font-bold text-gray-900 mb-2">${escapeHtml(candidate.name)}</h3>
          <p class="text-sm text-gray-600 mb-3"><i class="ri-map-pin-line"></i> ${escapeHtml(candidate.address || '住所情報なし')}</p>
          <div class="flex flex-wrap gap-2 mb-3">${(candidate.types || []).map(type => `<span class="px-3 py-1 bg-blue-50 text-primary text-xs rounded-full">${escapeHtml(type)}</span>`).join('')}</div>
          <dl class="grid grid-cols-2 gap-2 text-sm text-gray-600 mb-3">
            <div><dt class="text-xs text-gray-400">賃料</dt><dd>${candidate.rent_yen == null ? '未登録' : `${Number(candidate.rent_yen).toLocaleString('ja-JP')}円/月`}</dd></div>
            <div><dt class="text-xs text-gray-400">面積</dt><dd>${candidate.area_sqm == null ? '未登録' : `${escapeHtml(candidate.area_sqm)}㎡`}</dd></div>
            <div><dt class="text-xs text-gray-400">築年</dt><dd>${candidate.built_year == null ? '未登録' : `${escapeHtml(candidate.built_year)}年`}</dd></div>
            <div><dt class="text-xs text-gray-400">構造</dt><dd>${escapeHtml(candidate.structure || '未登録')}</dd></div>
          </dl>
          <p class="text-xs text-gray-500">営業状態: ${escapeHtml(statusLabel(candidate.business_status))}</p>
          ${candidate.phone_number ? `<p class="text-sm text-gray-600 mt-2">電話: ${escapeHtml(candidate.phone_number)}</p>` : ''}
        </div>
      </article>`).join('') : '<p class="col-span-3 py-12 text-center text-gray-500">条件に一致する物件はありません。</p>';
    const pagination = document.getElementById('search-pagination');
    if (pagination) pagination.classList.add('hidden');
  }

  function renderMap(candidates) {
    const count = document.getElementById('search-result-count');
    if (count) count.textContent = `該当物件: ${candidates.length} 件（営業状態による絞り込みなし）`;
    const map = document.querySelector('#map-results > .absolute.inset-0');
    if (!map) return;
    map.querySelectorAll('.map-pin').forEach(pin => pin.remove());
    candidates.forEach((candidate, index) => {
      const pin = document.createElement('button');
      pin.type = 'button';
      pin.className = 'map-pin absolute w-10 h-10 flex items-center justify-center bg-primary text-white rounded-full shadow-lg';
      pin.style.left = `${12 + ((index * 23) % 76)}%`;
      pin.style.top = `${15 + ((index * 31) % 70)}%`;
      pin.title = `${candidate.name}\n${candidate.address || ''}\n${statusLabel(candidate.business_status)}`;
      pin.innerHTML = '<i class="ri-map-pin-fill text-xl"></i>';
      pin.addEventListener('click', event => {
        event.stopPropagation();
        alert(`${candidate.name}\n${candidate.address || '住所情報なし'}\n営業状態: ${statusLabel(candidate.business_status)}`);
      });
      map.appendChild(pin);
    });
  }

  function statusLabel(status) {
    return ({OPERATIONAL: '営業中', CLOSED_TEMPORARILY: '一時休業', CLOSED_PERMANENTLY: '閉業'})[status] || status || '不明';
  }

  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>'"]/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'})[char]);
  }
})();
