from openai import OpenAI
from app.config import settings


def build_customer_context(customer, followups):
    records = "\n".join(
        [
            f"- 时间：{f.created_at.strftime('%Y-%m-%d %H:%M')}；内容：{f.content}；下一步：{f.next_action or '暂无'}"
            for f in followups
        ]
    ) or "暂无跟进记录"

    return f"""
客户姓名：{customer.name}
公司名称：{customer.company}
行业：{customer.industry or '未知'}
客户等级：{customer.level or '未设置'}
意向程度：{customer.intention or '未设置'}
合作状态：{customer.cooperation_status or '未设置'}
电话：{customer.phone or '未填写'}
邮箱：{customer.email or '未填写'}

历史跟进记录：
{records}
"""


def call_llm(prompt: str) -> str:
    """
    没有 API Key 时走 mock 模式，方便先完成项目展示。
    DeepSeek、通义、智谱、OpenAI 等 OpenAI 兼容接口都可以接入。
    """
    if settings.LLM_PROVIDER != "openai_compatible" or not settings.OPENAI_API_KEY:
        return mock_llm_response(prompt)

    client = OpenAI(
        api_key=settings.OPENAI_API_KEY,
        base_url=settings.OPENAI_BASE_URL
    )

    response = client.chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=[
            {
                "role": "system",
                "content": "你是一个专业的 ToB 销售客户跟进助手，回答要具体、可执行、适合销售人员使用。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0.4
    )
    return response.choices[0].message.content


def mock_llm_response(prompt: str) -> str:
    if "知识库资料" in prompt or "参考资料" in prompt:
        return """【AI模拟RAG回答】
根据已上传资料，当前问题可以从产品应用场景、客户需求匹配和下一步沟通三个方面分析。

1. 产品匹配：建议优先结合客户行业、屏幕尺寸、亮度、接口方式和交付周期进行判断。
2. 客户沟通：可以追问客户项目阶段、预计用量、应用场景和是否有定制需求。
3. 下一步动作：建议发送产品资料，并同步确认客户的技术参数要求和采购时间节点。

注意：当前为 mock 模式，如需真实回答，请在 .env 中配置 DeepSeek API。"""

    if "总结" in prompt:
        return """【AI模拟总结】
该客户已建立基础联系，目前需要重点判断真实采购需求、项目时间节点、预算情况和决策链条。
从现有跟进信息看，下一步不应只做普通寒暄，而应围绕客户业务场景继续追问需求，并沉淀关键信息。"""

    return """【AI模拟建议】
1. 先确认客户目前是否有明确项目、采购计划或替换需求。
2. 重点询问：应用场景、预计数量、预算范围、决策人、时间节点。
3. 可以准备一段简短话术：您好，我这边想根据贵司实际应用场景，帮您初步匹配更合适的方案，方便了解下目前项目大概处在哪个阶段吗？
4. 跟进后及时记录客户反馈，为后续报价或方案推荐做准备。"""
