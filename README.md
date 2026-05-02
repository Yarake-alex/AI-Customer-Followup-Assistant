AI 客户跟进助手系列项目
本仓库包含 AI 客户跟进助手的三个版本，项目围绕 ToB 销售客户管理、AI 跟进分析、RAG 知识库问答和轻量 Agent 自动分析场景逐步升级。
项目版本说明

V1：客户管理 + AI 跟进建议
V1 实现基础客户管理功能，包括客户新增、客户列表、客户详情、客户修改、客户删除、跟进记录保存和历史记录查看。同时接入 DeepSeek API，实现客户跟进总结和下一步销售建议生成。
技术栈：Python、FastAPI、SQLite、SQLAlchemy、HTML、CSS、JavaScript、DeepSeek API。

---
V2：RAG 知识库问答版
V2 在 V1 基础上新增 RAG 知识库问答能力。系统支持上传产品资料和行业资料，自动切分资料片段，并在用户提问时先检索相关资料，再调用大模型生成回答，同时展示参考资料片段。
技术栈：Python、FastAPI、SQLite、SQLAlchemy、pypdf、scikit-learn、TF-IDF、DeepSeek API、RAG。

---
V3：轻量 Agent 自动跟进版
V3 在 V2 基础上新增轻量 Agent 跟进助手。用户选择客户并输入任务后，系统会自动查询客户基础信息、历史跟进记录和知识库资料，再调用大模型生成完整客户跟进方案。
技术栈：Python、FastAPI、SQLite、SQLAlchemy、RAG、Agent Workflow、DeepSeek API。

版本升级路线
V1：客户管理 + AI 跟进建议  
V2：增加 RAG 知识库问答  
V3：增加轻量 Agent 自动分析流程  

注意:本项目中的.env文件未上传。运行前请根据 .env.example 配置自己的API Key。