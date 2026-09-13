"""本地 Markdown RAG：标题感知切块、特征哈希向量、余弦检索与缓存。"""

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path


VECTOR_SIZE = 512
MAX_CHUNK_CHARS = 900
CHUNK_OVERLAP_CHARS = 120


@dataclass
class DocumentChunk:
    chunk_id: str
    source: str
    section: str
    line_start: int
    line_end: int
    content: str
    vector: list[float]


def _tokens(text: str) -> list[str]:
    """提取英文单词、代码标识符，以及中文单字和双字组合。"""
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9_./-]+", lowered)
    for sequence in re.findall(r"[\u4e00-\u9fff]+", lowered):
        tokens.extend(sequence)
        tokens.extend(sequence[index:index + 2] for index in range(len(sequence) - 1))
    return tokens


def _embed(text: str) -> list[float]:
    """用稳定哈希把词映射到固定维向量；不需要模型或网络。"""
    vector = [0.0] * VECTOR_SIZE
    for token in _tokens(text):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        number = int.from_bytes(digest, "big")
        index = number % VECTOR_SIZE
        sign = 1.0 if number & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _identifier_overlap(query: str, document: str) -> float:
    """提高错误码和配置键的权重，避免中文泛词淹没精确标识符。"""
    query_identifiers = set(re.findall(r"[a-z][a-z0-9_./-]{2,}", query.lower()))
    if not query_identifiers:
        return 0.0
    document_identifiers = set(
        re.findall(r"[a-z][a-z0-9_./-]{2,}", document.lower())
    )
    return len(query_identifiers & document_identifiers) / len(query_identifiers)


def _window(text: str) -> list[tuple[int, str]]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [(0, text)]
    step = MAX_CHUNK_CHARS - CHUNK_OVERLAP_CHARS
    return [
        (start, text[start:start + MAX_CHUNK_CHARS])
        for start in range(0, len(text), step)
    ]


def split_markdown(path: Path, project_root: Path) -> list[DocumentChunk]:
    """按 Markdown 标题分段，过长章节再滑窗切分。"""
    lines = path.read_text(encoding="utf-8").splitlines()
    sections: list[tuple[str, int, list[str]]] = []
    heading, line_start, buffer = "文档开头", 1, []
    for line_number, line in enumerate(lines, 1):
        if re.match(r"^#{1,6}\s+", line):
            if any(item.strip() for item in buffer):
                sections.append((heading, line_start, buffer))
            heading = re.sub(r"^#{1,6}\s+", "", line).strip()
            line_start, buffer = line_number, [line]
        else:
            buffer.append(line)
    if any(item.strip() for item in buffer):
        sections.append((heading, line_start, buffer))

    chunks: list[DocumentChunk] = []
    source = path.relative_to(project_root).as_posix()
    for section, start, section_lines in sections:
        content = "\n".join(section_lines).strip()
        for part_number, (character_start, part) in enumerate(_window(content), 1):
            part_line_start = start + content[:character_start].count("\n")
            part_line_end = part_line_start + part.count("\n")
            chunk_id = hashlib.sha256(
                f"{source}:{section}:{part_number}:{part}".encode("utf-8")
            ).hexdigest()[:16]
            chunks.append(DocumentChunk(
                chunk_id=chunk_id,
                source=source,
                section=section,
                line_start=part_line_start,
                line_end=part_line_end,
                content=part,
                vector=_embed(f"{section}\n{part}"),
            ))
    return chunks


class LocalDocumentIndex:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.knowledge_dirs = [
            project_root / "knowledge",
            project_root / "demo_app" / "docs",
        ]
        self.cache_path = project_root / ".incident_cache" / "rag_index.json"

    def _files(self) -> list[Path]:
        files = [
            path
            for directory in self.knowledge_dirs
            if directory.exists()
            for path in directory.rglob("*.md")
        ]
        return sorted(files)

    def _fingerprint(self, files: list[Path]) -> str:
        digest = hashlib.sha256()
        for path in files:
            digest.update(path.relative_to(self.project_root).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def _build(self, files: list[Path], fingerprint: str) -> list[DocumentChunk]:
        chunks = [chunk for path in files for chunk in split_markdown(path, self.project_root)]
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"fingerprint": fingerprint, "chunks": [asdict(chunk) for chunk in chunks]}
        self.cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return chunks

    def load(self) -> tuple[list[DocumentChunk], bool]:
        files = self._files()
        fingerprint = self._fingerprint(files)
        if self.cache_path.exists():
            try:
                payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
                if payload.get("fingerprint") == fingerprint:
                    return [DocumentChunk(**item) for item in payload["chunks"]], True
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass
        return self._build(files, fingerprint), False

    def search(self, query: str, top_k: int) -> tuple[list[dict], bool, int]:
        chunks, cache_hit = self.load()
        query_vector = _embed(query)
        ranked = sorted(
            (
                (
                    max(0.0, _cosine(query_vector, chunk.vector))
                    + _identifier_overlap(query, f"{chunk.section}\n{chunk.content}"),
                    chunk,
                )
                for chunk in chunks
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        results = [
            {
                "chunk_id": chunk.chunk_id,
                "source": chunk.source,
                "section": chunk.section,
                "line_start": chunk.line_start,
                "line_end": chunk.line_end,
                "content": chunk.content,
                "score": round(score, 4),
            }
            for score, chunk in ranked[:top_k]
            if score > 0
        ]
        return results, cache_hit, len(chunks)
