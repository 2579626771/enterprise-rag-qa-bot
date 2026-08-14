from pathlib import Path            # Path 是 Python 自带的工具，用来处理文件路径。  

BASE_DIR = Path(__file__).resolve().parent.parent    #找到项目根目录 enterprise-rag
ENV_FILE = BASE_DIR / ".env"     #找到 .env 文件, 在 Path 里，/ 表示拼接路径。

def load_env_file() -> dict[str,str]:    #定义读取 .env 的函数 
    env_values = {}

    if not ENV_FILE.exists():
        return env_values
    
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()    #去掉每行前后的空格 

        if  not line:    #跳过空行 
            continue
        
        if line.startswith("#"):    #跳过注释行 
            continue

        if "=" not in line:
            continue
        
        key,value = line.split("=",1)   # 这里的 1 表示：只按第一个等号切一次。 
        env_values[key.strip()] = value.strip()   #把配置项保存到字典里。

    return env_values


_env = load_env_file()

APP_NAME = _env.get("APP_NAME","Enterprise RAG")
APP_VERSION = _env.get("APP_VERSION","0.1.0")
APP_ENV = _env.get("APP_ENV","development")
EMBEDDING_PROVIDER = _env.get("EMBEDDING_PROVIDER", "aliyun")
ALIYUN_API_KEY = _env.get("ALIYUN_API_KEY", "")
ALIYUN_EMBEDDING_MODEL = _env.get("ALIYUN_EMBEDDING_MODEL","qwen3.7-text-embedding")
# 向量化并发度：大文档分多批调用阿里云 embedding，串行时批次逐个累加很慢。
# 用线程池并发发多个批次，墙钟时间约缩短为原来的 1/N。取值不宜过大以免触发限流。
EMBEDDING_CONCURRENCY = int(_env.get("EMBEDDING_CONCURRENCY", "5"))
ANSWER_PROVIDER = _env.get("ANSWER_PROVIDER","deepseek")
DEEPSEEK_API_KEY = _env.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_CHAT_MODEL=_env.get("DEEPSEEK_CHAT_MODEL","deepseek-v4-pro")
# DeepSeek 的 OpenAI 兼容基址。答案层「研判」用 LangChain 的 ChatOpenAI 走这个基址。
# 现有 answer_service 用 urllib 直连 /chat/completions；judge 复用同一账号但走 OpenAI 兼容端点。
DEEPSEEK_BASE_URL = _env.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")

