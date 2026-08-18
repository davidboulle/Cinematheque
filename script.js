/* TODO
    - Rennomer fichier depuis le site (que se passe til si le fichier est renommé en dehors du site ?)
    - Derniere discussion, fichier déplacé -> fusion
    - Bulk tag edit causes json brain damage
*/

let library = { movies: {}, playlists: {} };
let currentFilter = { type: 'all', value: null };
let searchTerm = '';
let searchTagsTerm = '';
let selectedTags = []; // Support du filtrage par plusieurs étiquettes
let tagsEditMode = false; // Mode édition des étiquettes (icônes ✎/× visibles ou non)
let bulkTagCandidates = [];
let showThumbnails = true;
let sortType = 'random'; // name_asc, name_desc, random

async function api(path, opts) {
    const res = await fetch(path, opts);
    return res.json();
}

async function loadLibrary() {
    library = await api('/api/library');
    renderSidebar();
    renderGrid();
    renderOptions();
}

function movieList() {
    return Object.entries(library.movies).map(([id, m]) => ({ id, ...m }));
}

function tagsList() {
    const tagsCount = {};
    movieList().forEach(m => (m.tags || []).forEach(t => { tagsCount[t] = (tagsCount[t] || 0) + 1; }));
    return Object.keys(tagsCount).sort();
}

function renderOptions() {
    let btnThumbnails = document.getElementById('showHideThumbnails')
    let btnSort = document.getElementById('sortType')

    switch (sortType) {
        case 'name_asc':
            btnSort.textContent = 'Titre ↓';
            break;
        case 'name_desc':
            btnSort.textContent = 'Titre ↑';
            break;
        case 'random':
            btnSort.textContent = 'Aléatoire';
            break;
        default:
            btnSort.textContent = 'Aléatoire';
    }

    btnThumbnails.textContent = showThumbnails ? '🖼️' : '✖️';
}

function renderSidebar() {
    const movies = movieList();

    const tagsCount = {};
    movies.forEach(m => (m.tags || []).forEach(t => { tagsCount[t] = (tagsCount[t] || 0) + 1; }));
    const tags = filteredTags();

    const currentFilteredMovies = filteredMovies();
    const availableTags = {};

    currentFilteredMovies.forEach(m => {
        (m.tags || []).forEach(t => {
            availableTags[t] = (availableTags[t] || 0) + 1;
        });
    });

    const tagsToDisplay = tags.filter(t =>
        selectedTags.includes(t) || (availableTags[t] > 0)
    );

    document.getElementById('count-all').textContent = movies.length;
    document.getElementById('count-fav').textContent = movies.filter(m => m.favorite).length;
    document.getElementById('count-dup').textContent = movies.filter(m => (m.duplicate_of || []).length > 0).length;

    // ---------------------------------------------------------
    // ÉTIQUETTES
    // ---------------------------------------------------------

    const tagsContainer = document.getElementById('tags-list');

    tagsContainer.innerHTML = tagsToDisplay.map(tag => {
        const isSelected = selectedTags.includes(tag);
        const count = availableTags[tag] || 0;

        return `
    <div
      class="nav-item tag-item ${isSelected ? 'active' : ''}"
      data-tag="${escapeAttr(tag)}"
      title="Filtrer par #${escapeAttr(tag)}"
    >
      <span># ${escapeHtml(tag)}</span>

      <div>
        <span
          class="count"
          style="margin-right:6px;"
        >${count}</span>

        <button
          class="list-edit tag-edit ${tagsEditMode ? '' : 'tag-edit-unactive'}"
          title="Modifier l'étiquette"
          data-edit-tag="${escapeAttr(tag)}"
        >✎</button>

        <button
          class="list-edit tag-edit ${tagsEditMode ? '' : 'tag-edit-unactive'}"
          title="Supprimer l'étiquette"
          style="color:red;"
          data-del-tag="${escapeAttr(tag)}"
        >✕</button>
      </div>
    </div>
  `;
    }).join('') || `
  <div
    class="nav-item"
    style="color:var(--text-muted);cursor:default;"
  >
    Aucune étiquette
  </div>
`;

    // Playlists
    const plList = document.getElementById('playlists-list');
    const names = Object.keys(library.playlists || {});
    plList.innerHTML = names.map(n => {
        // On vérifie si la playlist est actuellement sélectionnée
        const isActive = (currentFilter.type === 'playlist' && currentFilter.value === n);
        return `
        <div class="nav-item ${isActive ? 'active' : ''}" data-filter="playlist" data-value="${escapeAttr(n)}">
          <span>${escapeHtml(n)}</span>
          <div>
            <span class="count" style="margin-right:6px;">${library.playlists[n].length}</span>
            <button class="list-edit" title="Renommer la playlist" data-edit-playlist="${escapeAttr(n)}">✎</button>
          </div>
        </div>`;
    }).join('') || `<div class="nav-item" style="color:var(--text-muted);cursor:default;">Aucune</div>`;

    attachSidebarEvents();
}

