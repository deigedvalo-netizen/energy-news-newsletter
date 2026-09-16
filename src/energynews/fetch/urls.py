from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def canonicalize_url(url: str) -> str:
    p = urlsplit(url.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
    path = p.path.rstrip("/") or ""
    return urlunsplit((p.scheme.lower() or "https", p.netloc.lower(), path, urlencode(q), ""))
