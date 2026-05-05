from io import BytesIO
from typing import List

from fastapi import UploadFile, HTTPException
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.models import DocumentChunk


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