function filteredMovies() {
    let movies = movieList();

    // -------------------------------------------------------
    // FILTRE PAR ÉTIQUETTES
    // -------------------------------------------------------
    if (selectedTags.length > 0) {
        movies = movies.filter(movie => {
            const movieTags = movie.tags || [];

            // Le film doit posséder TOUTES les étiquettes sélectionnées.
            return selectedTags.every(tag => movieTags.includes(tag));
        });
    }

    // -------------------------------------------------------
    // AUTRES FILTRES
    // -------------------------------------------------------
    else if (currentFilter.type === 'favorites') {
        movies = movies.filter(m => m.favorite);

    } else if (currentFilter.type === 'duplicates') {
        movies = movies.filter(m =>
            (m.duplicate_of || []).length > 0
        );

    } else if (currentFilter.type === 'category') {
        movies = movies.filter(m =>
            (m.categories || []).includes(currentFilter.value)
        );

    } else if (currentFilter.type === 'playlist') {
        const ids = library.playlists[currentFilter.value] || [];

        movies = movies.filter(m =>
            ids.includes(m.id)
        );
    }

    // -------------------------------------------------------
    // RECHERCHE GLOBALE
    // -------------------------------------------------------
    if (searchTerm.trim()) {
        const term = searchTerm.toLowerCase();

        movies = movies.filter(m =>
            m.title.toLowerCase().includes(term) ||
            (m.tags || []).some(tag =>
                tag.toLowerCase().includes(term)
            )
        );
    }

    // -------------------------------------------------------
    // TRI (SORTING)
    // -------------------------------------------------------
    if (sortType === 'name_asc') {
        movies.sort((a, b) => a.title.localeCompare(b.title));
    } else if (sortType === 'name_desc') {
        movies.sort((a, b) => b.title.localeCompare(a.title));
    } else if (sortType === 'random') {
        // Mélange de Fisher-Yates pour un tri aléatoire robuste
        for (let i = movies.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [movies[i], movies[j]] = [movies[j], movies[i]];
        }
    }

    return movies;
}


function filteredTags() {
    let tags = tagsList();

    // Recherche dans les étiquettes
    if (searchTagsTerm.trim()) {
        const search = searchTagsTerm.toLowerCase();

        tags = tags.filter(tag =>
            tag.toLowerCase().includes(search)
        );
    }

    return tags.sort((a, b) =>
        a.localeCompare(b)
    );
}

function renderGrid() {
    const movies = filteredMovies();
    const grid = document.getElementById('grid');
    const empty = document.getElementById('emptyMsg');

    bulkTagCandidates = Array.from(new Set(
        movieList().flatMap(m => m.tags || [])
    )).sort();

    const bulkForm = document.querySelector('.bulk-tag-form');
    const filterActive = selectedTags.length > 0 || searchTerm.trim().length > 0;
    bulkForm.style.display = filterActive ? 'flex' : 'none';

    const titles = {
        all: 'Tous les films',
        favorites: '★ Favoris',
        duplicates: '⚠ Doublons potentiels',
        category: currentFilter.value,
        playlist: currentFilter.value,
        tags: selectedTags.length
            ? selectedTags.map(tag => `# ${tag}`).join(' + ')
            : 'Étiquettes'
    };

    document.getElementById('sectionTitle').innerHTML =
        `${escapeHtml(titles[currentFilter.type] || 'Films')} <span class="tag" id="sectionCount">${movies.length}</span>`;

    if (movies.length === 0) {
        grid.innerHTML = '';
        empty.style.display = 'block';
        return;
    }
    empty.style.display = 'none';

    grid.innerHTML = movies.map(m => {
        const isDup = (m.duplicate_of || []).length > 0;
        let posterFallbackBlock = `<span class="poster-fallback">🎞️</span>`;
        let posterThumbnailBlock = `
            <img class="poster-img" src="/api/thumbnail?id=${m.id}_1" alt="" loading="lazy" onerror="this.remove();">
                <div class="poster-dots">
                    <span class="dot active"></span><span class="dot"></span><span class="dot"></span>
                </div>`;

        return `
    <div class="card" data-id="${m.id}">
      <div class="strip"></div>
        <div class="poster ${m.missing ? 'missing' : ''}">
        ${m.missing ? 'FICHIER INTROUVABLE' : showThumbnails ? posterThumbnailBlock : posterFallbackBlock}
            <div class="card-actions">
                <button class="card-btn fav-btn ${m.favorite ? 'active' : ''}" title="Favori" data-action="fav">★</button>
                  ${isDup ? '<span class="card-btn dup-badge" title="Voir les doublons" data-action="dup">⚠</span>' : ''}
                <span class="action-filler"></span>
                <button class="card-btn details-btn" title="Détails, étiquettes et playlists" data-action="details">⋯</button>
            </div>
        </div>
      <div class="card-body">
        <div class="card-title-row">
          <p class="card-title">${escapeHtml(m.title)}</p>
        </div>
      </div>
    </div>
  `;
    }).join('');

    attachCardEvents();
}

