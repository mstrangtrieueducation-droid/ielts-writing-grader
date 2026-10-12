/* IELTS_WRITING_ASSIGNMENT_HELPERS_V1: shared, public assignment metadata only. */
const ieltsWritingAssignments_ = (() => {
  'use strict';
  const array = value => Array.isArray(value) ? value : [];
  function code(value) {
    const text = String(value || '').normalize('NFC').trim().toUpperCase().replace(/[^A-Z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    const match = text.match(/^(?:IELTS-)?WRITING-W0*(\d{1,3})(?:-.*)?$/);
    return match ? 'IELTS-WRITING-W' + String(Number(match[1])).padStart(2, '0') : '';
  }
  function safeUrl(value) {
    try {
      if (!String(value || '').trim()) return '';
      const url = new URL(String(value), document.baseURI);
      return url.protocol === 'https:' && !url.username && !url.password ? url.href : '';
    } catch (_) { return ''; }
  }
  function lessonKey(value) {
    const safe = safeUrl(value); if (!safe) return '';
    let url = new URL(safe);
    // The classroom viewer carries a lesson URL plus private prefill hints.
    // Match only the lesson; never treat the shared viewer path as one lesson.
    if (url.origin === 'https://mstrangtrieueducation-droid.github.io' && /^\/student-learning(?:\/|$)/.test(url.pathname)) {
      const lessons = url.searchParams.getAll('lesson');
      if (!/^\/student-learning(?:\/index\.html|\/)?$/.test(url.pathname) || lessons.length !== 1) return '';
      const nested = safeUrl(lessons[0]); if (!nested) return '';
      url = new URL(nested);
      if (url.origin === 'https://mstrangtrieueducation-droid.github.io' && /^\/student-learning(?:\/|$)/.test(url.pathname)) return '';
    }
    return url.origin + url.pathname.replace(/\/+$/, '');
  }
  function currentClass() {
    return String(typeof ieltsParentAccess !== 'undefined' ? ieltsParentAccess.className : typeof state !== 'undefined' && state.dashboard ? state.dashboard.className : '').trim();
  }
  function all(className = currentClass()) {
    const manifest = window.IELTS_WRITING_ASSIGNMENTS;
    const entries = Array.isArray(manifest) ? manifest : array(manifest && manifest.assignments);
    const groups = new Map();
    entries.forEach(entry => {
      if (!entry || entry.enabled === false || entry.autoGrade === false) return;
      if (!array(entry.classNames).includes(className)) return;
      const assignmentCode = code(entry.assignmentCode);
      const week = Number(assignmentCode.match(/W(\d+)$/)?.[1]);
      const notebook = entry.notebook === true;
      const enabledFromWeek = Number(entry.enabledFromWeek || (notebook ? 5 : 9));
      if (!assignmentCode || !Number.isFinite(enabledFromWeek) || week < Math.max(notebook ? 5 : 9, enabledFromWeek)) return;
      if (notebook && !groups.has(assignmentCode)) {
        groups.set(assignmentCode, {assignmentCode, weekCode:'W' + String(week).padStart(2, '0'), notebook:true,
          lessonUrls:[entry.lessonUrl,...array(entry.lessonAliases)].map(lessonKey).filter(Boolean),
          sessionNumbers:array(entry.sessionNumbers).map(Number).filter(Number.isFinite), reviewDriven:entry.reviewDriven===true, tasks:[]});
      }
      if (notebook) groups.get(assignmentCode).notebook = true;
      const tasks = Array.isArray(entry.tasks) ? entry.tasks : [entry];
      tasks.forEach(task => {
        if (!task || task.enabled === false || task.autoGrade === false) return;
        const taskNumber = Number(task.taskNumber);
        if (!Number.isInteger(taskNumber) || taskNumber < 1 || taskNumber > 50) return;
        let group = groups.get(assignmentCode);
        if (!group) {
          group = {assignmentCode, weekCode:'W' + String(week).padStart(2, '0'), notebook:false, reviewDriven:entry.reviewDriven===true,
            lessonUrls:[], sessionNumbers:array(entry.sessionNumbers).map(Number).filter(Number.isFinite), tasks:[]};
          groups.set(assignmentCode, group);
        }
        [entry.lessonUrl, ...array(entry.lessonAliases), task.lessonUrl, ...array(task.lessonAliases)].map(lessonKey).filter(Boolean).forEach(url => {
          if (!group.lessonUrls.includes(url)) group.lessonUrls.push(url);
        });
        if (group.tasks.some(existing => existing.taskNumber === taskNumber)) return;
        group.tasks.push({taskNumber, displayLabel:String(task.displayLabel || ''), title:String(task.title || ''), promptText:String(task.promptText || ''),
          imageUrl:safeUrl(task.imageUrl), sourceUrl:safeUrl(task.sourceUrl || entry.sourceUrl || task.lessonUrl || entry.lessonUrl)});
      });
    });
    return [...groups.values()].map(group => ({...group, tasks:group.tasks.sort((a,b) => a.taskNumber-b.taskNumber)}));
  }
  function forItem(item) {
    if (!item || item.skill !== 'writing') return null;
    const values = [item.assignmentCode, item.sourceCode, item.code];
    const urls = [item.lessonUrl, item.url];
    array(item.tasks).forEach(task => {
      if (!task) return;
      values.push(task.assignmentCode, task.sourceCode, task.code, task.title);
      urls.push(task.url, task.lessonUrl);
      array(task.actions).forEach(action => { if (action) urls.push(action.url); });
    });
    const codes = [...new Set(values.map(code).filter(Boolean))];
    // An explicit code is authoritative; a lesson link cannot override it.
    if (codes.length) return codes.length === 1 ? all().find(entry => entry.assignmentCode === codes[0]) || null : null;
    const keys = urls.map(lessonKey).filter(Boolean);
    const matches = all().filter(entry => entry.lessonUrls.some(url => keys.includes(url)));
    if (matches.length === 1) return matches[0];
    const sessionNumber = Number(item.sessionNumber);
    const sessionMatches = Number.isFinite(sessionNumber) ? all().filter(entry => entry.sessionNumbers.includes(sessionNumber)) : [];
    return sessionMatches.length === 1 ? sessionMatches[0] : null;
  }
  return {code, all, forItem, safeUrl};
})();
/* IELTS_WRITING_ASSIGNMENT_HELPERS_END_V1 */
