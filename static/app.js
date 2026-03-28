document.addEventListener('DOMContentLoaded', () => {
    // Elements
    const searchInput = document.getElementById('searchInput');
    const gallery = document.getElementById('gallery');
    const loadingSpinner = document.getElementById('loadingSpinner');
    
    // Modal Elements
    const btnSettings = document.getElementById('btnSettings');
    const settingsModal = document.getElementById('settingsModal');
    const btnCloseModal = document.getElementById('closeModal');
    const folderPathInput = document.getElementById('folderPathInput');
    const btnStartIndex = document.getElementById('btnStartIndex');
    const btnStopIndex = document.getElementById('btnStopIndex');
    
    // Status Elements
    const statusIndicator = document.getElementById('statusIndicator');
    const currentFolderText = document.getElementById('currentFolderText');
    const filesFoundCount = document.getElementById('filesFoundCount');
    const filesProcessedCount = document.getElementById('filesProcessedCount');
    const filesErrorCount = document.getElementById('filesErrorCount');
    const indexProgressFill = document.getElementById('indexProgressFill');
    const indexedFoldersList = document.getElementById('indexedFoldersList');

    // Lightbox
    const lightbox = document.getElementById('lightbox');
    const closeLightbox = document.getElementById('closeLightbox');
    const lightboxImg = document.getElementById('lightboxImg');
    const lightboxMeta = document.getElementById('lightboxMeta');

    // State
    let statusInterval = null;

    // --- Search functionality ---
    let searchTimeout = null;
    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        const q = e.target.value.trim();
        if (q.length > 2) {
            searchTimeout = setTimeout(() => {
                performSearch(q);
            }, 800);
        } else if (q.length === 0) {
            showWelcome();
        }
    });

    searchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            clearTimeout(searchTimeout);
            const q = e.target.value.trim();
            if (q.length > 0) performSearch(q);
        }
    });

    function showWelcome() {
        gallery.innerHTML = `
            <div class="welcome-hero">
                <i class="fa-regular fa-images hero-icon"></i>
                <h2>Descubra as suas memórias através de IA</h2>
                <p>Pesquise por conceitos, objetos ou emoções. FotosAI compreende linguagem natural.</p>
            </div>
        `;
    }

    async function performSearch(query) {
        gallery.innerHTML = '';
        loadingSpinner.classList.remove('hidden');

        try {
            const response = await fetch('/api/search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ query, top_k: 30 })
            });
            const data = await response.json();
            
            loadingSpinner.classList.add('hidden');
            
            if (!data.results || data.results.length === 0) {
                gallery.innerHTML = `
                    <div class="welcome-hero">
                        <i class="fa-solid fa-ghost hero-icon"></i>
                        <h2>Nenhum resultado</h2>
                        <p>A IA não encontrou correspondências altamente prováveis para "${query}".</p>
                    </div>
                `;
                return;
            }

            renderGallery(data.results);
        } catch (error) {
            console.error('Search error:', error);
            loadingSpinner.classList.add('hidden');
        }
    }

    function renderGallery(results) {
        gallery.innerHTML = '';
        results.forEach((res, index) => {
            const card = document.createElement('div');
            card.className = 'photo-card';
            card.style.animationDelay = `${index * 0.05}s`;
            
            // For a production system we'd use bounding box / thumb api, but for now we pipe the full image 
            // from the backend. The object-fit: cover CSS handles the thumbnail view.
            const imageUrl = `/image/${res.id}`;
            const similarityPercent = Math.max(0, (1 - res.score)*100).toFixed(1);
            
            card.innerHTML = `
                <img src="${imageUrl}" alt="${res.file_name}" loading="lazy">
                <div class="score-badge"><i class="fa-solid fa-wand-magic-sparkles"></i> ${similarityPercent}%</div>
                <div class="photo-overlay">
                    <p class="value-text" style="word-break: break-all; font-size: 0.8rem;">${res.file_name}</p>
                </div>
            `;
            
            card.addEventListener('click', () => openLightbox(imageUrl, res.file_path));
            gallery.appendChild(card);
        });
    }

    // --- Lightbox ---
    function openLightbox(url, path) {
        lightboxImg.src = url;
        lightboxMeta.innerHTML = `<strong>Caminho:</strong> ${path}`;
        lightbox.classList.remove('hidden');
    }

    closeLightbox.addEventListener('click', () => {
        lightbox.classList.add('hidden');
        lightboxImg.src = '';
    });

    // --- Indexer Modal & State ---
    btnSettings.addEventListener('click', () => {
        settingsModal.classList.remove('hidden');
        checkStatus();
        fetchFolders();
    });

    btnCloseModal.addEventListener('click', () => {
        settingsModal.classList.add('hidden');
    });

    btnStartIndex.addEventListener('click', async () => {
        const path = folderPathInput.value.trim();
        if (!path) return alert("Introduza um caminho válido!");
        
        try {
            const res = await fetch('/api/index', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ folder_path: path })
            });
            const data = await res.json();
            if (res.ok) {
                checkStatus();
            } else {
                alert("Erro: " + data.detail);
            }
        } catch (err) {
            console.error(err);
        }
    });

    btnStopIndex.addEventListener('click', async () => {
        await fetch('/api/index/stop', { method: 'POST' });
        checkStatus();
    });

    async function checkStatus() {
        try {
            const res = await fetch('/api/status');
            const data = await res.json();
            
            if (data.is_running) {
                statusIndicator.textContent = "A Indexar";
                statusIndicator.className = "badge active";
                btnStartIndex.classList.add('hidden');
                btnStopIndex.classList.remove('hidden');
                
                if (!statusInterval) {
                    statusInterval = setInterval(checkStatus, 2000);
                }
            } else {
                statusIndicator.textContent = "Inativo";
                statusIndicator.className = "badge";
                btnStartIndex.classList.remove('hidden');
                btnStopIndex.classList.add('hidden');
                
                if (statusInterval) {
                    clearInterval(statusInterval);
                    statusInterval = null;
                }
            }
            
            currentFolderText.textContent = data.current_folder || "-";
            filesFoundCount.textContent = data.total_files_found;
            filesProcessedCount.textContent = data.files_processed;
            filesErrorCount.textContent = data.errors;
            
            if (data.total_files_found > 0) {
                const percent = (data.files_processed / data.total_files_found) * 100;
                indexProgressFill.style.width = percent + '%';
            } else {
                indexProgressFill.style.width = '0%';
            }

        } catch (err) {
            console.error("Erro ao verificar estado", err);
        }
    }
    
    async function fetchFolders() {
        try {
            const res = await fetch('/api/folders');
            const data = await res.json();
            indexedFoldersList.innerHTML = '';
            
            if (data.folders.length === 0) {
                indexedFoldersList.innerHTML = '<li style="padding: 0.75rem; color: #94a3b8; font-size: 0.9rem;">Nenhuma pasta indexada.</li>';
                return;
            }
            
            data.folders.forEach(f => {
                const li = document.createElement('li');
                li.style.cssText = 'padding: 0.75rem 1rem; border-bottom: 1px solid rgba(255,255,255,0.05); font-size: 0.9rem; display: flex; justify-content: space-between; align-items: center;';
                
                const date = new Date(f.last_indexed + 'Z').toLocaleString('pt-PT');
                li.innerHTML = `
                    <div style="flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; margin-right: 15px;">
                        <i class="fa-regular fa-folder" style="color:#6366f1; margin-right:8px;"></i>${f.folder_path}
                    </div>
                    <div style="display:flex; align-items:center; gap: 10px; min-width: 140px; justify-content: flex-end;">
                        <span style="color:#94a3b8; font-size:0.8rem;">${date}</span>
                        <button class="icon-btn delete-folder-btn" data-id="${f.id}" title="Eliminar pasta e fotos associadas" style="color: #ef4444; font-size: 1rem; padding: 4px;">
                            <i class="fa-solid fa-trash"></i>
                        </button>
                    </div>
                `;
                indexedFoldersList.appendChild(li);
            });

            // Add event listeners to delete buttons
            document.querySelectorAll('.delete-folder-btn').forEach(btn => {
                btn.addEventListener('click', async (e) => {
                    const folderId = e.currentTarget.getAttribute('data-id');
                    if(confirm("Tem a certeza que deseja eliminar esta pasta e todas as suas fotografias do índice?")) {
                        try {
                            const delRes = await fetch('/api/folders/' + folderId, { method: 'DELETE' });
                            if (delRes.ok) {
                                fetchFolders();
                            } else {
                                const errData = await delRes.json();
                                alert("Erro: " + errData.detail);
                            }
                        } catch (err) {
                            console.error(err);
                            alert("Erro ao eliminar a pasta.");
                        }
                    }
                });
            });
        } catch(err) {
            console.error(err);
        }
    }
});
