/**
 * Dorsal Collection Report/Dashboard Script
 * Handles all interactivity for the HTML dashboard.
 */
document.addEventListener('DOMContentLoaded', () => {
    // --- Global variables & Main Initializer ---
    let ALL_FILES_DATA = [];
    const MODAL_ELEMENTS = {
        overlay: null,
        content: null,
        body: null,
        title: null,
        closeBtn: null,
    };

    const htmlLegendPlugin = {
        id: 'htmlLegend',
        afterUpdate(chart, args, options) {
            if (!options.containerID) return;
            const ul = getOrCreateLegendList(chart, options.containerID);
            if (!ul) return;
            const isDark = document.documentElement.classList.contains('dark');
            const textColor = isDark ? '#e5e7eb' : '#1f2937';
            ul.innerHTML = '';
            const items = chart.options.plugins.legend.labels.generateLabels(chart);
            items.forEach(item => {
                const li = document.createElement('li');
                li.style.alignItems = 'center';
                li.style.cursor = 'pointer';
                li.style.display = 'flex';
                li.style.flexDirection = 'row';
                li.style.marginLeft = '5px';
                li.onclick = () => {
                    const { type } = chart.config;
                    if (type === 'pie' || type === 'doughnut') {
                        chart.toggleDataVisibility(item.index);
                    } else {
                        chart.setDatasetVisibility(item.datasetIndex, !chart.isDatasetVisible(item.datasetIndex));
                    }
                    chart.update();
                };
                const boxSpan = document.createElement('span');
                boxSpan.style.background = item.fillStyle;
                boxSpan.style.borderColor = item.strokeStyle;
                boxSpan.style.borderWidth = item.lineWidth + 'px';
                boxSpan.style.display = 'inline-block';
                boxSpan.style.height = '10px';
                boxSpan.style.width = '10px';
                boxSpan.style.marginRight = '8px';
                boxSpan.style.borderRadius = '2px';
                const textContainer = document.createElement('p');
                textContainer.style.color = textColor;
                textContainer.style.margin = 0;
                textContainer.style.padding = 0;
                textContainer.style.textDecoration = item.hidden ? 'line-through' : '';
                textContainer.style.fontSize = '0.9em';
                let labelText = item.text;
                if (labelText && labelText.length > 25) {
                    labelText = labelText.substring(0, 23) + '...';
                }
                const text = document.createTextNode(labelText);
                textContainer.appendChild(text);
                li.appendChild(boxSpan);
                li.appendChild(textContainer);
                ul.appendChild(li);
            });
        }
    };

    const getOrCreateLegendList = (chart, id) => {
        const legendContainer = document.getElementById(id);
        if (!legendContainer) return null;
        let list = legendContainer.querySelector('ul');
        if (!list) {
            list = document.createElement('ul');
            list.style.display = 'flex';
            list.style.flexDirection = 'column';
            list.style.margin = 0;
            list.style.padding = 0;
            list.style.gap = '0.25rem';
            legendContainer.appendChild(list);
        }
        return list;
    };

    Chart.register(htmlLegendPlugin);
    mainInit();

    function mainInit() {
        const dataElement = document.getElementById('full-collection-data');
        if (!dataElement) {
            console.error("CRITICAL: Could not find 'full-collection-data' script tag.");
            return;
        }
        const collectionData = JSON.parse(dataElement.textContent);
        ALL_FILES_DATA = collectionData.results || [];

        initThemeToggle();
        initAccordions();
        initCopyIcons();
        initModal();
        initCollectionOverview(collectionData);
        initDynamicSizeHistogram(collectionData);
        initFileExplorer(ALL_FILES_DATA);
    }

    function initModal() {
        MODAL_ELEMENTS.overlay = document.getElementById('file-modal-overlay');
        MODAL_ELEMENTS.content = document.getElementById('file-modal-content');
        MODAL_ELEMENTS.body = document.getElementById('file-modal-body');
        MODAL_ELEMENTS.title = document.getElementById('file-modal-title');
        MODAL_ELEMENTS.closeBtn = document.getElementById('file-modal-close');

        const expandBtn = document.getElementById('expand-file-view-btn');

        if (!MODAL_ELEMENTS.overlay || !expandBtn) {
            return;
        }

        MODAL_ELEMENTS.closeBtn.addEventListener('click', closeFileModal);
        MODAL_ELEMENTS.overlay.addEventListener('click', (e) => {
            if (e.target === MODAL_ELEMENTS.overlay) {
                closeFileModal();
            }
        });

        expandBtn.addEventListener('click', () => {
            const panel = document.querySelector('.mini-file-view-panel');
            const fileHash = panel?.dataset.currentHash;

            if (fileHash) {
                const fileData = ALL_FILES_DATA.find(f => f.hash === fileHash);
                if (fileData) {
                    openFileModal(fileData);
                }
            }
        });
    }

    function openFileModal(fileObject) {
        if (!MODAL_ELEMENTS.body) return;

        MODAL_ELEMENTS.title.textContent = fileObject.annotations['file/base'].record.name;
        MODAL_ELEMENTS.body.innerHTML = renderFullFileView(fileObject);
        document.body.classList.add('modal-open');
        activateModalInteractivity(MODAL_ELEMENTS.body);
    }

    function closeFileModal() {
        document.body.classList.remove('modal-open');
        if (MODAL_ELEMENTS.body) {
            MODAL_ELEMENTS.body.innerHTML = '';
        }
    }

    function activateModalInteractivity(container) {
        activateTabs(container);
        const genericToggles = container.querySelectorAll('[data-toggle="value"]');
        genericToggles.forEach(el => {
            el.addEventListener('click', () => {
                const currentText = el.textContent;
                const humanValue = el.getAttribute('data-human');
                const rawValue = el.getAttribute('data-raw');
                el.textContent = currentText === humanValue ? rawValue : humanValue;
            });
            el.style.cursor = 'pointer';
            el.setAttribute('title', 'Click to toggle format');
        });
    }

    function initCollectionOverview(collection) {
        const overviewPanel = document.querySelector('#composition-chart');
        if (!overviewPanel) return;

        const overviewData = collection.panels.find(p => p.id === 'collection_overview')?.data;
        if (!overviewData) return;

        initInteractiveCompositionChart(overviewData);
        renderTimelineChart(overviewData);
    }

    function initDynamicSizeHistogram(collection) {
        const histogramCanvas = document.getElementById('dynamic-size-histogram-chart');
        if (!histogramCanvas) return;

        const histogramData = collection.panels.find(p => p.id === 'dynamic_size_histogram')?.data;
        if (!histogramData || histogramData.length === 0) {
            const section = histogramCanvas.closest('.section');
            if (section) section.style.display = 'none';
            return;
        }

        const isDark = document.documentElement.classList.contains('dark');
        const textColor = isDark ? '#e5e7eb' : '#1f2937';

        const options = createChartOptions('File Count by Size', textColor, false);
        options.scales.y.type = 'linear';

        new Chart(histogramCanvas, {
            type: 'bar',
            data: {
                labels: histogramData.map(item => item.bin_label),
                datasets: [{
                    label: 'File Count',
                    data: histogramData.map(item => item.count),
                    backgroundColor: '#4ade80'
                }]
            },
            options: options
        });
    }

    function initInteractiveCompositionChart(data) {
        const compositionCanvas = document.getElementById('composition-chart');
        const viewControlContainer = document.querySelector('.chart-controls');
        const metricControlContainer = document.querySelector('.metric-toggle-controls');

        if (!compositionCanvas || !viewControlContainer || !metricControlContainer) return;

        const isDark = document.documentElement.classList.contains('dark');
        const textColor = isDark ? '#e5e7eb' : '#1f2937';
        const chartColors = ['#38bdf8', '#fbbf24', '#4ade80', '#f87171', '#a78bfa', '#9ca3af'];

        let currentView = 'media_type';
        let currentMetric = 'count';

        const datasets = {
            media_type: {
                by_size: {
                    labels: data.media_type.by_size.map(item => item.media_type),
                    values: data.media_type.by_size.map(item => item.total_size),
                    title: 'Distribution by Media Type (Size)'
                },
                by_count: {
                    labels: data.media_type.by_count.map(item => item.media_type),
                    values: data.media_type.by_count.map(item => item.count),
                    title: 'Distribution by Media Type (Count)'
                }
            },
            extension: {
                by_size: {
                    labels: data.extension.by_size.map(item => item.extension),
                    values: data.extension.by_size.map(item => item.total_size),
                    title: 'Top Extensions (Size)'
                },
                by_count: {
                    labels: data.extension.by_count.map(item => item.extension),
                    values: data.extension.by_count.map(item => item.count),
                    title: 'Top Extensions (Count)'
                }
            },
            largest_files: {
                by_size: {
                    labels: data.largest_files.by_size.map(item => item.name),
                    values: data.largest_files.by_size.map(item => item.size),
                    title: 'Distribution by Largest Files (Size)'
                }
            }
        };

        const compositionChart = new Chart(compositionCanvas, {
            type: 'doughnut',
            data: {
                labels: [],
                datasets: [{ data: [], backgroundColor: chartColors }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    htmlLegend: { containerID: 'composition-chart-legend' },
                    title: { display: true, text: '', color: textColor, font: { size: 14 } },
                    tooltip: {
                        callbacks: {
                            label: function (context) {
                                const label = context.label || '';
                                const value = context.parsed || 0;
                                if (currentMetric === 'size') {
                                    return `${label}: ${humanFileSize(value)}`;
                                }
                                return `${label}: ${value.toLocaleString()}`;
                            }
                        }
                    }
                }
            }
        });

        function updateChart() {
            const isLargestFiles = currentView === 'largest_files';
            metricControlContainer.querySelectorAll('button').forEach(btn => btn.disabled = isLargestFiles);
            if (isLargestFiles) currentMetric = 'size';
            metricControlContainer.querySelectorAll('button').forEach(btn => btn.classList.toggle('active', btn.dataset.metric === currentMetric));

            const data = datasets[currentView]?.[`by_${currentMetric}`];
            if (!data) return;

            compositionChart.data.labels = data.labels;
            compositionChart.data.datasets[0].data = data.values;
            compositionChart.options.plugins.title.text = data.title;
            compositionChart.update();
        }

        viewControlContainer.addEventListener('click', (e) => {
            if (e.target.tagName !== 'BUTTON' || e.target.dataset.chart === currentView) return;
            viewControlContainer.querySelector('.active').classList.remove('active');
            e.target.classList.add('active');
            currentView = e.target.dataset.chart;
            updateChart();
        });

        metricControlContainer.addEventListener('click', (e) => {
            if (e.target.tagName !== 'BUTTON' || e.target.disabled || e.target.dataset.metric === currentMetric) return;
            currentMetric = e.target.dataset.metric;
            updateChart();
        });

        updateChart();
    }

    function renderTimelineChart(data) {
        const timelineCanvas = document.getElementById('overview-timeline-chart');
        if (!timelineCanvas || !data.timeline_data) return;

        const isDark = document.documentElement.classList.contains('dark');
        const textColor = isDark ? '#e5e7eb' : '#1f2937';

        const options = createChartOptions('Files by Date Modified', textColor, false);
        options.scales = {
            x: {
                type: 'time',
                time: { unit: 'month' },
                grid: { color: isDark ? '#374151' : '#e5e7eb' },
                ticks: { color: textColor, maxTicksLimit: 8 }
            },
            y: { display: false }
        };
        options.plugins.tooltip = {
            callbacks: {
                label: (context) => {
                    const fileData = data.timeline_data[context.dataIndex];
                    return fileData ? `${fileData.y} (${new Date(fileData.x).toLocaleString()})` : '';
                }
            }
        };

        new Chart(timelineCanvas, {
            type: 'scatter',
            data: {
                datasets: [{
                    label: 'File Modified Date',
                    data: data.timeline_data.map(d => ({ x: d.x, y: 0 })),
                    backgroundColor: '#38bdf8'
                }]
            },
            options: options
        });
    }

    function initFileExplorer(files) {
        const tableBody = document.querySelector('#file-explorer-table tbody');
        if (!tableBody) return;

        const filterInput = document.getElementById('file-explorer-filter');
        const paginationControls = document.getElementById('file-explorer-pagination');
        const tableHeaders = document.querySelectorAll('#file-explorer-table th[data-sort-key]');

        let currentPage = 1;
        const rowsPerPage = 15;
        let currentSort = { key: 'name', order: 'asc' };
        let filteredFiles = [...files];

        tableBody.addEventListener('click', (e) => {
            const fileLink = e.target.closest('.file-link');
            if (fileLink) {
                const fileHash = fileLink.closest('tr').dataset.hash;
                const fileData = files.find(f => f.hash === fileHash);
                if (fileData) {
                    updateMiniFileView(fileData);
                    window.scrollTo({ top: 0, behavior: 'smooth' });
                }
            }
        });

        function renderTable() {
            filteredFiles.sort((a, b) => {
                const aVal = getFileValue(a, currentSort.key);
                const bVal = getFileValue(b, currentSort.key);
                if (aVal < bVal) return currentSort.order === 'asc' ? -1 : 1;
                if (aVal > bVal) return currentSort.order === 'asc' ? 1 : -1;
                return 0;
            });

            const startIndex = (currentPage - 1) * rowsPerPage;
            const pageFiles = filteredFiles.slice(startIndex, startIndex + rowsPerPage);

            tableBody.innerHTML = pageFiles.map(file => {
            const baseRecord = file.annotations['file/base'].record;
            const localAttrs = file.local_attributes;
            return `<tr data-hash="${file.hash}">
                <td class="truncate-cell" data-tooltip="${escapeHtml(baseRecord.name)}" data-tooltip-placement="top">
                    <span class="file-link">${escapeHtml(baseRecord.name)}</span>
                </td>
                <td>${humanFileSize(baseRecord.size)}</td>
                <td class="truncate-cell" data-tooltip="${escapeHtml(baseRecord.media_type)}" data-tooltip-placement="top">
                    <span>${escapeHtml(baseRecord.media_type)}</span>
                </td>
                <td data-tooltip="${new Date(localAttrs.date_modified).toLocaleString()}">${formatRelativeTime(new Date(localAttrs.date_modified))}</td>
            </tr>`;
        }).join('');

            renderPagination();
            updateSortIndicators();
        }

        function renderPagination() {
            const totalPages = Math.ceil(filteredFiles.length / rowsPerPage);
            paginationControls.innerHTML = `<button id="prev-page" ${currentPage === 1 ? 'disabled' : ''}>Previous</button><span>Page ${totalPages > 0 ? currentPage : 0} of ${totalPages} (${filteredFiles.length} files)</span><button id="next-page" ${currentPage >= totalPages ? 'disabled' : ''}>Next</button>`;
            document.getElementById('prev-page')?.addEventListener('click', () => { if (currentPage > 1) { currentPage--; renderTable(); } });
            document.getElementById('next-page')?.addEventListener('click', () => { if (currentPage < totalPages) { currentPage++; renderTable(); } });
        }

        filterInput.addEventListener('input', (e) => {
            const searchTerm = e.target.value.toLowerCase();
            filteredFiles = files.filter(file => getFileValue(file, 'name').toLowerCase().includes(searchTerm));
            currentPage = 1;
            renderTable();
        });

        tableHeaders.forEach(header => {
            header.addEventListener('click', () => {
                const sortKey = header.dataset.sortKey;
                currentSort.order = (currentSort.key === sortKey && currentSort.order === 'asc') ? 'desc' : 'asc';
                currentSort.key = sortKey;
                currentPage = 1;
                renderTable();
            });
        });

        function updateSortIndicators() {
            tableHeaders.forEach(header => {
                header.classList.remove('sorted');
                const indicator = header.querySelector('.sort-indicator') || document.createElement('span');
                indicator.className = 'sort-indicator';
                if (header.dataset.sortKey === currentSort.key) {
                    header.classList.add('sorted');
                    indicator.textContent = currentSort.order === 'asc' ? '▲' : '▼';
                } else {
                    indicator.textContent = '';
                }
                if (!header.querySelector('.sort-indicator')) header.appendChild(indicator);
            });
        }

        renderTable();
    }

    function updateMiniFileView(file) {
        const panel = document.querySelector('.mini-file-view-panel');
        if (!panel) return;

        panel.dataset.currentHash = file.hash;
        const baseRecord = file.annotations['file/base'].record;
        const localAttrs = file.local_attributes;
        const modifiedDate = new Date(localAttrs.date_modified);
        const createdDate = new Date(localAttrs.date_created);

        panel.querySelector('.panel-content').innerHTML = `
            <div class="mini-section">
                <div class="grid-single-col" style="gap: 0.75rem;">
                    <div class="grid-item"><span class="label">Name</span><div class="value" data-tooltip="${escapeHtml(baseRecord.name)}" data-tooltip-placement="top">${escapeHtml(baseRecord.name)}</div></div>
                    <div class="grid-item"><span class="label">Extension</span><span class="value ${!baseRecord.extension ? 'subdued' : ''}">${baseRecord.extension ? escapeHtml(baseRecord.extension) : 'None'}</span></div>
                    <div class="grid-item"><span class="label">Size</span><span class="value">${humanFileSize(baseRecord.size)}</span></div>
                    <div class="grid-item"><span class="label">Media Type</span><span class="value mono">${escapeHtml(baseRecord.media_type)}</span></div>
                    <div class="grid-item"><span class="label">Modified</span><span class="value">${modifiedDate.getFullYear()}-${String(modifiedDate.getMonth() + 1).padStart(2, '0')}-${String(modifiedDate.getDate()).padStart(2, '0')} ${String(modifiedDate.getHours()).padStart(2, '0')}:${String(modifiedDate.getMinutes()).padStart(2, '0')}</span></div>
                    <div class="grid-item"><span class="label">Created</span><span class="value">${createdDate.getFullYear()}-${String(createdDate.getMonth() + 1).padStart(2, '0')}-${String(createdDate.getDate()).padStart(2, '0')} ${String(createdDate.getHours()).padStart(2, '0')}:${String(createdDate.getMinutes()).padStart(2, '0')}</span></div>
                </div>
            </div>`;
    }

    function renderFullFileView(file) {
        const baseRecord = file.annotations['file/base'].record;
        const localAttrs = file.local_attributes;
        const fileSize = { human: humanFileSize(baseRecord.size), raw: `${baseRecord.size} bytes` };
        const modifiedDate = { human: new Date(localAttrs.date_modified).toLocaleString(), raw: localAttrs.date_modified };
        const createdDate = { human: new Date(localAttrs.date_created).toLocaleString(), raw: localAttrs.date_created };

        const renderHash = (label, tooltip, url, value) => value ? `
            <div class="grid-item">
                <span class="label" data-tooltip="${tooltip}" data-tooltip-placement="top">
                    <a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>
                </span>
                <div class="hash-container"><span class="hash-value">${escapeHtml(value)}</span>
                    <svg class="copy-icon" data-copy-text="${escapeHtml(value)}" title="Copy to clipboard" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 0 1-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 0 1 1.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 0 0-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 0 1-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 0 0-3.375-3.375h-1.5a1.125 1.125 0 0 1-1.125-1.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H9.75" /></svg>
                </div>
            </div>` : '';

        const renderAnnotationFields = (data) => {
            let html = '';
            for (const [key, value] of Object.entries(data)) {
                if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
                    html += `<div class="annotation-group"><h3 class="sub-header">${escapeHtml(key)}</h3><div class="nested-item">${renderAnnotationFields(value)}</div></div>`;
                } else if (Array.isArray(value)) {
                    html += `<div class="annotation-group"><h3 class="sub-header">${escapeHtml(key)}</h3><div class="nested-item">
                        ${value.map(item => {
                            if (typeof item === 'object' && item !== null) {
                                return renderAnnotationFields(item);
                            } else {
                                return `<div class="grid-item"><span class="value">${escapeHtml(item)}</span></div>`;
                            }
                        }).join('<hr style="border-color: var(--border-color); margin: 0.5rem 0;">')}
                    </div></div>`;
                } else {
                    html += `<div class="grid-item"><span class="label">${escapeHtml(key)}</span><span class="value">${escapeHtml(value)}</span></div>`;
                }
            }
            return `<div class="grid-single-col">${html}</div>`;
        };

        const annotationsHtml = Object.entries(file.annotations || {})
            .filter(([key, value]) => key !== 'file/base' && value)
            .map(([key, annotation]) => `
                <div class="accordion-item">
                    <div class="accordion-header"><span>${escapeHtml(key)}</span><span class="accordion-icon">▼</span></div>
                    <div class="accordion-content">${renderAnnotationFields(annotation.record)}</div>
                </div>`
            ).join('');

        const tagsHtml = (file.tags || []).map(tag => `<span class="tag">${escapeHtml(tag.name)}: ${escapeHtml(tag.value)}</span>`).join('');

        return `
            <main>
                <div class="tabs">
                    <span class="tab-link active" data-target="#tab-info">File Information</span>
                    <span class="tab-link" data-target="#tab-json">Raw JSON</span>
                </div>
                <div id="tab-info" class="tab-content active">
                    <div class="section"><div class="grid">
                        <div class="grid-item"><div class="label">Name</div><div class="value">${escapeHtml(baseRecord.name)}</div></div>
                        <div class="grid-item"><div class="label">Extension</div><div class="value ${!baseRecord.extension ? 'subdued' : ''}">${baseRecord.extension ? escapeHtml(baseRecord.extension) : 'None'}</div></div>
                        <div class="grid-item"><div class="label">Size</div><div class="value" data-toggle="value" data-human="${fileSize.human}" data-raw="${fileSize.raw}">${fileSize.human}</div></div>
                        <div class="grid-item"><div class="label">Media Type</div><div class="value mono">${escapeHtml(baseRecord.media_type)}</div></div>
                        <div class="grid-item"><div class="label">Date Modified (Local)</div><div class="value" data-toggle="value" data-human="${modifiedDate.human}" data-raw="${modifiedDate.raw}">${modifiedDate.human}</div></div>
                        <div class="grid-item"><div class="label">Date Created (Local)</div><div class="value" data-toggle="value" data-human="${createdDate.human}" data-raw="${createdDate.raw}">${createdDate.human}</div></div>
                    </div></div>
                    <div class="section"><h2 class="section-title">Content Hashes</h2><div class="grid-single-col">
                        ${renderHash('SHA-256', 'Cryptographic hash for verifying file integrity.', 'https://en.wikipedia.org/wiki/SHA-2', file.hash)}
                        ${renderHash('BLAKE3', 'A modern, high-speed cryptographic hash.', 'https://en.wikipedia.org/wiki/BLAKE_(hash_function)', file.validation_hash)}
                        ${renderHash('TLSH', 'A locality-sensitive hash used to detect similar (but not identical) files.', 'https://en.wikipedia.org/wiki/Locality-sensitive_hashing', file.similarity_hash)}
                        ${renderHash('Quick Hash', 'A fast, sample-based hash for quick identification of large files.', 'http://docs.dorsalhub.com/quick', file.quick_hash)}
                    </div></div>
                    ${annotationsHtml ? `<div class="section"><h2 class="section-title">Annotations</h2><div class="accordion">${annotationsHtml}</div></div>` : ''}
                    ${tagsHtml ? `<div class="section"><h2 class="section-title">Tags</h2><div>${tagsHtml}</div></div>` : ''}
                </div>
                <div id="tab-json" class="tab-content"><pre><code>${escapeHtml(JSON.stringify(file, null, 2))}</code></pre></div>
            </main>`;
    }

    function initThemeToggle() {
        const themeToggle = document.getElementById('theme-toggle');
        const root = document.documentElement;
        if (localStorage.getItem('theme') === 'dark' || (!('theme' in localStorage) && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
            root.classList.add('dark');
        } else {
            root.classList.remove('dark');
        }
        if (themeToggle) {
            themeToggle.addEventListener('click', function () {
                const isDark = root.classList.toggle('dark');
                localStorage.setItem('theme', isDark ? 'dark' : 'light');
                if (window.Chart && Chart.helpers) {
                    Chart.helpers.each(Chart.instances, (instance) => {
                        const textColor = isDark ? '#e5e7eb' : '#1f2937';
                        const gridColor = isDark ? '#374151' : '#e5e7eb';
                        if (instance.options.plugins.title) instance.options.plugins.title.color = textColor;
                        if (instance.options.plugins.legend) instance.options.plugins.legend.labels.color = textColor;
                        if (instance.options.scales.x) { instance.options.scales.x.grid.color = gridColor; instance.options.scales.x.ticks.color = textColor; }
                        if (instance.options.scales.y) { instance.options.scales.y.grid.color = gridColor; instance.options.scales.y.ticks.color = textColor; }
                        instance.update();
                    });
                }
            });
        }
    }

    function activateTabs(container) {
        const tabs = container.querySelectorAll('.tab-link');
        const tabContents = container.querySelectorAll('.tab-content');

        tabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const target = container.querySelector(tab.dataset.target);
                tabs.forEach(t => t.classList.remove('active'));
                tabContents.forEach(c => c.classList.remove('active'));
                tab.classList.add('active');
                if (target) target.classList.add('active');
            });
        });
    }

    function initAccordions() {
        document.body.addEventListener('click', function (event) {
            const accordionHeader = event.target.closest('.accordion-header');
            if (accordionHeader) {
                const content = accordionHeader.nextElementSibling;
                const icon = accordionHeader.querySelector('.accordion-icon');
                const isVisible = content.style.display === 'block';
                content.style.display = isVisible ? 'none' : 'block';
                if (icon) icon.style.transform = isVisible ? 'rotate(0deg)' : 'rotate(180deg)';
            }
        });
    }

    function initCopyIcons() {
        document.body.addEventListener('click', function (event) {
            const copyIcon = event.target.closest('.copy-icon');
            if (copyIcon && copyIcon.dataset.copyText) {
                navigator.clipboard.writeText(copyIcon.dataset.copyText)
                    .then(() => showToast('Copied!'))
                    .catch(err => showToast('Failed to copy!'));
            }
        });
    }

    function createChartOptions(title, textColor, showLegend = true, indexAxis = 'x') {
        const isDark = document.documentElement.classList.contains('dark');
        return {
            indexAxis: indexAxis,
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: showLegend, position: 'bottom', labels: { color: textColor, padding: 20 } },
                title: { display: true, text: title, color: textColor, font: { size: 14 } }
            },
            scales: {
                x: { grid: { color: isDark ? '#374151' : '#e5e7eb' }, ticks: { color: textColor } },
                y: { grid: { color: isDark ? '#374151' : '#e5e7eb' }, ticks: { color: textColor } }
            }
        };
    }

    function getFileValue(file, key) {
        switch (key) {
            case 'name': return file.annotations['file/base'].record.name;
            case 'size': return file.annotations['file/base'].record.size;
            case 'media_type': return file.annotations['file/base'].record.media_type;
            case 'date_modified': return new Date(file.local_attributes.date_modified);
            default: return '';
        }
    }

    function humanFileSize(bytes, si = false, dp = 1) {
        const thresh = si ? 1000 : 1024;
        if (Math.abs(bytes) < thresh) return bytes + ' B';
        const units = si ? ['kB', 'MB', 'GB', 'TB'] : ['KiB', 'MiB', 'GiB', 'TiB'];
        let u = -1;
        const r = 10 ** dp;
        do { bytes /= thresh; ++u; } while (Math.round(Math.abs(bytes) * r) / r >= thresh && u < units.length - 1);
        return bytes.toFixed(dp) + ' ' + units[u];
    }

    function formatRelativeTime(date) {
        const seconds = Math.round((new Date() - date) / 1000);
        if (seconds < 5) return "just now";
        if (seconds < 60) return `${seconds} sec ago`;
        const minutes = Math.round(seconds / 60);
        if (minutes < 60) return `${minutes} min ago`;
        const hours = Math.round(minutes / 60);
        if (hours < 24) return `${hours} hr ago`;
        const days = Math.round(hours / 24);
        return `${days} day${days > 1 ? 's' : ''} ago`;
    }

    function escapeHtml(unsafe) {
        if (typeof unsafe !== 'string') return unsafe;
        return unsafe.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }

    let toastTimeout;
    function showToast(message) {
        const toast = document.getElementById('toast');
        if (!toast) return;
        toast.textContent = message;
        toast.classList.add('show');
        clearTimeout(toastTimeout);
        toastTimeout = setTimeout(() => { toast.classList.remove('show'); }, 2000);
    }
});