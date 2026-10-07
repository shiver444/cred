"""
Small security helpers for the API server: rate limiting and CSRF.

Everything here is in-memory on purpose. The app runs as ONE gunicorn
worker (see railway.json), so one process sees every request and a
database or Redis would be extra moving parts for nothing. The counters
reset when the app restarts, which is fine: they only need to slow down
guessing and flooding, not keep a permanent record.
"""

import hmac
import secrets
import threading
import time
from collections import deque


class SlidingLimiter:
    """Allow at most `limit` hits per `window` seconds for each key."""

    def __init__(self):
        self._lock = threading.Lock()
        self._hits = {}          # key -> deque of timestamps

    def hit(self, key, limit, window, now=None):
        """Record one hit. Returns (allowed, retry_after_seconds)."""
        now = time.time() if now is None else now
        with self._lock:
            q = self._hits.setdefault(key, deque())
            cutoff = now - window
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= limit:
                return False, max(1, int(q[0] + window - now) + 1)
            q.append(now)
            if len(self._hits) > 5000:
                self._purge(now, window)
            return True, 0

    def _purge(self, now, window):
        # Called with the lock held. Drops keys with nothing recent in them
        # so a flood of different addresses cannot grow memory without end.
        for k in [k for k, q in self._hits.items() if not q or q[-1] <= now - window]:
            del self._hits[k]

    def reset(self):
        with self._lock:
            self._hits.clear()


class LoginGuard:
    """Locks out repeated wrong admin passwords.

    Two layers: one counter per client address, and one for the whole site.
    The per-address one stops a single guesser. The site-wide one is the
    backstop for a guesser who keeps changing the address they appear to
    come from. While a lock is on, even the right password is refused,
    otherwise the guessing could simply carry on through the lock."""

    def __init__(self, max_fails=5, window=15 * 60, lock_for=15 * 60,
                 global_max_fails=60):
        self.max_fails = max_fails
        self.window = window
        self.lock_for = lock_for
        self.global_max_fails = global_max_fails
        self._lock = threading.Lock()
        self._fails = {}         # key -> list of failure timestamps
        self._locked_until = {}  # key -> timestamp
        self._global_fails = []
        self._global_locked_until = 0.0

    def seconds_locked(self, key, now=None):
        """0 when attempts are allowed, otherwise seconds left on the lock."""
        now = time.time() if now is None else now
        with self._lock:
            left = max(self._locked_until.get(key, 0), self._global_locked_until) - now
            return max(0, int(left) + 1) if left > 0 else 0

    def fail(self, key, now=None):
        now = time.time() if now is None else now
        with self._lock:
            cutoff = now - self.window
            fails = [t for t in self._fails.get(key, []) if t > cutoff]
            fails.append(now)
            self._fails[key] = fails
            if len(fails) >= self.max_fails:
                self._locked_until[key] = now + self.lock_for
                self._fails[key] = []
            self._global_fails = [t for t in self._global_fails if t > cutoff]
            self._global_fails.append(now)
            if len(self._global_fails) >= self.global_max_fails:
                self._global_locked_until = now + self.lock_for
                self._global_fails = []
            if len(self._fails) > 2000:
                self._purge(now)

    def success(self, key):
        with self._lock:
            self._fails.pop(key, None)
            self._locked_until.pop(key, None)

    def _purge(self, now):
        cutoff = now - self.window
        for k in [k for k, v in self._fails.items() if not v or v[-1] <= cutoff]:
            del self._fails[k]
        for k in [k for k, t in self._locked_until.items() if t <= now]:
            del self._locked_until[k]

    def reset(self):
        with self._lock:
            self._fails.clear()
            self._locked_until.clear()
            self._global_fails = []
            self._global_locked_until = 0.0


def same_secret(supplied, expected):
    """Constant-time comparison for passwords / API secrets."""
    if not supplied or not expected:
        return False
    return hmac.compare_digest(str(supplied).encode("utf-8"),
                               str(expected).encode("utf-8"))


# ── CSRF ──
# The admin pages are driven by a login cookie, and a cookie is sent by the
# browser no matter which site made the request. A token that only our own
# pages know closes that gap: every state-changing admin request must carry
# the token stored in the session.

def csrf_token(sess):
    tok = sess.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        sess["csrf"] = tok
    return tok


def csrf_ok(sess, supplied):
    want = sess.get("csrf")
    if not want or not supplied:
        return False
    return hmac.compare_digest(str(want).encode("utf-8"), str(supplied).encode("utf-8"))


# Added to every admin page. It puts the token on every same-site POST made
# by the page (fetch, XMLHttpRequest and ordinary forms), so each page does
# not have to be taught about it one by one.
_CSRF_JS = """<meta name="csrf-token" content="__TOKEN__">
<script id="csrf-helper">(function(){
var T=document.querySelector('meta[name="csrf-token"]').content;
function same(u){try{return new URL(u,location.href).origin===location.origin}catch(e){return false}}
function writes(m){m=String(m||'GET').toUpperCase();return m!=='GET'&&m!=='HEAD'&&m!=='OPTIONS'}
var F=window.fetch;
if(F){window.fetch=function(i,o){
 try{var m=(o&&o.method)||(i&&i.method)||'GET';
  var u=(typeof i==='string')?i:((i&&i.url)||String(i));
  if(writes(m)&&same(u)){o=o||{};var h=new Headers(o.headers||(i&&i.headers)||{});h.set('X-CSRF-Token',T);o.headers=h}
 }catch(e){}
 return F.call(this,i,o)}}
var X=window.XMLHttpRequest&&XMLHttpRequest.prototype;
if(X){var O=X.open,S=X.send;
 X.open=function(m,u){this._cm=m;this._cu=u;return O.apply(this,arguments)};
 X.send=function(){try{if(writes(this._cm)&&same(this._cu))this.setRequestHeader('X-CSRF-Token',T)}catch(e){}return S.apply(this,arguments)}}
function addTo(f){try{
 if(String(f.getAttribute('method')||'get').toLowerCase()!=='post')return;
 if(!same(f.getAttribute('action')||location.href))return;
 if(f.querySelector('input[name="csrf_token"]'))return;
 var i=document.createElement('input');i.type='hidden';i.name='csrf_token';i.value=T;f.appendChild(i)}catch(e){}}
document.addEventListener('submit',function(e){addTo(e.target)},true);
document.addEventListener('DOMContentLoaded',function(){var l=document.querySelectorAll('form');for(var k=0;k<l.length;k++)addTo(l[k])});
})();</script>"""


def inject_csrf(html, token):
    """Put the CSRF helper at the top of an admin page's <head>."""
    snippet = _CSRF_JS.replace("__TOKEN__", token)
    low = html.lower()
    i = low.find("<head")
    if i != -1:
        j = html.find(">", i)
        if j != -1:
            return html[:j + 1] + "\n" + snippet + html[j + 1:]
    return snippet + html
