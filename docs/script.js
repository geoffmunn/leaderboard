let leaderboardData = [];

function getEntryDevice(entry) {
  const d = entry?.system_info?.device;
  return (typeof d === 'string' && d.trim().length > 0) ? d.trim() : 'N/A';
}

// Helpers to format and parse size bucket labels (e.g. "600MB - 1GB")
function _toMB(str) {
  if (!str) return NaN;
  const s = String(str).trim().toLowerCase();
  if (s.endsWith('gb')) {
    return parseFloat(s.replace(/gb$/,'').trim()) * 1000;
  }
  // assume MB
  return parseFloat(s.replace(/mb$/,'').trim());
}

function bucketLabel(startMB, endMB) {
  const fmt = (mb) => {
    if (mb % 1000 === 0) return (mb/1000) + 'GB';
    if (mb >= 1000) return (mb/1000).toFixed(1).replace(/\.0$/, '') + 'GB';
    return Math.round(mb) + 'MB';
  };
  return `${fmt(startMB)} - ${fmt(endMB)}`;
}

function parseBucketLabel(label) {
  if (!label) return null;
  const parts = label.split(' - ');
  if (parts.length !== 2) return null;
  const start = _toMB(parts[0]);
  const end = _toMB(parts[1]);
  if (isNaN(start) || isNaN(end)) return null;
  return [start, end];
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
        ppl: getVal('filter-ppl'), // now used as sort order: '', 'low-high', 'high-low'
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
      // Build size buckets: 0-300MB, 300-600MB, 600-1GB, then 500MB increments (1GB-1.5GB, 1.5GB-2GB, ...)
      (function buildSizeBuckets() {
        // find max file size in MB
        let maxSize = 0;
        leaderboardData.forEach(e => {
          if (e && typeof e.file_size_mb === 'number' && !isNaN(e.file_size_mb)) {
            maxSize = Math.max(maxSize, e.file_size_mb);
          }
        });
        // ensure at least 1GB range shown
        const minCover = Math.max(1000, Math.ceil(maxSize));

        const buckets = [[0,300],[300,600],[600,1000]];
        let start = 1000;
        const maxCeil = Math.ceil(minCover / 500) * 500;
        while (start < maxCeil) {
          buckets.push([start, start + 500]);
          start += 500;
        }
        const labels = buckets.map(b => bucketLabel(b[0], b[1]));
        addOptions('filter-size', labels);
      })();
      // Speed select is used as a sort order control rather than filtering by exact speed value.
      const speedSelect = document.getElementById('filter-speed');
      if (speedSelect) {
        const selSpeed = speedSelect.value;
        speedSelect.innerHTML = '';
        const sUn = document.createElement('option'); sUn.value = ''; sUn.textContent = 'Unsorted'; speedSelect.appendChild(sUn);
        const sLow = document.createElement('option'); sLow.value = 'low-high'; sLow.textContent = 'Lowest to Highest'; speedSelect.appendChild(sLow);
        const sHigh = document.createElement('option'); sHigh.value = 'high-low'; sHigh.textContent = 'Highest to Lowest'; speedSelect.appendChild(sHigh);
        if (['', 'low-high', 'high-low'].includes(selSpeed)) speedSelect.value = selSpeed;
      }

      // PPL select is a sort-order control (not a literal filter by PPL value)
      const pplSelect = document.getElementById('filter-ppl');
      if (pplSelect) {
        const sel = pplSelect.value;
        pplSelect.innerHTML = '';
        const o1 = document.createElement('option'); o1.value = ''; o1.textContent = 'Unsorted'; pplSelect.appendChild(o1);
        const o2 = document.createElement('option'); o2.value = 'low-high'; o2.textContent = 'Lowest to Highest'; pplSelect.appendChild(o2);
        const o3 = document.createElement('option'); o3.value = 'high-low'; o3.textContent = 'Highest to Lowest'; pplSelect.appendChild(o3);
        if (['', 'low-high', 'high-low'].includes(sel)) pplSelect.value = sel;
      }

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
        const tbody = document.getElementById('table-body');
        if (tbody) tbody.innerHTML = '<tr><td colspan="9">Error loading leaderboard.json</td></tr>';
      }
    }

    // Render table
    function renderTable() {
      const tbody = document.getElementById('table-body');
      if (!tbody) return;
      const filters = getFilters();
      tbody.innerHTML = '';

      // Collect visible entries first (apply filters except PPL sort)
      const visibleEntries = [];
      leaderboardData.forEach(entry => {
        const speed = entry.avg_tokens_per_sec || 0;
        const entryDevice = getEntryDevice(entry);
        const sizeStr = entry.file_size_mb != null ? entry.file_size_mb.toFixed(1) : 'N/A';
        const speedStr = speed.toFixed(2);
        const pplStr = entry.perplexity != null ? entry.perplexity.toFixed(2) : 'N/A';
        const peakStr = entry.peak_memory_mb != null ? entry.peak_memory_mb.toFixed(1) : 'N/A';
        const ramStr = entry.system_info?.ram_gb ?? 'N/A';

        if (filters.model && entry.model_name !== filters.model) return;
        if (filters.params && (entry.parameters || 'N/A') !== filters.params) return;
        if (filters.size) {
          const range = parseBucketLabel(filters.size);
          if (range) {
            const fs = entry.file_size_mb;
            if (fs == null) return;
            const [s,e] = range;
            if (!(fs >= s && fs <= e)) return;
          } else {
            // fallback to exact string match (legacy)
            if (sizeStr !== filters.size) return;
          }
        }
        // PPL select controls sort order rather than filtering by exact PPL value
        if (filters.peakRam && peakStr !== filters.peakRam) return;
        if (filters.device && entryDevice !== filters.device) return;
        if (filters.ram && ramStr !== filters.ram) return;

        visibleEntries.push(entry);
      });

      // Combined sorting: If both PPL and Speed are selected, PPL takes precedence
      // (so a user's PPL sort choice remains effective even after selecting Speed).
      if (filters.speed || filters.ppl) {
        visibleEntries.sort((a, b) => {
          // If PPL sort selected, compare by PPL first (missing values go to end)
          if (filters.ppl === 'low-high' || filters.ppl === 'high-low') {
            const aHas = (a.perplexity != null);
            const bHas = (b.perplexity != null);
            if (!aHas && !bHas) {
              // equal by PPL, continue to next key
            } else if (!aHas) {
              return 1; // a (N/A) goes after b
            } else if (!bHas) {
              return -1; // b (N/A) goes after a
            } else {
              // both have numeric PPL
              let cmpP = 0;
              if (a.perplexity < b.perplexity) cmpP = -1;
              else if (a.perplexity > b.perplexity) cmpP = 1;
              if (filters.ppl === 'high-low') cmpP = -cmpP;
              if (cmpP !== 0) return cmpP;
            }
          }

          // If Speed sort selected, compare by Speed next
          if (filters.speed === 'low-high' || filters.speed === 'high-low') {
            const aa = (a.avg_tokens_per_sec != null) ? a.avg_tokens_per_sec : (filters.speed === 'low-high' ? Infinity : -Infinity);
            const bb = (b.avg_tokens_per_sec != null) ? b.avg_tokens_per_sec : (filters.speed === 'low-high' ? Infinity : -Infinity);
            let cmpS = 0;
            if (aa < bb) cmpS = -1;
            else if (aa > bb) cmpS = 1;
            if (filters.speed === 'high-low') cmpS = -cmpS;
            if (cmpS !== 0) return cmpS;
          }

          return 0;
        });
      }

      // Now render rows in the final order
      visibleEntries.forEach(entry => {
        const speed = entry.avg_tokens_per_sec || 0;
        const isFailed = speed === 0;
        const entryDevice = getEntryDevice(entry);
        const sizeStr = entry.file_size_mb != null ? entry.file_size_mb.toFixed(1) : 'N/A';
        const speedStr = speed.toFixed(2);
        const pplStr = entry.perplexity != null ? entry.perplexity.toFixed(2) : 'N/A';
        const peakStr = entry.peak_memory_mb != null ? entry.peak_memory_mb.toFixed(1) : 'N/A';
        const ramStr = entry.system_info?.ram_gb ?? 'N/A';

        const row = document.createElement('tr');
        if (isFailed) row.classList.add('failed');
        row.dataset.modelName = entry.model_name || '';

        function formatDate(isoString) {
          if (!isoString) return 'N/A';
          return new Date(isoString).toLocaleString();
        }

        const modelNameCell = entry.huggingface_repo
          ? `<code><a href="${entry.huggingface_repo}" target="_blank" rel="noopener noreferrer">${entry.model_name}</a></code>`
          : `<code>${entry.model_name}</code>`;

        row.innerHTML = `
          <td>${entryDevice}</td>
          <td>${modelNameCell}</td>
          <td>${entry.parameters || 'N/A'}</td>
          <td>${peakStr}</td>
          <td>${speedStr}</td>
          <td>${sizeStr}</td>
          <td>${pplStr}</td>
          <td>${ramStr}</td>
          <td>${formatDate(entry.date_checked)}</td>
        `;

        tbody.appendChild(row);
      });
    }

    // Render chart: Speed vs Size
    function renderChart() {
      const canvas = document.getElementById('perfChart');
      if (!canvas) return;
      const ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);

      const filters = getFilters();

      // Get all valid entries (speed > 0)
      const validEntries = leaderboardData.filter(e => {
        if ((e.avg_tokens_per_sec || 0) <= 0) return false;
        const entryDevice = getEntryDevice(e);
        const speed = e.avg_tokens_per_sec || 0;
        const sizeStr = e.file_size_mb != null ? e.file_size_mb.toFixed(1) : 'N/A';
        const speedStr = speed.toFixed(2);
        const peakStr = e.peak_memory_mb != null ? e.peak_memory_mb.toFixed(1) : 'N/A';
        const ramStr = e.system_info?.ram_gb ?? 'N/A';

        // Apply filters (PPL is only a table sort control)
        if (filters.model && e.model_name !== filters.model) return false;
        if (filters.size) {
          const range = parseBucketLabel(filters.size);
          if (range) {
            const fs = e.file_size_mb;
            if (fs == null) return false;
            const [s,e2] = range;
            if (!(fs >= s && fs <= e2)) return false;
          } else {
            if (sizeStr !== filters.size) return false;
          }
        }
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

      // Save original colors for later restore and initialize per-point radii
      if (window.perfChart) {
        const ds = window.perfChart.data.datasets[0];
        ds._origBg = Array.isArray(ds.backgroundColor) ? ds.backgroundColor.slice() : Array(ds.data.length).fill(ds.backgroundColor);
        ds._origBorder = Array.isArray(ds.borderColor) ? ds.borderColor.slice() : Array(ds.data.length).fill(ds.borderColor);
        ds.radius = ds.data.map(() => 6);
      }

      // Helpers to highlight points by index(es)
      function setChartHighlight(indices) {
        const chart = window.perfChart;
        if (!chart) return;
        const ds = chart.data.datasets[0];
        const defaultRadius = 6;
        const highlightRadius = 10;
        const highlightBg = 'rgba(230,126,34,0.95)';
        const highlightBorder = 'rgba(189,74,0,1)';

        ds.radius = ds.data.map((_, i) => indices.includes(i) ? highlightRadius : defaultRadius);
        ds.backgroundColor = ds._origBg.map((c, i) => indices.includes(i) ? highlightBg : c);
        ds.borderColor = ds._origBorder.map((c, i) => indices.includes(i) ? highlightBorder : c);
        chart.update('none');
      }

      function clearChartHighlight() {
        const chart = window.perfChart;
        if (!chart) return;
        const ds = chart.data.datasets[0];
        ds.radius = ds.data.map(() => 6);
        ds.backgroundColor = ds._origBg.slice();
        ds.borderColor = ds._origBorder.slice();
        chart.update('none');
      }

      // Attach hover listeners to table rows to link with chart points
      const rows = document.querySelectorAll('#table-body tr');
      rows.forEach(row => {
        row.addEventListener('mouseenter', () => {
          const model = row.dataset.modelName;
          if (!model || !window.perfChart) return;
          const labels = window.perfChart.data.labels || [];
          const indices = [];
          labels.forEach((lab, idx) => { if (lab === model) indices.push(idx); });
          if (indices.length) setChartHighlight(indices);
        });
        row.addEventListener('mouseleave', () => {
          clearChartHighlight();
        });
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
    const refreshBtn = document.getElementById('refresh');
    if (refreshBtn) refreshBtn.addEventListener('click', loadLeaderboard);

    // Initialize
    loadLeaderboard();