function attachCardEvents() {
    document.querySelectorAll('.card').forEach(card => {
        const id = card.dataset.id;

        card.querySelector('.poster').onclick = () => playMovie(id);
        card.querySelector('.card-title').onclick = () => playMovie(id);

        const posterEl = card.querySelector('.poster');
        const posterImg = card.querySelector('.poster-img');
        const dots = card.querySelectorAll('.poster-dots .dot');

        if (posterEl && posterImg) {
            posterEl.onmousemove = (e) => {
                const rect = posterEl.getBoundingClientRect();
                const relX = e.clientX - rect.left;
                const section = Math.min(3, Math.max(1, Math.ceil((relX / rect.width) * 3)));
                console.log(`Section: ${section}`);
                const newSrc = `/api/thumbnail?id=${id}_${section}`;
                console.log(`New src: ${newSrc}`);
                if (!posterImg.src.endsWith(`n=${section}`)) {
                    posterImg.src = newSrc;
                    dots.forEach((d, i) => d.classList.toggle('active', i === section - 1));
                }
            };

            posterEl.onmouseleave = () => {
                posterImg.src = `/api/thumbnail?id=${id}_1`;
                dots.forEach((d, i) => d.classList.toggle('active', i === 0));
            };
        }

        card.querySelector('[data-action="fav"]').onclick = async (e) => {
            e.stopPropagation();
            const m = library.movies[id];
            const value = !m.favorite;
            await api('/api/favorite', { method: 'POST', body: JSON.stringify({ id, value }) });
            m.favorite = value;
            renderSidebar();
            renderGrid();
        };

        const dupBtn = card.querySelector('[data-action="dup"]');
        if (dupBtn) {
            dupBtn.onclick = (e) => {
                e.stopPropagation();
                togglePopover(e.currentTarget, () => openDuplicatesPopover(id, e.currentTarget));
            };
        }

        card.querySelector('[data-action="details"]').onclick = (e) => {
            e.stopPropagation();
            togglePopover(e.currentTarget, () => openDetailsPopover(id, e.currentTarget));
        };
    });
}

async function playMovie(id) {
    const res = await api(`/api/play?id=${id}`);
    if (res.error) alert("Impossible de lancer le fichier : " + res.error);
}

// ---------- Popover ajout à une playlist (fusionnée dans openDetailsPopover) ----------

function outsideClickClose(e) {
    const pop = document.getElementById('activePopover');
    if (pop && !pop.contains(e.target)) closePopover();
}

function closePopover() {
    const pop = document.getElementById('activePopover');
    if (pop) pop.remove();
    document.removeEventListener('click', outsideClickClose);
    activePopoverAnchor = null;
}

// Garde en mémoire quel bouton a ouvert le popover actif, pour distinguer
// "reclic sur le même bouton" (toggle → fermer) de "clic sur un autre
// bouton" (fermer l'ancien et ouvrir le nouveau en un seul clic).
let activePopoverAnchor = null;

function togglePopover(anchor, openFn) {
    if (activePopoverAnchor === anchor) {
        closePopover(); // reclic sur le même bouton → juste fermer
        return;
    }
    closePopover(); // ferme l'éventuel autre popover ouvert
    openFn();
}

function formatSize(bytes) {
    if (bytes === null || bytes === undefined) return 'Taille inconnue';
    const gb = bytes / (1024 ** 3);
    if (gb >= 1) return gb.toFixed(2) + ' Go';
    const mb = bytes / (1024 ** 2);
    return mb.toFixed(0) + ' Mo';
}

