const aiAgentConfig = document.getElementById('ai_agent_js_config');
if (!aiAgentConfig) {
    throw new Error('AI-Agent JavaScript configuration is missing.');
}

document.addEventListener('DOMContentLoaded', function () {
    const internalProvider = document.getElementById('internal_ai_provider');
    const internalProviderNote = document.getElementById('internal_ai_provider_note');
    const genericProvider = document.getElementById('ai_provider');
    const genericProviderNote = document.getElementById('ai_provider_note');

    function applyProvider(select, note, contextName) {
        if (!select || !note) return;
        if (select.value === 'copilot') {
            note.textContent = 'Microsoft Copilot selected. The connection is pending administrator activation. OpenAI will not be used as a silent fallback.';
        } else {
            note.textContent = 'OpenAI is currently available for ' + contextName + ' interpretation and analysis when required.';
        }
    }

    if (internalProvider) {
        const saved = sessionStorage.getItem('aiAgentInternalAiProvider');
        if (saved && ['openai', 'copilot'].includes(saved)) internalProvider.value = saved;
        internalProvider.addEventListener('change', function () {
            sessionStorage.setItem('aiAgentInternalAiProvider', internalProvider.value);
            applyProvider(internalProvider, internalProviderNote, 'Internal / Customer Knowledge');
        });
        applyProvider(internalProvider, internalProviderNote, 'Internal / Customer Knowledge');
    }

    if (genericProvider) {
        const saved = sessionStorage.getItem('aiAgentGenericAiProvider');
        if (saved && ['openai', 'copilot'].includes(saved)) genericProvider.value = saved;
        genericProvider.addEventListener('change', function () {
            sessionStorage.setItem('aiAgentGenericAiProvider', genericProvider.value);
            applyProvider(genericProvider, genericProviderNote, 'Generic Knowledge');
        });
        applyProvider(genericProvider, genericProviderNote, 'Generic Knowledge');
    }
});

const knowledgeMode = document.getElementById('knowledge_mode');
const internalSection = document.getElementById('internal_section');
const genericSection = document.getElementById('generic_section');
const apiSection = document.getElementById('api_section');
const modeNote = document.getElementById('mode_note');

function prepareNewQuestion(textareaId) {
    const questionBox = document.getElementById(textareaId);

    if (questionBox) {
        questionBox.value = '';
        questionBox.focus();
    }

    document.querySelectorAll('.previous-result').forEach(function (element) {
        element.style.display = 'none';
    });

    // Internal Knowledge: reset the complete previous request display.
    if (textareaId === 'question') {
        stopInternalTimer();
        internalStartedAt = null;
        internalLastActivityAt = null;

        if (internalLiveProgressFill) internalLiveProgressFill.style.width = '0%';
        if (internalLiveProgressPercent) internalLiveProgressPercent.textContent = '0%';
        if (internalLiveProgressStage) internalLiveProgressStage.textContent = 'Ready';
        if (internalLiveProgressElapsed) internalLiveProgressElapsed.textContent = '00:00';
        if (internalLiveActivityRows) internalLiveActivityRows.innerHTML = '';

        if (internalLiveProgressBox) internalLiveProgressBox.style.display = 'none';
        if (internalLiveResultContainer) {
            internalLiveResultContainer.innerHTML = '';
            internalLiveResultContainer.style.display = 'none';
        }

        const internalSubmitButton = document.querySelector(
            '#internal_form button[type="submit"]'
        );
        if (internalSubmitButton) {
            internalSubmitButton.disabled = false;
            internalSubmitButton.textContent = 'Ask Internal Knowledge';
        }
    }

    // Generic Knowledge: reset the complete previous request display.
    if (textareaId === 'generic_question') {
        stopGenericTimer();
        genericStartedAt = null;
        genericLastActivityAt = null;

        if (liveProgressFill) liveProgressFill.style.width = '0%';
        if (liveProgressPercent) liveProgressPercent.textContent = '0%';
        if (liveProgressStage) liveProgressStage.textContent = 'Ready';
        if (liveProgressElapsed) liveProgressElapsed.textContent = '00:00';
        if (liveActivityRows) liveActivityRows.innerHTML = '';

        if (liveProgressBox) {
            liveProgressBox.style.display = 'none';
        }

        if (liveResultContainer) {
            liveResultContainer.innerHTML = '';
            liveResultContainer.style.display = 'none';
        }

        const genericSubmitButton = document.querySelector(
            '#generic_form button[type="submit"]'
        );
        if (genericSubmitButton) {
            genericSubmitButton.disabled = false;
            genericSubmitButton.textContent = 'Ask AI-Agent';
        }
    }
}

function updateKnowledgeMode() {
    // Public Ask AI-Agent page uses Generic Knowledge only.
    // Knowledge-source routing remains a backend/admin concern.
}

// No public knowledge-source selector is required on this page.


const allDocumentsCheckbox = document.getElementById('all_documents');
const sourceCheckboxes = Array.from(document.querySelectorAll('.source-checkbox'));

function updateDocumentScope() {
    if (!allDocumentsCheckbox) return;
    const useAllDocuments = allDocumentsCheckbox.checked;
    sourceCheckboxes.forEach(function (checkbox) {
        checkbox.disabled = useAllDocuments;
        if (useAllDocuments) checkbox.checked = false;
    });
}

if (allDocumentsCheckbox) {
    allDocumentsCheckbox.addEventListener('change', updateDocumentScope);
    updateDocumentScope();
}

const internalForm = document.getElementById('internal_form');
const internalLiveProgressBox = document.getElementById('internal_live_progress_box');
const internalLiveProgressFill = document.getElementById('internal_live_progress_fill');
const internalLiveProgressStage = document.getElementById('internal_live_progress_stage');
const internalLiveProgressPercent = document.getElementById('internal_live_progress_percent');
const internalLiveProgressElapsed = document.getElementById('internal_live_progress_elapsed');
const internalLiveActivityRows = document.getElementById('internal_live_activity_rows');
const internalLiveResultContainer = document.getElementById('internal_live_result_container');