# ===== 答案层「研判」防幻觉 =====
# 背景：评测(见 eval/)证明——主题相关但库里没答案的问题(hard-negative)，其检索距离
# 与「真能回答」的问题几乎完全重叠，单靠 RAG_MAX_DISTANCE 距离阈值无法区分，导致大模型
# 拿「答非所问」的片段硬编、产生幻觉(基线幻觉风险率 91.7%)。
# 研判层：作答时先让 LLM 判断「这些资料是否真能回答该问题」，不能答就明确拒答。
# JUDGE_ENABLED：是否启用研判层。默认关闭(false)保守上线——关闭时问答行为与引入前完全一致，
#   出任何问题可一键切回。验证有效后再在生产 .env 打开。
JUDGE_ENABLED = _env.get("JUDGE_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}

# 向量库（Chroma）相关配置
# CHROMA_DIR：向量库存在硬盘上的目录，程序重启后数据还在。
# CHROMA_COLLECTION：知识库集合名字（相当于“档案柜”的名字），至少 3 个字符。
# RAG_TOP_K：每次提问时，从全库检索最相关的前几段文字。
CHROMA_DIR = _env.get("CHROMA_DIR", str(BASE_DIR / "data" / "chroma"))
CHROMA_COLLECTION = _env.get("CHROMA_COLLECTION", "knowledge_base")
RAG_TOP_K = int(_env.get("RAG_TOP_K", "5"))
DOCUMENTS_DIR = _env.get("DOCUMENTS_DIR", str(BASE_DIR / "data" / "documents"))

# RAG_MAX_DISTANCE：相似度距离阈值（余弦距离，0=完全一样，1=毫不相关）。
# 检索回来的片段，距离若大于这个值，就当作“不相关”丢弃。
# 作用：问一个文档里根本没有的问题时，不会硬凑无关来源、也不会让大模型乱编。
# 值越小越严格（只留高度相关的），越大越宽松。0.5 是一个较稳妥的起点，可按效果调。
RAG_MAX_DISTANCE = float(_env.get("RAG_MAX_DISTANCE", "0.5"))

# ===== 检索重排（rerank）·检索质量专线阶段3 =====
# 背景：正例召回已近满分，但「能答/不能答」在向量距离上区间重叠、个别 hard case 漏召回。
# rerank 用交叉编码器对「query-候选片段」逐对精排，比双塔向量粗排更能拉开相关/不相关分差，
# 把真正相关的片段顶到前面。实现走阿里云 gte-rerank-v2（纯 HTTP，复用 ALIYUN_API_KEY）。
# RERANK_ENABLED：是否启用重排。默认关闭(false)保守上线——关闭时检索行为与引入前完全一致，
#   出任何问题可一键切回。评测(eval_retrieval before/after)验证有效后再在生产 .env 打开。
# RERANK_PROVIDER：aliyun（真实）/ fake（确定性启发式，供单测零网络）。
# rerank 只重排候选、不改每条的向量 distance，故 RAG_MAX_DISTANCE 阈值语义不受影响。
RERANK_ENABLED = _env.get("RERANK_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
RERANK_PROVIDER = _env.get("RERANK_PROVIDER", "aliyun")
ALIYUN_RERANK_MODEL = _env.get("ALIYUN_RERANK_MODEL", "gte-rerank-v2")
ALIYUN_RERANK_URL = _env.get(
    "ALIYUN_RERANK_URL",
    "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
)

# ===== 多查询改写（multi-query）·检索质量专线阶段4 =====
# 背景：rerank 精排解决不了「压根没召回进候选池」的漏召回（#8/#55），且用户问法与文档
# 措辞不一致时单条查询可能错过相关片段。多查询从**召回侧**补强：LLM 把原问题改写成若干
# 语义等价、措辞不同的查询，各自召回后合并去重，用多个入口覆盖同一答案的不同表述，提升 Recall。
# MULTI_QUERY_ENABLED：是否启用。默认关闭(false)——开启会多一次 LLM 调用(~2-8s)且多路召回，
#   出问题可一键切回。评测(eval_retrieval before/after)验证有效后再在生产 .env 打开。
# MULTI_QUERY_COUNT：改写条数（原查询之外额外生成几条）。默认 3。
# QUERY_REWRITE_PROVIDER：deepseek（真实）/ fake（确定性，供单测零网络）。
# 隔离红线：所有改写查询共用同一个 where=kb_id 过滤，范围不变，普通用户「全部」仍只查自己库。
MULTI_QUERY_ENABLED = _env.get("MULTI_QUERY_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
MULTI_QUERY_COUNT = int(_env.get("MULTI_QUERY_COUNT", "3"))
QUERY_REWRITE_PROVIDER = _env.get("QUERY_REWRITE_PROVIDER", "deepseek")

# ===== MySQL（文档元数据持久化）=====
# 存放文档的分类/描述/上传时间/状态等元数据，替换早期前端 localStorage 占位。
# MYSQL_ENABLED：是否启用 MySQL。为空或数据库不可用时，后端自动降级为“内存元数据”，
#   保证上传/问答主流程不受数据库影响（仅元数据不落盘）。
MYSQL_HOST = _env.get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(_env.get("MYSQL_PORT", "3306"))
MYSQL_USER = _env.get("MYSQL_USER", "root")
MYSQL_PASSWORD = _env.get("MYSQL_PASSWORD", "")
MYSQL_DATABASE = _env.get("MYSQL_DATABASE", "enterprise_rag")
# 默认：只要填了用户名就启用；可用 MYSQL_ENABLED=false 显式关闭。
MYSQL_ENABLED = _env.get("MYSQL_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}

# ===== 认证（JWT）=====
# JWT_SECRET：签发/校验登录令牌的密钥。生产环境务必改成足够随机的长字符串，
#   一旦泄露，攻击者可伪造任意用户的登录令牌。默认值仅供本地开发。
# JWT_EXPIRE_MINUTES：令牌有效期（分钟），默认 720 = 12 小时。
# DEFAULT_ADMIN_*：系统首次启动、用户表为空时，自动预置的管理员账号。
JWT_SECRET = _env.get("JWT_SECRET", "dev-only-change-me-in-production")
JWT_EXPIRE_MINUTES = int(_env.get("JWT_EXPIRE_MINUTES", "720"))
JWT_ALGORITHM = "HS256"
DEFAULT_ADMIN_USERNAME = _env.get("DEFAULT_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = _env.get("DEFAULT_ADMIN_PASSWORD", "admin123")

# ===== 多知识库（多租户隔离）=====
# DEFAULT_KB_QUOTA：普通用户初始可拥有的知识库上限（超出需向管理员申请）。
# ADMIN_KB_QUOTA：管理员的配额（给一个很大的值，等同不限制）。
DEFAULT_KB_QUOTA = int(_env.get("DEFAULT_KB_QUOTA", "3"))
ADMIN_KB_QUOTA = int(_env.get("ADMIN_KB_QUOTA", "9999"))