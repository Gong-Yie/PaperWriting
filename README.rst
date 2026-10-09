论文研究工作台
==============

支持中英文论文研究的本地网页应用，首先面向计算机 / 人工智能领域。

当前阶段
--------

已实现选题讨论、arXiv 论文摘要检索、完整选题档案本地保存与重载，
以及研究工作台的文献 / 实验 / 写作档案查看和任务配置保存。
已有题目时可以跳过选题讨论，让 Agent 围绕该题目整理档案。

当前工作台展示的是选题阶段的方案与材料。自动研究启动、暂停恢复、
实验执行、论文生成及文件导出尚未实现；保存配置不会启动这些任务。
交付格式的选择目前只保存需求，不生成对应格式文件。

运行（PowerShell）
-----------------

在项目目录执行：

::

    uv sync --locked
    uv run uvicorn paper_agent.app:app --host 127.0.0.1 --port 8000

在浏览器打开 http://127.0.0.1:8000 。首次依赖安装需要联网。

模型配置
--------

项目根目录的 ``.env`` 需要以下配置项：

::

    API_KEY=你的模型服务密钥
    BASE_URL=https://api.deepseek.com
    MODEL=你的模型名称

使用兼容 Chat Completions 且支持 JSON Output 的模型接口。
保留现有配置，不将密钥发送给网页或写入档案。
每轮选题讨论会调用模型两次：生成检索表达式、基于检索论文形成回复与档案。
arXiv 检索为空时显示实际空结果；请求或解析失败时显示错误，不自动重试。
当前只依据论文元数据与摘要辅助初步分析，不视为全文精读或创新性证明。

本地数据
--------

``data/topics/<选题 UUID>.json`` 保存讨论记录、检索到的论文、选题方案、
确认状态和任务配置。文件使用 UTF-8，更新时使用临时文件原子替换。
网页侧栏可以重新打开历史选题；已敲定的选题保留原讨论记录。

``.env``、``data/`` 和 ``.venv/`` 均不纳入 Git。
尊重初始化时已有的 ``*.md`` 忽略规则，``开发问答记录.md`` 保留在本地。

验证
----

::

    uv run pytest tests/test_topics.py -q

测试使用临时目录和 HTTP Mock 隔离模型、文献服务及本地用户数据。

接口依据
--------

- DeepSeek Chat Completions：https://api-docs.deepseek.com/api/create-chat-completion/
- arXiv API：https://info.arxiv.org/help/api/user-manual.html