// ---------- Popover comparaison de doublons ----------
function openDuplicatesPopover(id, anchor) {
    closePopover();
    activePopoverAnchor = anchor;
    const m = library.movies[id];
    const groupIds = [id, ...(m.duplicate_of || [])];
    const rect = anchor.getBoundingClientRect();

    const pop = document.createElement('div');
    pop.className = 'popover dup-popover';
    pop.id = 'activePopover';
    pop.style.top = (rect.bottom + 6) + 'px';
    pop.style.left = Math.min(rect.left, window.innerWidth - 360) + 'px';

    pop.innerHTML = `
    <div style="font-size:11px;color:var(--text-muted);margin-bottom:8px;">
      ${groupIds.length} FICHIERS AU TITRE SIMILAIRE — compare et supprime toi-même celui que tu ne veux pas garder
    </div>
    ${groupIds.map(gid => {
        const gm = library.movies[gid];
        if (!gm) return '';
        return `
        <div class="dup-entry">
          <p class="dup-title">${escapeHtml(gm.title)}</p>
          <p class="dup-path">${escapeHtml(gm.path)}</p>
          <p class="dup-size">${formatSize(gm.size_bytes)}</p>
          <div class="dup-actions">
            <button class="btn" data-play="${gid}">▶ Lire</button>
            <button class="btn" data-reveal="${gid}">📂 Ouvrir le dossier</button>
          </div>
        </div>
      `;
    }).join('')}
  `;
    document.body.appendChild(pop);

    pop.querySelectorAll('[data-play]').forEach(btn => {
        btn.onclick = () => playMovie(btn.dataset.play);
    });
    pop.querySelectorAll('[data-reveal]').forEach(btn => {
        btn.onclick = async () => {
            const res = await api(`/api/reveal?id=${btn.dataset.reveal}`);
            if (res.error) alert("Impossible d'ouvrir le dossier : " + res.error);
        };
    });

    setTimeout(() => document.addEventListener('click', outsideClickClose), 0);
}

// =========================================================
// GESTION DES ÉVÉNEMENTS DE LA SIDEBAR
// =========================================================

// Suppression d'une étiquette — réutilisée par le bouton supprimer et par
// le renommage quand le nouveau nom est laissé vide.
async function performDeleteTag(tagName) {
    try {
        const response = await api('/api/tag/delete', {
            method: 'POST',
            body: JSON.stringify({ tag: tagName })
        });

        if (response && response.error) {
            alert("Impossible de supprimer l'étiquette : " + response.error);
            return false;
        }

        selectedTags = selectedTags.filter(tag => tag !== tagName);
        await loadLibrary();
        return true;

    } catch (error) {
        console.error("Erreur lors de la suppression de l'étiquette :", error);
        alert("Impossible de supprimer l'étiquette.");
        return false;
    }
}

// Suppression d'une playlist — réutilisée par le bouton supprimer et par
// le renommage quand le nouveau nom est laissé vide.
async function performDeletePlaylist(name) {
    const r = await api('/api/playlist/delete', {
        method: 'POST',
        body: JSON.stringify({ name })
    });
    library.playlists = r.playlists;

    // Si cette playlist était le filtre actif, on revient à "Tous les films".
    if (currentFilter.type === 'playlist' && currentFilter.value === name) {
        currentFilter = { type: 'all', value: null };
    }
    renderSidebar();
    renderGrid();
}

