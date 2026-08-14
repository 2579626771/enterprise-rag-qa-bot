import json
from urllib import request
from app.config import ANSWER_PROVIDER,DEEPSEEK_API_KEY, DEEPSEEK_CHAT_MODEL

# 作答提示词的默认「指令前言」（不含资料/问题本体，由代码拼接）。
# 抽成模块常量后，检索配置页可在线覆盖它（存 retrieval_configs.answer_prompt）；
# 未覆盖时用这里的默认，行为与抽取前完全一致。
DEFAULT_ANSWER_PROMPT = (
    "你是一个专业的企业知识库问答助手。请依据下面提供的资料回答问题。\n"
    "要求：\n"
    "1. 以资料为准，可以对资料中的信息进行归纳、整理和合理串联后作答，"
    "不要引入资料之外的编造内容。\n"
    "2. 资料可能是从文档中切分出来的片段，顺序可能被打乱、也可能夹杂标题或目录，"
    "请聚焦其中与问题相关的部分，只要能找到相关信息就尽量给出有帮助的回答。\n"
    "3. 只有当资料里确实完全没有与问题相关的信息时，才回答"
    "「根据现有资料，无法回答这个问题。」。\n"
    "4. 回答要简洁、准确，必要时可引用资料原文。"
)


def generate_fake_answer(
    question:str,
    context:str,
) -> str:
    return f"根据检索到的内容:{context},可以回答你的问题:{question}"

def generate_deepseek_answer(
    question:str,
    context:str,
    answer_prompt: str | None = None,
) -> str:
    url = "https://api.deepseek.com/v1/chat/completions"
    # ★第二道防线：约束大模型只依据资料作答，禁止编造★
    # 即使有片段通过了相似度过滤，也要求它严格基于资料；资料没有就老实说不知道。
    # answer_prompt：指令前言，可被检索配置页在线覆盖；为空则用 DEFAULT_ANSWER_PROMPT。
    instruction = (answer_prompt or "").strip() or DEFAULT_ANSWER_PROMPT
    prompt = (
        f"{instruction}\n\n"
        f"资料:\n{context}\n\n"
        f"问题:{question}"
    )

    payload = {
        "model": DEEPSEEK_CHAT_MODEL,
        "messages":[
            {"role":"user", "content": prompt},
            ],
    }

    data = json.dumps(payload).encode("utf-8")

    req = request.Request(
        url=url,
        data=data,
        headers={
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type" : "application/json",
        },
        method="POST",
    )

    with request.urlopen(req,timeout=60) as response:
        response_data = json.loads(response.read().decode("utf-8"))

    return response_data["choices"][0]["message"]["content"]

def generate_answer(
    question:str,
    context:str,
    answer_prompt: str | None = None,
) -> str:
    if ANSWER_PROVIDER == "fake":
        return generate_fake_answer(
            question=question,
            context=context,
        )

    if ANSWER_PROVIDER == "deepseek":
        return generate_deepseek_answer(
            question=question,
            context=context,
            answer_prompt=answer_prompt,
        )
    raise ValueError(f"Unsupported answer provider: {ANSWER_PROVIDER}")