let internalTimerId = null;
let internalStartedAt = null;
let internalLastActivityAt = null;

function startInternalTimer() {
    if (internalTimerId) clearInterval(internalTimerId);
    internalStartedAt = Date.now();
    internalLastActivityAt = internalStartedAt;
    if (internalLiveProgressElapsed) internalLiveProgressElapsed.textContent = '00:00';
    internalTimerId = setInterval(function () {
        if (internalLiveProgressElapsed && internalStartedAt) {
            internalLiveProgressElapsed.textContent =
                formatElapsedSeconds((Date.now() - internalStartedAt) / 1000);
        }
    }, 1000);
}

function stopInternalTimer() {
    if (internalTimerId) {
        clearInterval(internalTimerId);
        internalTimerId = null;
    }
    if (internalLiveProgressElapsed && internalStartedAt) {
        internalLiveProgressElapsed.textContent =
            formatElapsedSeconds((Date.now() - internalStartedAt) / 1000);
    }
}

function addInternalActivity(percent, stage) {
    if (!internalLiveActivityRows) return;

    const now = Date.now();
    let durationText = 'started';
    if (internalLastActivityAt && internalLiveActivityRows.children.length > 0) {
        durationText = formatElapsedSeconds((now - internalLastActivityAt) / 1000);
    }
    internalLastActivityAt = now;

    const row = document.createElement('div');
    row.className = 'activity-row';

    const percentCell = document.createElement('div');
    percentCell.className = 'activity-percent';
    percentCell.textContent = String(percent) + '%';

    const stageCell = document.createElement('div');
    stageCell.className = 'activity-stage';
    stageCell.textContent = stage || 'Processing...';

    const durationCell = document.createElement('div');
    durationCell.className = 'activity-duration';
    durationCell.textContent = durationText;

    row.appendChild(percentCell);
    row.appendChild(stageCell);
    row.appendChild(durationCell);
    internalLiveActivityRows.appendChild(row);
}

function firstSentences(text, count) {
    const clean = String(text || '').replace(/\s+/g, ' ').trim();
    if (!clean) return '';
    const parts = clean.match(/[^.!?]+[.!?]+|[^.!?]+$/g) || [clean];
    return parts.slice(0, count || 3).join(' ').trim();
}

function buildProfessionalInternalReport(result) {
    const rawAnswer = String(result.answer || '');
    const customerText = rawAnswer.replace(/^CUSTOMER \/ INTERNAL INFORMATION\s*/i, '').trim();
    const executiveSummary = firstSentences(customerText, 3);
    const assessed = ((result.evidence_assessment || {}).aspects || []);

    const investigationRows = assessed.length ? assessed.map(function(a) {
        const status = String(a.status || 'NOT_FOUND').toUpperCase();
        const css = status === 'FOUND' ? 'status-found' : (status === 'PARTIAL' ? 'status-partial' : 'status-not-found');
        return '<tr><td>' + escapeHtml(a.aspect || '') + '</td><td class="' + css + '">' +
            escapeHtml(status) + '</td><td>' + escapeHtml(a.summary || '') + '</td></tr>';
    }).join('') : '<tr><td colspan="3">No aspect assessment available.</td></tr>';

    const gapRows = assessed.filter(function(a) {
        return ['PARTIAL', 'NOT_FOUND'].includes(String(a.status || '').toUpperCase());
    }).map(function(a) {
        const status = String(a.status || '').toUpperCase();
        const css = status === 'PARTIAL' ? 'status-partial' : 'status-not-found';
        return '<tr><td>' + escapeHtml(a.aspect || '') + '</td><td class="' + css + '">' +
            escapeHtml(status) + '</td><td>' + escapeHtml(a.missing_information || 'Requires confirmation.') + '</td></tr>';
    }).join('');

    return '<div class="professional-report">' +
        '<div class="report-header"><h3>AI-Agent Internal Knowledge Analysis</h3>' +
        '<div class="report-subtitle">' + escapeHtml(result.organization_name || '') + ' | ' +
        escapeHtml(result.document_name || '') + '</div></div>' +
        '<div class="report-section"><h4>1. Executive Summary</h4><div class="report-text">' +
        escapeHtml(executiveSummary || customerText) + '</div></div>' +
        '<div class="report-section"><h4>2. Investigation Summary</h4>' +
        '<table class="report-table"><thead><tr><th>Area</th><th>Status</th><th>Assessment</th></tr></thead><tbody>' +
        investigationRows + '</tbody></table></div>' +
        '<div class="report-section"><h4>3. Customer / Internal Information</h4><div class="report-text">' +
        escapeHtml(customerText) + '</div></div>' +
        '<div class="report-section"><h4>4. Gaps / Information Requiring Confirmation</h4>' +
        (gapRows ? '<table class="report-table"><thead><tr><th>Area</th><th>Status</th><th>Information Required</th></tr></thead><tbody>' + gapRows + '</tbody></table>' : '<div class="report-text">No unresolved gaps were identified.</div>') +
        '</div>' +
        '<div class="report-section"><h4>5. Recommended Approach</h4>' +
        '<div class="report-note"><strong>AI-Agent recommendation:</strong> This is professional guidance, not customer-provided information.</div>' +
        '<div class="report-text">' + escapeHtml(result.recommended_approach || 'No recommendation was generated.') + '</div></div>' +
        '</div>';
}

function exportInternalAnalysis(analysisId) {
    const templateUrl = aiAgentConfig.dataset.exportInternalDocxUrl;
    window.location.href = templateUrl.replace('999999', String(analysisId));
}

