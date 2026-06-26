async function loadStats() {
    const r = await fetch("/api/stats");
    const data = await r.json();

    document.getElementById("workers").innerText = data.workers;
    document.getElementById("ativos").innerText = data.ativos;
    document.getElementById("concluidos").innerText = data.concluidos;
    document.getElementById("erros").innerText = data.erros;
}

async function loadJobs() {
    const r = await fetch("/api/jobs");
    const data = await r.json(); // Now returns array directly

    const table = document.getElementById("jobs-table");
    table.innerHTML = "";

    data.forEach(job => {
        table.innerHTML += `
            <tr>
                <td>${job.media_id}</td>
                <td>${job.tipo || '-'}</td>
                <td>${job.status}</td>
                <td>
                    <progress value="${job.percentual || 0}" max="100">
                    </progress>
                    ${job.percentual || 0}%
                </td>
                <td>
                    <button onclick="cancelJob('${job.media_id}')">
                        ✖
                    </button>
                </td>
            </tr>
        `;
    });
}

async function loadHistory() {
    const r = await fetch("/api/history");
    const data = await r.json(); // Now returns array directly

    const table = document.getElementById("history-table");
    table.innerHTML = "";

    data.forEach(item => {
        table.innerHTML += `
            <tr>
                <td>${item.media_id}</td>
                <td>${item.status || item.resultado || '-'}</td>
                <td>${item.fim || item.horario || '-'}</td>
            </tr>
        `;
    });
}

// New function to load media details (for future enhancement)
async function loadMediaDetails(mediaId) {
    try {
        const mediaResp = await fetch(`/api/media/${mediaId}`);
        const media = await mediaResp.json();

        const eventsResp = await fetch(`/api/media/${mediaId}/events`);
        const events = await eventsResp.json();

        // This would populate a modal or detail view
        console.log("Media details:", media);
        console.log("Media events:", events);
    } catch (error) {
        console.error("Error loading media details:", error);
    }
}

async function loadData() {
    await loadStats();
    await loadJobs();
    await loadHistory();
}

loadData();
setInterval(loadData, 2000);

async function cancelJob(mediaId) {
    if (!confirm("Cancelar processamento?")) {
        return;
    }

    const r = await fetch(`/api/job/${mediaId}/cancel`, {
        method: "POST"
    });
    const data = await r.json();

    if (!data.ok) {
        alert(`Erro ao cancelar: ${data.erro}`);
    }

    loadData();
}