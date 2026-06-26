/**
 * ProxyGen TV Cultura — v3.0.0
 * Inclui suporte à Fila Manual com prioridade
 */

// ─── Utilitários ───────────────────────────────────────────────

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = type;
    toast.style.display = 'block';
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => {
        toast.style.display = 'none';
    }, 3500);
}

function formatDatetime(dt) {
    if (!dt) return '—';
    if (dt.includes('T')) {
        return dt.replace('T', ' ').substring(0, 19);
    }
    return dt;
}

function updateLastRefresh() {
    const el = document.getElementById('last-update');
    if (el) {
        const now = new Date().toLocaleTimeString('pt-BR');
        el.textContent = `Atualizado às ${now}`;
    }
}


// ─── Stats ─────────────────────────────────────────────────────

async function fetchStats() {
    try {
        const res  = await fetch('/api/stats');
        const data = await res.json();

        document.getElementById('stats').innerHTML = `
            <div class="stat-card">
                <div class="stat-label">Workers</div>
                <div class="stat-value">${data.workers}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Ativos</div>
                <div class="stat-value">${data.ativos}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Concluídos</div>
                <div class="stat-value">${data.concluidos}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Erros</div>
                <div class="stat-value">${data.erros}</div>
            </div>
        `;
    } catch (err) {
        console.error('Erro carregando stats', err);
    }
}


// ─── Fila Manual ───────────────────────────────────────────────

async function fetchFilaManual() {
    try {
        const res   = await fetch('/api/fila-manual');
        const itens = await res.json();

        // ── Separa em dois grupos ──────────────────────────────
        // "Aguardando" = reservado pelo worker (na fila do executor), conta como ativo.
        const ATIVOS = ['Processando', 'Aguardando'];
        const pendentes    = itens.filter(i => i.status === 'Pendente');
        const processando  = itens.filter(i => ATIVOS.includes(i.status));
        const finalizados  = itens.filter(i => i.status !== 'Pendente' && !ATIVOS.includes(i.status));

        // ── Badge da fila de espera ────────────────────────────
        const badgeEspera = document.getElementById('manual-count');
        badgeEspera.textContent = pendentes.length > 0
            ? `${pendentes.length} na fila`
            : '0 na fila';

        // ── Badge dos em reprocessamento ───────────────────────
        const badgeReproc = document.getElementById('reprocessando-count');
        badgeReproc.textContent = processando.length > 0
            ? `${processando.length} ativo${processando.length !== 1 ? 's' : ''}`
            : '0 ativos';

        // ── Renderiza fila de espera (Pendente) ───────────────
        const tbodyEspera = document.getElementById('fila-manual-body');
        if (!pendentes.length) {
            tbodyEspera.innerHTML = `
                <tr class="empty-row">
                    <td colspan="7">Nenhum proxy aguardando na fila</td>
                </tr>`;
        } else {
            // Ordena por ID (quem entrou primeiro sai primeiro)
            const ordenados = [...pendentes].sort((a, b) => a.id - b.id);
            tbodyEspera.innerHTML = ordenados.map((item, idx) => {
                const criadoEm = formatDatetime(item.criado_em);
                const mensagem = item.mensagem || '—';
                const titulo   = item.titulo   || '—';
                const tipo     = item.tipo     || '—';
                const duracao  = item.duracao  || '—';
                const posicao  = idx === 0
                    ? `<span style="color:var(--accent);font-weight:700;">⚡ Próximo</span>`
                    : `<span style="color:var(--yellow);font-weight:700;">#${idx + 1}</span>`;
                return `
                    <tr>
                        <td>${posicao}</td>
                        <td><span class="mono">${item.media_id}</span></td>
                        <td class="text-muted" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${titulo}">${titulo}</td>
                        <td>${tipo}</td>
                        <td>${duracao}</td>
                        <td class="text-muted">${criadoEm}</td>
                        <td class="text-muted" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                            title="${mensagem}">${mensagem}</td>
                    </tr>
                `;
            }).join('');
        }

        // ── Renderiza em reprocessamento (Processando) ────────
        const tbodyReproc = document.getElementById('reprocessando-body');
        if (!processando.length) {
            tbodyReproc.innerHTML = `
                <tr class="empty-row">
                    <td colspan="7">Nenhum reprocessamento ativo</td>
                </tr>`;
        } else {
            tbodyReproc.innerHTML = [...processando].sort((a, b) => a.id - b.id).map(item => {
                const criadoEm = formatDatetime(item.criado_em);
                const mensagem = item.mensagem || '—';
                const titulo   = item.titulo   || '—';
                const tipo     = item.tipo     || '—';
                const duracao  = item.duracao  || '—';
                const st = item.status === 'Aguardando' ? 'Aguardando' : 'Processando';
                return `
                    <tr>
                        <td><span class="mono">${item.media_id}</span></td>
                        <td class="text-muted" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${titulo}">${titulo}</td>
                        <td>${tipo}</td>
                        <td>${duracao}</td>
                        <td><span class="badge badge-${st}">${st}</span></td>
                        <td class="text-muted">${criadoEm}</td>
                        <td class="text-muted" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                            title="${mensagem}">${mensagem}</td>
                    </tr>
                `;
            }).join('');
        }

    } catch (err) {
        console.error('Erro carregando fila manual', err);
    }
}