function exportInternalAnalysisPdf(analysisId) {
    const templateUrl = aiAgentConfig.dataset.exportInternalPdfUrl;
    window.location.href = templateUrl.replace('999999', String(analysisId));
}

function renderInternalResult(result) {
    const sourceRows = Array.isArray(result.sources) ? result.sources.map(function (source) {
        const title = source.kind === 'knowledge_item'
            ? (source.title || 'Reusable Knowledge')
            : (source.source_name || 'Information Source');
        const detail = source.kind === 'knowledge_item'
            ? (source.source_reference || 'Internal validated knowledge')
            : ('Content record: ' + (Number(source.chunk_index || 0) + 1) +
               (source.source_reference ? ' | Reference: ' + source.source_reference : ''));
        const score = source.score == null ? '' : ' | Score: ' + source.score;
        return '<div class="source"><div class="source-title">' +
            escapeHtml(title) + '</div><div class="source-meta">' +
            escapeHtml(detail + score) + '</div></div>';
    }).join('') : '';

    internalLiveResultContainer.style.display = 'block';
    internalLiveResultContainer.innerHTML =
        '<div class="card previous-result">' +
        '<h3>AI-Agent Internal Knowledge Answer</h3>' +
        '<div class="api-status ' + (result.openai_interpretation_used ? 'api-status-openai' : 'api-status-local') + '">' +
        (result.openai_knowledge_used
            ? 'OpenAI API Used: YES — question interpretation and external assistance for remaining knowledge gaps.'
            : (result.openai_interpretation_used
                ? 'OpenAI API Used: YES — question interpretation. Customer facts came from the Internal Knowledge database; identified gaps were checked against Generic Knowledge first.'
                : 'OpenAI API Used: NO — answer information came from the local Internal Knowledge database.')) +
        '</div>' +
        '<div class="trace-box"><h4 class="trace-title">AI-Agent Source Trace</h4>' +
        '<div class="trace-row"><div class="trace-label">Organization</div><div class="trace-neutral">' +
        escapeHtml(result.organization_name || '') + '</div></div>' +
        '<div class="trace-row"><div class="trace-label">Document Scope</div><div class="trace-neutral">' +
        escapeHtml(result.document_name || '') + '</div></div>' +
        '<div class="trace-row"><div class="trace-label">Question Interpretation</div><div class="trace-neutral">' +
        escapeHtml(result.interpretation_source || 'LOCAL') + '</div></div>' +
        (result.interpretation ? (
            '<div class="trace-row"><div class="trace-label">Canonical Concept</div><div class="trace-neutral">' +
            escapeHtml(result.interpretation.canonical_concept || '') + '</div></div>' +
            '<div class="trace-row"><div class="trace-label">Requested Aspect</div><div class="trace-neutral">' +
            escapeHtml(result.interpretation.knowledge_aspect || '') + '</div></div>' +
            '<div class="trace-row"><div class="trace-label">Intent</div><div class="trace-neutral">' +
            escapeHtml(result.interpretation.intent || '') + '</div></div>' +
            '<div class="trace-row"><div class="trace-label">Requested Aspects</div><div class="trace-neutral">' +
            escapeHtml((result.requested_aspects || []).join(', ')) + '</div></div>'
        ) : '') +
        '<div class="trace-row"><div class="trace-label">Customer Information Source</div><div class="trace-local">INTERNAL DATABASE</div></div>' +
        '<div class="trace-row"><div class="trace-label">Generic Knowledge Used</div><div class="' +
        (result.generic_knowledge_used ? 'trace-openai' : 'trace-local') + '">' +
        yesNo(result.generic_knowledge_used) + '</div></div>' +
        '<div class="trace-row"><div class="trace-label">OpenAI Interpretation Used</div><div class="' +
        (result.openai_interpretation_used ? 'trace-openai' : 'trace-local') + '">' +
        yesNo(result.openai_interpretation_used) + '</div></div>' +
        '<div class="trace-row"><div class="trace-label">OpenAI External Knowledge Used</div><div class="' +
        (result.openai_knowledge_used ? 'trace-openai' : 'trace-local') + '">' +
        yesNo(result.openai_knowledge_used) + '</div></div>' +
        '<div class="trace-row"><div class="trace-label">Missing Information Identified</div><div class="' +
        (result.missing_information_identified ? 'trace-openai' : 'trace-local') + '">' +
        yesNo(result.missing_information_identified) + '</div></div>' +
        '<div class="trace-row"><div class="trace-label">Answer Information Source</div><div class="trace-neutral">' +
        escapeHtml(result.answer_information_source || 'INTERNAL_DATABASE') + '</div></div>' +
        ((result.aspect_evidence || []).length ? (
        '<div class="trace-row"><div class="trace-label">Aspect Investigation</div><div class="trace-neutral">' +
        (result.aspect_evidence || []).map(function(a) {
            const assessed = ((result.evidence_assessment || {}).aspects || []).find(function(x) {
                return (x.aspect || '').toLowerCase() === (a.aspect || '').toLowerCase();
            });
            const status = assessed ? assessed.status : (a.found ? 'FOUND' : 'NOT FOUND');
            return escapeHtml(a.aspect) + ': ' +
                escapeHtml(status) +
                ' (' + a.knowledge_items + ' item(s), ' + a.content_records + ' record(s))';
        }).join('<br>') +
        '</div></div>'
    ) : '') +
        '<div class="trace-row"><div class="trace-label">Local Database Searched</div><div class="trace-local">YES</div></div>' +
        '<div class="trace-row"><div class="trace-label">Database Match Found</div><div class="trace-neutral">' +
        yesNo(result.database_match_found) + '</div></div>' +
        '<div class="trace-row"><div class="trace-label">Retrieved Knowledge Items</div><div class="trace-neutral">' +
        escapeHtml(result.retrieved_items || 0) + '</div></div>' +
        '<div class="trace-row"><div class="trace-label">Retrieved Content Records</div><div class="trace-neutral">' +
        escapeHtml(result.retrieved_chunks || 0) + '</div></div>' +
        '</div>' +
        buildProfessionalInternalReport(result) +
        (result.pending_analysis_id ? '<div class="action-row" style="margin-top:16px;"><button type="button" class="export-docx-button" onclick="exportInternalAnalysis(' + Number(result.pending_analysis_id) + ')">Export to Word (.docx)</button><button type="button" class="export-pdf-button" onclick="exportInternalAnalysisPdf(' + Number(result.pending_analysis_id) + ')">Export to PDF (.pdf)</button></div>' : '') +
        '<div class="analysis-review" style="margin-top:16px;">' +
            '<div class="analysis-review-title">Need More Assistance?</div>' +
            '<div class="analysis-review-note">Optional: search reusable Generic Knowledge first. OpenAI external knowledge is used only if the Generic Knowledge workflow still needs it.</div>' +
            '<div class="analysis-review-actions"><button type="button" class="generic-button" onclick="requestMoreAssistance()">Need More Assistance</button></div>' +
        '</div>' +
        (result.pending_analysis_id ?
            '<div class="analysis-review" id="analysis_review_' + escapeHtml(result.pending_analysis_id) + '">' +
            '<div class="analysis-review-title">Customer-Specific Analysis — Pending Validation</div>' +
            '<div class="analysis-review-note">This analysis has been saved as PENDING. Select Proceed to validate it as trusted Internal Knowledge, or Reject to keep it out of validated knowledge.</div>' +
            '<div class="analysis-review-actions">' +
            '<button type="button" onclick="reviewInternalAnalysis(' + Number(result.pending_analysis_id) + ', &quot;PROCEED&quot;)">Proceed</button>' +
            '<button type="button" class="reject-analysis-button" onclick="reviewInternalAnalysis(' + Number(result.pending_analysis_id) + ', &quot;REJECT&quot;)">Reject</button>' +
            '</div><div class="analysis-review-status" id="analysis_review_status_' + escapeHtml(result.pending_analysis_id) + '">Status: PENDING</div></div>' : '') +
        (sourceRows ? '<div class="card" style="margin-top:16px;"><h3>Sources Used</h3>' + sourceRows + '</div>' : '') +
        '</div>';
}

