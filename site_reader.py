"""
Credential Protocol: read the colors and type of the creator's own website.

Used by the Emails screen's "Match my website" button. The creator types their
website address; this module fetches that one page (and up to three of its
stylesheets), finds the page color, the text color, an accent color and whether
the type is serif, sans-serif or monospaced, and hands back plain values. Those
values are saved like any other setting, so emails never depend on the website
being up, and nothing is fetched when an email is sent.

Safety: this server fetches an address someone typed, so it refuses anything
that is not an ordinary public website: only http/https on ports 80/443, the
name must resolve only to public internet addresses (never this machine, a
private network or a cloud metadata address), the connection goes to the very
address that was checked (so a name cannot change its answer in between), at
most 3 redirects each re-checked the same way, a short timeout, and a size cap
on every download. Nothing from the page is ever kept except the few colors.
"""

import http.client
import ipaddress
import re
import socket
import ssl
import time
from urllib.parse import urljoin, urlsplit

import email_look

TIMEOUT = 6                 # seconds for each connection and read
MAX_BYTES = 400_000         # per download
MAX_STYLESHEETS = 3
MAX_REDIRECTS = 3
TOTAL_SECONDS = 15          # for everything together
UA = "CredentialProtocol-ColorReader/1.0 (+reads page colors only)"

# Tests switch this on to read a page on this computer. Never set in the app.
_allow_private = False


class SiteError(Exception):
    """Something the creator can be told in plain words."""


