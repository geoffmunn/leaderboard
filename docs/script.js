let leaderboardData = [];

function getEntryDevice(entry) {
  const d = entry?.system_info?.device;
  return (typeof d === 'string' && d.trim().length > 0) ? d.trim() : 'N/A';
}

function getFilters() {
  const getVal = id => {
    const el = document.getElementById(id);
    return el ? el.value : '';
  };
  return {
    model: getVal('filter-model'),
    params: getVal('filter-params'),
    size: getVal('filter-size'),
    speed: getVal('filter-speed'),
    ppl: getVal('filter-ppl'),
    peakRam: getVal('filter-peak-ram'),
    device: getVal('filter-device'),
    ram: getVal('filter-ram'),
  };
}

function populateFilters() {
  const addOptions = (id, values) => {
    const select = document.getElementById(id);
    if (!select) return;
    const selected = select.value;
    select.innerHTML = '';
    const allOpt = document.createElement('option');
    allOpt.value = '';
    allOpt.textContent = 'All';
    select.appendChild(allOpt);
    values.forEach(v => {
      const opt = document.createElement('option');
      opt.value = v;
      opt.textContent = v;
      select.appendChild(opt);
    });
    if (selected && values.includes(selected)) {
      select.value = selected;
    }
  };

  const models = new Set();
  const params = new Set();
  const sizes = new Set();
  const speeds = new Set();
  const ppls = new Set();
  const peaks = new Set();
  const devices = new Set();
  const rams = new Set();

  leaderboardData.forEach(entry => {
    const speed = entry.avg_tokens_per_sec || 0;
    const speedStr = speed.toFixed(2);
    const sizeStr = entry.file_size_mb != null ? entry.file_size_mb.toFixed(1) : 'N/A';
    const pplStr = entry.perplexity != null ? entry.perplexity.toFixed(2) : 'N/A';
    const peakStr = entry.peak_memory_mb != null ? entry.peak_memory_mb.toFixed(1) : 'N/A';
    const deviceStr = getEntryDevice(entry);
    const ramStr = entry.system_info?.ram_gb ?? 'N/A';

    if (entry.model_name) models.add(entry.model_name);
    params.add(entry.parameters || 'N/A');
    sizes.add(sizeStr);
    speeds.add(speedStr);
    ppls.add(pplStr);
    peaks.add(peakStr);
    devices.add(deviceStr);
    rams.add(ramStr);
  });

  const alphaSort = arr => arr.sort((a, b) => String(a).localeCompare(String(b), undefined, { sensitivity: 'base' }));

  addOptions('filter-model', alphaSort(Array.from(models)));
  addOptions('filter-params', alphaSort(Array.from(params)));
  addOptions('filter-size', alphaSort(Array.from(sizes)));
  addOptions('filter-speed', alphaSort(Array.from(speeds)));
  addOptions('filter-ppl', alphaSort(Array.from(ppls)));
  addOptions('filter-peak-ram', alphaSort(Array.from(peaks)));
  addOptions('filter-device', alphaSort(Array.from(devices)));
  addOptions('filter-ram', alphaSort(Array.from(rams)));
}

// Load and render data
async function loadLeaderboard() {
  try {
    const response = await fetch('leaderboard.json');
    leaderboardData = await response.json();
    populateFilters();
    renderTable();
    renderChart();
  } catch (error) {
    console.error('Failed to load leaderboard:', error);
    document.getElementById('table-body').innerHTML = 
      '<tr><td colspan="5">Error loading leaderboard.json</td></tr>';
  }
}

// Render table
function renderTable() {
  const tbody = document.getElementById('table-body');
  const filters = getFilters();
  
  tbody.innerHTML = '';
  
  leaderboardData.forEach(entry => {
    const speed = entry.avg_tokens_per_sec || 0;
    const isFailed = speed === 0;
    const entryDevice = getEntryDevice(entry);
    const sizeStr = entry.file_size_mb != null ? entry.file_size_mb.toFixed(1) : 'N/A';
    const speedStr = speed.toFixed(2);
    const pplStr = entry.perplexity != null ? entry.perplexity.toFixed(2) : 'N/A';
    const peakStr = entry.peak_memory_mb != null ? entry.peak_memory_mb.toFixed(1) : 'N/A';
    const ramStr = entry.system_info?.ram_gb ?? 'N/A';

    if (filters.model && entry.model_name !== filters.model) return;
    if (filters.params && (entry.parameters || 'N/A') !== filters.params) return;
    if (filters.size && sizeStr !== filters.size) return;
    if (filters.speed && speedStr !== filters.speed) return;
    if (filters.ppl && pplStr !== filters.ppl) return;
    if (filters.peakRam && peakStr !== filters.peakRam) return;
    if (filters.device && entryDevice !== filters.device) return;
    if (filters.ram && ramStr !== filters.ram) return;
    
    const row = document.createElement('tr');
    if (isFailed) row.classList.add('failed');
    
    const config = entry.hardware_config;
    const configStr = `threads=${config.threads}, ctx=${config.ctx_size}`;
    
    // Format ISO date to readable string
    function formatDate(isoString) {
      if (!isoString) return 'N/A';
      return new Date(isoString).toLocaleString();
    }

    // Format model name with link if HuggingFace repo is available
    const modelNameCell = entry.huggingface_repo
      ? `<code><a href="${entry.huggingface_repo}" target="_blank" rel="noopener noreferrer">${entry.model_name}</a></code>`
      : `<code>${entry.model_name}</code>`;

    // In renderTable():
    row.innerHTML = `
      <td>${modelNameCell}</td>
      <td>${entry.parameters || 'N/A'}</td>
      <td>${sizeStr}</td>
      <td>${speedStr}</td>
      <td>${pplStr}</td>
      <td>${peakStr}</td>
      <td>${entryDevice}</td>
      <td>${ramStr}</td>
      <td>${formatDate(entry.date_checked)}</td>
    `;
    
    tbody.appendChild(row);
  });
}