function attachSidebarEvents() {

    // -------------------------------------------------------
    // ÉTIQUETTES — renommer / supprimer uniquement.
    // Le clic de sélection/désélection est géré une seule fois par
    // le listener délégué setupSidebarDelegatedEvents() ci-dessous,
    // pour éviter le doublon qui causait un toggle en double.
    // -------------------------------------------------------

    document.querySelectorAll('.tag-item').forEach(item => {

        const tagName = item.dataset.tag;

        // -------------------------------------------------------
        // RENOMMER
        // -------------------------------------------------------

        const editButton =
            item.querySelector('[data-edit-tag]');

        if (editButton) {

            editButton.onclick = async (event) => {

                // Empêche le clic de remonter jusqu'à la ligne.
                event.stopPropagation();

                const newName = prompt(
                    "Renommer l'étiquette :",
                    tagName
                );

                // Annulé (Échap ou bouton Annuler) : on ne fait rien.
                if (newName === null) {
                    return;
                }

                const cleanName = newName.trim();

                // Champ vidé volontairement : on propose la suppression.
                if (!cleanName) {
                    if (confirm(
                        `Supprimer l'étiquette "${tagName}" ?`
                    )) {
                        await performDeleteTag(tagName);
                    }
                    return;
                }

                if (cleanName === tagName) {
                    return;
                }

                try {

                    const response = await api('/api/tag/rename', {
                        method: 'POST',
                        body: JSON.stringify({
                            old: tagName,
                            new: cleanName
                        })
                    });

                    // Si l'API retourne une erreur explicite.
                    if (response && response.error) {
                        alert(
                            "Impossible de renommer l'étiquette : " +
                            response.error
                        );
                        return;
                    }

                    // Conserver la sélection si cette étiquette
                    // faisait partie du filtre actuel.
                    selectedTags = selectedTags.map(tag =>
                        tag === tagName
                            ? cleanName
                            : tag
                    );

                    await loadLibrary();

                } catch (error) {

                    console.error(
                        "Erreur lors du renommage de l'étiquette :",
                        error
                    );

                    alert(
                        "Impossible de renommer l'étiquette."
                    );
                }
            };
        }


        // -------------------------------------------------------
        // SUPPRIMER
        // -------------------------------------------------------

        const deleteButton =
            item.querySelector('[data-del-tag]');

        if (deleteButton) {

            deleteButton.onclick = async (event) => {

                // Empêche le clic de sélectionner/désélectionner
                // l'étiquette.
                event.stopPropagation();

                const confirmed = confirm(
                    `Supprimer l'étiquette "${tagName}" ` +
                    `de tous les films ?`
                );

                if (!confirmed) {
                    return;
                }

                await performDeleteTag(tagName);
            };
        }
    });


    // -------------------------------------------------------
    // AUTRES FILTRES DE LA SIDEBAR
    // -------------------------------------------------------

    document
        .querySelectorAll('.nav-item[data-filter]')
        .forEach(item => {

            // Les étiquettes sont gérées séparément.
            if (item.classList.contains('tag-item')) {
                return;
            }

            item.onclick = (e) => {

                // Les boutons renommer/supprimer gèrent leur propre clic.
                if (e.target.closest('[data-edit-playlist]') || e.target.closest('[data-del-playlist]')) {
                    return;
                }

                // Quitter le mode de filtrage par étiquettes.
                selectedTags = [];

                // Si on reclique sur le filtre déjà actif, on le désactive
                // et on revient à "Tous les films" au lieu de ne rien faire.
                const isSameFilterAlreadyActive =
                    currentFilter.type === item.dataset.filter &&
                    currentFilter.value === (item.dataset.value || null);

                // Retirer l'état actif de tous les éléments.
                document
                    .querySelectorAll('.nav-item')
                    .forEach(navItem =>
                        navItem.classList.remove('active')
                    );

                if (isSameFilterAlreadyActive) {
                    currentFilter = { type: 'all', value: null };
                    document.querySelector('.nav-item[data-filter="all"]').classList.add('active');
                } else {
                    item.classList.add('active');
                    currentFilter = {
                        type: item.dataset.filter,
                        value: item.dataset.value || null
                    };
                }

                renderSidebar();
                renderGrid();
            };
        });

    // -------------------------------------------------------
    // PLAYLISTS — renommer / supprimer
    // -------------------------------------------------------

    document.querySelectorAll('[data-edit-playlist]').forEach(btn => {
        btn.onclick = async (e) => {
            e.stopPropagation();
            const oldName = btn.dataset.editPlaylist;
            const newName = prompt('Renommer la playlist (ou laisser vide pour supprimer) :', oldName);

            // Annulé (Échap ou bouton Annuler) : on ne fait rien.
            if (newName === null) return;

            const cleanName = newName.trim();

            // Champ vidé volontairement : on propose la suppression.
            if (!cleanName) {
                if (confirm(`Supprimer la playlist "${oldName}" ?`)) {
                    await performDeletePlaylist(oldName);
                }
                return;
            }

            if (cleanName === oldName) return;

            const r = await api('/api/playlist/rename', {
                method: 'POST',
                body: JSON.stringify({ old_name: oldName, new_name: cleanName })
            });
            if (r.error) { alert('Impossible de renommer la playlist : ' + r.error); return; }

            library.playlists = r.playlists;
            // Si cette playlist était le filtre actif, on suit le renommage.
            if (currentFilter.type === 'playlist' && currentFilter.value === oldName) {
                currentFilter.value = cleanName;
            }
            renderSidebar();
            renderGrid();
        };
    });

    document.querySelectorAll('[data-del-playlist]').forEach(btn => {
        btn.onclick = async (e) => {
            e.stopPropagation();
            const name = btn.dataset.delPlaylist;
            if (!confirm(`Supprimer la playlist "${name}" ? Les films eux-mêmes ne seront pas touchés.`)) return;
            await performDeletePlaylist(name);
        };
    });
}

