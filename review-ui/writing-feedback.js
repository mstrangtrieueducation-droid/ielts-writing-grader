/* IELTS_WRITING_FEEDBACK_V1: personal results only, with live bearer authorization. IELTS_WRITING_HOMEWORK_WARM_V2 */
const ieltsWritingReviews_ = (() => {
  'use strict';
  const REFRESH_INTERVAL_MS = 180000;
  let identity = '', generation = 0, status = 'idle', reviews = [], sourceStates = [], notebookStates = [], writingPolicyStates = [], inFlight = null, lastFetch = 0, hasLoaded = false, refreshing = false;
  let dialog = null, opener = null, scrollBefore = '', selectedReview = null;
  const revisionCache = new Map();
  const savedReviews = new Map();
  let reviewWarmObserver = null, reviewWarmTimer = 0;
  const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
  const normalizedName = value => String(value || '').normalize('NFC').trim().replace(/\s+/g, ' ').toLocaleUpperCase('vi');
  const array = value => Array.isArray(value) ? value : [];
  function inline(value) {
    // User/model text is escaped first. Only local emphasis is rendered; no HTML or links.
    return escape(value).replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>').replace(/`([^`\n]+)`/g, '<code>$1</code>');
  }
  function prose(value) { return String(value || '').split(/\n\s*\n/).map(p => '<p>' + inline(p).replace(/\n/g, '<br>') + '</p>').join(''); }
  function who() {
    return ieltsWritingAssignments_.all().length && parentState.authorized && !parentState.locked && parentState.name
      ? [ieltsParentAccess.className, parentState.revision, parentState.name].join('|') : '';
  }
  function close() {
    if (dialog && dialog.open) dialog.close();
    document.body.style.overflow = scrollBefore;
    if (opener && opener.isConnected) opener.focus({preventScroll:true});
    selectedReview = null;
  }
  function clear() {
    ieltsHybridReviews_.clear();
    generation++; identity = ''; reviews = []; sourceStates = []; notebookStates = []; writingPolicyStates = []; status = 'idle'; inFlight = null; lastFetch = 0; hasLoaded = false; refreshing = false;
    revisionCache.clear(); savedReviews.clear();
    clearTimeout(reviewWarmTimer); reviewWarmTimer = 0;
    reviewWarmObserver?.disconnect(); reviewWarmObserver = null;
    if (dialog) { close(); dialog.remove(); dialog = null; }
  }
  function current() {
    const next = who();
    if (next !== identity) { clear(); identity = next; }
    return Boolean(next);
  }
  const code = ieltsWritingAssignments_.code;
  function validRecord(record) {
    if (record && record.taskType === 2 && (!record.task2 || array(record.task2.criteria).length !== 5 || !Array.isArray(record.task2.outlineCoverage))) return false;
    return Boolean(record && record.schemaVersion === 1 && record.resultId &&
      record.className === ieltsParentAccess.className && normalizedName(record.studentName) === normalizedName(parentState.name) &&
      code(record.assignmentCode) && Number.isInteger(Number(record.taskNumber)) && Number(record.taskNumber) > 0 && Number(record.taskNumber) <= 50 &&
      typeof record.overall === 'string' && typeof record.originalEssay === 'string' && record.originalEssay && record.suggestedRevision &&
      record.publication && ['published','returned'].includes(record.publication.state));
  }
  function repaint() {
    if (!current() || !state.student || !state.dashboard || normalizedName(state.student.name) !== normalizedName(parentState.name)) return;
    // Remove details from already-rendered inactive panels as soon as a closure arrives.
    document.querySelectorAll('.wr-assignment[data-wr-assignment]').forEach(node => {
      const assignment = ieltsWritingAssignments_.all().find(item => item.assignmentCode === node.dataset.wrAssignment);
      if (assignment && writingBlockedByPolicy(assignment.assignmentCode)) node.outerHTML = groupHtml(assignment);
    });
    if (state.active === 'writing') renderSkill('writing');
    if (state.active === 'overview') renderOverview();
  }
  function sourceState(assignmentCode, taskNumber) {
    return sourceStates.find(item => code(item.assignmentCode) === code(assignmentCode) && Number(item.taskNumber) === Number(taskNumber)) || {state:'source_unavailable'};
  }
  function isCurrentReview(record) {
    if(record && savedReviews.get(record.resultId)===record) return !writingBlockedByPolicy(record.assignmentCode);
    return Boolean(record && !writingBlockedByPolicy(record.assignmentCode) && sourceState(record.assignmentCode, record.taskNumber).state === 'current' &&
      sourceState(record.assignmentCode, record.taskNumber).currentResultId === record.resultId);
  }
  function readSourceStates(data) {
    const allowed = ['current','pending','empty_submission','ambiguous_source','source_error','source_unavailable','not_submitted'];
    const entries = array(data.sourceStates), seen = new Set();
    const valid = entries.every(item => {
      if (!item || !code(item.assignmentCode) || !Number.isInteger(item.taskNumber) || item.taskNumber < 1 || item.taskNumber > 50 || !allowed.includes(item.state)) return false;
      const group = code(item.assignmentCode) + '|' + item.taskNumber;
      if (seen.has(group)) return false; seen.add(group);
      return item.state !== 'current' || typeof item.currentResultId === 'string' && data.reviews.some(record =>
        record.resultId === item.currentResultId && code(record.assignmentCode) === code(item.assignmentCode) && Number(record.taskNumber) === item.taskNumber);
    });
    // Missing or invalid freshness evidence must not promote a historical review.
    return valid ? entries : [];
  }
  function readNotebookStates(data) {
    if (data.notebookStates === undefined) return [];
    if (!Array.isArray(data.notebookStates)) throw new Error('Notebook response mismatch');
    const seen = new Set();
    for (const item of data.notebookStates) {
      if (!item || item.className !== ieltsParentAccess.className || normalizedName(item.studentName) !== normalizedName(parentState.name) ||
          !code(item.assignmentCode) || seen.has(code(item.assignmentCode)) || typeof item.state !== 'string' ||
          typeof item.current !== 'boolean' || typeof item.historical !== 'boolean' ||
          (item.essayGradingLocked !== undefined && typeof item.essayGradingLocked !== 'boolean') ||
          !['notebook_only','notebook_and_writing'].includes(item.homeworkMode)) throw new Error('Notebook identity mismatch');
      seen.add(code(item.assignmentCode));
    }
    return data.notebookStates;
  }
  function writingPolicy(assignmentCode) {
    return writingPolicyStates.find(item => code(item.assignmentCode) === code(assignmentCode));
  }
  function writingBlockedByPolicy(assignmentCode) {
    return ['too_late','policy_unavailable'].includes(writingPolicy(assignmentCode)?.state);
  }
  function readWritingPolicyStates(data) {
    // Older responses may omit this field. They cannot clear an already-known closure.
    if (data.writingPolicyStates === undefined) return writingPolicyStates;
    const unavailable = assignmentCode => ({assignmentCode,state:'policy_unavailable',closed:true});
    const allUnavailable = () => ieltsWritingAssignments_.all().map(item => unavailable(item.assignmentCode));
    if (!Array.isArray(data.writingPolicyStates)) return allUnavailable();
    const entries = new Map();
    for (const item of data.writingPolicyStates) {
      const assignmentCode = code(item && item.assignmentCode);
      if (!assignmentCode) return allUnavailable();
      const cutoffValid = typeof item.cutoffAt === 'string' && /^\d{4}-\d{2}-\d{2}T00:00:00(?:\.000)?\+07:00$/.test(item.cutoffAt) && Number.isFinite(Date.parse(item.cutoffAt));
      const valid = item.closed === true && ['grading_closed','too_late','policy_unavailable'].includes(item.state) &&
        (item.state === 'policy_unavailable' || cutoffValid);
      entries.set(assignmentCode, entries.has(assignmentCode) || !valid ? unavailable(assignmentCode) : {...item,assignmentCode});
    }
    return [...entries.values()];
  }
  async function refresh(force = false) {
    if (!current() || document.visibilityState === 'hidden') return;
    if (inFlight) return inFlight;
    if (!force && lastFetch && Date.now() - lastFetch < (hasLoaded ? REFRESH_INTERVAL_MS : 30000)) return;
    const epoch = generation, startedFor = identity;
    lastFetch = Date.now(); refreshing = true;
    if (!hasLoaded) status = 'loading';
    // A background read is not a change to a saved review. Keep the DOM and
    // last authenticated snapshot until a response supplies new evidence.
    const before = JSON.stringify([status,reviews,sourceStates,notebookStates,writingPolicyStates]);
    const request = ieltsParentAccess.request('writing', force).then(data => {
      if (epoch !== generation || who() !== startedFor) return;
      if (!data || data.className !== ieltsParentAccess.className || data.parentName !== parentState.name ||
          data.parentRosterRevision !== parentState.revision || normalizedName(data.studentName) !== normalizedName(parentState.name) ||
          !Array.isArray(data.reviews)) throw new Error('Writing identity mismatch');
      // Apply an authenticated closure even if the accompanying feedback is malformed.
      writingPolicyStates = readWritingPolicyStates(data); updateOpenFreshness();
      // Reject a mixed payload as a whole, including malformed/unpublished entries.
      if (data.reviews.some(record => !validRecord(record))) throw new Error('Writing result mismatch');
      const checkedNotebooks = readNotebookStates(data);
      reviews = data.reviews.slice().sort((a,b) => String(b.publication.publishedAt || '').localeCompare(String(a.publication.publishedAt || '')));
      notebookStates = checkedNotebooks;
      sourceStates = readSourceStates(data);
      status = 'ready'; hasLoaded = true; refreshing = false; updateOpenFreshness();
    }).catch(() => {
      if (epoch === generation && who() === startedFor) {
        sourceStates = []; notebookStates = notebookStates.map(item => item.publicationFinal ? item : ({...item,current:false,historical:Boolean(item.overall),receiptStatus:undefined})); refreshing = false;
        // A transient read failure cannot certify an old review as current.
        // Its already-authorized historical content remains available in place.
        if (hasLoaded) { status = 'ready'; updateOpenFreshness(); }
        else { reviews = []; status = 'error'; }
      }
    })
      .finally(() => { if (epoch === generation && who() === startedFor) {
        inFlight = null;
        if (before !== JSON.stringify([status,reviews,sourceStates,notebookStates,writingPolicyStates])) repaint();
      } });
    inFlight = request; return request;
  }
  function updateOpenFreshness() {
    if (dialog && writingBlockedByPolicy(dialog.dataset.wrAssignment)) {
      close(); dialog.remove(); dialog = null; return;
    }
    if (!dialog || !dialog.open || !selectedReview) return;
    dialog.querySelector('[data-wr-review-label]').textContent = isCurrentReview(selectedReview) ? 'Đã trả bài' : 'Bài chữa lần nộp trước';
    dialog.querySelector('[data-wr-freshness]').innerHTML = freshnessHtml(selectedReview.assignmentCode, selectedReview.taskNumber, selectedReview);
  }
  function overallHtml(record) { return '<div class="wr-copy wr-overall">' + prose(record.overall) + '</div>'; }
  function submissionDate(value) {
    const text = String(value || '');
    if (!/^\d{4}-\d{2}-\d{2}T/.test(text)) return text;
    const date = new Date(text); if (!Number.isFinite(date.getTime())) return text;
    return new Intl.DateTimeFormat('vi-VN', {day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',hourCycle:'h23',timeZone:'Asia/Bangkok'}).format(date).replace(', ', ' · ');
  }
  function freshnessHtml(assignmentCode, taskNumber, record) {
    if (isCurrentReview(record)) return '';
    const latest = sourceState(assignmentCode, taskNumber);
    // A temporary source-read failure does not invalidate an already returned review.
    if (record && latest.state === 'source_unavailable') return '';
    const messages = {
      current:'Đã có bài chữa cho lần nộp mới nhất. Em đang xem bài chữa được mở trước đó.',
      pending:'Lần nộp mới nhất của Đề ' + taskNumber + ' chưa có bài chữa theo tiêu chí hiện hành.',
      empty_submission:'Lần gửi mới nhất để trống Đề ' + taskNumber + '. Chưa có bài viết mới để chấm.',
      ambiguous_source:'Có các bài Đề ' + taskNumber + ' khác nội dung cùng thời điểm nộp. Cần đối chiếu nguồn trước khi chấm.',
      source_error:'Thông tin tên hoặc thời điểm nộp Đề ' + taskNumber + ' cần được đối chiếu trước khi chấm.',
      not_submitted:'Chưa tìm thấy bài nộp Đề ' + taskNumber + ' trong nguồn chấm hiện tại.',
      source_unavailable:refreshing ? 'Đang kiểm tra lần nộp mới nhất của Đề ' + taskNumber + '…' : 'Chưa xác minh được lần nộp mới nhất của Đề ' + taskNumber + '.'
    };
    const message = messages[latest.state] || messages.source_unavailable;
    return '<p class="wr-status" role="status">' + escape(message) + (latest.submittedAt ? ' <span>Lần gửi: ' + escape(submissionDate(latest.submittedAt)) + '.</span>' : '') +
      (record ? ' Bài chữa bên dưới được lưu từ lần chấm trước.' : '') + '</p>';
  }
  function card(record, assignment, task) {
    const label = assignment.weekCode + ' · ' + (task.displayLabel || 'Đề ' + task.taskNumber);
    const head = '<h5>' + escape(label) + '</h5>' + (task.title ? '<p class="wr-task-title">' + escape(task.title) + '</p>' : '');
    if (!record) return '<article class="wr-summary wr-pending" data-wr-task="' + task.taskNumber + '">' + head +
      freshnessHtml(assignment.assignmentCode, task.taskNumber, null) + '</article>';
    return '<article class="wr-summary" data-wr-task="' + task.taskNumber + '"><span class="wr-kicker">' + (isCurrentReview(record) ? 'Bài chữa của Cô · Đã trả' : 'Bài chữa lần nộp trước') + '</span>' + head +
      freshnessHtml(assignment.assignmentCode, task.taskNumber, record) +
      '<span class="wr-verdict">' + escape(record.learningVerdict) + '</span>' + (record.submissionStatus === 'wrong_task' ? '<p class="wr-wrong-task">Bài nộp chưa đúng đề</p>' : '') + overallHtml(record) +
      '<p class="wr-submitted">Bài em nộp: ' + escape(submissionDate(record.submittedAt || record.source && record.source.submittedAt)) + ' · ' + escape(record.originalWordCount) + ' từ</p>' +
      '<button class="wr-button" type="button" data-wr-open="' + escape(record.resultId) + '" aria-label="Xem bài chữa ' + escape(label) + '">Xem bài chữa</button></article>';
  }
  function loadStatus() {
    if (status === 'error') return '<div class="wr-status" role="status">Chưa tải được bài chữa.<button class="wr-button secondary" type="button" data-wr-retry>Thử lại</button></div>';
    return '<p class="wr-status" role="status">Đang tải bài chữa của em…</p>';
  }
  function assignmentHtml(item) {
    if (!current()) return '';
    const assignment = ieltsWritingAssignments_.forItem(item); if (!assignment) return '';
    return groupHtml(assignment);
  }
  function hasAssignmentResults(assignment) {
    return reviews.some(record => code(record.assignmentCode) === assignment.assignmentCode) ||
      notebookStates.some(record => code(record.assignmentCode) === assignment.assignmentCode) || Boolean(writingPolicy(assignment.assignmentCode));
  }
  function submissionSummary(assignment) {
    if (!current() || status !== 'ready' || refreshing || !assignment.tasks.length || writingBlockedByPolicy(assignment.assignmentCode)) return '';
    const latest = assignment.tasks.map(task => ({...sourceState(assignment.assignmentCode, task.taskNumber),taskNumber:task.taskNumber}));
    if (!latest.every(item => ['current','pending','empty_submission','not_submitted'].includes(item.state))) return '';
    const submitted = latest.filter(item => ['current','pending'].includes(item.state));
    const missing = latest.filter(item => !['current','pending'].includes(item.state));
    let summary = submitted.length ? 'Đã nộp ' + submitted.length + '/' + latest.length + ' bài viết' : 'Chưa nộp bài viết';
    if (submitted.length && missing.length) summary += ' · Chưa nộp: ' + missing.map(item => 'Đề ' + item.taskNumber + (item.state === 'empty_submission' ? ' (để trống)' : '')).join(', ');
    else if (!submitted.length && missing.some(item => item.state === 'empty_submission')) summary += ' · Để trống: ' + missing.filter(item => item.state === 'empty_submission').map(item => 'Đề ' + item.taskNumber).join(', ');
    const times = submitted.map(item => Date.parse(item.submittedAt)).filter(Number.isFinite);
    if (times.length) summary += ' · ' + submissionDate(new Date(Math.max(...times)).toISOString());
    return summary;
  }
  function homeworkStatusHtml(item, legacyHtml) {
    // Establish the identity before the hybrid fragment starts loading. A later
    // first refresh must not clear the just-created private result cache.
    if (!current()) return legacyHtml;
    const assignment = ieltsWritingAssignments_.forItem(item);
    const hybrid = ieltsHybridReviews_.fragment(item,legacyHtml,assignment && (writingBlockedByPolicy(assignment.assignmentCode) || writingBlockedByNotebook(assignment)));
    if (hybrid !== null) return hybrid;
    if (!assignment) return legacyHtml;
    if (assignment.reviewDriven && !hasLoaded && status !== 'error') {
      const waiting = document.createElement('template'); waiting.innerHTML = legacyHtml || '';
      waiting.content.querySelectorAll('.ielts-feedback-message,.ielts-feedback-empty').forEach(node => node.remove());
      return waiting.innerHTML + '<section class="wr-assignment" aria-busy="true">' + loadStatus() + '</section>';
    }
    const summary = submissionSummary(assignment);
    const feedbackActive = !assignment.reviewDriven || hasAssignmentResults(assignment);
    if (!feedbackActive && !summary) return legacyHtml;
    // Replace feedback prose in this display fragment only. Submission badges,
    // attempts, timestamps, missing/late alerts and source links stay intact.
    const retained = document.createElement('template');
    retained.innerHTML = legacyHtml || '';
    if (feedbackActive) {
      retained.content.querySelectorAll('.ielts-feedback-message,.ielts-feedback-empty').forEach(node => node.remove());
      retained.content.querySelectorAll('p > strong').forEach(node => {
        if (node.textContent.trim().replace(/:$/, '') === 'Nhận xét bài tập về nhà') node.textContent = 'Tình trạng nộp bài:';
      });
    }
    // A complete fresh read can replace the legacy source warning without
    // changing deadline, missing/late badges, attempts or receipt metadata.
    if (summary) retained.content.querySelectorAll('p.direct-source-status').forEach(node => {
      const receipt = document.createElement('p');
      receipt.className = 'wr-submitted wr-receipt-summary'; receipt.textContent = summary;
      node.replaceWith(receipt);
    });
    return retained.innerHTML + (feedbackActive ? assignmentHtml(item) : '');
  }
  function groupHtml(assignment) {
    if (assignment.reviewDriven && !hasAssignmentResults(assignment)) return '';
    const policy = writingPolicy(assignment.assignmentCode), policyBlocked = writingBlockedByPolicy(assignment.assignmentCode);
    const results = assignment.tasks.map(task => reviews.find(record => code(record.assignmentCode) === assignment.assignmentCode && Number(record.taskNumber) === task.taskNumber));
    const count = results.filter(isCurrentReview).length;
    const essayBlocked = writingBlockedByNotebook(assignment);
    const finalNotebookFailure = notebookStates.some(item => code(item.assignmentCode) === assignment.assignmentCode && item.essayGradingLocked === true);
    const subtitle = policyBlocked ? '' : essayBlocked ? (finalNotebookFailure ? ' · Vở chưa đạt yêu cầu' : ' · Chờ xác minh vở') :
      assignment.tasks.length && status === 'ready' ? ' · Đã trả ' + count + '/' + assignment.tasks.length + ' bài chữa' + (policy?.state === 'grading_closed' ? '' : ' cho lần nộp mới nhất') : '';
    const title = policyBlocked ? 'Tình trạng nộp bài' : 'Nhận xét bài tập về nhà';
    return '<section class="wr-assignment" data-wr-assignment="' + escape(assignment.assignmentCode) + '" aria-label="' + title + ' · Writing ' + escape(assignment.weekCode) + '">' +
      '<header class="wr-feedback-head"><h4>' + title + '</h4><p>Writing ' + escape(assignment.weekCode) + subtitle + '</p></header>' +
      (policyBlocked ? writingPolicyHtml(policy) : status === 'ready' ? notebookHtml(assignment) + (assignment.tasks.length && !essayBlocked ? '<div class="wr-exercises">' + assignment.tasks.map((task,index) => card(results[index], assignment, task)).join('') + '</div>' : '') : loadStatus()) + '</section>';
  }
  function writingPolicyHtml(item) {
    if (item.state === 'policy_unavailable') return '<section class="wr-policy wr-policy-unavailable" role="status"><p>Hiện chưa thể hiển thị bài chữa. Vui lòng thử lại sau.</p></section>';
    const urls = [...new Set(array(item.files).map(file => ieltsWritingAssignments_.safeUrl(file && file.url)).filter(Boolean))];
    const links = urls.map((url,index) => '<a class="wr-button secondary" href="' + escape(url) + '" target="_blank" rel="noopener noreferrer">Mở vở đã nộp' + (urls.length > 1 ? ' ' + (index + 1) : '') + '</a>').join('');
    const received = typeof item.submittedAt === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(item.submittedAt) && Number.isFinite(Date.parse(item.submittedAt))
      ? '<p class="wr-submitted">Đã nhận bài: <time datetime="' + escape(item.submittedAt) + '">' + escape(submissionDate(item.submittedAt)) + '</time></p>' : '';
    return '<section class="wr-policy wr-policy-too-late" role="alert"><h5>NỘP QUÁ MUỘN — KHÔNG ĐƯỢC CHẤM CHỮA CHI TIẾT</h5>' + received + (links ? '<div class="wr-policy-files">' + links + '</div>' : '') + '</section>';
  }
  function writingBlockedByNotebook(assignment) {
    const item = notebookStates.find(entry => code(entry.assignmentCode) === assignment.assignmentCode);
    return Boolean(item && item.homeworkMode === 'notebook_and_writing' &&
      (item.essayGradingLocked === true || (!refreshing && item.current && !['notebook_complete', 'teacher_grading_exception'].includes(item.state))));
  }
  function notebookHtml(assignment) {
    const item = notebookStates.find(entry => code(entry.assignmentCode) === assignment.assignmentCode);
    if (!item) return assignment.notebook ? '<section class="wr-notebook wr-notebook-pending"><h5>Vở chép · Nhận xét của Cô</h5><p>Chưa có kết quả kiểm tra vở.' + (assignment.tasks.length ? ' Bài viết mới chỉ được chấm sau khi vở đạt yêu cầu.' : ' Kết quả sẽ hiện sau khi vở được đối chiếu với tài liệu Cô giao.') + '</p></section>' : '';
    const hasWriting = item.homeworkMode === 'notebook_and_writing';
    const current = item.current;
    const notebookFinal = !hasWriting && item.state === 'notebook_verdict_final' && Boolean(item.overall);
    const teacherException = current && item.state === 'teacher_grading_exception' && item.essayGradingLocked === false;
    const failed = notebookFinal || teacherException || current && item.state === 'awaiting_notebook_completion' && (array(item.issues).length || item.overall);
    const complete = current && item.state === 'notebook_complete';
    const finalLock = item.essayGradingLocked === true;
    const writingBlocked = hasWriting && (finalLock || (current && failed && !teacherException));
    const blockedNotebookUrls = array(item.notebookUrls).map(value => ieltsWritingAssignments_.safeUrl(typeof value === 'string' ? value : value && value.url)).filter(Boolean);
    const blockedNotebookLinks = blockedNotebookUrls.map((url, index) => '<a class="wr-button secondary" href="' + escape(url) + '" target="_blank" rel="noopener noreferrer">Mở vở đã nộp' + (blockedNotebookUrls.length > 1 ? ' ' + (index + 1) : '') + '</a>').join('');
    const blockedHtml = () => '<section class="wr-notebook wr-notebook-quick wr-notebook-blocked" aria-label="Kiểm tra vở" role="alert"><span class="wr-kicker">Vở chép · Nhận xét của Cô</span><h5>KHÔNG ĐƯỢC CHẤM BÀI VIẾT</h5><div class="wr-notebook-alert"><strong>Vở chưa đạt yêu cầu nên bài viết không được chấm chữa chi tiết.</strong></div><div class="wr-notebook-reason"><strong>Lý do vở chưa đạt:</strong>' + prose(item.overall || item.reason || 'Vở chưa đáp ứng yêu cầu của bài được giao.') + '</div>' +
      (item.submittedAt ? '<p class="wr-submitted">Đã nhận vở: ' + escape(submissionDate(item.submittedAt)) + '</p>' : '') + blockedNotebookLinks + '</section>';
    // Receipt evidence is separate from a current check. Access failures and
    // refreshes must never turn an unknown receipt into a missing notebook.
    const receiptTitle = item.receiptStatus === 'submitted' ? 'Đã nộp vở' : item.receiptStatus === 'not_submitted' ? 'Chưa nộp vở' : '';
    const title = !current ? (receiptTitle || (item.historical ? 'Nhận xét vở lần kiểm tra trước' : 'Chờ xác minh vở hiện tại')) :
      failed ? (teacherException || item.homeworkMode === 'notebook_only' ? 'VỞ CHƯA ĐẠT YÊU CẦU' : 'KHÔNG ĐƯỢC CHẤM BÀI') :
      complete ? 'VỞ ĐÃ ĐẠT YÊU CẦU' : item.displayTitle || 'Chờ kiểm tra vở';
    const latestNote = !notebookFinal && !current && (!receiptTitle || item.overall) ? '<p class="wr-notebook-freshness">' + (refreshing ? 'Đang đối chiếu lần nộp mới nhất…' : 'Kết quả bên dưới chưa xác nhận tình trạng vở hiện tại.' + (hasWriting ? ' Bài viết mới tiếp tục chờ kiểm tra vở.' : ' Cần đối chiếu vở mới nhất với tài liệu Cô giao.')) + '</p>' +
      (!refreshing && item.overall && item.reason ? '<p class="wr-notebook-current-reason"><strong>Lần nộp hiện tại: </strong>' + escape(item.reason) + '</p>' : '') : '';
    if (item.reviewMode === 'quick_check' || complete) {
      const notebookLinks = array(item.notebookUrls).map((value, index) => {
        const url = ieltsWritingAssignments_.safeUrl(typeof value === 'string' ? value : value && value.url);
        return url ? '<a class="wr-button secondary" href="' + escape(url) + '" target="_blank" rel="noopener noreferrer">Mở vở đã nộp' + (item.notebookUrls.length > 1 ? ' ' + (index + 1) : '') + '</a>' : '';
      }).join('');
      const latestSubmission = item.historical && item.submittedAt && item.submittedAt !== item.reviewSubmittedAt
        ? '<p class="wr-submitted">Lần nộp mới nhất: ' + escape(submissionDate(item.submittedAt)) + '</p>' : '';
      const quickTitle = notebookFinal || teacherException || (failed && item.homeworkMode === 'notebook_only') ? 'VỞ CHƯA ĐẠT YÊU CẦU' : complete ? 'VỞ ĐÃ ĐẠT YÊU CẦU' : receiptTitle || (!current ? title : failed ? 'Vở đã nộp' : item.displayTitle || 'Kiểm tra vở');
      if (writingBlocked) return blockedHtml();
      return '<section class="wr-notebook wr-notebook-quick ' + (failed ? 'wr-notebook-blocked' : complete ? 'wr-notebook-complete' : 'wr-notebook-pending') + '" aria-label="Kiểm tra vở"><h5>' + escape(quickTitle) + '</h5>' + latestNote +
        (item.overall ? '<div class="wr-copy">' + prose(item.overall) + '</div>' : '<p>' + escape(item.reason || 'Đang chờ kết quả kiểm tra vở.') + '</p>') +
        (item.submittedAt && !latestSubmission ? '<p class="wr-submitted">Đã nhận vở: ' + escape(submissionDate(item.submittedAt)) + '</p>' : '') + latestSubmission +
        (notebookLinks ? '<details class="wr-notebook-details"><summary>' + (item.publicationFinal ? 'Xem vở đã được kiểm tra' : 'Xem vở lần nộp mới nhất') + '</summary>' + notebookLinks + '</details>' : '') + '</section>';
    }
    if (writingBlocked) return blockedHtml();
    const issues = array(item.issues).map(issue => {
      const pages = [...new Set(array(issue.notebookPages).map(p => Number(p.page)).filter(n => Number.isInteger(n) && n > 0))];
      return '<article class="wr-notebook-issue"><h6>' + escape(issue.section || 'Phần cần bổ sung') + (pages.length ? ' · Vở trang ' + escape(pages.join(', ')) : '') + '</h6>' + prose(issue.evidence) + (issue.action ? '<p class="wr-notebook-action">' + inline(issue.action) + '</p>' : '') + '</article>';
    }).join('');
    const handwriting = array(item.handwriting && item.handwriting.evidence).map(text => '<li>' + inline(text) + '</li>').join('');
    const sources = array(item.sourceUrls).map((value, index) => {
      const url = ieltsWritingAssignments_.safeUrl(typeof value === 'string' ? value : value && value.url);
      return url ? '<a class="wr-button secondary" href="' + escape(url) + '" target="_blank" rel="noopener noreferrer">Tài liệu Cô giao' + (item.sourceUrls.length > 1 ? ' ' + (index + 1) : '') + '</a>' : '';
    }).join('');
    return '<section class="wr-notebook ' + (failed ? 'wr-notebook-blocked' : complete ? 'wr-notebook-complete' : 'wr-notebook-pending') + '" aria-label="Kiểm tra vở"><span class="wr-kicker">Vở chép · Nhận xét của Cô</span><h5>' + escape(title) + '</h5>' + latestNote +
      (item.overall ? '<div class="wr-copy">' + prose(item.overall) + '</div>' : '<p>' + escape(item.reason || 'Vở đang chờ kiểm tra theo tài liệu được giao.') + '</p>') +
      (array(item.nextSteps).length ? '<div class="wr-notebook-steps"><strong>Việc em cần làm</strong><ul>' + item.nextSteps.map(text => '<li>' + inline(text) + '</li>').join('') + '</ul></div>' : '') +
      (issues || handwriting ? '<details class="wr-notebook-details"><summary>Xem phần cần sửa và nhận xét chữ viết</summary>' + issues + (handwriting ? '<h6>Chữ viết và bản chụp</h6><ul>' + handwriting + '</ul>' : '') + '</details>' : '') +
      '<p class="wr-submitted">' + (item.historical && item.reviewSubmittedAt ? 'Vở của nhận xét này: ' + escape(submissionDate(item.reviewSubmittedAt)) : item.submittedAt ? 'Vở nộp: ' + escape(submissionDate(item.submittedAt)) : '') + (item.checkedAt ? ' · Kiểm tra: ' + escape(submissionDate(item.checkedAt)) : '') + '</p>' +
      (item.historical && item.submittedAt && item.submittedAt !== item.reviewSubmittedAt ? '<p class="wr-submitted">Lần nộp mới nhất: ' + escape(submissionDate(item.submittedAt)) + '</p>' : '') + sources + '</section>';
  }
  function overviewHtml() {
    if (!current()) return '';
    const assignments = ieltsWritingAssignments_.all().filter(assignment => hasAssignmentResults(assignment) ||
      array(state.dashboard && state.dashboard.assignments).some(item => ieltsWritingAssignments_.forItem(item)?.assignmentCode === assignment.assignmentCode));
    const content = assignments.length ? '<div class="wr-result-list">' + assignments.map(groupHtml).join('') + '</div>' : status !== 'ready' ? loadStatus() : '<p class="wr-status">Nhận xét sẽ hiện tại đây sau khi bài tập của em được kiểm tra.</p>';
    return '<section class="wr-personal"><header class="fighter-section-head"><span>BÀI LUYỆN TẬP TẠI NHÀ</span><h3>Writing · Bài chữa của Cô</h3><p>Xem nhận xét, chú thích trên bài gốc và bản sửa gợi ý.</p></header>' + content + '</section>';
  }
  function originalHtml(record) {
    const source = record.originalEssay, notes = array(record.annotations), anchors = [];
    notes.forEach((note, index) => array(note.anchors).forEach(anchor => {
      if (Number.isInteger(anchor.start) && Number.isInteger(anchor.end) && anchor.start >= 0 && anchor.end > anchor.start && anchor.end <= source.length && source.slice(anchor.start, anchor.end) === anchor.quote) anchors.push({start:anchor.start,end:anchor.end,index});
    }));
    const cuts = [...new Set([0,source.length,...anchors.flatMap(a => [a.start,a.end])])].sort((a,b) => a-b);
    return cuts.slice(0,-1).map((start,index) => {
      const end = cuts[index+1], active = anchors.filter(a => a.start <= start && a.end >= end).map(a => a.index);
      const text = escape(source.slice(start,end));
      if (!active.length) return text;
      const ids = [...new Set(active)], serious = ids.some(i => notes[i].severity === 'serious');
      return '<button type="button" class="wr-mark' + (serious ? ' is-serious' : '') + '" data-wr-notes="' + ids.join(',') + '" aria-label="Xem chú thích ' + escape(ids.map(i => notes[i].label || String(i + 1)).join(', ')) + '">' + text + '</button>';
    }).join('');
  }
  function notesHtml(record) {
    return array(record.annotations).map((note,index) => '<article class="wr-note' + (note.severity === 'serious' ? ' is-serious' : '') + '" id="wr-note-' + index + '" tabindex="-1"><h5>' + escape(note.label || 'Chú thích ' + (index + 1)) + (note.title ? ' · ' + inline(note.title) : '') + '</h5><div class="wr-copy">' + prose(note.bodyMarkdown) + '</div>' + (array(note.anchors).length ? '<button class="wr-note-jump" type="button" data-wr-back="' + index + '">Về đoạn được chú thích</button>' : '') + '</article>').join('');
  }
  function revisionHtml(record) {
    const paragraphs = array(record.suggestedRevisionParagraphs).map(p => String(p ?? ''));
    const plain = () => paragraphs.map(p => '<p>' + escape(p) + '</p>').join('');
    if (record.revisionKind === 'scaffold' || record.submissionStatus === 'wrong_task') return {
      essay:plain(), legend:'Đây là khung hướng dẫn viết lại đúng đề, chưa phải bản sửa từ bài em đã nộp.'
    };
    const source = record.originalEssay, revised = paragraphs.join('\n\n');
    // Compare exact words and punctuation, ignoring whitespace for matching only.
    // Offset slices always render the saved revision verbatim; no grading text is edited.
    const tokens = text => Array.from(text.matchAll(/[\p{L}\p{M}\p{N}]+(?:['’][\p{L}\p{M}\p{N}]+)*|[^\s]/gu), match => ({text:match[0],start:match.index,end:match.index+match[0].length}));
    const unavailable = {essay:plain(),legend:'Bản sửa được giữ nguyên. Bài quá dài để tô thay đổi chi tiết; em đối chiếu với tab Bài viết gốc - kèm chú thích.'};
    if (source.length + revised.length > 200000) return unavailable;
    const before = tokens(source), after = tokens(revised);
    if (before.length + after.length > 12000) return unavailable;
    let prefix = 0, endBefore = before.length, endAfter = after.length;
    while (prefix < endBefore && prefix < endAfter && before[prefix].text === after[prefix].text) prefix++;
    while (endBefore > prefix && endAfter > prefix && before[endBefore-1].text === after[endAfter-1].text) { endBefore--; endAfter--; }
    const rows = endBefore-prefix, cols = endAfter-prefix;
    // At most ~4 MB and one million comparisons, including malformed long input.
    if ((rows+1)*(cols+1) > 1000000) return unavailable;
    const table = new Uint32Array((rows+1)*(cols+1)), stride = cols+1;
    for (let i=rows-1;i>=0;i--) for (let j=cols-1;j>=0;j--) table[i*stride+j] = before[prefix+i].text === after[prefix+j].text
      ? table[(i+1)*stride+j+1]+1 : Math.max(table[(i+1)*stride+j],table[i*stride+j+1]);
    const changed = new Set(); let i=0,j=0,deleted=0;
    while (i<rows || j<cols) {
      if (i<rows && j<cols && before[prefix+i].text === after[prefix+j].text) {i++;j++;}
      else if (i<rows && (j===cols || table[(i+1)*stride+j] >= table[i*stride+j+1])) {i++;deleted++;}
      else {changed.add(prefix+j);j++;}
    }
    const intervals = [];
    after.forEach((token,index) => {
      if (!changed.has(index)) return;
      const previous = intervals[intervals.length-1];
      if (previous && changed.has(index-1)) previous.end=token.end;
      else intervals.push({start:token.start,end:token.end});
    });
    let offset=0;
    const essay = paragraphs.map(paragraph => {
      const start=offset,end=start+paragraph.length; offset=end+2;
      let cursor=start,html='';
      intervals.forEach(interval => {
        const from=Math.max(start,interval.start),to=Math.min(end,interval.end);
        if (from>=to) return;
        html+=escape(revised.slice(cursor,from))+'<mark class="wr-revision-change">'+escape(revised.slice(from,to))+'</mark>';cursor=to;
      });
      return '<p>'+html+escape(revised.slice(cursor,end))+'</p>';
    }).join('');
    const legend = intervals.length ? 'Phần tô xanh và gạch chân là chỗ Cô đã sửa hoặc bổ sung so với bài em nộp.'
      : deleted ? 'Bản sửa có lược bỏ từ hoặc dấu câu; những từ và dấu câu còn lại được giữ nguyên.'
      : 'Bản sửa giữ nguyên các từ và dấu câu của bài em nộp.';
    return {essay,legend:legend+(deleted ? ' Phần đã lược bỏ không xuất hiện trong bản sửa; em đối chiếu ở tab Bài viết gốc - kèm chú thích.' : '')};
  }
  function cachedRevisionHtml(record) {
    const cached = revisionCache.get(record.resultId);
    if (cached) return cached;
    const revision = revisionHtml(record);
    revisionCache.set(record.resultId, revision);
    return revision;
  }
  function warmReviewButton(target) {
    const button = target?.closest?.('[data-wr-open]');
    if (!button) return;
    const record = reviews.find(review => review.resultId === button.dataset.wrOpen);
    if (!record || revisionCache.has(record.resultId)) return;
    const warm = () => {
      if (current() && reviews.includes(record) && !revisionCache.has(record.resultId)) cachedRevisionHtml(record);
    };
    if ('requestIdleCallback' in window) window.requestIdleCallback(warm, {timeout:350});
    else setTimeout(warm, 0);
  }
  function observeReviewButtons() {
    clearTimeout(reviewWarmTimer);
    reviewWarmTimer = setTimeout(() => {
      const buttons = document.querySelectorAll('[data-wr-open]');
      if (!buttons.length) return;
      if (!('IntersectionObserver' in window)) { warmReviewButton(buttons[0]); return; }
      if (!reviewWarmObserver) reviewWarmObserver = new IntersectionObserver(items => items.forEach(item => {
        if (!item.isIntersecting) return;
        reviewWarmObserver?.unobserve(item.target);
        warmReviewButton(item.target);
      }), {rootMargin:'700px 0px'});
      buttons.forEach(button => {
        if (button.dataset.wrWarmObserved === '1') return;
        button.dataset.wrWarmObserved = '1'; reviewWarmObserver.observe(button);
      });
    }, 0);
  }
  function promptHtml(assignment, task) {
    const label = task.displayLabel || 'Đề ' + task.taskNumber;
    return '<section class="wr-section wr-prompt"><h3>Đề bài gốc · ' + escape(label) + '</h3>' +
      (task.title ? '<h4>' + escape(task.title) + '</h4>' : '') +
      (task.promptText ? '<div class="wr-prompt-text" lang="en">' + escape(task.promptText) + '</div>' : '<p class="wr-status">Đề gốc đang được cập nhật.</p>') +
      (task.imageUrl ? '<figure><img class="wr-prompt-image" src="' + escape(task.imageUrl) + '" alt="Biểu đồ gốc · ' + escape(assignment.weekCode + ' · ' + label + (task.title ? ': ' + task.title : '')) + '" loading="lazy" decoding="async" referrerpolicy="no-referrer"></figure>' : '') +
      (task.sourceUrl ? '<a class="wr-source-link" href="' + escape(task.sourceUrl) + '" target="_blank" rel="noopener noreferrer">Mở đề gốc trong bài học</a>' : '') + '</section>';
  }
  function task2CriteriaHtml(record) {
    return '<section class="wr-section wr-task2-criteria"><h3>Yêu cầu bài luyện Task 2</h3><div class="wr-task2-grid">' + array(record.task2.criteria).map(item =>
      '<article><h4>' + inline(item.title) + '</h4><span class="wr-verdict">' + escape(item.status) + '</span><div class="wr-copy">' + prose(item.comment) +
      (item.action ? '<p><strong>Cách sửa:</strong> ' + inline(item.action) + '</p>' : '') +
      (array(item.evidence).length ? '<details><summary>Xem câu trong bài em</summary>' + item.evidence.map(quote => '<blockquote lang="en">' + escape(quote) + '</blockquote>').join('') + '</details>' : '') + '</div></article>').join('') + '</div></section>';
  }
  function task2OutlineHtml(record) {
    return '<section class="wr-section wr-task2-outline"><h3>Bám sát ý Cô đã cho</h3><details><summary>Xem đối chiếu các ý trong bài</summary><div class="wr-task2-grid">' + array(record.task2.outlineCoverage).map(item =>
      '<article><p class="wr-copy">' + inline(item.requiredText) + '</p><span class="wr-verdict">' + escape(item.status) + '</span><div class="wr-copy">' + prose(item.comment) +
      array(item.studentQuotes).map(quote => '<blockquote lang="en">' + escape(quote) + '</blockquote>').join('') + '</div></article>').join('') + '</div></details></section>';
  }
  function knowledgeHtml(record, knowledgeRows) {
    if(record.savedModelResult) return '';
    if (record.taskType === 2) return '<section class="wr-section"><h3>Kiến thức đã được ghi chép và giảng kỹ</h3><div class="wr-task2-grid">' + array(record.task2.appliedKnowledge).map(item =>
      '<article class="wr-copy">' + prose(item.explanation) + '<blockquote lang="en">' + escape(item.revisionEvidence) + '</blockquote></article>').join('') + '</div></section>';
    return '<section class="wr-section"><h3>Kiến thức đã được ghi chép và giảng kỹ</h3><div class="wr-knowledge"><table><thead><tr><th scope="col">Kỹ thuật</th><th scope="col">Mức vận dụng</th><th scope="col">Bằng chứng</th></tr></thead><tbody>' + knowledgeRows.map(row => '<tr><td>' + inline(row.technique) + '</td><td>' + inline(row.application) + '</td><td>' + inline(row.evidence) + '</td></tr>').join('') + '</tbody></table></div></section>';
  }
  function open(resultId, button) {
    if (!current()) return;
    const record = savedReviews.get(resultId) || reviews.find(review => review.resultId === resultId); if (!record || !validRecord(record)) return;
    const assignment = ieltsWritingAssignments_.all().find(entry => entry.assignmentCode === code(record.assignmentCode));
    const task = assignment && assignment.tasks.find(entry => entry.taskNumber === Number(record.taskNumber));
    if (!task || writingBlockedByPolicy(assignment.assignmentCode)) return;
    if (dialog) { close(); dialog.remove(); }
    selectedReview = record; opener = button; scrollBefore = document.body.style.overflow;
    dialog = document.createElement('dialog'); dialog.className = 'wr-dialog'; dialog.setAttribute('aria-labelledby','wr-title');
    dialog.dataset.wrAssignment = assignment.assignmentCode;
    const knowledgeRows = array(record.knowledge && record.knowledge.rows);
    const revisionLabel = record.revisionLabel || 'Bản sửa gợi ý';
    const revision = cachedRevisionHtml(record);
    dialog.innerHTML = '<header class="wr-head"><div><span class="wr-kicker">' + escape(record.className) + ' · ' + escape(assignment.weekCode) + ' · ' + escape(task.displayLabel || 'Đề ' + task.taskNumber) + '</span><h2 id="wr-title">Bài chữa của Cô</h2><p>' + escape(record.studentName) + '</p></div><button class="wr-close" type="button" aria-label="Đóng bài chữa" data-wr-close>×</button></header>' +
      '<div class="wr-body"><div class="wr-top"><span class="wr-verdict">' + escape(record.learningVerdict) + '</span>' + (record.submissionStatus === 'wrong_task' ? '<strong class="wr-wrong-task">Bài nộp chưa đúng đề</strong>' : '') + '<small>Bài gốc: ' + escape(record.originalWordCount) + ' từ</small><small data-wr-review-label>' + (isCurrentReview(record) ? 'Đã trả bài' : 'Bài chữa lần nộp trước') + '</small></div><div data-wr-freshness>' + freshnessHtml(record.assignmentCode, record.taskNumber, record) + '</div>' +
      promptHtml(assignment,task) +
      (record.taskType === 2 ? '<section class="wr-section"><h3>Nhận xét của Cô</h3>' + overallHtml(record) + '</section>' + task2CriteriaHtml(record) + task2OutlineHtml(record) : '<div class="wr-context"><section class="wr-section"><h3>Nhận xét của Cô</h3>' + overallHtml(record) + '</section><section class="wr-section"><h3>' + (record.savedModelResult ? 'Vận dụng kiến thức đã học' : 'Cách em chia dữ liệu') + '</h3><div class="wr-copy">' + prose(record.dataGrouping) + '</div></section></div>') +
      '<section class="wr-section wr-writing"><header class="wr-writing-head"><h3>Bài em đã nộp</h3><div class="wr-tabs" role="tablist" aria-label="Phiên bản bài viết"><button class="wr-tab" type="button" role="tab" id="wr-tab-original" aria-controls="wr-original" aria-selected="true" data-wr-tab="original">Bài viết gốc - kèm chú thích</button><button class="wr-tab" type="button" role="tab" id="wr-tab-revision" aria-controls="wr-revision" aria-selected="false" tabindex="-1" data-wr-tab="revision">' + escape(revisionLabel) + '</button></div></header>' +
      '<div class="wr-pane" id="wr-original" role="tabpanel" aria-labelledby="wr-tab-original"><div class="wr-original-grid"><div class="wr-essay-col"><p class="wr-essay-hint">Chọn phần được đánh dấu để đọc chú thích của Cô. Màu đỏ là lỗi cần sửa trước.</p><div class="wr-essay" lang="en">' + originalHtml(record) + '</div></div><aside class="wr-notes" aria-label="Chú thích của Cô"><h4>' + array(record.annotations).length + ' chú thích</h4>' + notesHtml(record) + '</aside></div></div>' +
      '<div class="wr-pane" id="wr-revision" role="tabpanel" aria-labelledby="wr-tab-revision" hidden><div class="wr-revision">' + (record.revisionKind === 'scaffold' ? '<p class="wr-scaffold-label">' + escape(revisionLabel) + '</p>' : '') + '<p class="wr-essay-hint">' + escape(record.suggestedRevisionWordCount) + ' từ · Đọc cách sửa và vận dụng kiến thức vào bài của em.</p><p class="wr-revision-legend" id="wr-revision-legend">' + escape(revision.legend) + '</p><div class="wr-essay" lang="en" aria-describedby="wr-revision-legend">' + revision.essay + '</div><div class="wr-applied"><h4>Kiến thức đã áp dụng</h4><ul class="wr-copy">' + array(record.appliedKnowledge).map(item => '<li>' + inline(item) + '</li>').join('') + '</ul></div></div></div></section>' +
      knowledgeHtml(record,knowledgeRows) +
      (array(record.nextSteps).length ? '<section class="wr-section"><h3>Việc em làm tiếp</h3><ol class="wr-next wr-copy">' + array(record.nextSteps).map(step => '<li>' + inline(step) + '</li>').join('') + '</ol></section>' : '') + '<div class="wr-scope">' + prose(record.scopeMarkdown) + '</div></div>';
    document.body.appendChild(dialog); dialog.showModal(); document.body.style.overflow = 'hidden';
    dialog.addEventListener('cancel', event => { event.preventDefault(); close(); });
    dialog.addEventListener('close', () => { document.body.style.overflow = scrollBefore; });
    dialog.addEventListener('click', event => { if (event.target === dialog) { const r=dialog.getBoundingClientRect(); if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom) close(); } });
    dialog.querySelector('[data-wr-close]').focus();
  }
  function activateTab(name, focus) {
    if (!dialog) return;
    dialog.querySelectorAll('[data-wr-tab]').forEach(tab => { const active=tab.dataset.wrTab===name; tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;if(active&&focus)tab.focus(); });
    dialog.querySelectorAll('.wr-pane').forEach(pane => { pane.hidden = pane.id !== 'wr-'+name; });
  }
  function selectNotes(indexes, returnToEssay) {
    if (!dialog || !selectedReview) return;
    const ids = indexes.filter(i => Number.isInteger(i) && i >= 0 && i < array(selectedReview.annotations).length);
    dialog.querySelectorAll('.wr-note').forEach((note,index) => note.classList.toggle('is-selected',ids.includes(index)));
    dialog.querySelectorAll('[data-wr-notes]').forEach(mark => mark.classList.toggle('is-selected',mark.dataset.wrNotes.split(',').some(i => ids.includes(Number(i)))));
    const target=returnToEssay ? [...dialog.querySelectorAll('[data-wr-notes]')].find(mark => mark.dataset.wrNotes.split(',').some(i => ids.includes(Number(i)))) : dialog.querySelector('#wr-note-'+ids[0]);
    if(target){target.scrollIntoView({block:'nearest',behavior:'smooth'});target.focus({preventScroll:true});}
  }
  document.addEventListener('pointerover', event => warmReviewButton(event.target), true);
  document.addEventListener('focusin', event => warmReviewButton(event.target), true);
  document.addEventListener('touchstart', event => warmReviewButton(event.target), {capture:true,passive:true});
  document.addEventListener('click', event => {
    const button=event.target.closest('button'); if(!button)return;
    if(button.hasAttribute('data-wr-open'))open(button.dataset.wrOpen,button);
    else if(button.hasAttribute('data-wr-retry')){status='idle';refresh(true);repaint();}
    else if(button.hasAttribute('data-wr-close'))close();
    else if(button.hasAttribute('data-wr-tab'))activateTab(button.dataset.wrTab,false);
    else if(button.hasAttribute('data-wr-notes'))selectNotes(button.dataset.wrNotes.split(',').map(Number),false);
    else if(button.hasAttribute('data-wr-back'))selectNotes([Number(button.dataset.wrBack)],true);
  });
  document.addEventListener('keydown', event => {
    if(!dialog||!dialog.open||!event.target.matches('[data-wr-tab]')||!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();activateTab(event.key==='Home'?'original':event.key==='End'?'revision':event.target.dataset.wrTab==='original'?'revision':'original',true);
  });
  window.addEventListener('hashchange',clear);window.addEventListener('pagehide',clear);
  const baseLock=ieltsParentLock_;
  ieltsParentLock_=function(){clear();return baseLock.apply(this,arguments);};
  const baseRender=parentRender_;
  parentRender_=function(){const result=baseRender.apply(this,arguments);if(who())refresh();observeReviewButtons();return result;};
  const baseResume=parentQuietResume_;
  parentQuietResume_=async function(){const result=await baseResume.apply(this,arguments);if(who())refresh(true);return result;};
  window.setInterval(() => {
    // The first read can fail too; refresh() throttles retries until it succeeds.
    if (document.visibilityState === 'hidden' || !current() || inFlight) return;
    refresh();
  }, 30000);
  const baseOverview=renderOverview;
  renderOverview=function(){const result=baseOverview.apply(this,arguments);const host=document.getElementById('panel-overview');if(host&&state.student&&who())host.insertAdjacentHTML('beforeend',overviewHtml());return result;};
  function savedResultCard(record) {
    if(!current() || !validRecord(record) || writingBlockedByPolicy(record.assignmentCode)) return '';
    const assignment=ieltsWritingAssignments_.all().find(a=>a.assignmentCode===code(record.assignmentCode));
    const task=assignment?.tasks.find(t=>t.taskNumber===Number(record.taskNumber));
    if(!task) return '';
    const existing=savedReviews.get(record.resultId);
    if(existing && JSON.stringify(existing)===JSON.stringify(record)) record=existing;
    savedReviews.set(record.resultId,record);
    return card(record,assignment,task);
  }
  return {assignmentHtml,homeworkStatusHtml,refresh,clear,savedResultCard};
})();
/* IELTS_WRITING_FEEDBACK_END_V1 */