// Render chart: Speed vs Size
function renderChart() {
  const ctx = document.getElementById('perfChart').getContext('2d');
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
  
  const filters = getFilters();
  
  // Get all valid entries (speed > 0) - don't filter by params for chart
  const validEntries = leaderboardData.filter(e => {
    if ((e.avg_tokens_per_sec || 0) <= 0) return false;
    const entryDevice = getEntryDevice(e);
    const speed = e.avg_tokens_per_sec || 0;
    const sizeStr = e.file_size_mb != null ? e.file_size_mb.toFixed(1) : 'N/A';
    const speedStr = speed.toFixed(2);
    const pplStr = e.perplexity != null ? e.perplexity.toFixed(2) : 'N/A';
    const peakStr = e.peak_memory_mb != null ? e.peak_memory_mb.toFixed(1) : 'N/A';
    const ramStr = e.system_info?.ram_gb ?? 'N/A';

    // Apply all filters except params - params filter affects styling only
    if (filters.model && e.model_name !== filters.model) return false;
    if (filters.size && sizeStr !== filters.size) return false;
    if (filters.speed && speedStr !== filters.speed) return false;
    if (filters.ppl && pplStr !== filters.ppl) return false;
    if (filters.peakRam && peakStr !== filters.peakRam) return false;
    if (filters.device && entryDevice !== filters.device) return false;
    if (filters.ram && ramStr !== filters.ram) return false;
    return true;
  });
  
  if (validEntries.length === 0) {
    ctx.font = '16px sans-serif';
    ctx.fillText('No valid benchmark data', 10, 30);
    return;
  }

  // Determine which entries match the param filter
  const paramFilter = filters.params;
  const pointBackgroundColors = validEntries.map(e => {
    const entryParams = e.parameters || 'N/A';
    const matches = !paramFilter || entryParams === paramFilter;
    return matches ? 'rgba(52, 152, 219, 0.6)' : 'rgba(200, 200, 200, 0.3)';
  });
  const pointBorderColors = validEntries.map(e => {
    const entryParams = e.parameters || 'N/A';
    const matches = !paramFilter || entryParams === paramFilter;
    return matches ? 'rgba(41, 128, 185, 1)' : 'rgba(150, 150, 150, 0.5)';
  });

  const data = {
    labels: validEntries.map(e => e.model_name),
    datasets: [{
      label: 'Tokens per Second',
      data: validEntries.map(e => ({ x: e.file_size_mb, y: e.avg_tokens_per_sec })),
      backgroundColor: pointBackgroundColors,
      borderColor: pointBorderColors,
      borderWidth: 1,
      radius: 6
    }]
  };
  
  // Destroy existing chart if it exists
  if (window.perfChart && typeof window.perfChart.destroy === 'function') {
    window.perfChart.destroy();
  }
  
  window.perfChart = new Chart(ctx, {
    type: 'scatter',
    data,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { title: { display: true, text: 'Model Size (MB)' }, beginAtZero: true },
        y: { title: { display: true, text: 'Speed (tokens/sec)' }, beginAtZero: true }
      },
      plugins: {
        tooltip: {
          callbacks: {
            label: ctx => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(2)} t/s`,
            afterLabel: ctx => `Size: ${validEntries[ctx.dataIndex].file_size_mb.toFixed(1)} MB`
          }
        },
        legend: { display: false }
      }
    }
  });
}

// Event listeners
['filter-model','filter-params','filter-size','filter-speed','filter-ppl','filter-peak-ram','filter-device','filter-ram']
  .forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.addEventListener('change', () => {
        renderTable();
        renderChart();
      });
    }
  });
document.getElementById('refresh').addEventListener('click', loadLeaderboard);

// Initialize
loadLeaderboard();