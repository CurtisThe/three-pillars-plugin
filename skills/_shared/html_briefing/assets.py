"""html_briefing/assets.py — inline CSS and JS blobs for the briefing document.

Kept as a separate module to prevent briefing.py from approaching the
500-line / 50k-char hard cap.

Stdlib only. Flat-import package — no __init__.py.
"""

CSS = """\
/* html_briefing — inline styles */
*, *::before, *::after { box-sizing: border-box; }
body {
  font-family: system-ui, -apple-system, sans-serif;
  margin: 0;
  padding: 1rem 2rem;
  background: #f8f9fa;
  color: #212529;
}
#briefing { max-width: 960px; margin: 0 auto; }
.seed-card {
  background: #fff;
  border: 1px solid #dee2e6;
  border-radius: 6px;
  padding: 1rem;
  margin-bottom: 1rem;
}
.seed-name { margin: 0 0 0.25rem; font-size: 1.1rem; }
.brief { margin: 0 0 0.5rem; color: #495057; }
.meta { font-size: 0.85rem; color: #6c757d; margin-bottom: 0.5rem; }
.branch-sha { margin-left: 1rem; }
.badges { display: flex; flex-wrap: wrap; gap: 0.25rem; }
.badge {
  background: #e9ecef;
  border-radius: 3px;
  padding: 0.1rem 0.4rem;
  font-size: 0.8rem;
}
.banner {
  margin-top: 0.5rem;
  padding: 0.4rem 0.6rem;
  border-radius: 4px;
  font-size: 0.85rem;
}
.banner.probe { background: #fff3cd; border: 1px solid #ffc107; }
.banner.premise { background: #d1ecf1; border: 1px solid #17a2b8; }
.svg-block { margin: 1rem 0; }
section { margin-bottom: 2rem; }
.question { margin-bottom: 1.5rem; }
.q-label { font-weight: bold; margin-bottom: 0.4rem; }
label { display: block; margin: 0.2rem 0; cursor: pointer; }
input[type="text"] { width: 100%; padding: 0.4rem; border: 1px solid #ced4da; border-radius: 4px; }
#controls { margin-top: 2rem; }
#assemble-btn {
  padding: 0.6rem 1.2rem;
  background: #0d6efd;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 1rem;
}
#assemble-btn:hover { background: #0b5ed7; }
#answer-output {
  margin-top: 1rem;
  padding: 0.75rem;
  background: #f8f9fa;
  border: 1px solid #dee2e6;
  border-radius: 4px;
  white-space: pre-wrap;
  font-family: monospace;
  min-height: 2rem;
}
"""

JS = """\
/* html_briefing — assemble-answers button logic.
   Serializes form state into the canonical compact answer string.
   Inline only — no external fetch, no CDN. */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('assemble-btn');
    if (!btn) return;
    btn.addEventListener('click', assembleAnswers);
  });

  function assembleAnswers() {
    var btn = document.getElementById('assemble-btn');
    var qMap = JSON.parse(btn.getAttribute('data-q-map'));
    var output = document.getElementById('answer-output');
    var overrides = [];

    var qNums = Object.keys(qMap).map(Number).sort(function(a,b){return a-b;});
    qNums.forEach(function(num) {
      var question = document.querySelector('[data-num="' + num + '"]');
      if (!question) return;
      var kind = question.getAttribute('data-kind');
      if (kind === 'free') {
        var inp = question.querySelector('input[type="text"],textarea');
        if (inp) {
          var defaultVal = inp.defaultValue;
          var curVal = inp.value;
          if (curVal !== defaultVal) {
            overrides.push(num + ': ' + curVal);
          }
        }
      } else if (kind === 'single') {
        var checked = question.querySelector('input[type="radio"]:checked');
        if (checked) {
          var defaultRadio = question.querySelector('input[type="radio"][checked]');
          var defaultLetter = defaultRadio ? defaultRadio.value : null;
          if (checked.value !== defaultLetter) {
            overrides.push('' + num + checked.value);
          }
        }
      } else if (kind === 'multi') {
        var checkedBoxes = question.querySelectorAll('input[type="checkbox"]:checked');
        var defaultBoxes = question.querySelectorAll('input[type="checkbox"][checked]');
        var chosen = Array.from(checkedBoxes).map(function(el){return el.value;}).sort();
        var defaults = Array.from(defaultBoxes).map(function(el){return el.value;}).sort();
        if (JSON.stringify(chosen) !== JSON.stringify(defaults)) {
          overrides.push(num + chosen.join(' '));
        }
      }
    });

    var result = overrides.length === 0 ? 'defaults' : overrides.join('\\n');
    output.textContent = result;

    /* Copy to clipboard if available */
    if (navigator && navigator.clipboard) {
      navigator.clipboard.writeText(result).catch(function(){});
    }
  }
})();
"""
