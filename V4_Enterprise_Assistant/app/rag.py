import logging
from io import BytesIO
from typing import List

from fastapi import UploadFile, HTTPException
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy.orm import Session

from app.config import settings
from app.models import DocumentChunk

logger = logging.getLogger(__name__)


def extract_text_from_upload(file: UploadFile, data: bytes) -> str:
    filename = (file.filename or "").lower()

    if filename.endswith(".pdf"):
        try:
            reader = PdfReader(BytesIO(data))
            pages = []
            for page in reader.pages:
                pages.append(page.extract_text() or "")
            return "\n".join(pages).strip()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"PDF 解析失败：{exc}")

    if filename.endswith(".txt") or filename.endswith(".md") or filename.endswith(".csv"):
        for encoding in ["utf-8", "gbk", "gb2312"]:
            try:
                return data.decode(encoding).strip()
            except UnicodeDecodeError:
                continue
        raise HTTPException(status_code=400, detail="文本文件编码无法识别，请保存为 UTF-8 后再上传")

    raise HTTPException(status_code=400, detail="暂时只支持上传 PDF、TXT、MD、CSV 文件")


def split_text(text: str, chunk_size: int = 800, overlap: int = 120) -> List[str]:
    text = "\n".join([line.strip() for line in text.splitlines() if line.strip()])
    if not text:
        return []

    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = min(start + chunk_size, text_length)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == text_length:
            break
        start = max(0, end - overlap)

    return chunks


def retrieve_chunks(question: str, chunks: List[DocumentChunk], top_k: int = 4) -> List[DocumentChunk]:
    if not chunks:
        return []

    corpus = [chunk.content for chunk in chunks]

    # 使用字符级 ngram，中文资料不分词也能做基础检索。
    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
    matrix = vectorizer.fit_transform(corpus + [question])

    question_vec = matrix[-1]
    doc_vecs = matrix[:-1]
    scores = cosine_similarity(question_vec, doc_vecs).flatten()

    ranked_indexes = scores.argsort()[::-1][:top_k]
    return [chunks[i] for i in ranked_indexes if scores[i] > 0]


def _load_user_chunks(db: Session, user_id: int) -> List[DocumentChunk]:
    """Load all chunks for a user from SQL (used as TF-IDF fallback input)."""
    return (
        db.query(DocumentChunk)
        .filter(DocumentChunk.user_id == user_id)
        .order_by(DocumentChunk.id.asc())
        .all()
    )


def retrieve_chunks_vector(
    db: Session,
    question: str,
    user_id: int,
    top_k: int = 4,
) -> List[DocumentChunk]:
    """Vector-based retrieval with graceful TF-IDF fallback.

    Degradation chain:
      1. VECTOR_SEARCH_ENABLED=False → immediate TF-IDF
      2. Vector store unavailable → TF-IDF
      3. Vector search returns incomplete results → TF-IDF merge
      4. Embedding / search error at query time → TF-IDF
    """
    # Layer 1: config switch
    if not settings.VECTOR_SEARCH_ENABLED:
        chunks = _load_user_chunks(db, user_id)
        return retrieve_chunks(question, chunks, top_k)

    try:
        from app.embeddings import get_embedding_service
        from app.vector_store import get_vector_store

        emb_svc = get_embedding_service()
        vs = get_vector_store()

        # Layer 2: vector store unavailable
        if vs is None:
            logger.info("Vector store unavailable, falling back to TF-IDF")
            chunks = _load_user_chunks(db, user_id)
            return retrieve_chunks(question, chunks, top_k)

        # Layer 3: actual vector search
        query_emb = emb_svc.embed_query(question)
        chunk_ids = vs.search(query_emb, user_id, top_k)

        # Layer 3a: vector search returned empty — check if vectors are incomplete
        if not chunk_ids:
            indexed = vs.count_user_chunks(user_id) if hasattr(vs, "count_user_chunks") else 0
            total_sql = (
                db.query(DocumentChunk)
                .filter(DocumentChunk.user_id == user_id)
                .count()
            )
            # If SQL has chunks but vector store doesn't (incomplete index), fall back
            if total_sql > 0 and indexed < total_sql:
                logger.info(
                    f"Vector index incomplete ({indexed}/{total_sql}), falling back to TF-IDF"
                )
                chunks = _load_user_chunks(db, user_id)
                return retrieve_chunks(question, chunks, top_k)
            return []

        # Layer 3b: vector search returned fewer than top_k — try TF-IDF merge
        if len(chunk_ids) < top_k:
            logger.info(
                f"Vector search returned only {len(chunk_ids)}/{top_k} results, "
                f"trying TF-IDF for completeness"
            )
            tfidf_chunks = retrieve_chunks(question, _load_user_chunks(db, user_id), top_k)
            # Merge: vector results first, then TF-IDF deduped
            seen = set(chunk_ids)
            for tc in tfidf_chunks:
                if tc.id not in seen:
                    chunk_ids.append(tc.id)
                    seen.add(tc.id)
                    if len(chunk_ids) >= top_k:
                        break

        # Fetch matching chunks preserving search rank order
        chunk_map = {
            c.id: c
            for c in db.query(DocumentChunk)
            .filter(DocumentChunk.id.in_(chunk_ids))
            .all()
        }
        return [chunk_map[cid] for cid in chunk_ids if cid in chunk_map]

    except Exception as exc:
        logger.warning(f"Vector search failed, falling back to TF-IDF: {exc}")
        chunks = _load_user_chunks(db, user_id)
        return retrieve_chunks(question, chunks, top_k)


def build_rag_prompt(question: str, retrieved_chunks: List[DocumentChunk]) -> str:
    references = []
    for idx, chunk in enumerate(retrieved_chunks, start=1):
        references.append(
            f"【资料{idx}】文件名：{chunk.filename}；片段序号：{chunk.chunk_index}\n{chunk.content}"
        )

    context = "\n\n".join(references)

    return f"""
你是一个 ToB 销售产品资料问答助手。
请严格根据下面的“知识库资料”回答用户问题。

要求：
1. 优先基于知识库资料回答，不要脱离资料胡编。
2. 如果资料中没有明确答案，要说明“资料中未明确提到”，并给出合理的销售追问建议。
3. 回答要适合销售人员使用，尽量具体、可执行。
4. 如果涉及产品推荐，请说明推荐依据。
5. 最后给出“可直接对客户说的话术”。

用户问题：
{question}

知识库资料：
{context}
"""