function requestMoreAssistance() {
    const internalQuestion = document.getElementById('question');
    const genericQuestion = document.getElementById('generic_question');
    if (genericQuestion && internalQuestion) genericQuestion.value = internalQuestion.value || '';
    knowledgeMode.value = 'generic';
    sessionStorage.setItem('aiAgentKnowledgeMode', 'generic');
    updateKnowledgeMode();
    if (genericQuestion) {
        genericQuestion.focus();
        genericQuestion.scrollIntoView({behavior: 'smooth', block: 'center'});
    }
}

async function reviewInternalAnalysis(analysisId, decision) {
    const statusBox = document.getElementById('analysis_review_status_' + analysisId);
    const reviewBox = document.getElementById('analysis_review_' + analysisId);
    if (!statusBox || !reviewBox) return;

    const csrfInput = internalForm ? internalForm.querySelector('input[name="csrfmiddlewaretoken"]') : null;
    const formData = new FormData();
    formData.append('analysis_id', analysisId);
    formData.append('decision', decision);
    if (csrfInput) formData.append('csrfmiddlewaretoken', csrfInput.value);

    reviewBox.querySelectorAll('button').forEach(function(button) { button.disabled = true; });
    statusBox.textContent = decision === 'PROCEED' ? 'Validating analysis...' : 'Rejecting analysis...';

    try {
        const response = await fetch(aiAgentConfig.dataset.reviewInternalAnalysisUrl, {
            method: 'POST',
            body: formData,
            headers: { 'X-Requested-With': 'XMLHttpRequest' }
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.message || 'Unable to review analysis.');
        statusBox.textContent = 'Status: ' + payload.status + ' — ' + payload.message;
    } catch (error) {
        statusBox.textContent = error.message || 'Unable to review analysis.';
        reviewBox.querySelectorAll('button').forEach(function(button) { button.disabled = false; });
    }
}

if (internalForm && internalLiveProgressBox) {
    internalForm.addEventListener('submit', async function (event) {
        // Keep the existing normal POST behavior for organization-change refreshes.
        if (internalForm.querySelector('input[name="organization_change"]')) return;

        event.preventDefault();

        if (allDocumentsCheckbox && !allDocumentsCheckbox.checked) {
            const selectedDocuments = sourceCheckboxes.filter(function (checkbox) {
                return checkbox.checked;
            });
            if (!selectedDocuments.length) {
                alert('Select at least one document, or choose All Documents.');
                return;
            }
        }

        const submitButton = internalForm.querySelector('button[type="submit"]');
        if (submitButton) {
            submitButton.disabled = true;
            submitButton.textContent = 'Processing...';
        }

        document.querySelectorAll('.previous-result').forEach(function (element) {
            element.style.display = 'none';
        });

        internalLiveResultContainer.innerHTML = '';
        internalLiveResultContainer.style.display = 'none';
        internalLiveProgressBox.style.display = 'block';
        internalLiveProgressFill.style.width = '0%';
        internalLiveProgressPercent.textContent = '0%';
        internalLiveProgressStage.textContent = 'Starting AI-Agent processing...';
        if (internalLiveActivityRows) internalLiveActivityRows.innerHTML = '';

        startInternalTimer();
        addInternalActivity(0, 'Starting AI-Agent processing...');

        try {
            const formData = new FormData(internalForm);
            const response = await fetch(aiAgentConfig.dataset.internalProgressUrl, {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });

            if (!response.ok || !response.body) {
                throw new Error('Unable to start Internal Knowledge processing.');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let finalResult = null;

            function processInternalStreamLine(line) {
                if (!line || !line.trim()) return;
                const message = JSON.parse(line);

                if (message.type === 'progress') {
                    const percent = Math.max(0, Math.min(100, Number(message.percent) || 0));
                    internalLiveProgressFill.style.width = percent + '%';
                    internalLiveProgressPercent.textContent = percent + '%';
                    internalLiveProgressStage.textContent = message.stage || 'Processing...';
                    addInternalActivity(percent, message.stage || 'Processing...');
                } else if (message.type === 'result') {
                    finalResult = message.result;
                } else if (message.type === 'error') {
                    throw new Error(message.message || 'Internal Knowledge processing failed.');
                }
            }

            while (true) {
                const read = await reader.read();

                if (read.done) {
                    buffer += decoder.decode();
                    if (buffer.trim()) {
                        processInternalStreamLine(buffer);
                        buffer = '';
                    }
                    break;
                }

                buffer += decoder.decode(read.value, {stream: true});
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    processInternalStreamLine(line);
                }
            }

            if (!finalResult) {
                throw new Error('Internal Knowledge processing completed without returning a result.');
            }

            internalLiveProgressFill.style.width = '100%';
            internalLiveProgressPercent.textContent = '100%';
            internalLiveProgressStage.textContent = 'Completed';
            stopInternalTimer();
            renderInternalResult(finalResult);

        } catch (error) {
            stopInternalTimer();
            internalLiveProgressStage.textContent = error.message || 'Processing failed.';
            addInternalActivity(
                Number((internalLiveProgressPercent.textContent || '0').replace('%', '')) || 0,
                error.message || 'Processing failed.'
            );
        } finally {
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.textContent = 'Ask Internal Knowledge';
            }
        }
    });
}


