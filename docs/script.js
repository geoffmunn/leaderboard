let leaderboardData = [];

// Load and render data
async function loadLeaderboard() {
  try {
    const response = await fetch('leaderboard.json');
    leaderboardData = await response.json();
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
  const hideFailed = document.getElementById('hide-failed').checked;
  
  tbody.innerHTML = '';
  
  leaderboardData.forEach(entry => {
    const speed = entry.avg_tokens_per_sec || 0;
    const isFailed = speed === 0;
    
    if (hideFailed && isFailed) return;
    
    const row = document.createElement('tr');
    if (isFailed) row.classList.add('failed');
    
    const config = entry.hardware_config;
    const configStr = `threads=${config.threads}, ctx=${config.ctx_size}`;
    
    row.innerHTML = `
      <td><code>${entry.model_name}</code></td>
      <td>${entry.parameters || 'N/A'}</td>
      <td>${entry.file_size_mb?.toFixed(1) || 'N/A'}</td>
      <td>${speed.toFixed(2)}</td>
      <td>${entry.peak_memory_mb?.toFixed(1) || 'N/A'}</td>
      <td>
        <small>
          ${entry.system_info?.device || 'N/A'} • 
          ${entry.system_info?.ram || 'N/A'}<br>
          <code>${entry.system_info?.cpu || 'N/A'}</code>
        </small>
      </td>
    `;
    
    tbody.appendChild(row);
  });
}

// Render chart: Speed vs Size
function renderChart() {
  const ctx = document.getElementById('perfChart').getContext('2d');
  ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
  
  const validEntries = leaderboardData.filter(e => e.avg_tokens_per_sec > 0);
  if (validEntries.length === 0) {
    ctx.font = '16px sans-serif';
    ctx.fillText('No valid benchmark data', 10, 30);
    return;
  }

  const data = {
    labels: validEntries.map(e => e.model_name),
    datasets: [{
      label: 'Tokens per Second',
      data: validEntries.map(e => ({ x: e.file_size_mb, y: e.avg_tokens_per_sec })),
      backgroundColor: 'rgba(52, 152, 219, 0.6)',
      borderColor: 'rgba(41, 128, 185, 1)',
      borderWidth: 1,
      radius: 6
    }]
  };
  
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

// Sort table
let sortDir = 1; // 1 = asc, -1 = desc
function sortTable(colIndex) {
  const headers = document.querySelectorAll('th');
  headers.forEach((th, i) => {
    if (i === colIndex) {
      th.textContent = th.textContent.replace(/ ▲| ▼/, '') + (sortDir === 1 ? ' ▲' : ' ▼');
    } else {
      th.textContent = th.textContent.replace(/ ▲| ▼/, '') + ' ▲';
    }
  });
  
  leaderboardData.sort((a, b) => {
    let aVal, bVal;
    switch(colIndex) {
      case 0: aVal = a.model_name; bVal = b.model_name; break;
      case 1: aVal = a.file_size_mb || 0; bVal = b.file_size_mb || 0; break;
      case 2: aVal = a.avg_tokens_per_sec || 0; bVal = b.avg_tokens_per_sec || 0; break;
      case 3: aVal = a.peak_memory_mb || 0; bVal = b.peak_memory_mb || 0; break;
      default: return 0;
    }
    if (typeof aVal === 'string') {
      return sortDir * aVal.localeCompare(bVal);
    }
    return sortDir * (aVal - bVal);
  });
  
  sortDir *= -1;
  renderTable();
  renderChart(); // Re-render chart after sorting (optional)
}

// Event listeners
document.getElementById('hide-failed').addEventListener('change', () => {
  renderTable();
  renderChart();
});
document.getElementById('refresh').addEventListener('click', loadLeaderboard);

// Initialize
loadLeaderboard();