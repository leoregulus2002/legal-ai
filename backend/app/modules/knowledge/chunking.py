import re
from dataclasses import dataclass

from app.modules.knowledge.schemas import ParseResult


@dataclass
class Segment:
    start: int
    end: int
    node_id: str | None
    content: str


def split_document(result: ParseResult, mode: str, size: int = 1000) -> list[Segment]:
    boundaries = {0, len(result.text)}
    articles = sorted(
        (node for node in result.nodes if node.kind == "ARTICLE"), key=lambda n: n.start
    )
    if mode == "LEGAL":
        for article in articles:
            boundaries.update((article.start, article.end))
    points = sorted(boundaries)
    segments: list[Segment] = []
    article_index = 0
    for left, right in zip(points, points[1:], strict=False):
        while left < right:
            end = min(left + size, right)
            if end < right:
                candidates = list(
                    re.finditer(r"\n|[。；！？]", result.text[left + size // 2 : end])
                )
                if candidates:
                    end = left + size // 2 + candidates[-1].end()
            while article_index < len(articles) and articles[article_index].end <= left:
                article_index += 1
            article = articles[article_index] if article_index < len(articles) else None
            node_id = (
                article.id if article and article.start <= left and end <= article.end else None
            )
            content = result.text[left:end]
            if content.strip():
                segments.append(Segment(left, end, node_id, content))
            left = end
    return segments
