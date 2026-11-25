/* ScamRead News Feed: keeps the list fresh while the page is open.
   Live style: stories pop in on load, and new ones slide in at the top with a NEW tag. */
(function () {
  'use strict';

  function timeAgo(iso) {
    var then = Date.parse(iso);
    if (isNaN(then)) return '';
    var s = Math.max(0, Math.round((Date.now() - then) / 1000));
    if (s < 60) return 'just now';
    var m = Math.round(s / 60);
    if (m < 60) return m + (m === 1 ? ' min ago' : ' mins ago');
    var h = Math.round(m / 60);
    if (h < 24) return h + (h === 1 ? ' hour ago' : ' hours ago');
    var d = Math.round(h / 24);
    return d + (d === 1 ? ' day ago' : ' days ago');
  }

  function safeUrl(url) {
    try {
      var u = new URL(url);
      return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : null;
    } catch (e) {
      return null;
    }
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text; // textContent, never innerHTML: feed text is untrusted
    return node;
  }

  function link(source, text) {
    var a = el('a', '', text);
    a.href = safeUrl(source.url);
    a.target = '_blank';
    a.rel = 'noopener nofollow';
    return a;
  }

  /* "Learn the concept": built with textContent only, like the rest of the card. */
  function renderConcept(concept) {
    if (!concept || !concept.title || !Array.isArray(concept.points)) return null;
    var points = concept.points.filter(function (p) { return p && String(p).trim(); }).slice(0, 3);
    if (points.length < 2) return null;
    var details = el('details', 'srn-concept');
    details.appendChild(el('summary', '', 'Learn the concept'));
    var body = el('div', 'srn-concept-body');
    body.appendChild(el('p', 'srn-concept-title', String(concept.title)));
    var list = el('ol', 'srn-concept-points');
    points.forEach(function (p) { list.appendChild(el('li', '', String(p))); });
    body.appendChild(list);
    body.appendChild(el('p', 'srn-concept-note', 'Explained for beginners by AI (Claude).'));
    details.appendChild(body);
    return details;
  }

  function renderItem(item) {
    var sources = (item.sources || []).filter(function (s) { return safeUrl(s.url); });
    if (!item.headline || !sources.length) return null;

    var article = el('article', 'srn-item');
    article.dataset.id = String(item.id || '');
    var meta = el('div', 'srn-meta');
    meta.appendChild(el('span', 'srn-cat srn-cat-' + String(item.category).replace(/[^a-z0-9-]/g, ''), item.label || 'Cyber news'));
    if (item.published) {
      var t = el('time', '', timeAgo(item.published));
      t.setAttribute('datetime', item.published);
      meta.appendChild(t);
    }
    article.appendChild(meta);
    article.appendChild(el('h3', 'srn-headline', item.headline));
    if (item.summary) article.appendChild(el('p', 'srn-summary', item.summary));
    var concept = renderConcept(item.concept);
    if (concept) article.appendChild(concept);

    var links = el('p', 'srn-links');
    if (sources.length === 1) {
      links.appendChild(link(sources[0], 'Read full article on ' + sources[0].name + ' →'));
    } else {
      links.appendChild(document.createTextNode('Read full article: '));
      sources.forEach(function (s, i) {
        if (i) links.appendChild(document.createTextNode(' · '));
        links.appendChild(link(s, s.name));
      });
    }
    article.appendChild(links);
    return article;
  }

  function markNew(node) {
    node.classList.add('srn-new');
    var meta = node.querySelector('.srn-meta');
    if (meta && !meta.querySelector('.srn-new-badge')) {
      meta.insertBefore(el('span', 'srn-new-badge', 'NEW'), meta.firstChild);
    }
  }

  /* Bring the list in line with the latest items without rebuilding it, so existing
     cards stay put and only genuinely new stories animate in. */
  function reconcile(section, items) {
    var list = section.querySelector('.srn-list');
    var live = section.classList.contains('srn-live');
    var existing = {};
    list.querySelectorAll('.srn-item[data-id]').forEach(function (n) { existing[n.dataset.id] = n; });
    var hadItems = Object.keys(existing).length > 0;

    var wanted = [];
    items.forEach(function (item) {
      var node = existing[String(item.id)];
      if (!node) {
        node = renderItem(item);
        if (node && live && hadItems) markNew(node);
      } else if (item.concept && !node.querySelector('.srn-concept')) {
        // An explainer was written after this card appeared: add it in place.
        var concept = renderConcept(item.concept);
        if (concept) node.insertBefore(concept, node.querySelector('.srn-links'));
      }
      if (node) wanted.push(node);
    });
    if (!wanted.length) return; // keep what is on screen rather than blanking it

    wanted.forEach(function (node, i) {
      if (list.children[i] !== node) list.insertBefore(node, list.children[i] || null);
    });
    Array.prototype.slice.call(list.children, wanted.length).forEach(function (n) { n.remove(); });
  }

  function updateTimes(section) {
    section.querySelectorAll('time[datetime]').forEach(function (t) {
      t.textContent = timeAgo(t.getAttribute('datetime'));
    });
  }

  function refresh(section) {
    if (document.hidden) return;
    fetch(section.dataset.endpoint, { headers: { Accept: 'application/json' }, cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        var limit = parseInt(section.dataset.limit, 10) || 20;
        var category = section.dataset.category;
        var items = (data.items || []).filter(function (i) { return !category || i.category === category; }).slice(0, limit);
        reconcile(section, items);
        updateTimes(section);
        var updated = section.querySelector('.srn-updated');
        if (updated && data.updated_at) updated.textContent = timeAgo(data.updated_at);
      })
      .catch(function () { /* network hiccup: try again next tick */ });
  }

  // Count how often visitors open "Learn the concept" (if Google Analytics is on the page).
  document.addEventListener('toggle', function (e) {
    var d = e.target;
    if (d && d.classList && d.classList.contains('srn-concept') && d.open && typeof window.gtag === 'function') {
      var item = d.closest('.srn-item');
      window.gtag('event', 'learn_concept_open', { story_id: item ? item.dataset.id : '' });
    }
  }, true);

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.srn-feed[data-endpoint]').forEach(function (section) {
      var intro = section.classList.contains('srn-intro');
      if (intro) {
        // CSS staggers the pop-in; drop the class once it has played so later changes don't replay it.
        setTimeout(function () { section.classList.remove('srn-intro'); }, 2500);
      }
      var seconds = parseInt(section.dataset.refresh, 10);
      if (!seconds || seconds < 60) return;
      // The page may come from a cache, so fetch fresh stories soon after it opens.
      setTimeout(function () { refresh(section); }, intro ? 2600 : 0);
      setInterval(function () { refresh(section); }, seconds * 1000);
      setInterval(function () { updateTimes(section); }, 60 * 1000);
      document.addEventListener('visibilitychange', function () {
        if (!document.hidden) refresh(section);
      });
    });
  });
})();