# ── safe fetching ──
def _public(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if getattr(a, "ipv4_mapped", None):
        a = a.ipv4_mapped
    return a.is_global and not a.is_multicast


def _resolve(host: str, port: int) -> str:
    """One checked address for `host`. Every address the name resolves to must be public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        raise SiteError("That website address could not be found. Check the spelling.")
    ips = [i[4][0] for i in infos]
    if not ips:
        raise SiteError("That website address could not be found. Check the spelling.")
    if not _allow_private and not all(_public(ip) for ip in ips):
        raise SiteError("That address is not a public website.")
    return ips[0]


class _Pinned(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedTLS(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def fetch(url: str, deadline: float = None):
    """(final_url, text) of a public page, or raise SiteError."""
    deadline = deadline or (time.time() + TOTAL_SECONDS)
    for _hop in range(MAX_REDIRECTS + 1):
        if time.time() > deadline:
            raise SiteError("The website took too long to answer.")
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise SiteError("Type a website address that starts with https://")
        if parts.username or parts.password:
            raise SiteError("Type the plain address, without a name or password in it.")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if port not in (80, 443) and not _allow_private:
            raise SiteError("Only ordinary website addresses (port 80 or 443) can be read.")
        ip = _resolve(parts.hostname, port)
        conn = (_PinnedTLS if parts.scheme == "https" else _Pinned)(parts.hostname, port, ip, TIMEOUT)
        path = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
        try:
            conn.request("GET", path, headers={"Host": parts.netloc, "User-Agent": UA, "Accept": "text/html,text/css,*/*;q=0.5",
                                               "Accept-Encoding": "identity", "Connection": "close"})
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308) and resp.getheader("Location"):
                url = urljoin(url, resp.getheader("Location"))
                continue
            if resp.status != 200:
                raise SiteError(f"The website answered with an error ({resp.status}).")
            ctype = (resp.getheader("Content-Type") or "").lower()
            if ctype and not any(t in ctype for t in ("text/", "html", "css", "xml")):
                raise SiteError("That address is not a web page.")
            raw = resp.read(MAX_BYTES + 1)[:MAX_BYTES]
        except SiteError:
            raise
        except (OSError, http.client.HTTPException, ssl.SSLError):
            raise SiteError("The website could not be reached. Check the address.")
        finally:
            try:
                conn.close()
            except Exception:
                pass
        enc = "utf-8"
        m = re.search(r"charset=([\w-]+)", ctype)
        if m:
            enc = m.group(1)
        try:
            return url, raw.decode(enc, "replace")
        except LookupError:
            return url, raw.decode("utf-8", "replace")
    raise SiteError("The website sent us around in circles (too many redirects).")


# ── understanding the page ──
_NAMED = {"white": "#ffffff", "black": "#000000", "red": "#ff0000", "blue": "#0000ff", "green": "#008000",
          "orange": "#ffa500", "yellow": "#ffff00", "purple": "#800080", "gray": "#808080", "grey": "#808080",
          "navy": "#000080", "teal": "#008080", "pink": "#ffc0cb", "silver": "#c0c0c0"}


def _hsl(h, s, l):
    h = (h % 360) / 360.0
    def f(n):
        k = (n + h * 12) % 12
        a = s * min(l, 1 - l)
        return l - a * max(-1, min(k - 3, 9 - k, 1))
    return email_look._hex(f(0) * 255, f(8) * 255, f(4) * 255)


def parse_color(value):
    """The first plain color in a CSS value as #rrggbb, or "" (no gradients, images or var())."""
    v = str(value or "").strip().lower()
    if not v or "gradient" in v:
        return ""
    m = re.search(r"#([0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{3})\b", v)
    if m:
        h = m.group(1)
        if len(h) == 8:
            if int(h[6:], 16) < 0x80:
                return ""                      # mostly transparent
            h = h[:6]
        return email_look.clean_hex(h)
    m = re.search(r"rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)", v)
    if m:
        a = m.group(4)
        if a is not None:
            af = float(a.rstrip("%")) / (100.0 if a.endswith("%") else 1.0)
            if af < 0.5:
                return ""
        return email_look._hex(float(m.group(1)), float(m.group(2)), float(m.group(3)))
    m = re.search(r"hsla?\(\s*([\d.]+)(?:deg)?[ ,]+([\d.]+)%[ ,]+([\d.]+)%", v)
    if m:
        return _hsl(float(m.group(1)), float(m.group(2)) / 100.0, float(m.group(3)) / 100.0)
    w = re.match(r"^([a-z]+)\b", v)
    if w and w.group(1) in _NAMED:
        return _NAMED[w.group(1)]
    return ""


def _strip_at_blocks(css: str) -> str:
    """Remove @media/@supports/@font-face... blocks (dark-mode or phone-only rules would mislead us)."""
    out, i, n = [], 0, len(css)
    while i < n:
        j = css.find("@", i)
        if j < 0:
            out.append(css[i:])
            break
        out.append(css[i:j])
        k = j
        while k < n and css[k] not in "{;":
            k += 1
        if k < n and css[k] == "{":
            depth = 1
            k += 1
            while k < n and depth:
                depth += (css[k] == "{") - (css[k] == "}")
                k += 1
        else:
            k += 1
        i = k
    return "".join(out)


def _rules(css: str):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = _strip_at_blocks(css)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sels = [x.strip().lower() for x in m.group(1).split(",")]
        props = {}
        for decl in m.group(2).split(";"):
            if ":" in decl:
                k, v = decl.split(":", 1)
                props[k.strip().lower()] = v.strip()
        yield sels, props


def _var_color(value, variables, depth=0):
    value = str(value or "")
    m = re.search(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]*))?\)", value)
    if m and depth < 4:
        inner = variables.get(m.group(1).lower())
        if inner:
            return _var_color(inner, variables, depth + 1)
        return parse_color(m.group(2) or "")
    return parse_color(value)


def font_group(family: str) -> str:
    f = str(family or "").lower()
    first = f.split(",")[0]
    if re.search(r"mono|courier|consolas|menlo|code|typewriter", first):
        return "mono"
    if re.search(r"georgia|times|garamond|palatino|baskerville|playfair|merriweather|lora|cormorant|crimson|libre bask|"
                 r"pt serif|noto serif|source serif|dm serif|bodoni|didot|cambria|serif", first) and "sans" not in first:
        return "serif"
    if first.strip() in ("serif", "ui-serif"):
        return "serif"
    if not first.strip():
        return ""
    return "sans"


