/* commonplace.js — consolidated frontend JS
   CSP-safe: no inline script tags needed.
   CSRF token read from <meta name="csrf-token"> in base.html. */

(function() {
    'use strict';

    /* ── CSRF token from meta tag ──────────────────── */
    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    var CSRF_TOKEN = csrfMeta ? csrfMeta.content : '';

    /* ── Utility functions ─────────────────────────── */

    window.escapeHtml = function(str) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(str || ''));
        return div.innerHTML;
    };

    window.showToast = function(message, type) {
        type = type || 'info';
        var container = document.getElementById('toast-container');
        if (!container) return;
        var colors = { success: 'bg-emerald-600', error: 'bg-red-600', info: 'bg-sidebar text-sidebar' };
        var icons = { success: '\u2705', error: '\u274c', info: '\u2139\ufe0f' };
        var el = document.createElement('div');
        el.className = (colors[type] || colors.info) + ' text-white text-sm px-4 py-2.5 rounded-lg shadow-lg pointer-events-auto transition-all duration-300 flex items-center gap-2 max-w-sm';
        el.style.transform = 'translateX(120%)';
        el.innerHTML = '<span>' + (icons[type] || icons.info) + '</span><span>' + message + '</span>';
        container.appendChild(el);
        requestAnimationFrame(function() { el.style.transform = 'translateX(0)'; });
        setTimeout(function() {
            el.style.transform = 'translateX(120%)';
            el.style.opacity = '0';
            setTimeout(function() { el.remove(); }, 300);
        }, 3500);
    };

    window.confirmModal = function(title, message) {
        return new Promise(function(resolve) {
            var overlay = document.getElementById('confirm-overlay');
            var titleEl = document.getElementById('confirm-title');
            var msgEl = document.getElementById('confirm-message');
            var cancelBtn = document.getElementById('confirm-cancel');
            var actionBtn = document.getElementById('confirm-action');
            if (!overlay || !titleEl || !msgEl) { resolve(true); return; }
            titleEl.textContent = title;
            msgEl.textContent = message;
            overlay.classList.remove('hidden');
            function cleanup(result) { overlay.classList.add('hidden'); resolve(result); }
            cancelBtn.onclick = function() { cleanup(false); };
            actionBtn.onclick = function() { cleanup(true); };
            overlay.onclick = function(e) { if (e.target === overlay) cleanup(false); };
        });
    };

    window.cacheBust = function(url) {
        return url + (url.includes('?') ? '&' : '?') + 'v=' + Date.now();
    };

    window.setLoading = function(el, loading) {
        if (loading) {
            el.dataset.origText = el.textContent;
            el.textContent = '...';
            el.style.pointerEvents = 'none';
            el.style.opacity = '0.5';
        } else {
            el.textContent = el.dataset.origText || el.textContent;
            el.style.pointerEvents = '';
            el.style.opacity = '';
        }
    };

    window.cardData = function(el) {
        var card = el.closest('[data-hl-id]');
        return card ? card.dataset.hlId : '';
    };

    window.updateFileName = function(input, displayId) {
        var display = document.getElementById(displayId);
        if (input.files && input.files.length > 0) {
            display.textContent = '\uD83D\uDCCE ' + input.files[0].name;
            display.className = 'text-xs text-indigo-600 font-medium mt-2';
        } else {
            display.textContent = '';
        }
    };

    window.copyText = function(text, label) {
        label = label || 'Text';
        if (!navigator.clipboard || !navigator.clipboard.writeText) {
            window.showToast('Clipboard not available', 'error');
            return;
        }
        navigator.clipboard.writeText(text).then(function() {
            window.showToast(label + ' copied!', 'success');
        }).catch(function(e) {
            window.showToast('Copy failed: ' + e.message, 'error');
        });
    };

    /* ── Push notification subscribe/unsubscribe ─────────── */

    window.subscribePush = function() {
        if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
            window.showToast('Push notifications not supported in this browser', 'error');
            return Promise.resolve(false);
        }
        if (!window.isSecureContext && location.hostname !== 'localhost') {
            window.showToast('Push notifications require HTTPS (not available on HTTP connections)', 'error');
            return Promise.resolve(false);
        }
        if (Notification.permission === 'denied') {
            window.showToast('Notifications blocked in browser settings', 'error');
            return Promise.resolve(false);
        }
        var vapidMeta = document.querySelector('meta[name="vapid-public-key"]');
        if (!vapidMeta || !vapidMeta.content) {
            window.showToast('VAPID public key not configured', 'error');
            return Promise.resolve(false);
        }
        return navigator.serviceWorker.ready.then(function(reg) {
            return reg.pushManager.subscribe({
                userVisibleOnly: true,
                applicationServerKey: window.urlBase64ToUint8Array(vapidMeta.content),
            });
        }).then(function(sub) {
            var body = JSON.stringify({
                endpoint: sub.endpoint,
                keys: sub.toJSON().keys,
            });
            return fetch('/api/push/subscribe', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: body,
            });
        }).then(function(r) {
            if (r.ok) {
                window.showToast('Notifications enabled', 'success');
                return true;
            }
            return r.json().then(function(d) {
                window.showToast('Subscribe failed: ' + (d.error || 'unknown'), 'error');
                return false;
            });
        }).catch(function(e) {
            if (e.name === 'NotAllowedError') {
                window.showToast('Notification permission denied', 'error');
            } else {
                window.showToast('Subscribe failed: ' + e.message, 'error');
            }
            return false;
        });
    };

    window.unsubscribePush = function() {
        return navigator.serviceWorker.ready.then(function(reg) {
            return reg.pushManager.getSubscription();
        }).then(function(sub) {
            if (!sub) return true;
            var endpoint = sub.endpoint;
            return sub.unsubscribe().then(function() {
                return fetch('/api/push/subscribe', {
                    method: 'DELETE',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ endpoint: endpoint }),
                });
            });
        }).then(function(r) {
            if (r && !r.ok) return r.json().then(function(d) {
                window.showToast('Unsubscribe failed: ' + (d.error || 'unknown'), 'error');
                return false;
            });
            window.showToast('Notifications disabled', 'success');
            return true;
        }).catch(function(e) {
            window.showToast('Unsubscribe failed: ' + e.message, 'error');
            return false;
        });
    };

    window.urlBase64ToUint8Array = function(base64String) {
        var padding = '='.repeat((4 - base64String.length % 4) % 4);
        var base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        var rawData = window.atob(base64);
        var output = new Uint8Array(rawData.length);
        for (var i = 0; i < rawData.length; ++i) {
            output[i] = rawData.charCodeAt(i);
        }
        return output;
    };

    /* ── Base page initialisation ──────────────────── */

    // PWA service worker
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/static/sw.js', { scope: '/' }).catch(function(e) {
            console.warn('SW registration failed (push disabled):', e.message);
        });
    }

    // Mobile sidebar toggle
    (function() {
        var toggle = document.getElementById('sidebar-toggle');
        var sidebar = document.getElementById('sidebar');
        var overlay = document.getElementById('sidebar-overlay');
        if (toggle && sidebar && overlay) {
            function open() {
                sidebar.classList.remove('-translate-x-full');
                overlay.classList.remove('hidden');
                document.body.style.overflow = 'hidden';
            }
            function close() {
                sidebar.classList.add('-translate-x-full');
                overlay.classList.add('hidden');
                document.body.style.overflow = '';
            }
            toggle.addEventListener('click', open);
            overlay.addEventListener('click', close);
        }
    })();

    // Theme switcher
    (function() {
        var THEME_STORAGE_KEY = 'commonplace-theme';
        var body = document.body;

        function getStoredTheme() {
            var serverTheme = body.getAttribute('data-theme');
            var stored = localStorage.getItem(THEME_STORAGE_KEY);
            return stored || serverTheme || 'modern';
        }

        function applyTheme(theme) {
            // Remove all .theme-* classes, then add current
            body.className = body.className.replace(/\btheme-\S+/g, '').trim();
            body.classList.add('theme-' + theme);
            localStorage.setItem(THEME_STORAGE_KEY, theme);
            body.setAttribute('data-theme', theme);

            var icon = document.getElementById('theme-toggle-icon');
            var label = document.getElementById('theme-toggle-label');
            if (icon && label) {
                var order = (body.getAttribute('data-theme-order') || 'modern,reader,dark').split(',');
                var idx = order.indexOf(theme);
                var next = order[(idx + 1) % order.length];
                var nextLabel = next.charAt(0).toUpperCase() + next.slice(1);
                icon.textContent = '\uD83C\uDFA8';
                label.textContent = 'Switch to ' + nextLabel;
            }
        }

        applyTheme(getStoredTheme());

        window.toggleTheme = function() {
            var current = localStorage.getItem(THEME_STORAGE_KEY) || body.getAttribute('data-theme') || 'modern';
            var order = (body.getAttribute('data-theme-order') || 'modern,reader,dark').split(',');
            var idx = order.indexOf(current);
            var next = order[(idx + 1) % order.length];
            applyTheme(next);
            fetch('/settings/theme', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: 'theme=' + next + '&csrf_token=' + CSRF_TOKEN,
            }).catch(function() {});
        };
    })();

    // Achievement badge in sidebar
    fetch('/api/achievements').then(function(r) { return r.json(); }).then(function(data) {
        var count = data.filter(function(a) { return a.unlocked; }).length;
        var link = document.querySelector('a[href="/achievements"]');
        if (link && count > 0) {
            var badge = document.createElement('span');
            badge.className = 'ml-auto text-xs bg-accent text-white rounded-full px-1.5 py-0.5 font-bold min-w-[20px] text-center';
            badge.textContent = count;
            link.appendChild(badge);
        }
    }).catch(function() {});

    /* ── Highlights page ───────────────────────────── */

    window.toggleFav = function(id, btn) {
        fetch('/api/highlights/' + id + '/favorite', { method: 'POST' })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.favorite) {
                    btn.innerHTML = '\u2B50';
                    btn.className = 'text-lg leading-none hover:scale-110 transition-transform text-amber-400';
                } else {
                    btn.innerHTML = '\u2606';
                    btn.className = 'text-lg leading-none hover:scale-110 transition-transform text-slate-300 hover:text-amber-300';
                }
            });
    };

    (function() {
        var rows = document.querySelectorAll('.highlight-row');
        rows.forEach(function(row) {
            row.addEventListener('click', function() {
                var targetId = row.getAttribute('data-target');
                var detail = document.getElementById(targetId);
                if (detail) detail.classList.toggle('hidden');
            });
        });
    })();

    window.toggleMobileDetail = function(id) {
        var el = document.getElementById('card-detail-' + id);
        if (el) el.classList.toggle('open');
    };

    window.scrollToEdit = function(id) {
        setTimeout(function() {
            var el = document.getElementById('edit-' + id);
            if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }, 100);
    };

    // Swipe to reveal
    (function() {
        var containers = document.querySelectorAll('.hl-card-swipe-container');
        var startX = 0, currentX = 0, isDragging = false, activeSwipe = null;

        function getTranslateX(el) {
            var reveal = el.querySelector('.hl-card-swipe-reveal');
            if (!reveal) return 0;
            var w = reveal.offsetWidth;
            var tr = reveal.style.transform;
            if (tr && tr !== 'translateX(100%)' && tr !== '') {
                var m = tr.match(/translateX\((-?\d+)px\)/);
                if (m) return parseInt(m[1]);
            }
            return reveal.classList.contains('open') ? -w : 0;
        }

        function setTranslateX(el, x) {
            var reveal = el.querySelector('.hl-card-swipe-reveal');
            if (!reveal) return;
            reveal.style.transition = 'none';
            reveal.style.transform = 'translateX(' + x + 'px)';
        }

        function closeAllSwipe() {
            document.querySelectorAll('.hl-card-swipe-reveal.open').forEach(function(r) {
                r.classList.remove('open');
                r.style.transform = '';
                r.style.transition = '';
            });
        }

        containers.forEach(function(container) {
            container.addEventListener('touchstart', function(e) {
                var touch = e.changedTouches[0];
                startX = touch.clientX;
                isDragging = true;
                activeSwipe = container;
                var otherReveal = container.querySelector('.hl-card-swipe-reveal');
                if (otherReveal && !otherReveal.classList.contains('open')) {
                    closeAllSwipe();
                }
            }, { passive: true });

            container.addEventListener('touchmove', function(e) {
                if (!isDragging || activeSwipe !== container) return;
                var touch = e.changedTouches[0];
                currentX = touch.clientX;
                var dx = startX - currentX;
                var reveal = container.querySelector('.hl-card-swipe-reveal');
                if (!reveal) return;
                var w = reveal.offsetWidth || 128;
                var isOpen = reveal.classList.contains('open');
                if (isOpen) {
                    var openOffset = -w;
                    var newX = Math.min(0, openOffset + dx);
                    setTranslateX(container, newX);
                } else if (dx > 0) {
                    var newX = Math.max(-w, -dx);
                    setTranslateX(container, newX);
                }
            }, { passive: true });

            container.addEventListener('touchend', function(e) {
                if (!isDragging || activeSwipe !== container) return;
                isDragging = false;
                activeSwipe = null;
                var reveal = container.querySelector('.hl-card-swipe-reveal');
                if (!reveal) return;
                var w = reveal.offsetWidth || 128;
                var dx = startX - currentX;
                var isOpen = reveal.classList.contains('open');

                reveal.style.transition = '';
                reveal.style.transform = '';

                if (isOpen) {
                    if (dx < -30) reveal.classList.remove('open');
                    else reveal.classList.add('open');
                } else if (dx > w * 0.35) {
                    reveal.classList.add('open');
                }
            }, { passive: true });
        });

        document.addEventListener('click', function(e) {
            if (!e.target.closest('.hl-card-swipe-container')) {
                closeAllSwipe();
            }
        });
    })();

    window.loadContext = function(id) {
        var container = document.getElementById('context-' + id);
        if (!container) return;
        if (!container.classList.contains('hidden')) {
            container.classList.add('hidden');
            return;
        }
        container.classList.remove('hidden');
        container.innerHTML = '<div class="text-sm text-slate-400 text-center py-2">Loading...</div>';

        fetch('/api/highlights/' + id + '/context')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                var html = '<div class="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">\uD83D\uDCD6 Context from <span class="text-slate-700">' + window.escapeHtml(data.current.book_title) + '</span></div>';
                if (data.before.length === 0 && data.after.length === 0) {
                    html += '<div class="text-sm text-slate-400 italic py-2">No other highlights from this book.</div>';
                    container.innerHTML = html;
                    return;
                }
                data.before.forEach(function(hl) {
                    html += contextItemHtml(hl, false, id);
                });
                html += contextItemHtml(data.current, true, id);
                data.after.forEach(function(hl) {
                    html += contextItemHtml(hl, false, id);
                });
                container.innerHTML = html;
                container.querySelectorAll('.context-fav-btn').forEach(function(btn) {
                    btn.addEventListener('click', function(e) {
                        e.stopPropagation();
                        var hlId = parseInt(btn.getAttribute('data-id'));
                        window.toggleFav(hlId, btn);
                    });
                });
            })
            .catch(function(e) {
                container.innerHTML = '<div class="text-sm text-red-500 py-2">Failed to load context: ' + e.message + '</div>';
            });
    };

    function contextItemHtml(hl, isCurrent, highlightId) {
        var cls = isCurrent ? 'bg-indigo-50 border-indigo-200 ring-1 ring-indigo-200' : 'bg-white border-slate-200';
        var favStar = hl.favorite ? '\u2B50' : '\u2606';
        var text = hl.text.length > 120 ? hl.text.substring(0, 120) + '\u2026' : hl.text;
        var pageInfo = '';
        if (hl.chapter) pageInfo += ' <span class="text-slate-400">\xb7</span> ' + hl.chapter;
        if (hl.page) pageInfo += ' <span class="text-slate-400">\xb7</span> p.' + hl.page;
        var escapedText = window.escapeHtml(hl.text);
        var actions = '<div class="flex gap-2 mt-1.5 pt-1.5 border-t border-slate-100">' +
            '<button data-action="copy-text" data-text="' + escapedText + '" data-label="Highlight" class="text-xs text-indigo-500 hover:text-indigo-700">\uD83D\uDCCB Copy</button>';
        if (hl.share_token) {
            actions += ' <a href="/share/' + hl.share_token + '" class="text-xs text-indigo-500 hover:text-indigo-700">\uD83D\uDCE4 Open</a>' +
                       ' <a href="/share/' + hl.share_token + '" target="_blank" class="text-xs text-indigo-500 hover:text-indigo-700">\uD83D\uDCE4 Share</a>';
        }
        actions += '</div>';
        return '<div class="flex items-start gap-2 px-3 py-2.5 rounded-lg text-sm border ' + cls + '">' +
            '<button class="context-fav-btn shrink-0 mt-0.5 text-sm leading-none ' + (hl.favorite ? 'text-amber-400' : 'text-slate-300 hover:text-amber-300') + '" data-id="' + hl.id + '">' + favStar + '</button>' +
            '<div class="min-w-0 flex-1">' +
            '<p class="text-slate-700 leading-relaxed ' + (isCurrent ? 'font-medium' : '') + '">' + window.escapeHtml(text) + '</p>' +
            '<div class="text-xs text-slate-400 mt-0.5">' +
            (hl.highlighted_at || '') + pageInfo +
            '</div>' + actions +
            '</div></div>';
    }

    window.toggleEdit = function(id) {
        var form = document.getElementById('edit-' + id);
        form.classList.toggle('hidden');
    };

    window.cancelEdit = function(id) {
        document.getElementById('edit-' + id).classList.add('hidden');
    };

    window.saveEdit = function(id) {
        var data = {
            text: document.getElementById('edit-text-' + id).value,
            note: document.getElementById('edit-note-' + id).value,
            book_title: document.getElementById('edit-book-' + id).value,
            book_author: document.getElementById('edit-author-' + id).value,
            tags: document.getElementById('edit-tags-' + id).value.split(',').map(function(t) { return t.trim(); }).filter(Boolean)
        };
        fetch('/api/highlights/' + id, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        }).then(function(r) { return r.json(); }).then(function(result) {
            if (result.ok) location.reload();
            else window.showToast('Save failed: ' + (result.error || 'unknown'), 'error');
        }).catch(function(e) {
            window.showToast('Save failed: ' + e.message, 'error');
        });
    };

    window.deleteHighlight = function(id) {
        window.confirmModal('Delete highlight?', 'This cannot be undone.').then(function(ok) {
            if (!ok) return;
            fetch('/api/highlights/' + id, { method: 'DELETE' })
                .then(function(r) { return r.json(); })
                .then(function(result) {
                    if (result.ok) location.reload();
                });
        });
    };

    window.getSelectedIds = function() {
        var checks = document.querySelectorAll('.hl-select:checked');
        return Array.from(checks).map(function(c) { return c.value; });
    };

    window.toggleSelectAll = function() {
        var checked = document.getElementById('select-all').checked;
        document.querySelectorAll('.hl-select').forEach(function(c) { c.checked = checked; });
        window.updateBatchBar();
    };

    window.updateBatchBar = function() {
        var ids = window.getSelectedIds();
        var bar = document.getElementById('batch-bar');
        var count = document.getElementById('batch-count');
        if (ids.length > 0) {
            bar.classList.remove('hidden');
            count.textContent = ids.length + ' selected';
        } else {
            bar.classList.add('hidden');
        }
    };

    window.clearSelection = function() {
        document.querySelectorAll('.hl-select').forEach(function(c) { c.checked = false; });
        var sa = document.getElementById('select-all');
        if (sa) sa.checked = false;
        window.updateBatchBar();
    };

    window.batchAddTag = function() {
        var ids = window.getSelectedIds();
        if (ids.length === 0) return;
        var tagName = prompt('Enter tag name to add to ' + ids.length + ' highlights:');
        if (!tagName || !tagName.trim()) return;
        tagName = tagName.trim();
        Promise.all(ids.map(function(id) {
            return fetch('/api/highlights/' + id)
                .then(function(r) { return r.json(); })
                .then(function(hl) {
                    var tags = (hl.tags || []).concat([tagName]);
                    return fetch('/api/highlights/' + id, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ tags: tags })
                    });
                });
        })).then(function() {
            window.showToast('Tag added to ' + ids.length + ' highlights', 'success');
            window.clearSelection();
            location.reload();
        }).catch(function(e) {
            window.showToast('Error: ' + e.message, 'error');
        });
    };

    window.batchDelete = function() {
        var ids = window.getSelectedIds();
        if (ids.length === 0) return;
        if (!confirm('Delete ' + ids.length + ' highlights? This cannot be undone.')) return;
        Promise.all(ids.map(function(id) {
            return fetch('/api/highlights/' + id, { method: 'DELETE' });
        })).then(function() {
            window.showToast('Deleted ' + ids.length + ' highlights', 'success');
            window.clearSelection();
            location.reload();
        }).catch(function(e) {
            window.showToast('Error: ' + e.message, 'error');
        });
    };

    /* ── Books page ────────────────────────────────── */

    function updateCoverImage(card, newUrl) {
        var imgContainer = card.querySelector('.aspect-\\[2\\/3\\]');
        if (!imgContainer) return;
        var busted = window.cacheBust(newUrl);
        imgContainer.innerHTML = '<img src="' + busted + '" alt="Cover" class="w-full h-full object-cover" loading="lazy">';
    }

    window.openCoverSelector = function(el) {
        var card = el.closest('[data-hl-id]');
        if (!card) return;
        var title = card.dataset.title || '';
        var author = card.dataset.author || '';
        document.getElementById('cs-title').value = title;
        document.getElementById('cs-author').value = author;
        document.getElementById('cs-query').value = (title + ' ' + author).trim();
        // Clear previous results
        var resultsEl = document.getElementById('cs-results');
        var emptyEl = document.getElementById('cs-empty');
        if (emptyEl) emptyEl.style.display = '';
        // Remove any result items but keep empty state
        resultsEl.querySelectorAll('.cs-result-item').forEach(function(n) { n.remove(); });
        // Show modal
        document.getElementById('cover-selector-modal').classList.remove('hidden');
        // Focus search input and add Enter handler
        var input = document.getElementById('cs-query');
        input.focus();
        input.addEventListener('keydown', window._csKeydown);
    };

    window._csKeydown = function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            window.searchCoverSelector();
        }
    };

    window.closeCoverSelector = function(e) {
        if (e && e.target !== e.currentTarget) return;
        document.getElementById('cover-selector-modal').classList.add('hidden');
        // Clean up keydown listener
        var input = document.getElementById('cs-query');
        input.removeEventListener('keydown', window._csKeydown);
    };

    window.searchCoverSelector = function() {
        var query = document.getElementById('cs-query').value.trim();
        if (!query) { window.showToast('Enter a search term', 'error'); return; }
        var resultsEl = document.getElementById('cs-results');
        var emptyEl = document.getElementById('cs-empty');
        if (emptyEl) emptyEl.style.display = 'none';
        // Remove old results
        resultsEl.querySelectorAll('.cs-result-item').forEach(function(n) { n.remove(); });
        // Show loading
        var loading = document.createElement('div');
        loading.className = 'col-span-full text-center text-slate-400 py-12 text-sm cs-result-item';
        loading.id = 'cs-loading';
        loading.textContent = 'Searching...';
        resultsEl.appendChild(loading);

        var fd = new FormData();
        fd.append('title', query);
        fd.append('author', '');
        fetch('/api/books/cover/search', { method: 'POST', body: fd })
            .then(function(r) { return r.json(); })
            .then(function(d) {
                var loadingEl = document.getElementById('cs-loading');
                if (loadingEl) loadingEl.remove();
                if (!d.ok) {
                    window.showToast(d.error || 'Search failed', 'error');
                    if (emptyEl) emptyEl.style.display = '';
                    return;
                }
                var options = d.options || [];
                if (options.length === 0) {
                    if (emptyEl) {
                        emptyEl.style.display = '';
                        emptyEl.innerHTML = '<p class="text-slate-400">No covers found for that search.</p>';
                    }
                    return;
                }
                options.forEach(function(opt) {
                    var item = document.createElement('div');
                    item.className = 'cs-result-item cursor-pointer group';
                    item.setAttribute('data-cover-url', opt.cover_url || '');
                    item.setAttribute('data-source', opt.source || '');
                    if (opt.hardcover_id) item.setAttribute('data-hardcover-id', opt.hardcover_id);
                    if (opt.isbn) item.setAttribute('data-isbn', opt.isbn);
                    item.innerHTML =
                        '<div class="aspect-[2/3] bg-slate-100 rounded-lg overflow-hidden border border-slate-200 group-hover:border-indigo-400 group-hover:shadow-md transition-all">' +
                            '<img src="' + (opt.cover_url || '') + '" alt="Cover" class="w-full h-full object-cover" loading="lazy">' +
                        '</div>' +
                        '<div class="mt-1 text-center">' +
                            '<span class="text-xs font-medium text-indigo-600 opacity-0 group-hover:opacity-100 transition-opacity">Select</span>' +
                            '<span class="text-xs text-slate-400 ml-1">(' + opt.source + ')</span>' +
                        '</div>';
                    // Handle image load errors
                    var img = item.querySelector('img');
                    if (img) {
                        img.onerror = function() {
                            this.outerHTML = '<div class="flex items-center justify-center h-full text-slate-300 text-xs p-2">No img</div>';
                        };
                    }
                    item.addEventListener('click', function() {
                        window.pickCover(this);
                    });
                    resultsEl.appendChild(item);
                });
            })
            .catch(function(e) {
                var loadingEl = document.getElementById('cs-loading');
                if (loadingEl) loadingEl.remove();
                window.showToast('Network error: ' + e.message, 'error');
                if (emptyEl) emptyEl.style.display = '';
            });
    };

    window.pickCover = function(el) {
        var coverUrl = el.getAttribute('data-cover-url');
        var source = el.getAttribute('data-source');
        var title = document.getElementById('cs-title').value;
        var author = document.getElementById('cs-author').value;
        var hardcoverId = el.getAttribute('data-hardcover-id') || '';
        var isbn = el.getAttribute('data-isbn') || '';
        if (!coverUrl || !title) return;

        // Save the cover
        var fd = new FormData();
        fd.append('title', title);
        fd.append('author', author);
        fd.append('cover_url', coverUrl);
        fd.append('source', source);
        if (hardcoverId) fd.append('hardcover_id', hardcoverId);
        if (isbn) fd.append('isbn', isbn);

        fetch('/api/books/cover/save', { method: 'POST', body: fd })
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (d.ok) {
                    window.showToast('Cover saved', 'success');
                    window.closeCoverSelector();
                    location.reload();
                } else {
                    window.showToast(d.error || 'Failed to save cover', 'error');
                }
            })
            .catch(function(e) {
                window.showToast('Error: ' + e.message, 'error');
            });
    };

    window.closeCoverSelector = function(e) {
        if (e && e.target !== e.currentTarget) return;
        document.getElementById('cover-selector-modal').classList.add('hidden');
    };

    window.backfillCovers = function() {
        window.confirmModal('Fetch covers?', 'Fetch covers for all books from online sources? This may take a minute.').then(function(ok) {
            if (!ok) return;
            var btn = document.querySelector('[data-action="backfill-covers"]');
            window.setLoading(btn, true);
            fetch('/api/books/cover/backfill', { method: 'POST' })
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    window.setLoading(btn, false);
                    if (d.ok) location.reload();
                    else window.showToast('Error: ' + (d.error || 'unknown'), 'error');
                })
                .catch(function(e) {
                    window.setLoading(btn, false);
                    window.showToast('Network error: ' + e.message, 'error');
                });
        });
    };

    window.uploadCover = function(el) {
        var hlId = window.cardData(el);
        if (!hlId) return;
        var input = document.createElement('input');
        input.type = 'file';
        input.accept = '.jpg,.jpeg,.png,.webp';
        input.onchange = function() {
            if (!input.files || !input.files[0]) return;
            var file = input.files[0];
            if (file.size > 10 * 1024 * 1024) {
                window.showToast('File too large. Max 10MB.', 'error');
                return;
            }
            window.setLoading(el, true);
            var fd = new FormData();
            fd.append('file', file);
            fetch('/api/books/cover/upload/' + hlId, { method: 'POST', body: fd })
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    window.setLoading(el, false);
                    if (d.ok) {
                        var card = el.closest('[data-hl-id]');
                        if (card && d.cover_url) updateCoverImage(card, d.cover_url);
                    } else {
                        window.showToast('Error: ' + (d.error || 'unknown'), 'error');
                    }
                })
                .catch(function(e) {
                    window.setLoading(el, false);
                    alert('Network error: ' + e.message);
                });
        };
        input.click();
    };

    var renameCard = null;

    window.renameBook = function(el) {
        renameCard = el.closest('[data-hl-id]');
        if (!renameCard) { window.showToast('Could not find book data', 'error'); return; }
        var oldTitle = renameCard.dataset.title;
        var oldAuthor = renameCard.dataset.author;
        var hlEl = renameCard.querySelector('.text-indigo-600');
        var hlCount = hlEl ? hlEl.textContent.trim() : '?';
        document.getElementById('rename-old-title').value = oldTitle || '';
        document.getElementById('rename-old-author').value = oldAuthor || '';
        document.getElementById('rename-new-title').value = oldTitle || '';
        document.getElementById('rename-new-author').value = (oldAuthor === 'Unknown' ? '' : (oldAuthor || ''));
        var warningEl = document.getElementById('rename-warning');
        if (warningEl) warningEl.textContent = 'Renaming will update ' + hlCount + '.';
        var submitBtn = document.getElementById('rename-submit');
        if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = 'Save Changes'; }
        document.getElementById('rename-modal').classList.remove('hidden');
    };

    window.closeRenameModal = function(e) {
        if (e && e.target !== e.currentTarget) return;
        document.getElementById('rename-modal').classList.add('hidden');
        renameCard = null;
    };

    window.submitRename = function(event) {
        event.preventDefault();
        var btn = document.getElementById('rename-submit');
        btn.disabled = true;
        btn.textContent = 'Saving...';
        var fd = new FormData(document.getElementById('rename-form'));

        function doRequest(mergeFlag) {
            if (mergeFlag) fd.set('merge', 'true');
            fetch('/api/books/rename', { method: 'POST', body: fd })
                .then(function(r) {
                    if (!r.ok) return r.text().then(function(text) { throw new Error('HTTP ' + r.status + ': ' + text.slice(0, 200)); });
                    return r.json();
                })
                .then(function(d) {
                    if (d.ok) { window.closeRenameModal(); location.reload(); }
                    else if (d.conflict) {
                        if (confirm(d.message)) doRequest(true);
                        else { btn.disabled = false; btn.textContent = 'Save Changes'; }
                    } else {
                        window.showToast('Error: ' + (d.error || 'unknown'), 'error');
                        btn.disabled = false; btn.textContent = 'Save Changes';
                    }
                })
                .catch(function(e) {
                    window.showToast('Rename failed: ' + e.message, 'error');
                    btn.disabled = false; btn.textContent = 'Save Changes';
                });
        }
        doRequest(false);
        return false;
    };

    (function() {
        var modal = document.getElementById('rename-modal');
        if (modal) modal.addEventListener('click', window.closeRenameModal);
    })();

    window.deleteBook = function() {
        var title = document.getElementById('rename-old-title').value;
        var author = document.getElementById('rename-old-author').value;
        if (!title) return;
        if (!confirm('Delete "' + title + '" and ALL its highlights? This cannot be undone.')) return;
        var btn = document.getElementById('rename-delete-btn');
        btn.disabled = true; btn.textContent = 'Deleting...';
        var fd = new FormData();
        fd.append('title', title);
        fd.append('author', author);
        fetch('/api/books/delete', { method: 'POST', body: fd })
            .then(function(r) {
                if (!r.ok) return r.text().then(function(text) { throw new Error('HTTP ' + r.status + ': ' + text.slice(0, 200)); });
                return r.json();
            })
            .then(function(d) {
                if (d.ok) { window.closeRenameModal(); location.reload(); }
                else { window.showToast('Delete failed: ' + (d.error || 'unknown'), 'error'); btn.disabled = false; btn.textContent = '\uD83D\uDDD1\ufe0f Delete book'; }
            })
            .catch(function(e) {
                window.showToast('Delete failed: ' + e.message, 'error');
                btn.disabled = false; btn.textContent = '\uD83D\uDDD1\ufe0f Delete book';
            });
    };

    var metaCard = null;

    window.openMetadata = function(el) {
        metaCard = el.closest('[data-hl-id]');
        if (!metaCard) { window.showToast('Could not find book data', 'error'); return; }
        document.getElementById('meta-title').value = metaCard.dataset.title || '';
        document.getElementById('meta-author').value = (metaCard.dataset.author === 'Unknown' ? '' : (metaCard.dataset.author || ''));
        document.getElementById('meta-hardcover-id').value = metaCard.dataset.hardcoverId || '';
        document.getElementById('meta-isbn').value = metaCard.dataset.isbn || '';
        document.getElementById('metadata-modal').classList.remove('hidden');
    };

    window.closeMetadataModal = function(e) {
        if (e && e.target !== e.currentTarget) return;
        document.getElementById('metadata-modal').classList.add('hidden');
        metaCard = null;
    };

    window.submitMetadata = function(event) {
        event.preventDefault();
        var btn = event.target.querySelector('button[type="submit"]');
        btn.disabled = true; btn.textContent = 'Saving...';
        var fd = new FormData(document.getElementById('metadata-form'));
        fetch('/api/books/metadata', { method: 'POST', body: fd })
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (d.ok) {
                    if (d.cover_url && metaCard) {
                        updateCoverImage(metaCard, d.cover_url);
                        metaCard.dataset.hardcoverId = d.hardcover_id != null ? String(d.hardcover_id) : '';
                        metaCard.dataset.isbn = d.isbn || '';
                    }
                    window.showToast('Metadata saved', 'success');
                    window.closeMetadataModal();
                } else {
                    window.showToast('Error: ' + (d.error || 'unknown'), 'error');
                }
            })
            .catch(function(e) { window.showToast('Network error: ' + e.message, 'error'); })
            .finally(function() { btn.disabled = false; btn.textContent = 'Save'; });
    };

    (function() {
        var modal = document.getElementById('metadata-modal');
        if (modal) modal.addEventListener('click', window.closeMetadataModal);
    })();

    /* ── Tags page ─────────────────────────────────── */

    window.renameTag = function(btn) {
        var row = btn.closest('[data-tag-id]');
        if (!row) return;
        document.getElementById('rename-tag-id').value = row.dataset.tagId;
        document.getElementById('rename-tag-name').value = row.dataset.tagName;
        var colorInput = document.getElementById('rename-tag-color');
        if (colorInput) colorInput.value = row.dataset.tagColor || '#3b82f6';
        document.getElementById('rename-modal').classList.remove('hidden');
        document.getElementById('rename-tag-name').focus();
    };

    window.closeTagRenameModal = function() {
        document.getElementById('rename-modal').classList.add('hidden');
    };

    window.submitTagRename = function(event) {
        event.preventDefault();
        var id = document.getElementById('rename-tag-id').value;
        var name = document.getElementById('rename-tag-name').value.trim();
        if (!name) return;
        var fd = new FormData();
        fd.append('name', name);
        var colorEl = document.getElementById('rename-tag-color');
        if (colorEl) fd.append('color', colorEl.value);
        fetch('/api/tags/' + id, { method: 'PUT', body: fd })
            .then(function(r) {
                if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Error'); });
                return r.json();
            })
            .then(function() { location.reload(); })
            .catch(function(e) { window.showToast('Error: ' + e.message, 'error'); });
        return false;
    };

    var mergeSourceId = null;

    window.mergeTag = function(btn) {
        var row = btn.closest('[data-tag-id]');
        if (!row) return;
        mergeSourceId = row.dataset.tagId;
        document.getElementById('merge-source-id').value = mergeSourceId;
        document.getElementById('merge-source-name').textContent = row.dataset.tagName;
        document.getElementById('merge-target-id').value = '';
        document.getElementById('merge-modal').classList.remove('hidden');
    };

    window.closeMergeModal = function() {
        document.getElementById('merge-modal').classList.add('hidden');
    };

    window.submitMerge = function(event) {
        event.preventDefault();
        var sourceId = document.getElementById('merge-source-id').value;
        var targetId = document.getElementById('merge-target-id').value;
        if (!targetId) { window.showToast('Select a target tag', 'error'); return; }
        var fd = new FormData();
        fd.append('source_id', sourceId);
        fd.append('target_id', targetId);
        fetch('/api/tags/merge', { method: 'POST', body: fd })
            .then(function(r) {
                if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Error'); });
                return r.json();
            })
            .then(function() { location.reload(); })
            .catch(function(e) { window.showToast('Error: ' + e.message, 'error'); });
        return false;
    };

    window.deleteTag = function(btn) {
        var row = btn.closest('[data-tag-id]');
        if (!row) return;
        var id = row.dataset.tagId;
        var name = row.dataset.tagName;
        if (!confirm('Delete tag "' + name + '"? It will be removed from all highlights.')) return;
        fetch('/api/tags/' + id, { method: 'DELETE' })
            .then(function(r) {
                if (!r.ok) return r.json().then(function(d) { throw new Error(d.detail || 'Error'); });
                location.reload();
            })
            .catch(function(e) { window.showToast('Error: ' + e.message, 'error'); });
    };

    (function() {
        var m = document.getElementById('rename-modal');
        if (m) m.addEventListener('click', window.closeTagRenameModal);
        var m2 = document.getElementById('merge-modal');
        if (m2) m2.addEventListener('click', window.closeMergeModal);
    })();

    /* ── Settings page ─────────────────────────────── */

    window.switchTab = function(name) {
        location.hash = name;
        document.querySelectorAll('.tab-panel').forEach(function(p) { p.style.display = 'none'; });
        document.querySelectorAll('.tab-btn').forEach(function(b) {
            b.classList.remove('border-accent', 'text-accent');
            b.classList.add('border-transparent', 'text-muted');
        });
        var panel = document.getElementById('panel-' + name);
        var btn = document.getElementById('tab-' + name);
        if (panel) panel.style.display = '';
        if (btn) {
            btn.classList.remove('border-transparent', 'text-muted');
            btn.classList.add('border-accent', 'text-accent');
        }
    };

    (function() {
        var valid = ['data', 'api-keys', 'email', 'notifications', 'appearance', 'bookorbit'];
        var tab = location.hash.slice(1) || 'data';
        if (!valid.includes(tab)) tab = 'data';
        window.switchTab(tab);
        window.addEventListener('hashchange', function() {
            window.switchTab(location.hash.slice(1) || 'data');
        });
    })();

    window.setTheme = function(theme) {
        document.querySelectorAll('.theme-option [data-action="set-theme"]').forEach(function(el) {
            el.classList.remove('border-accent', 'bg-accent-light');
            el.classList.add('border-card');
        });
        var selected = document.querySelector('[data-theme="' + theme + '"]');
        if (selected) {
            selected.classList.remove('border-card');
            selected.classList.add('border-accent', 'bg-accent-light');
        }
        if (window.toggleTheme) {
            var current = localStorage.getItem('commonplace-theme') || document.body.getAttribute('data-theme') || 'modern';
            if (current !== theme) window.toggleTheme();
        }
    };

    window.uploadTheme = function() {
        var input = document.getElementById('theme-file-input');
        var status = document.getElementById('theme-upload-status');
        if (!input || !input.files || !input.files[0]) {
            if (status) status.textContent = '❌ Select a CSS file first';
            return;
        }
        var file = input.files[0];
        if (file.size > 50 * 1024) {
            if (status) status.textContent = '❌ File too large. Max 50KB.';
            return;
        }
        var fd = new FormData();
        fd.append('file', file);
        if (status) status.textContent = '⏳ Uploading...';
        fetch('/api/themes/upload', { method: 'POST', body: fd })
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (d.ok) {
                    if (status) status.textContent = '✅ ' + d.message + ' — reloading...';
                    setTimeout(function() { location.reload(); }, 1000);
                } else {
                    if (status) status.textContent = '❌ ' + (d.error || 'Upload failed');
                }
            })
            .catch(function(e) {
                if (status) status.textContent = '❌ Network error: ' + e.message;
            });
    };

    window.deleteTheme = function(name) {
        if (!confirm('Delete theme "' + name + '"? This cannot be undone.')) return;
        var status = document.getElementById('theme-upload-status');
        if (status) status.textContent = '⏳ Deleting...';
        var fd = new FormData();
        fd.append('name', name);
        fetch('/api/themes/delete', { method: 'POST', body: fd })
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (d.ok) {
                    if (status) status.textContent = '✅ ' + d.message + ' — reloading...';
                    setTimeout(function() { location.reload(); }, 1000);
                } else {
                    if (status) status.textContent = '❌ ' + (d.error || 'Delete failed');
                }
            })
            .catch(function(e) {
                if (status) status.textContent = '❌ Network error: ' + e.message;
            });
    };

    window.confirmRestore = function(event) {
        event.preventDefault();
        var fileInput = document.querySelector('[name="file"]');
        if (!fileInput || !fileInput.files || !fileInput.files[0]) {
            window.showToast('Select a backup file first', 'error');
            return false;
        }
        var filename = fileInput.files[0].name;
        window.confirmModal('Restore backup?', 'Replace your current database with "' + filename + '"? All current data will be replaced.').then(function(ok) {
            if (!ok) return;
            var btn = document.getElementById('restore-btn');
            btn.disabled = true; btn.textContent = 'Restoring...';
            document.getElementById('restore-form').submit();
        });
        return false;
    };

    window.saveCoverKey = function() {
        var key = document.getElementById('hardcover-key').value.trim();
        var result = document.getElementById('hc-result');
        var status = document.getElementById('hc-status');
        result.textContent = 'Saving...';
        var fd = new FormData();
        fd.append('csrf_token', CSRF_TOKEN);
        fd.append('hardcover_key', key);
        fd.append('action', 'set');
        fetch('/settings/cover-source', { method: 'POST', body: fd })
            .then(function(r) { return r.json(); })
            .then(function(d) {
                if (d.ok) {
                    status.textContent = d.connected ? '\u2705 Connected' : '\uD83D\uDD11 Saved';
                    result.textContent = d.message || 'Saved';
                } else result.textContent = 'Error: ' + (d.detail || 'unknown');
            })
            .catch(function() { result.textContent = 'Network error'; });
    };

    window.clearCoverKey = function() {
        window.confirmModal('Remove HardCover key?', 'Covers will fall back to Open Library.').then(function(ok) {
            if (!ok) return;
            var result = document.getElementById('hc-result');
            var status = document.getElementById('hc-status');
            document.getElementById('hardcover-key').value = '';
            var fd = new FormData();
            fd.append('csrf_token', CSRF_TOKEN);
            fd.append('action', 'clear');
            fetch('/settings/cover-source', { method: 'POST', body: fd })
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    if (d.ok) { status.textContent = '\u2B1c Empty'; result.textContent = 'Key removed'; }
                })
                .catch(function() { result.textContent = 'Network error'; });
        });
    };

    /* ── BookOrbit Sync ──────────────────────────────────── */

    function getBookOrbitFields() {
        return {
            bookorbit_url: document.getElementById('bo-url').value.trim(),
            bookorbit_username: document.getElementById('bo-username').value.trim(),
            bookorbit_password: document.getElementById('bo-password').value,
            bookorbit_sync_enabled: document.getElementById('bo-auto-sync').checked,
        };
    }

    function setBookOrbitResult(msg, isError) {
        var el = document.getElementById('bo-result');
        el.textContent = msg;
        el.style.color = isError ? '#dc2626' : '#6b7280';
    }

    window.testBookOrbit = function() {
        var fields = getBookOrbitFields();
        if (!fields.bookorbit_url || !fields.bookorbit_username || !fields.bookorbit_password) {
            setBookOrbitResult('Fill in URL, username, and password first', true);
            return;
        }
        setBookOrbitResult('Testing...', false);
        fetch('/api/settings/bookorbit-test', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(fields),
        })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.ok) setBookOrbitResult('Connected!', false);
            else setBookOrbitResult('Failed: ' + (d.error || 'unknown'), true);
        })
        .catch(function() { setBookOrbitResult('Network error', true); });
    };

    window.saveBookOrbit = function() {
        var fields = getBookOrbitFields();
        setBookOrbitResult('Saving...', false);
        fetch('/api/settings/bookorbit-sync', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(fields),
        })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.ok) setBookOrbitResult('Settings saved', false);
            else setBookOrbitResult('Save failed', true);
        })
        .catch(function() { setBookOrbitResult('Network error', true); });
    };

    window.syncBookOrbitNow = function() {
        setBookOrbitResult('Syncing... (may take a moment)', false);
        var btn = document.querySelector('[data-action="sync-bookorbit-now"]');
        if (btn) btn.disabled = true;
        fetch('/api/settings/bookorbit-sync-now', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
        })
        .then(function(r) { return r.json(); })
        .then(function(d) {
            if (d.ok) {
                var r = d.result;
                setBookOrbitResult(
                    'Done: ' + r.posted + ' imported, ' + r.skipped + ' skipped, ' + r.errors + ' errors',
                    r.errors > 0
                );
                if (btn) btn.disabled = false;
                // Reload page to refresh status
                location.reload();
            } else {
                setBookOrbitResult('Sync failed', true);
                if (btn) btn.disabled = false;
            }
        })
        .catch(function() { setBookOrbitResult('Network error', true); if (btn) btn.disabled = false; });
    };

    window.confirmReset = function() {
        window.confirmModal('Reset database?', 'This will permanently delete ALL highlights, books, and review history. This cannot be undone.').then(function(ok) {
            if (!ok) return;
            var response = prompt('Type "reset" to confirm:');
            if (response === 'reset') {
                var form = document.createElement('form');
                form.method = 'POST'; form.action = '/settings/reset';
                var input = document.createElement('input');
                input.type = 'hidden'; input.name = 'confirm'; input.value = 'reset';
                form.appendChild(input);
                var csrf = document.createElement('input');
                csrf.type = 'hidden'; csrf.name = 'csrf_token'; csrf.value = CSRF_TOKEN;
                form.appendChild(csrf);
                document.body.appendChild(form);
                form.submit();
            }
        });
    };

    window.runDedup = function() {
        window.confirmModal('Deduplicate highlights?', 'Merge highlights with identical text/book/author into one, preserving tags and review history.').then(function(ok) {
            if (!ok) return;
            fetch('/api/settings/dedup', {method: 'POST', headers: {'X-CSRF-Token': CSRF_TOKEN}})
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.ok) {
                    window.showToast('Dedup complete: ' + data.groups_merged + ' groups merged, ' + data.duplicates_removed + ' duplicates removed.', 'success');
                } else {
                    window.showToast('Dedup failed: ' + (data.error || 'unknown'), 'error');
                }
            })
            .catch(function(err) { window.showToast('Dedup error: ' + err, 'error'); });
        });
    };

    window.saveEmailConfig = function() {
        var result = document.getElementById('email-result');
        result.textContent = 'Saving...';
        var config = {
            mailjet_api_key: document.getElementById('mj-api-key').value.trim(),
            mailjet_secret_key: document.getElementById('mj-secret-key').value.trim(),
            email_from_name: document.getElementById('email-from-name').value.trim(),
            email_from_addr: document.getElementById('email-from-addr').value.trim(),
            email_to_addr: document.getElementById('email-to-addr').value.trim(),
            base_url: document.getElementById('base-url').value.trim(),
            email_digest_enabled: document.getElementById('email-digest-enabled').checked,
            email_digest_time: document.getElementById('email-digest-time').value,
        };
        fetch('/api/settings/email', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config),
        })
        .then(function(r) { return r.json(); })
        .then(function(data) { result.textContent = data.ok ? '\u2705 Saved' : 'Error: ' + (data.detail || 'unknown'); })
        .catch(function() { result.textContent = 'Network error'; });
    };

    window.sendTestEmail = function() {
        var result = document.getElementById('email-result');
        result.textContent = 'Sending...';
        var config = {
            mailjet_api_key: document.getElementById('mj-api-key').value.trim(),
            mailjet_secret_key: document.getElementById('mj-secret-key').value.trim(),
            email_from_name: document.getElementById('email-from-name').value.trim(),
            email_from_addr: document.getElementById('email-from-addr').value.trim(),
            email_to_addr: document.getElementById('email-to-addr').value.trim(),
        };
        fetch('/api/settings/email/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config),
        })
        .then(function(r) { return r.json(); })
        .then(function(data) { result.textContent = data.ok ? '\u2705 Test email sent!' : 'Error: ' + (data.detail || 'unknown'); })
        .catch(function() { result.textContent = 'Network error'; });
    };

    /* ── Dashboard (index.html) ────────────────────── */

    window.toggleDashFav = function(hlId, btn) {
        var wasFav = btn.classList.contains('text-amber-600');
        if (wasFav) {
            btn.classList.remove('bg-amber-50', 'border-amber-200', 'text-amber-600', 'hover:bg-amber-100');
            btn.classList.add('border-card', 'text-muted', 'hover:text-amber-500', 'hover:border-amber-200');
            btn.querySelector('span:first-child').textContent = '\u2606';
            btn.querySelector('span:last-child').textContent = 'Favorite';
        } else {
            btn.classList.remove('border-card', 'text-muted', 'hover:text-amber-500', 'hover:border-amber-200');
            btn.classList.add('bg-amber-50', 'border-amber-200', 'text-amber-600', 'hover:bg-amber-100');
            btn.querySelector('span:first-child').textContent = '\u2B50';
            btn.querySelector('span:last-child').textContent = 'Favorited';
        }
        fetch('/api/highlights/' + hlId + '/favorite', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: new URLSearchParams({ csrf_token: CSRF_TOKEN })
        }).then(function(r) {
            if (!r.ok) throw new Error('Failed');
            window.showToast(wasFav ? '\u2606 Unfavorited' : '\u2B50 Favorited', 'success');
        }).catch(function() {
            if (wasFav) {
                btn.classList.add('bg-amber-50', 'border-amber-200', 'text-amber-600', 'hover:bg-amber-100');
                btn.querySelector('span:first-child').textContent = '\u2B50';
                btn.querySelector('span:last-child').textContent = 'Favorited';
            } else {
                btn.classList.add('border-card', 'text-muted', 'hover:text-amber-500', 'hover:border-amber-200');
                btn.querySelector('span:first-child').textContent = '\u2606';
                btn.querySelector('span:last-child').textContent = 'Favorite';
            }
            window.showToast('Failed to save', 'error');
        });
    };

    /* ── Review page ──────────────────────────────────── */

    window.showReviewContext = function(id) {
        var modal = document.getElementById('review-context-modal');
        var body = document.getElementById('review-context-body');
        var title = document.getElementById('review-context-title');
        modal.classList.remove('hidden');
        body.innerHTML = '<div class="text-sm text-muted text-center py-4">Loading...</div>';
        fetch('/api/highlights/' + id + '/context')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                title.innerHTML = '\uD83D\uDCD6 Context \u2014 ' + window.escapeHtml(data.current.book_title);
                var html = '';
                if (data.before.length === 0 && data.after.length === 0) {
                    html += '<div class="text-sm text-muted italic py-4 text-center">No other highlights from this book.</div>';
                } else {
                    data.before.forEach(function(hl) { html += contextModalItem(hl, false); });
                    html += contextModalItem(data.current, true);
                    data.after.forEach(function(hl) { html += contextModalItem(hl, false); });
                }
                body.innerHTML = html;
            })
            .catch(function(e) {
                body.innerHTML = '<div class="text-sm text-red-500 py-4 text-center">Error: ' + e.message + '</div>';
            });
    };

    function contextModalItem(hl, isCurrent) {
        var cls = isCurrent ? 'bg-indigo-50 dark:bg-indigo-900/20 border-indigo-200 dark:border-indigo-700 ring-1 ring-indigo-200' : 'bg-page-alt border-card';
        var text = hl.text.length > 150 ? hl.text.substring(0, 150) + '\u2026' : hl.text;
        var pageInfo = '';
        if (hl.chapter) pageInfo += ' <span class="text-muted">\xb7</span> ' + hl.chapter;
        if (hl.page) pageInfo += ' <span class="text-muted">\xb7</span> p.' + hl.page;
        var escapedText = window.escapeHtml(hl.text);
        var actions = '<div class="flex gap-2 mt-1.5 pt-1 border-t border-card">' +
            '<button data-action="copy-text" data-text="' + escapedText + '" data-label="Highlight" class="text-xs text-indigo-500 hover:text-indigo-700">\uD83D\uDCCB Copy</button>';
        if (hl.share_token) {
            actions += ' <a href="/share/' + hl.share_token + '" class="text-xs text-indigo-500 hover:text-indigo-700">\uD83D\uDCE4 Open</a>' +
                       ' <a href="/share/' + hl.share_token + '" target="_blank" class="text-xs text-indigo-500 hover:text-indigo-700">\uD83D\uDCE4 Share</a>';
        }
        actions += '</div>';
        return '<div class="px-3 py-2.5 rounded-lg text-sm border ' + cls + '">' +
            '<p class="text-primary leading-relaxed ' + (isCurrent ? 'font-medium' : '') + '">' + window.escapeHtml(text) + '</p>' +
            '<div class="text-xs text-muted mt-0.5">' +
            (hl.highlighted_at || '') + pageInfo +
            '</div>' + actions +
            '</div>';
    }

    window.closeReviewContext = function(e) {
        document.getElementById('review-context-modal').classList.add('hidden');
    };

    // Review keyboard shortcuts (only if rating forms exist)
    (function() {
        var ratingForms = document.querySelectorAll('form[action="/review/rate"]');
        if (ratingForms.length === 0) return;
        document.addEventListener('keydown', function(e) {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
            if (e.key === '1') { e.preventDefault(); ratingForms[0]?.submit(); }
            else if (e.key === '2') { e.preventDefault(); ratingForms[1]?.submit(); }
            else if (e.key === '3') { e.preventDefault(); ratingForms[2]?.submit(); }
            else if (e.key === '4') { e.preventDefault(); ratingForms[3]?.submit(); }
            else if (e.key === 'f' || e.key === 'F') { e.preventDefault(); document.querySelector('form[action="/review/favorite"]')?.submit(); }
            else if (e.key === 'd' || e.key === 'D') { e.preventDefault(); document.querySelector('form[action="/review/delete"]')?.submit(); }
        });
    })();

    /* ── Settings page (CSP-safe, no inline handlers) ── */

    (function() {
        // Theme toggle sidebar button
        var themeBtn = document.getElementById('theme-toggle');
        if (themeBtn) {
            themeBtn.addEventListener('click', function(e) {
                e.preventDefault();
                if (window.toggleTheme) window.toggleTheme();
            });
        }

        // Mobile "More" button — triggers sidebar toggle
        var mobileMore = document.getElementById('mobile-more-btn');
        var sidebarToggle = document.getElementById('sidebar-toggle');
        if (mobileMore && sidebarToggle) {
            mobileMore.addEventListener('click', function(e) {
                e.preventDefault();
                sidebarToggle.click();
            });
        }

        // Settings page tab buttons — click delegation on the tab bar
        var tabBar = document.querySelector('.tab-bar');
        if (tabBar) {
            tabBar.addEventListener('click', function(e) {
                var btn = e.target.closest('[data-tab]');
                if (btn && window.switchTab) window.switchTab(btn.getAttribute('data-tab'));
            });
        }

        // Theme file input — show selected filename
        var themeFileInput = document.getElementById('theme-file-input');
        if (themeFileInput) {
            themeFileInput.addEventListener('change', function() {
                var label = document.getElementById('theme-file-name');
                if (label && this.files && this.files[0]) {
                    label.textContent = this.files[0].name;
                }
            });
        }

        // Theme selection buttons
        document.addEventListener('click', function(e) {
            var btn = e.target.closest('[data-action="set-theme"]');
            if (btn && window.setTheme) window.setTheme(btn.getAttribute('data-theme'));
        });

        // Universal data-action click delegation
        document.addEventListener('click', function(e) {
            var btn = e.target.closest('[data-action]');
            if (!btn) return;
            var action = btn.getAttribute('data-action');
            var hlId = btn.getAttribute('data-hl-id');

            // ── Settings page actions ──
            if (action === 'confirm-reset' && window.confirmReset) { e.preventDefault(); window.confirmReset(); }
            else if (action === 'dedup') { e.preventDefault(); window.runDedup(); }
            else if (action === 'save-cover-key' && window.saveCoverKey) { e.preventDefault(); window.saveCoverKey(); }
            else if (action === 'clear-cover-key' && window.clearCoverKey) { e.preventDefault(); window.clearCoverKey(); }
            else if (action === 'save-email' && window.saveEmailConfig) { e.preventDefault(); window.saveEmailConfig(); }
            else if (action === 'test-email' && window.sendTestEmail) { e.preventDefault(); window.sendTestEmail(); }
            else if (action === 'test-bookorbit' && window.testBookOrbit) { e.preventDefault(); window.testBookOrbit(); }
            else if (action === 'save-bookorbit' && window.saveBookOrbit) { e.preventDefault(); window.saveBookOrbit(); }
            else if (action === 'sync-bookorbit-now' && window.syncBookOrbitNow) { e.preventDefault(); window.syncBookOrbitNow(); }
            else if (action === 'revoke-token') {
                var name = btn.getAttribute('data-token-name') || 'this token';
                if (!confirm('Revoke token \'' + name + '\'? This will break the device until a new token is configured.')) {
                    e.preventDefault();
                }
            }
            // ── Highlights page actions ──
            else if (action === 'copy-text') { e.preventDefault(); e.stopPropagation(); var t = btn.getAttribute('data-text'); var l = btn.getAttribute('data-label') || 'Highlight'; if (window.copyText) window.copyText(t, l); }
            else if (action === 'toggle-fav' && hlId && window.toggleFav) { e.preventDefault(); window.toggleFav(hlId, btn); }
            else if (action === 'toggle-edit' && hlId && window.toggleEdit) { e.preventDefault(); window.toggleEdit(hlId); window.scrollToEdit(hlId); }
            else if (action === 'save-edit' && hlId && window.saveEdit) { e.preventDefault(); window.saveEdit(hlId); }
            else if (action === 'cancel-edit' && hlId && window.cancelEdit) { e.preventDefault(); window.cancelEdit(hlId); }
            else if (action === 'load-context' && hlId && window.loadContext) { e.preventDefault(); window.loadContext(hlId); }
            else if (action === 'delete-hl' && hlId && window.deleteHighlight) { e.preventDefault(); window.deleteHighlight(hlId); }
            // ── Books page actions ──
            else if (action === 'backfill-covers' && window.backfillCovers) { e.preventDefault(); window.backfillCovers(); }
            else if (action === 'rename-book' && window.renameBook) { e.preventDefault(); window.renameBook(btn); }
            else if (action === 'open-cover-selector' && window.openCoverSelector) { e.preventDefault(); window.openCoverSelector(btn); }
            else if (action === 'search-covers' && window.searchCoverSelector) { e.preventDefault(); window.searchCoverSelector(); }
            else if (action === 'close-cover-selector' && window.closeCoverSelector) { e.preventDefault(); window.closeCoverSelector(); }
            else if (action === 'open-metadata' && window.openMetadata) { e.preventDefault(); window.openMetadata(btn); }
            else if (action === 'upload-cover' && window.uploadCover) { e.preventDefault(); window.uploadCover(btn); }
            else if (action === 'close-rename-modal' && window.closeRenameModal) { e.preventDefault(); window.closeRenameModal(); }
            else if (action === 'close-metadata-modal' && window.closeMetadataModal) { e.preventDefault(); window.closeMetadataModal(); }
            else if (action === 'delete-book' && window.deleteBook) { e.preventDefault(); window.deleteBook(); }
            // ── Tags page actions ──
            else if (action === 'rename-tag' && window.renameTag) { e.preventDefault(); window.renameTag(btn); }
            else if (action === 'merge-tag' && window.mergeTag) { e.preventDefault(); window.mergeTag(btn); }
            else if (action === 'delete-tag' && window.deleteTag) { e.preventDefault(); window.deleteTag(btn); }
            else if (action === 'close-tag-rename' && window.closeTagRenameModal) { e.preventDefault(); window.closeTagRenameModal(); }
            else if (action === 'close-merge-modal' && window.closeMergeModal) { e.preventDefault(); window.closeMergeModal(); }
            // ── Dashboard actions ──
            else if (action === 'dash-fav' && hlId && window.toggleDashFav) { e.preventDefault(); window.toggleDashFav(hlId, btn); }
            // ── Review page actions ──
            else if (action === 'review-context' && hlId && window.showReviewContext) { e.preventDefault(); window.showReviewContext(hlId); }
            else if (action === 'close-review-context' && window.closeReviewContext) { window.closeReviewContext(e); }
            // ── Push notification actions ──
            else if (action === 'subscribe-push' && window.subscribePush) { e.preventDefault(); window.subscribePush().then(function(ok) { if (ok) { var btn = document.querySelector('[data-action=\"subscribe-push\"]'); if (btn) btn.style.display = 'none'; var ubtn = document.querySelector('[data-action=\"unsubscribe-push\"]'); if (ubtn) ubtn.style.display = ''; }}); }
            else if (action === 'unsubscribe-push' && window.unsubscribePush) { e.preventDefault(); window.unsubscribePush().then(function(ok) { if (ok) { var btn = document.querySelector('[data-action=\"unsubscribe-push\"]'); if (btn) btn.style.display = 'none'; var sbtn = document.querySelector('[data-action=\"subscribe-push\"]'); if (sbtn) sbtn.style.display = ''; }}); }
            // ── Theme selection ──
            else if (action === 'set-theme' && window.setTheme) { e.preventDefault(); window.setTheme(btn.getAttribute('data-theme')); }
            // ── Theme management ──
            else if (action === 'upload-theme' && window.uploadTheme) { e.preventDefault(); window.uploadTheme(); }
            else if (action === 'delete-theme' && window.deleteTheme) { e.preventDefault(); var tn = btn.getAttribute('data-theme-name'); if (tn) window.deleteTheme(tn); }
        });

        // Universal data-action change delegation
        document.addEventListener('change', function(e) {
            var el = e.target.closest('[data-action], [data-auto-submit]');
            if (!el) return;
            var action = el.getAttribute('data-action');

            if (action === 'toggle-select-all' && window.toggleSelectAll) { window.toggleSelectAll(); }
            else if (action === 'update-batch-bar' && window.updateBatchBar) { window.updateBatchBar(); }
            else if (action === 'submit-form') {
                var form = el.closest('form');
                if (form) form.submit();
            }
            else if (action === 'update-filename' && window.updateFileName) {
                window.updateFileName(el, el.getAttribute('data-display'));
            }
            else if (el.hasAttribute('data-auto-submit')) {
                var form = el.closest('form');
                if (form) form.submit();
            }
        });

        // Universal data-action submit delegation
        document.addEventListener('submit', function(e) {
            var form = e.target.closest('[data-action]');
            if (!form) return;
            var action = form.getAttribute('data-action');

            if (action === 'submit-rename' && window.submitRename) { e.preventDefault(); window.submitRename(e); }
            else if (action === 'submit-metadata' && window.submitMetadata) { e.preventDefault(); window.submitMetadata(e); }
            else if (action === 'submit-tag-rename' && window.submitTagRename) { e.preventDefault(); window.submitTagRename(e); }
            else if (action === 'submit-tag-merge' && window.submitMerge) { e.preventDefault(); window.submitMerge(e); }
            else if (action === 'confirm-delete') {
                if (!confirm('Delete this highlight? This cannot be undone.')) { e.preventDefault(); }
            }
        });

        // Confirm restore form submission
        var restoreForm = document.getElementById('restore-form');
        if (restoreForm) {
            restoreForm.addEventListener('submit', function(e) {
                if (window.confirmRestore) window.confirmRestore(e);
            });
        }

        // Review count slider live value display
        var reviewSlider = document.getElementById('review-count');
        var reviewVal = document.getElementById('review-count-value');
        if (reviewSlider && reviewVal) {
            reviewSlider.addEventListener('input', function() {
                reviewVal.textContent = this.value;
            });
        }
    })();

})();
