/* ScamRead News Feed: keeps the list fresh while the page is open. */
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
    a.href = source.url;
    a.target = '_blank';
    a.rel = 'noopener nofollow';
    return a;
  }

  function renderItem(item) {
    var sources = (item.sources || []).filter(function (s) { return safeUrl(s.url); });
    if (!item.headline || !sources.length) return null;

    var article = el('article', 'srn-item');
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

  function refresh(section) {
    if (document.hidden) return;
    fetch(section.dataset.endpoint, { headers: { Accept: 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        var limit = parseInt(section.dataset.limit, 10) || 20;
        var category = section.dataset.category;
        var items = (data.items || []).filter(function (i) { return !category || i.category === category; });
        var nodes = items.map(renderItem).filter(Boolean).slice(0, limit);
        if (!nodes.length) return; // keep what is on screen rather than blanking it
        var list = section.querySelector('.srn-list');
        list.replaceChildren.apply(list, nodes);
        var updated = section.querySelector('.srn-updated');
        if (updated && data.updated_at) updated.textContent = timeAgo(data.updated_at);
      })
      .catch(function () { /* network hiccup: try again next tick */ });
  }

  function updateTimes(section) {
    section.querySelectorAll('time[datetime]').forEach(function (t) {
      t.textContent = timeAgo(t.getAttribute('datetime'));
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.srn-feed[data-endpoint]').forEach(function (section) {
      var seconds = parseInt(section.dataset.refresh, 10);
      if (!seconds || seconds < 60) return;
      refresh(section); // the page itself may come from a cache, so fetch fresh stories right away
      setInterval(function () { refresh(section); }, seconds * 1000);
      setInterval(function () { updateTimes(section); }, 60 * 1000);
      document.addEventListener('visibilitychange', function () {
        if (!document.hidden) refresh(section);
      });
    });
  });
})();