const genericForm = document.getElementById('generic_form');
const processingBox = document.getElementById('processing_box');
const liveProgressBox = document.getElementById('live_progress_box');
const liveProgressFill = document.getElementById('live_progress_fill');
const liveProgressStage = document.getElementById('live_progress_stage');
const liveProgressPercent = document.getElementById('live_progress_percent');
const liveProgressElapsed = document.getElementById('live_progress_elapsed');
const liveActivityRows = document.getElementById('live_activity_rows');
const liveResultContainer = document.getElementById('live_result_container');

let genericTimerId = null;
let genericStartedAt = null;
let genericLastActivityAt = null;

function formatElapsedSeconds(totalSeconds) {
    const seconds = Math.max(0, Math.floor(totalSeconds || 0));
    const minutes = Math.floor(seconds / 60);
    const remaining = seconds % 60;
    return String(minutes).padStart(2, '0') + ':' + String(remaining).padStart(2, '0');
}

function startGenericTimer() {
    if (genericTimerId) clearInterval(genericTimerId);
    genericStartedAt = Date.now();
    genericLastActivityAt = genericStartedAt;
    if (liveProgressElapsed) liveProgressElapsed.textContent = '00:00';
    genericTimerId = setInterval(function () {
        if (liveProgressElapsed && genericStartedAt) {
            liveProgressElapsed.textContent =
                formatElapsedSeconds((Date.now() - genericStartedAt) / 1000);
        }
    }, 1000);
}

function stopGenericTimer() {
    if (genericTimerId) {
        clearInterval(genericTimerId);
        genericTimerId = null;
    }
    if (liveProgressElapsed && genericStartedAt) {
        liveProgressElapsed.textContent =
            formatElapsedSeconds((Date.now() - genericStartedAt) / 1000);
    }
}

function addGenericActivity(percent, stage) {
    if (!liveActivityRows) return;

    const now = Date.now();
    let durationText = 'started';
    if (genericLastActivityAt && liveActivityRows.children.length > 0) {
        durationText = formatElapsedSeconds((now - genericLastActivityAt) / 1000);
    }
    genericLastActivityAt = now;

    const row = document.createElement('div');
    row.className = 'activity-row';

    const percentCell = document.createElement('div');
    percentCell.className = 'activity-percent';
    percentCell.textContent = String(percent) + '%';

    const stageCell = document.createElement('div');
    stageCell.className = 'activity-stage';
    stageCell.textContent = stage || 'Processing...';

    const durationCell = document.createElement('div');
    durationCell.className = 'activity-duration';
    durationCell.textContent = durationText;

    row.appendChild(percentCell);
    row.appendChild(stageCell);
    row.appendChild(durationCell);
    liveActivityRows.appendChild(row);
}

function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
}

function yesNo(value) {
    return value ? 'YES' : 'NO';
}

