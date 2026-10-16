from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING
from unicodedata import normalize
from uuid import UUID

if TYPE_CHECKING:
    from jieba.posseg import POSTokenizer

LEXICAL_VERSION = 1
CANDIDATE_LIMIT = 50
RRF_K = 60


@dataclass(frozen=True)
class LexicalIndex:
    terms: dict[str, int]
    length: int


def lexical_tokens(text: str) -> list[str]:
    # 索引与查询共用规则；保留数字及“不、未”等单字，不按词性丢弃适用条件。
    return [
        word.word
        for word in tokenizer().cut(normalize("NFKC", text).casefold(), HMM=False)
        if any(char.isalnum() for char in word.word)
    ]


def lexical_indexes(contents: list[str]) -> list[LexicalIndex]:
    result = []
    for content in contents:
        counts = Counter(lexical_tokens(content))
        result.append(LexicalIndex(dict(counts), counts.total()))
    return result


def query_terms(query: str) -> list[str]:
    stop_words = STOP_WORDS | {
        "的",
        "了",
        "吗",
        "呢",
        "我",
        "你",
        "他",
        "她",
        "它",
        "我们",
        "他们",
        "这个",
        "那个",
        "请问",
        "一下",
        "一个",
        "一种",
    }
    return list(dict.fromkeys(word for word in lexical_tokens(query) if word not in stop_words))[
        :32
    ]


def reciprocal_rank_fusion(
    lexical: Sequence[UUID], vector: Sequence[UUID]
) -> list[tuple[UUID, float]]:
    scores: dict[UUID, float] = {}
    for ranking in (lexical, vector):
        for rank, chunk_id in enumerate(dict.fromkeys(ranking), 1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (RRF_K + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], str(item[0])))


# 问句中的常见泛指词不作为法律主题；只抽取用户实际输入的词语。
STOP_WORDS = {
    "什么",
    "如何",
    "怎么",
    "为何",
    "为什么",
    "多少",
    "多久",
    "是否",
    "能否",
    "可以",
    "需要",
    "应该",
    "问题",
    "情况",
    "法律",
    "规定",
    "相关",
    "哪些",
    "时候",
    "事情",
    "方式",
    "方法",
}


@lru_cache(maxsize=1)
def tokenizer() -> "POSTokenizer":
    # 字典的文件读取和首次初始化全部在调用线程执行，不阻塞异步请求。
    import jieba
    import jieba.posseg

    jieba.setLogLevel(30)
    return jieba.posseg.POSTokenizer(jieba.Tokenizer())


def keyword_query(query: str) -> str:
    words = list(tokenizer().cut(query, HMM=False))
    nouns = [word.word for word in words if word.flag.startswith("n") or word.flag == "eng"]
    values = [word for word in nouns if len(word) >= 2 and word not in STOP_WORDS]
    if not values:
        values = [
            word.word
            for word in words
            if word.flag.startswith("v") and len(word.word) >= 2 and word.word not in STOP_WORDS
        ]
    if not values:
        return query.strip()
    counts = Counter(values)
    # 高频主题优先，最多八个实词；不生成任何未在问题中出现的检索词。
    ranked = sorted(counts, key=lambda word: (-counts[word], -len(word), query.index(word)))
    return " ".join(ranked[:8])