def analyse(html: str, css_texts=()) -> dict:
    """Colors and type from a page's HTML and its stylesheets' text.
    Returns {bg, text, accent, font, found: [...]}; a value not found is ""."""
    html = html or ""
    variables, body, link_color, root_font = {}, {}, "", ""
    sheets = list(re.findall(r"<style[^>]*>(.*?)</style>", html, flags=re.S | re.I)) + list(css_texts or ())
    for css in sheets:
        for sels, props in _rules(css):
            for k, v in props.items():
                if k.startswith("--") and any(s in (":root", "html", "body") for s in sels):
                    variables.setdefault(k, v)
            if any(s in ("body", "html", ":root") for s in sels):
                for k in ("background", "background-color", "color", "font-family"):
                    if k in props:
                        body.setdefault(k, props[k])
                if "font" in props and "font-family" not in props:      # the shorthand: "16px/1.5 Arial, sans-serif"
                    m2 = re.search(r"\d(?:px|pt|em|rem|%)(?:/[\d.]+\w*)?\s+(.+)$", props["font"])
                    if m2:
                        body.setdefault("font-family", m2.group(1))
            if any(s in ("a", "a:link") for s in sels) and "color" in props and not link_color:
                link_color = _var_color(props["color"], variables)
    tag = re.search(r"<body[^>]*\sstyle=[\"']([^\"']*)", html, flags=re.I)
    if tag:
        for decl in tag.group(1).split(";"):
            if ":" in decl:
                k, v = decl.split(":", 1)
                body[k.strip().lower()] = v.strip()      # an inline style on <body> wins

    bg = _var_color(body.get("background-color") or body.get("background") or "", variables)
    text = _var_color(body.get("color") or "", variables)
    font = font_group(re.sub(r"var\([^)]*\)", "", body.get("font-family") or "")) or font_group(
        variables.get("--font-body", "") or variables.get("--font-family", "") or variables.get("--font", ""))

    accent = ""
    for pat in (r'<meta[^>]+name=["\']theme-color["\'][^>]*content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*name=["\']theme-color["\']'):
        m = re.search(pat, html, flags=re.I)
        if m:
            accent = parse_color(m.group(1))
            if accent:
                break
    if not accent:
        for want in ("primary", "accent", "brand", "main", "highlight", "link", "theme"):
            for k, v in variables.items():
                if want in k and not any(x in k for x in ("font", "radius", "size", "width", "shadow", "space")):
                    c = _var_color(v, variables)
                    if c:
                        accent = c
                        break
            if accent:
                break
    if not accent:
        accent = link_color

    found = [n for n, v in (("page color", bg), ("text color", text), ("accent color", accent), ("type style", font)) if v]
    return {"bg": bg, "text": text, "accent": accent, "font": font, "found": found}


def _stylesheet_urls(html: str, base: str):
    urls = []
    for tag in re.findall(r"<link\b[^>]*>", html, flags=re.I):
        if re.search(r'rel=["\']?[^"\'>]*stylesheet', tag, flags=re.I):
            m = re.search(r'href=["\']([^"\']+)', tag, flags=re.I)
            if m:
                urls.append(urljoin(base, m.group(1).replace("&amp;", "&")))
    return urls[:MAX_STYLESHEETS]


def finish(found: dict, brand_accent: str = "") -> dict:
    """Fill the gaps and make sure the colors can be read together."""
    bg, text, accent, font = found.get("bg", ""), found.get("text", ""), found.get("accent", ""), found.get("font", "")
    if not bg:
        bg = "#111111" if (text and email_look.luminance(text) > 0.6) else "#ffffff"
    if not text or email_look.contrast(text, bg) < 4.5:
        text = email_look.text_on(bg)
    accent = accent or email_look.clean_hex(brand_accent, email_look.DEFAULT_ACCENT)
    return {"email_bg": bg, "email_text": text, "email_accent": accent, "email_font": font or "sans"}


def read_site(url: str, brand_accent: str = "") -> dict:
    """The look of a public website: {"ok": True, settings..., "found": [...], "missing": [...], "site": url}.
    Raises SiteError with a plain-words message."""
    url = email_look.clean_url(url)
    if not url:
        raise SiteError("Type your website address, starting with https://")
    deadline = time.time() + TOTAL_SECONDS
    final, html = fetch(url, deadline)
    sheets = []
    for sheet_url in _stylesheet_urls(html, final):
        try:
            sheets.append(fetch(sheet_url, deadline)[1])
        except SiteError:
            continue
    found = analyse(html, sheets)
    out = finish(found, brand_accent)
    out.update({"ok": True, "found": found["found"], "site": final,
                "missing": [n for n in ("page color", "text color", "accent color", "type style") if n not in found["found"]]})
    return out
