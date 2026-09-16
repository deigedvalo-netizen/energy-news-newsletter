"""Clusterer (FR-5): deterministic TF-IDF cosine + shared commodity + time window, union-find."""
from __future__ import annotations
from collections import Counter
from decimal import Decimal
import hashlib
import re
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from ..models import Article, Cluster

SYN = {"fell": "down", "fall": "down", "falls": "down", "drop": "down", "drops": "down", "dropped": "down", "declin": "down",
       "slid": "down", "slump": "down", "lower": "down", "rose": "up", "rise": "up", "rises": "up", "climb": "up", "gain": "up",
       "jump": "up", "higher": "up", "increas": "up", "stockpil": "inventori", "stock": "inventori", "invent": "inventori",
       "output": "product", "bpd": "barrel", "says": "", "said": "", "report": "", "weekly": "week"}
STOP = {"the", "a", "an", "of", "in", "on", "to", "for", "by", "and", "or", "as", "at", "is", "are", "was", "were", "be", "with",
        "from", "its", "it", "that", "this", "after", "amid", "over", "last", "new", "us", "u.s"}
TOKEN = re.compile(r"\d+(?:\.\d+)?|[a-z][a-z+]+")


def _stem(w: str) -> str:
    for suf in ("ies", "ing", "ed", "es", "s"):
        if len(w) > 4 and w.endswith(suf):
            w = w[: -len(suf)] + ("i" if suf == "ies" else "")
            break
    return w


def analyze(text: str) -> list[str]:
    out = []
    for t in TOKEN.findall(text.lower()):
        if t in STOP:
            continue
        w = SYN.get(t, None)
        if w is None:
            st = _stem(t)
            w = SYN.get(st, SYN.get(st[:6], st))
        if w:
            out.append(w)
    return out


def cluster_articles(articles: list[Article], threshold: Decimal = Decimal("0.35"), window_hours: int = 72) -> list[Cluster]:
    arts = sorted((a for a in articles if a.status == "OK" and a.published_at and a.commodities and a.topic),
                  key=lambda a: (a.published_at, a.article_id))
    n = len(arts)
    if n == 0:
        return []
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    if n > 1:
        docs = [f"{a.title} {a.title} {a.excerpt}" for a in arts]
        m = TfidfVectorizer(analyzer=analyze, sublinear_tf=True).fit_transform(docs)
        sim = cosine_similarity(m)
        thr = float(threshold)
        for i in range(n):
            for j in range(i + 1, n):
                if (arts[j].published_at - arts[i].published_at).total_seconds() > window_hours * 3600:
                    break
                if sim[i, j] >= thr and arts[i].commodities & arts[j].commodities:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[max(ri, rj)] = min(ri, rj)
    groups: dict[int, list[Article]] = {}
    for i, a in enumerate(arts):
        groups.setdefault(find(i), []).append(a)
    out = []
    for members in groups.values():
        ids = sorted(a.article_id for a in members)
        topics = Counter(a.topic for a in members)
        top_n = max(topics.values())
        topic = next(a.topic for a in members if topics[a.topic] == top_n)  # tie -> earliest article
        comms = frozenset().union(*(a.commodities for a in members))
        out.append(Cluster(
            cluster_id=hashlib.sha1("|".join(ids).encode()).hexdigest()[:12], article_ids=ids, commodities=comms,
            topic=topic, first_published_at=members[0].published_at,
            distinct_source_count=len({a.source_id for a in members}), title=members[0].title))
    return sorted(out, key=lambda c: (c.first_published_at, c.cluster_id))