function stripGenericMarkdown(text) {
    return String(text || '')
        .replace(/^#{1,6}\s*/gm, '')
        .replace(/\*\*(.*?)\*\*/g, '$1')
        .replace(/^\s*[-*]\s+/gm, '')
        .trim();
}

function extractGenericReportSection(answer, heading, nextHeadings) {
    const text = String(answer || '');
    const escaped = heading.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const next = (nextHeadings || []).map(function(h) {
        return h.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    }).join('|');
    const rx = new RegExp(
        '(?:^|\\n)\\s*#{0,3}\\s*' + escaped + '\\s*\\n([\\s\\S]*?)' +
        (next ? '(?=\\n\\s*#{0,3}\\s*(?:' + next + ')\\s*\\n|$)' : '$'), 'i'
    );
    const m = text.match(rx);
    return m ? stripGenericMarkdown(m[1]) : '';
}

function genericLines(text) {
    return String(text || '').split(/\r?\n/)
        .map(function(x) { return stripGenericMarkdown(x).replace(/^\d+\.\s*/, '').trim(); })
        .filter(Boolean);
}

function buildProfessionalGenericReport(result) {
    const answer = String(result.answer || '');
    let executive = extractGenericReportSection(answer, 'EXECUTIVE SUMMARY', ['KEY FINDINGS', 'DETAILED ANALYSIS']);
    let findingsText = extractGenericReportSection(answer, 'KEY FINDINGS', ['DETAILED ANALYSIS']);
    let detailed = extractGenericReportSection(answer, 'DETAILED ANALYSIS', []);
    if (!executive) executive = firstSentences(stripGenericMarkdown(answer), 3);
    if (!detailed) detailed = stripGenericMarkdown(answer);

    const findings = genericLines(findingsText);
    const investigationRows = findings.length ? findings.map(function(item) {
        let area = item, assessment = item;
        const colon = item.indexOf(':');
        if (colon > 0) {
            area = item.slice(0, colon).trim();
            assessment = item.slice(colon + 1).trim();
        }
        return '<tr><td>' + escapeHtml(area) + '</td><td class="status-found">FOUND</td><td>' +
            escapeHtml(assessment || item) + '</td></tr>';
    }).join('') :
        '<tr><td>Requested information</td><td class="status-found">FOUND</td><td>' +
        escapeHtml(firstSentences(detailed, 2)) + '</td></tr>';

    const sourceNames = Array.isArray(result.attachment_files)
        ? result.attachment_files.map(function(f) { return f.name || ''; }).filter(Boolean) : [];
    const sourceRows = sourceNames.length ? sourceNames.map(function(name) {
        return '<tr><td>' + escapeHtml(name) + '</td><td class="status-found">USED</td>' +
               '<td>Attached document evidence used in this analysis.</td></tr>';
    }).join('') :
        '<tr><td>Generic Knowledge Database</td><td class="status-found">SEARCHED</td>' +
        '<td>Reusable Generic Knowledge was searched for this request.</td></tr>';

    let gaps = 'No unresolved gaps were identified in the information used for this answer.';
    const gapMatch = detailed.match(/(?:do not provide|not stated|not specify|no further details|requires? confirmation)[\s\S]*?(?:\.|$)/i);
    if (gapMatch) gaps = stripGenericMarkdown(gapMatch[0]);

    return '<div class="professional-report">' +
        '<div class="report-header"><h3>AI-Agent Generic Knowledge Analysis</h3>' +
        '<div class="report-subtitle">Generic / Reusable Knowledge | Professional Analysis</div></div>' +
        '<div class="report-section"><h4>1. Executive Summary</h4><div class="report-text">' +
        escapeHtml(executive) + '</div></div>' +
        '<div class="report-section"><h4>2. Investigation Summary</h4>' +
        '<table class="report-table"><thead><tr><th>Area</th><th>Status</th><th>Assessment</th></tr></thead><tbody>' +
        investigationRows + '</tbody></table></div>' +
        '<div class="report-section"><h4>3. Detailed Analysis</h4><div class="report-text" style="white-space:pre-wrap;">' +
        escapeHtml(detailed) + '</div></div>' +
        '<div class="report-section"><h4>4. Gaps / Information Requiring Confirmation</h4><div class="report-text">' +
        escapeHtml(gaps) + '</div></div>' +
        '<div class="report-section"><h4>5. Recommended Answer / Conclusion</h4>' +
        '<div class="report-note"><strong>AI-Agent conclusion:</strong> Based on the evidence and knowledge sources used for this request.</div>' +
        '<div class="report-text">' + escapeHtml(executive) + '</div></div>' +
        '<div class="report-section"><h4>6. Sources Used</h4>' +
        '<table class="report-table"><thead><tr><th>Source</th><th>Status</th><th>Usage</th></tr></thead><tbody>' +
        sourceRows + '</tbody></table></div></div>';
}

function exportGenericAnalysis(analysisId) {
    const templateUrl = aiAgentConfig.dataset.exportGenericDocxUrl;
    window.location.href = templateUrl.replace('999999', String(analysisId));
}
function exportGenericAnalysisPdf(analysisId) {
    const templateUrl = aiAgentConfig.dataset.exportGenericPdfUrl;
    window.location.href = templateUrl.replace('999999', String(analysisId));
}

function renderLiveResult(result) {
    if (!liveResultContainer) return;

    liveResultContainer.innerHTML =
        '<div class="card previous-result">' +
        '<h3>AI-Agent Answer</h3>' +
        '<div class="answer">' + escapeHtml(result.answer || '') + '</div>' +
        '</div>';

    liveResultContainer.style.display = 'block';
}


if (genericForm && liveProgressBox) {
    genericForm.addEventListener('submit', async function (event) {
        event.preventDefault();

        const submitButton = genericForm.querySelector('button[type="submit"]');
        if (submitButton) {
            submitButton.disabled = true;
            submitButton.textContent = 'Processing...';
        }

        document.querySelectorAll('.previous-result').forEach(function (element) {
            element.style.display = 'none';
        });

        if (processingBox) processingBox.style.display = 'none';
        liveResultContainer.innerHTML = '';
        liveProgressBox.style.display = 'block';
        liveProgressFill.style.width = '0%';
        liveProgressPercent.textContent = '0%';
        liveProgressStage.textContent = 'Starting AI-Agent processing...';
        if (liveActivityRows) liveActivityRows.innerHTML = '';
        startGenericTimer();
        

        try {
            const formData = new FormData(genericForm);
            const response = await fetch(aiAgentConfig.dataset.genericProgressUrl, {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });

            if (!response.ok || !response.body) {
                throw new Error('Unable to start AI-Agent processing.');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let finalResult = null;

            function processGenericStreamLine(line) {
                if (!line || !line.trim()) return;

                const message = JSON.parse(line);

                if (message.type === 'progress') {
                    const percent = Math.max(0, Math.min(100, Number(message.percent) || 0));
                    liveProgressFill.style.width = percent + '%';
                    liveProgressPercent.textContent = percent + '%';
                    liveProgressStage.textContent = percent >= 100 ? 'Completed' : 'Processing...';
                } else if (message.type === 'result') {
                    finalResult = message.result;
                } else if (message.type === 'error') {
                    throw new Error(message.message || 'AI-Agent processing failed.');
                }
            }

            while (true) {
                const read = await reader.read();

                if (read.done) {
                    // Flush any bytes still held by TextDecoder.
                    buffer += decoder.decode();

                    // A proxy/server may close the stream without leaving a final newline.
                    // Process the final NDJSON message instead of silently dropping it.
                    if (buffer.trim()) {
                        processGenericStreamLine(buffer);
                        buffer = '';
                    }
                    break;
                }

                buffer += decoder.decode(read.value, {stream: true});
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    processGenericStreamLine(line);
                }
            }

            if (!finalResult) {
                throw new Error('AI-Agent completed without returning a result.');
            }

            liveProgressFill.style.width = '100%';
            liveProgressPercent.textContent = '100%';
            liveProgressStage.textContent = 'Completed';
            addGenericActivity(100, 'Completed');
            stopGenericTimer();

            // The result container starts hidden. Make it visible before rendering
            // the completed Generic Knowledge answer.
            if (liveResultContainer) {
                liveResultContainer.style.display = 'block';
            }
            renderLiveResult(finalResult);

        } catch (error) {
            stopGenericTimer();
            liveProgressStage.textContent = error.message || 'Processing failed.';
            addGenericActivity(
                Number((liveProgressPercent && liveProgressPercent.textContent || '0').replace('%', '')) || 0,
                error.message || 'Processing failed.'
            );
        } finally {
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.textContent = 'Ask AI-Agent';
            }
        }
    });
}


