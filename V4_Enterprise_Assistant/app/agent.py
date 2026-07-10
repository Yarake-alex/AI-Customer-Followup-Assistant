from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import Customer, FollowUp, DocumentChunk
from app.rag import retrieve_chunks_vector
from app.llm import call_llm
from app.schemas import RagSource


def tool_get_customer_profile(db: Session, customer_id: int, user_id: int) -> Optional[Customer]:
    """
    Tool 1：查询客户基础信息。
    这里用函数形式模拟 Agent Tool，方便后续升级成真正 Tool Calling。
    """
    return (
        db.query(Customer)
        .filter(Customer.id == customer_id, Customer.user_id == user_id)
        .first()
    )


def tool_get_followup_records(db: Session, customer_id: int) -> List[FollowUp]:
    """
    Tool 2：查询客户历史跟进记录。
    """
    return (
        db.query(FollowUp)
        .filter(FollowUp.customer_id == customer_id)
        .order_by(FollowUp.created_at.asc())
        .all()
    )


def tool_retrieve_knowledge(db: Session, query: str, user_id: int, top_k: int = 4) -> List[DocumentChunk]:
    """
    Tool 3：从 RAG 知识库中检索相关资料片段。
    使用向量检索（自动降级到 TF-IDF）。
    """
    return retrieve_chunks_vector(db, query, user_id, top_k=top_k)


def build_followup_text(followups: List[FollowUp]) -> str:
    if not followups:
        return "暂无历史跟进记录"

    return "\n".join(
        [
            f"- 时间：{item.created_at.strftime('%Y-%m-%d %H:%M')}；"
            f"跟进内容：{item.content}；下一步动作：{item.next_action or '暂无'}"
            for item in followups
        ]
    )


def build_knowledge_text(chunks: List[DocumentChunk]) -> str:
    if not chunks:
        return "知识库中未检索到相关资料。"

    return "\n\n".join(
        [
            f"【资料{index}】文件名：{chunk.filename}；片段：{chunk.chunk_index}\n{chunk.content}"
            for index, chunk in enumerate(chunks, start=1)
        ]
    )


def build_agent_prompt(
    customer: Customer,
    followups: List[FollowUp],
    retrieved_chunks: List[DocumentChunk],
    task: str,
) -> str:
    followup_text = build_followup_text(followups)
    knowledge_text = build_knowledge_text(retrieved_chunks)

    return f"""
你是一个专业的 ToB 销售客户跟进 Agent。
你需要根据客户资料、历史跟进记录和知识库资料，生成一份完整的客户跟进分析方案。

用户任务：
{task}

客户基础信息：
客户姓名：{customer.name}
公司名称：{customer.company}
行业：{customer.industry or '未知'}
客户等级：{customer.level or '未设置'}
意向程度：{customer.intention or '未设置'}
合作状态：{customer.cooperation_status or '未设置'}
电话：{customer.phone or '未填写'}
邮箱：{customer.email or '未填写'}

历史跟进记录：
{followup_text}

检索到的知识库资料：
{knowledge_text}

请按下面结构输出：
1. 客户当前阶段判断
2. 客户需求与关注点总结
3. 知识库资料中可用于跟进的产品/方案依据
4. 当前风险点
5. 下一步跟进计划，按今天、明天、本周拆分
6. 可以直接复制给客户的销售话术
7. 如果资料不足，请说明还需要补充哪些信息

要求：
- 结论要具体，不要空泛。
- 要体现你参考了客户历史记录和知识库资料。
- 如果知识库没有相关资料，要明确说明，不要胡编。
"""


def run_customer_followup_agent(
    db: Session,
    customer_id: int,
    user_id: int,
    task: str,
) -> Tuple[List[str], str, List[RagSource]]:
    """
    轻量 Agent 主流程：
    1. 调用客户信息查询工具
    2. 调用历史跟进查询工具
    3. 调用知识库检索工具
    4. 构造 Agent Prompt
    5. 调用大模型生成跟进方案

    这个版本属于轻量 Agent Workflow，
    后续 V3.1 可以升级为真正 Tool Calling / 工具注册 / 自动规划。
    """
    steps = []

    customer = tool_get_customer_profile(db, customer_id, user_id)
    steps.append("Tool 1：查询客户基础信息")

    if not customer:
        raise ValueError("客户不存在")

    followups = tool_get_followup_records(db, customer_id)
    steps.append(f"Tool 2：查询历史跟进记录，共 {len(followups)} 条")

    retrieval_query = f"""
客户公司：{customer.company}
行业：{customer.industry or ''}
客户等级：{customer.level or ''}
意向程度：{customer.intention or ''}
合作状态：{customer.cooperation_status or ''}
用户任务：{task}
历史跟进：{build_followup_text(followups)}
"""

    retrieved_chunks = tool_retrieve_knowledge(db, retrieval_query, user_id=user_id, top_k=4)
    steps.append(f"Tool 3：检索知识库资料，命中 {len(retrieved_chunks)} 个相关片段")

    prompt = build_agent_prompt(
        customer=customer,
        followups=followups,
        retrieved_chunks=retrieved_chunks,
        task=task,
    )
    steps.append("Tool 4：整合客户信息、历史跟进和知识库资料，构造 Agent Prompt")

    result = call_llm(prompt, feature="agent_analyze", user_id=user_id, db=db)
    steps.append("Tool 5：调用大模型生成完整客户跟进方案")

    sources = [
        RagSource(
            filename=chunk.filename,
            chunk_index=chunk.chunk_index,
            content=chunk.content[:260],
        )
        for chunk in retrieved_chunks
    ]

    return steps, result, sources