// ---------- Popover détails d'un film (fusionne infos + étiquettes + playlists) ----------
function openDetailsPopover(id, anchor) {
    closePopover();
    activePopoverAnchor = anchor;
    const m = library.movies[id];
    const rect = anchor.getBoundingClientRect();

    const pop = document.createElement('div');
    pop.className = 'popover details-popover';
    pop.id = 'activePopover';
    pop.style.top = (rect.bottom + 6) + 'px';
    pop.style.left = Math.min(Math.max(rect.left - 260, 10), window.innerWidth - 320) + 'px';

    const rows = [
        ['Nom du fichier', m.title],
        ['Chemin complet', m.path],
        ['Taille', formatSize(m.size_bytes)],
        ['Année détectée', m.year || '—'],
    ];

    const allPlaylists = Object.keys(library.playlists || {});

    pop.innerHTML = `
    <div style="font-size:11px;color:var(--text-muted);margin-bottom:8px;">DÉTAILS DU FICHIER</div>
    ${rows.map(([label, value]) => `
      <div class="detail-row">
        <span class="detail-label">${escapeHtml(label)}</span>
        <span class="detail-value">${escapeHtml(String(value))}</span>
      </div>
    `).join('')}

    <div style="font-size:11px;color:var(--text-muted);margin:12px 0 4px;">ÉTIQUETTES</div>
    <div class="tags-edit" id="tagsPills">
      ${(m.tags || []).map(t => `<span class="pill remove" data-tag-rm="${escapeAttr(t)}" style="border-color:var(--amber-dim); color:var(--amber);"># ${escapeHtml(t)}</span>`).join('') || `<span style="font-size:12px;color:var(--text-muted);">Aucune</span>`}
    </div>
    <input type="text" id="newTagInput" placeholder="Ajouter une étiquette...">

    <div style="font-size:11px;color:var(--text-muted);margin:12px 0 4px;">PLAYLISTS</div>
    <div class="tags-edit" id="playlistPills">
      ${allPlaylists.length ? allPlaylists.map(p => `
        <span class="pill" data-playlist="${escapeAttr(p)}"
          style="cursor:pointer;${(library.playlists[p] || []).includes(id) ? 'border-color:var(--amber);color:var(--amber);' : ''}">
          ${(library.playlists[p] || []).includes(id) ? '✓ ' : ''}${escapeHtml(p)}
        </span>`).join('') : `<span style="font-size:12px;color:var(--text-muted);">Aucune playlist pour l'instant</span>`}
    </div>
    <input type="text" id="newPlaylistFromCard" placeholder="Nouvelle playlist...">

    <div class="dup-actions" style="margin-top:12px;">
      <button class="btn" id="detailsPlay">▶ Lire</button>
      <button class="btn" id="detailsReveal">📂 Ouvrir le dossier</button>
    </div>
  `;
    document.body.appendChild(pop);

    pop.querySelector('#detailsPlay').onclick = () => playMovie(id);
    pop.querySelector('#detailsReveal').onclick = async () => {
        const res = await api(`/api/reveal?id=${id}`);
        if (res.error) alert("Impossible d'ouvrir le dossier : " + res.error);
    };

    // ---- Étiquettes : suppression au clic sur une pastille ----
    pop.querySelectorAll('[data-tag-rm]').forEach(pill => {
        pill.onclick = async () => {
            const tags = (m.tags || []).filter(t => t !== pill.dataset.tagRm);
            await api('/api/tags', { method: 'POST', body: JSON.stringify({ id, tags }) });
            m.tags = tags;
            renderSidebar(); renderGrid();
            openDetailsPopover(id, anchor); // rafraîchit sur place sans fermer
        };
    });

    const tagInput = pop.querySelector('#newTagInput');
    tagInput.onkeydown = async (e) => {
        if (e.key === 'Enter' && tagInput.value.trim()) {
            const tags = Array.from(new Set([...(m.tags || []), tagInput.value.trim()]));
            await api('/api/tags', { method: 'POST', body: JSON.stringify({ id, tags }) });
            m.tags = tags;
            renderSidebar(); renderGrid();
            openDetailsPopover(id, anchor); // rafraîchit sur place sans fermer
        }
    };

    // ---- Playlists : toggle au clic sur une pastille ----
    pop.querySelectorAll('[data-playlist]').forEach(pill => {
        pill.onclick = async () => {
            const name = pill.dataset.playlist;
            const r = await api('/api/playlist/toggle', { method: 'POST', body: JSON.stringify({ name, id }) });
            library.playlists = r.playlists;
            renderSidebar();
            openDetailsPopover(id, anchor); // rafraîchit sur place sans fermer
        };
    });

    const playlistInput = pop.querySelector('#newPlaylistFromCard');
    playlistInput.onkeydown = async (e) => {
        if (e.key === 'Enter' && playlistInput.value.trim()) {
            const name = playlistInput.value.trim();
            const rc = await api('/api/playlist/create', { method: 'POST', body: JSON.stringify({ name }) });
            library.playlists = rc.playlists;
            const rt = await api('/api/playlist/toggle', { method: 'POST', body: JSON.stringify({ name, id }) });
            library.playlists = rt.playlists;
            renderSidebar();
            openDetailsPopover(id, anchor); // rafraîchit sur place sans fermer
        }
    };

    setTimeout(() => document.addEventListener('click', outsideClickClose), 0);
}

document.getElementById('scanBtn').onclick = async () => {
    const btn = document.getElementById('scanBtn');
    btn.textContent = '⏳ Scan en cours…';
    library = await api('/api/scan');
    btn.textContent = '↻ Rescanner les dossiers';
    renderSidebar();
    renderGrid();
};

document.getElementById('editTagsBtn').onclick = async () => {
    tagsEditMode = !tagsEditMode;
    document.querySelectorAll(".tag-edit").forEach(e => { e.classList.toggle("tag-edit-unactive", !tagsEditMode) });
    document.getElementById('editTagsBtn').classList.toggle("active", tagsEditMode);
};

document.getElementById('clearTagsBtn').onclick = () => {
    document.getElementById('tags-search').value = "";
    searchTagsTerm = "";

    // Désélectionner toutes les étiquettes
    selectedTags = [];
    // Revenir à l'affichage de tous les films
    currentFilter = {
        type: 'all',
        value: null
    };

    renderSidebar();
    renderGrid();
};

document.getElementById('search').oninput = (e) => {
    searchTerm = e.target.value;
    renderGrid();
};

document.getElementById('tags-search').oninput = (e) => {
    const value = e.target.value;

    // Si on a moins de 3 caractères, on vide le terme de recherche (donc tout s'affiche)
    // Sinon, on applique la recherche
    searchTagsTerm = value.length >= 2 ? value : '';

    renderSidebar();
};

document.getElementById('newPlaylist').onclick = async () => {
    const name = prompt('Nom de la nouvelle playlist :');
    if (name && name.trim()) {
        const r = await api('/api/playlist/create', { method: 'POST', body: JSON.stringify({ name: name.trim() }) });
        library.playlists = r.playlists;
        renderSidebar();
    }
};

document.getElementById('genThumbsBtn').onclick = async () => {
    const btn = document.getElementById('genThumbsBtn');
    btn.textContent = '⏳ Génération en cours (peut prendre du temps)…';
    const r = await api('/api/thumbnails/generate');
    btn.textContent = '🎬 Générer les miniatures';
    if (r.error) { alert(r.error); return; }
    alert(`Miniatures générées : ${r.generated}, déjà existantes : ${r.skipped}, échecs : ${r.failed}`);
    renderGrid();
};

document.getElementById('bulkTagBtn').onclick = async () => {
    const input = document.getElementById('bulkTagInput');
    const tagName = input.value.trim();
    if (!tagName) return;

    const movies = filteredMovies();
    if (movies.length === 0) { alert('Aucun film dans la liste actuelle.'); return; }

    const btn = document.getElementById('bulkTagBtn');
    btn.disabled = true;
    btn.textContent = '⏳…';

    const toUpdate = movies.filter(m =>
        !(m.tags || []).some(t => t.toLowerCase() === tagName.toLowerCase())
    );

    await Promise.all(toUpdate.map(async m => {
        const newTags = [...(m.tags || []), tagName];
        await api('/api/tags', { method: 'POST', body: JSON.stringify({ id: m.id, tags: newTags }) });
        library.movies[m.id].tags = newTags;
    }));

    btn.disabled = false;
    btn.textContent = '+ Ajouter';
    input.value = '';
    closeBulkTagAutocomplete();
    renderSidebar();
    renderGrid();
};

// ---------- Autocomplétion personnalisée pour l'étiquetage en masse ----------
function closeBulkTagAutocomplete() {
    const list = document.getElementById('bulkTagAutocomplete');
    list.classList.remove('open');
    list.innerHTML = '';
}

document.getElementById('bulkTagInput').oninput = (e) => {
    const term = e.target.value.trim().toLowerCase();
    const list = document.getElementById('bulkTagAutocomplete');

    if (term.length < 1) {
        closeBulkTagAutocomplete();
        return;
    }

    const lower = t => t.toLowerCase();
    const startsWithTerm = bulkTagCandidates.filter(t => lower(t).startsWith(term));
    const containsTerm = bulkTagCandidates.filter(t => !lower(t).startsWith(term) && lower(t).includes(term));
    const matches = [...startsWithTerm, ...containsTerm].slice(0, 8);

    if (matches.length === 0) {
        list.innerHTML = `<div class="ac-empty">Créer "${escapeHtml(e.target.value.trim())}"</div>`;
        list.classList.add('open');
        return;
    }

    list.innerHTML = matches.map(t => `<div class="ac-item" data-value="${escapeAttr(t)}">${escapeHtml(t)}</div>`).join('');
    list.classList.add('open');

    list.querySelectorAll('.ac-item').forEach(item => {
        item.onclick = () => {
            document.getElementById('bulkTagInput').value = item.dataset.value;
            closeBulkTagAutocomplete();
        };
    });
};

document.getElementById('bulkTagInput').onkeydown = (e) => {
    if (e.key === 'Enter') {
        closeBulkTagAutocomplete();
        document.getElementById('bulkTagBtn').click();
    } else if (e.key === 'Escape') {
        closeBulkTagAutocomplete();
    }
};

document.addEventListener('click', (e) => {
    if (!e.target.closest('.autocomplete-wrap')) closeBulkTagAutocomplete();
});

document.getElementById('bulkTagInput').onkeydown = (e) => {
    if (e.key === 'Enter') document.getElementById('bulkTagBtn').click();
};

document.getElementById('sortType').onclick = (e) => {
    switch (sortType) {
        case 'name_asc':
            sortType = 'name_desc';
            e.target.textContent = 'Titre ↑';
            break;
        case 'name_desc':
            sortType = 'random';
            e.target.textContent = 'Aléatoire';
            break;
        case 'random':
            sortType = 'name_asc';
            e.target.textContent = 'Titre ↓';
            break;
        default:
            sortType = 'random';
            e.target.textContent = 'Aléatoire';
    }
    renderGrid();
};

document.getElementById('showHideThumbnails').onclick = (e) => {
    e.target.classList.toggle('active');
    showThumbnails = !showThumbnails;
    e.target.textContent = showThumbnails ? '🖼️' : '✖️';
    renderGrid();
};

function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function escapeAttr(str) { return escapeHtml(str); }

// =========================================================
// LISTENER DÉLÉGUÉ UNIQUE POUR LA SIDEBAR
// =========================================================
// Attaché une seule fois (contrairement à attachSidebarEvents(),
// rappelée à chaque rendu) pour éviter l'accumulation de listeners
// qui causait un toggle en double sur les étiquettes.
function setupSidebarDelegatedEvents() {
    const sidebar = document.getElementById('sidebar');

    sidebar.addEventListener('click', (e) => {
        // 1. Repliement des sections (clic sur le titre h2)
        const h2 = e.target.closest('.nav-group > h2');
        if (h2) {
            const group = h2.parentElement;
            group.classList.toggle('collapsed');
            return;
        }

        // 2. Sélection/désélection d'une étiquette
        const tagItem = e.target.closest('.tag-item');
        if (tagItem) {
            // Les boutons modifier/supprimer gèrent leur propre clic
            // (avec stopPropagation), donc s'ils sont la cible réelle
            // du clic, on ne fait rien ici.
            if (e.target.closest('[data-edit-tag]') || e.target.closest('[data-del-tag]')) {
                return;
            }
            if (tagItem.classList.contains('disabled')) return;

            const tName = tagItem.dataset.tag;
            if (selectedTags.includes(tName)) {
                selectedTags = selectedTags.filter(t => t !== tName);
            } else {
                selectedTags.push(tName);
            }
            currentFilter.type = 'tags';
            renderSidebar();
            renderGrid();
        }
    });
}

setupSidebarDelegatedEvents();
loadLibrary();