const externalApiForm = document.getElementById('external_api_form');
const externalLiveProgressBox = document.getElementById('external_live_progress_box');
const externalLiveProgressFill = document.getElementById('external_live_progress_fill');
const externalLiveProgressStage = document.getElementById('external_live_progress_stage');
const externalLiveProgressPercent = document.getElementById('external_live_progress_percent');
const externalLiveResultContainer = document.getElementById('external_live_result_container');

function renderExternalApiResult(result) {
    const isLiveApi = !!result.live_api_used || result.knowledge_source === 'ALPACA_API';
    const openaiUsed = !!result.openai_used;
    const externalAiLookup = !!result.openai_external_lookup_performed;

    const rows = [
        ['Live API Used', isLiveApi ? 'YES' : 'NO'],
        ['OpenAI API Used', openaiUsed ? 'YES' : 'NO'],
        ['External AI Knowledge Lookup', externalAiLookup ? 'YES' : 'NO'],
        ['Local Database Searched', result.database_searched ? 'YES' : 'NO'],
        ['Database Match Found', result.database_match_found ? 'YES' : 'NO'],
        ['Knowledge Source', result.knowledge_source || result.provider || 'LIVE_API'],
        ['Answer Information Source', result.answer_information_source || 'LIVE_API'],
        ['Automatically Stored in Generic Knowledge', result.automatically_stored ? 'YES' : 'NO']
    ];

    const traceRows = rows.map(row =>
        '<div class="trace-row"><div class="trace-label">' +
        escapeHtml(row[0]) + '</div><div class="trace-neutral">' +
        escapeHtml(row[1]) + '</div></div>'
    ).join('');

    const symbol = result.symbol || '';
    const price = result.price != null ? Number(result.price) : null;
    const currency = result.currency || 'USD';
    const feed = (result.feed || '').toUpperCase();
    const timestamp = result.timestamp || '';
    const bars = Array.isArray(result.bars) ? result.bars : [];

    let chartHtml = '';
    if (bars.length >= 2) {
        const closes = bars.map(b => Number(b.close)).filter(Number.isFinite);
        const min = Math.min.apply(null, closes);
        const max = Math.max.apply(null, closes);
        const range = Math.max(max - min, 0.01);
        const W = 760, H = 220, PX = 20, PY = 18;
        const points = closes.map((v, i) => {
            const x = PX + (i * (W - 2 * PX) / Math.max(closes.length - 1, 1));
            const y = PY + ((max - v) / range) * (H - 2 * PY);
            return x.toFixed(1) + ',' + y.toFixed(1);
        }).join(' ');
        const firstTs = bars[0].timestamp ? new Date(bars[0].timestamp).toLocaleString() : '';
        const lastTs = bars[bars.length - 1].timestamp ? new Date(bars[bars.length - 1].timestamp).toLocaleString() : '';
        chartHtml =
            '<div style="margin-top:18px;border:1px solid #e2e8f0;border-radius:12px;padding:18px;background:#fff;">' +
            '<div style="font-weight:700;font-size:16px;margin-bottom:4px;">Recent 5-Minute Price Trend</div>' +
            '<div style="color:#64748b;font-size:12px;margin-bottom:10px;">Recent available Alpaca/IEX bars</div>' +
            '<svg viewBox="0 0 '+W+' '+H+'" style="width:100%;height:230px;display:block;background:#f8fafc;border-radius:8px;">' +
            '<line x1="20" y1="18" x2="20" y2="202" stroke="#cbd5e1"/>' +
            '<line x1="20" y1="202" x2="740" y2="202" stroke="#cbd5e1"/>' +
            '<polyline fill="none" stroke="#334155" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" points="'+points+'"/>' +
            '<text x="28" y="35" font-size="12" fill="#64748b">High '+max.toFixed(2)+'</text>' +
            '<text x="28" y="194" font-size="12" fill="#64748b">Low '+min.toFixed(2)+'</text>' +
            '</svg>' +
            '<div style="display:flex;justify-content:space-between;color:#64748b;font-size:11px;margin-top:5px;"><span>'+escapeHtml(firstTs)+'</span><span>'+escapeHtml(lastTs)+'</span></div>' +
            '</div>';
    } else {
        chartHtml =
            '<div style="margin-top:18px;padding:14px;border:1px solid #e2e8f0;border-radius:10px;color:#64748b;">' +
            'Price trend is not available for this request; the latest live trade was still retrieved successfully.' +
            '</div>';
    }

    const statusText = openaiUsed
        ? 'OpenAI API Used: YES'
        : 'Live Connected API Used: YES — OpenAI knowledge was not used.';

    externalLiveResultContainer.innerHTML =
        '<div class="card previous-result">' +
        '<h3>Connected API Answer</h3>' +
        '<div class="api-status" style="background:#ecfdf5;border:1px solid #a7f3d0;color:#166534;">' +
        escapeHtml(statusText) +
        '</div>' +
        '<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:16px 0;">' +
          '<div style="border:1px solid #e2e8f0;border-radius:10px;padding:14px;"><div style="font-size:12px;color:#64748b;">Symbol</div><div style="font-size:22px;font-weight:700;">'+escapeHtml(symbol)+'</div></div>' +
          '<div style="border:1px solid #e2e8f0;border-radius:10px;padding:14px;"><div style="font-size:12px;color:#64748b;">Latest Trade</div><div style="font-size:22px;font-weight:700;">'+(price === null ? 'N/A' : escapeHtml(price.toFixed(2)+' '+currency))+'</div></div>' +
          '<div style="border:1px solid #e2e8f0;border-radius:10px;padding:14px;"><div style="font-size:12px;color:#64748b;">API / Feed</div><div style="font-size:18px;font-weight:700;">Alpaca / '+escapeHtml(feed)+'</div></div>' +
        '</div>' +
        chartHtml +
        '<div class="trace-box" style="margin-top:18px;"><h4 class="trace-title">AI-Agent Source Trace</h4>' +
        traceRows + '</div>' +
        '<div class="answer" style="margin-top:16px;">' + escapeHtml(result.answer || '') + '</div>' +
        '</div>';
}
if (externalApiForm && externalLiveProgressBox) {
    externalApiForm.addEventListener('submit', async function (event) {
        event.preventDefault();

        const submitButton = externalApiForm.querySelector('button[type="submit"]');
        if (submitButton) {
            submitButton.disabled = true;
            submitButton.textContent = 'Processing...';
        }

        document.querySelectorAll('.previous-result').forEach(function (element) {
            element.style.display = 'none';
        });

        externalLiveResultContainer.innerHTML = '';
        externalLiveProgressBox.style.display = 'block';
        externalLiveProgressFill.style.width = '0%';
        externalLiveProgressPercent.textContent = '0%';
        externalLiveProgressStage.textContent = 'Starting connected API request...';

        try {
            const formData = new FormData(externalApiForm);
            const response = await fetch(aiAgentConfig.dataset.externalProgressUrl, {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });

            if (!response.ok || !response.body) {
                throw new Error('Unable to start external OpenAI processing.');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let finalResult = null;

            while (true) {
                const read = await reader.read();
                if (read.done) break;

                buffer += decoder.decode(read.value, {stream: true});
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.trim()) continue;
                    const message = JSON.parse(line);

                    if (message.type === 'progress') {
                        const percent = Math.max(0, Math.min(100, Number(message.percent) || 0));
                        externalLiveProgressFill.style.width = percent + '%';
                        externalLiveProgressPercent.textContent = percent + '%';
                        externalLiveProgressStage.textContent = message.stage || 'Processing...';
                    } else if (message.type === 'result') {
                        finalResult = message.result;
                    } else if (message.type === 'error') {
                        throw new Error(message.message || 'External OpenAI processing failed.');
                    }
                }
            }

            if (!finalResult) {
                throw new Error('External OpenAI request completed without returning a result.');
            }

            externalLiveProgressFill.style.width = '100%';
            externalLiveProgressPercent.textContent = '100%';
            externalLiveProgressStage.textContent = 'Completed';
            renderExternalApiResult(finalResult);

        } catch (error) {
            externalLiveProgressStage.textContent = error.message || 'Processing failed.';
        } finally {
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.textContent = 'Ask Connected API';
            }
        }
    });
}

const organizationSelect = document.getElementById('organization');

if (organizationSelect) {
    organizationSelect.addEventListener('change', function () {
        const form = this.form;
        const question = document.getElementById('question');

        if (question) {
            question.removeAttribute('required');
        }

        if (allDocumentsCheckbox) {
            allDocumentsCheckbox.checked = true;
            updateDocumentScope();
        }

        const marker = document.createElement('input');
        marker.type = 'hidden';
        marker.name = 'organization_change';
        marker.value = '1';
        form.appendChild(marker);

        // The organization change submits the form and reloads this page.
        // Remember that the user is working in Internal / Customer Knowledge.
        sessionStorage.setItem('aiAgentKnowledgeMode', 'internal');

        form.submit();
    });
}

(function () {
    const organizationSelect = document.getElementById('organization');
    const uploadFilesLink = document.getElementById('upload_files_link');

    function updateUploadFilesLink() {
        if (!organizationSelect || !uploadFilesLink) return;
        const organizationId = organizationSelect.value || '';
        uploadFilesLink.href = '/upload/?organization=' + encodeURIComponent(organizationId);
    }

    if (organizationSelect) {
        organizationSelect.addEventListener('change', updateUploadFilesLink);
        updateUploadFilesLink();
    }
})();
