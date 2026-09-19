import html
import re
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime


def _titulo_curto(title, limit=92):
    clean = re.sub(r"\s+[-|–—]\s+[^-|–—]+$", "", title).strip()
    return clean if len(clean) <= limit else clean[:limit - 1].rstrip() + "…"


def _topic_slug(value):
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_value = "".join(char for char in normalized if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")


def _rss_source_urls(query, include_primary=False, topic=None):
    encoded = urllib.parse.quote_plus(query)
    urls = [
        ("Google News", f"https://news.google.com/rss/search?q={encoded}&hl=pt-BR&gl=BR&ceid=BR:pt-419"),
        ("Bing News", f"https://www.bing.com/news/search?q={encoded}&format=rss"),
        ("Yahoo News", f"https://news.yahoo.com/rss/search?p={encoded}"),
        ("Reddit", f"https://www.reddit.com/search.rss?q={encoded}&sort=new"),
    ]
    topic_slug = _topic_slug(topic)
    if topic_slug:
        urls.extend([
            ("Flipboard", f"https://flipboard.com/topic/{topic_slug}.rss"),
            ("TecMundo", "https://www.tecmundo.com.br/rss"),
        ])
    if include_primary:
        urls.extend([
            ("G1", "https://g1.globo.com/rss/g1/"),
            ("UOL", "https://rss.uol.com.br/feed/noticias.xml"),
        ])
    return urls


def _parse_feed_date(value):
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except (TypeError, ValueError, OverflowError):
            return None


def buscar_itens_rss(query, categoria, limit=3, semantic_score=50, include_primary=False, topic=None):
    items = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    seen_links = set()
    for provider, url in _rss_source_urls(query, include_primary=include_primary, topic=topic):
        try:
            headers = {"User-Agent": "GrowthEngine/1.0 (local radar)"}
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=12) as response:
                root = ET.fromstring(response.read())
        except Exception:
            continue
        provider_items = 0
        feed_items = root.findall("./channel/item") or root.findall(".//item")
        for item in feed_items[:10]:
            title = html.unescape(item.findtext("title", "")).strip()
            link = item.findtext("link", "").strip()
            published = (item.findtext("pubDate", "").strip()
                         or item.findtext("published", "").strip()
                         or item.findtext("updated", "").strip()
                         or item.findtext("date", "").strip())
            source = item.findtext("source", "").strip() or provider
            if not title or not link or link in seen_links:
                continue
            published_at = _parse_feed_date(published)
            if not published_at or published_at < cutoff:
                continue
            seen_links.add(link)
            map_query = f"{title} {query}"
            items.append({
                "titulo": title,
                "titulo_curto": _titulo_curto(title),
                "link": link,
                "fonte": source,
                "provedor_rss": provider,
                "publicado_em": published,
                "categoria": categoria,
                "motivo": f"Relacionada a: {query}",
                "confianca": "verificar fonte original",
                "mapa_url": "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote_plus(map_query),
                "coordenadas": None,
                "relevancia_score": semantic_score,
            })
            provider_items += 1
            if provider_items >= 2:
                break
    return items[:limit]