async function adicionarFilaManual() {
    const input  = document.getElementById('manual-media-id');
    const btn    = document.getElementById('btn-add-manual');
    const mediaId = input.value.trim();

    if (!mediaId) {
        showToast('Digite um Media ID válido.', 'error');
        input.focus();
        return;
    }

    btn.disabled  = true;
    btn.textContent = 'Enviando...';

    try {
        const res = await fetch('/api/fila-manual', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ media_id: mediaId })
        });

        const data = await res.json();

        if (data.ok) {
            showToast(`Media ID ${mediaId} adicionado à fila com prioridade! ⚡`, 'success');
            input.value = '';
            fetchFilaManual();
            fetchStats();
        } else {
            showToast(data.erro || 'Erro ao adicionar à fila.', 'error');
        }
    } catch (err) {
        showToast('Falha ao conectar com a API.', 'error');
        console.error(err);
    } finally {
        btn.disabled    = false;
        btn.textContent = 'Adicionar à Fila';
    }
}

// Permite pressionar Enter no input para adicionar
document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('manual-media-id');
    if (input) {
        input.addEventListener('keydown', e => {
            if (e.key === 'Enter') adicionarFilaManual();
        });
    }
});


// ─── Jobs Ativos ───────────────────────────────────────────────

async function fetchActiveJobs() {
    try {
        const res    = await fetch('/api/jobs');
        const active = await res.json();
        const tbody  = document.getElementById('active-jobs');
        const badge  = document.getElementById('active-count');

        badge.textContent = `${active.length} ativo${active.length !== 1 ? 's' : ''}`;

        if (!active.length) {
            tbody.innerHTML = `
                <tr class="empty-row">
                    <td colspan="8">Nenhum job ativo no momento</td>
                </tr>`;
            return;
        }

        tbody.innerHTML = active.map(job => {
            const pct    = job.percentual || 0;
            const inicio = formatDatetime(job.inicio);
            const titulo = job.titulo || '—';
            const tipo   = job.tipo   || '—';
            const duracao = job.duracao || '—';

            return `
                <tr>
                    <td><span class="mono">${job.media_id}</span></td>
                    <td class="text-muted" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${titulo}">${titulo}</td>
                    <td>${tipo}</td>
                    <td>${duracao}</td>
                    <td><span class="badge badge-${job.status}">${job.status}</span></td>
                    <td>
                        <div class="progress-wrap">
                            <div class="progress-bar-bg">
                                <div class="progress-bar-fill" style="width:${pct}%"></div>
                            </div>
                            <span class="progress-label">${pct}%</span>
                        </div>
                    </td>
                    <td class="text-muted">${inicio}</td>
                    <td>
                        <button class="btn-sm btn-cancel" onclick="cancelJob('${job.media_id}')">
                            Cancelar
                        </button>
                    </td>
                </tr>
            `;
        }).join('');

    } catch (err) {
        console.error('Erro carregando jobs ativos', err);
    }
}


// ─── Histórico ─────────────────────────────────────────────────

async function fetchHistory() {
    try {
        const res     = await fetch('/api/history');
        const history = await res.json();
        const tbody   = document.getElementById('history-jobs');
        const badge   = document.getElementById('history-count');

        badge.textContent = `${history.length} registro${history.length !== 1 ? 's' : ''}`;

        if (!history.length) {
            tbody.innerHTML = `
                <tr class="empty-row">
                    <td colspan="8">Sem histórico disponível</td>
                </tr>`;
            return;
        }

        tbody.innerHTML = history.slice().reverse().map(job => {
            const status      = job.status || '';
            const canRetry    = status === 'Erro' || status === 'Cancelado';
            const classStatus = status === 'Concluído' ? 'Concluido' : status;
            const horario     = formatDatetime(job.fim);
            const mensagem    = job.mensagem || '—';
            const titulo      = job.titulo   || '—';
            const tipo        = job.tipo     || '—';
            const duracao     = job.duracao  || '—';
            // Entradas do MAM legado têm id=null — o botão Refazer chama force-retry via retryJob
            const isLegado    = job.id === null;

            return `
                <tr>
                    <td><span class="mono">${job.media_id}</span></td>
                    <td class="text-muted" style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${titulo}">${titulo}</td>
                    <td>${tipo}</td>
                    <td>${duracao}</td>
                    <td><span class="badge badge-${isLegado ? 'legado' : classStatus}">${isLegado ? 'Legado' : status}</span></td>
                    <td class="text-muted">${horario}</td>
                    <td class="text-muted"
                        style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                        title="${mensagem}">${mensagem}</td>
                    <td>
                        ${canRetry
                            ? `<button class="btn-sm btn-retry" onclick="retryJob('${job.media_id}')">
                                   Refazer
                               </button>`
                            : '—'
                        }
                    </td>
                </tr>
            `;
        }).join('');

    } catch (err) {
        console.error('Erro carregando histórico', err);
    }
}


// ─── Ações ─────────────────────────────────────────────────────

async function cancelJob(mediaId) {
    if (!confirm(`Cancelar processamento de ${mediaId}?`)) return;

    try {
        await fetch(`/api/job/${mediaId}/cancel`, { method: 'POST' });
        showToast(`Job ${mediaId} cancelado.`, 'success');
        fetchAll();
    } catch (err) {
        showToast('Falha ao cancelar.', 'error');
        console.error(err);
    }
}


async function retryJob(mediaId) {
    if (!confirm(`Refazer processamento de ${mediaId}?`)) return;

    try {
        const res  = await fetch(`/api/job/${mediaId}/retry`, { method: 'POST' });
        const data = await res.json();

        if (data.ok) {
            showToast(`Job ${mediaId} reenviado para a fila.`, 'success');
            fetchAll();
        } else {
            showToast(data.erro || 'Erro ao refazer job.', 'error');
        }
    } catch (err) {
        showToast('Falha ao conectar.', 'error');
        console.error(err);
    }
}


// ─── Loop principal ────────────────────────────────────────────

function fetchAll() {
    fetchStats();
    fetchFilaManual();
    fetchActiveJobs();
    fetchHistory();
    updateLastRefresh();
}

fetchAll();
setInterval(fetchAll, 3000);