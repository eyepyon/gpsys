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
      <button id="vacant-search-button" type="submit" class="col-span-2 md:col-span-6 px-5 py-2 bg-orange-500 hover:bg-orange-600 text-white font-bold rounded-lg">営業状態を問わず検索</button>
      <p id="vacant-search-message" class="col-span-2 md:col-span-6 text-sm text-gray-600" aria-live="polite"></p>
    </form>`;
  document.body.appendChild(panel);

  document.getElementById('vacant-search-form').addEventListener('submit', search);

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
      message.textContent = `検索に失敗しました: ${error.message}`;
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
          <p class="text-xs text-gray-500">営業状態: ${escapeHtml(statusLabel(candidate.business_status))}</p>
          ${candidate.phone_number ? `<p class="text-sm text-gray-600 mt-2">電話: ${escapeHtml(candidate.phone_number)}</p>` : ''}
        </div>
      </article>`).join('') : '<p class="col-span-3 py-12 text-center text-gray-500">条件に一致する物件はありません。</p>';
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
