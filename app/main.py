from app.services.rag_service import run_rag_pipeline
from app.config import APP_ENV,APP_NAME,APP_VERSION,EMBEDDING_PROVIDER,ANSWER_PROVIDER
from app.utils.logger import get_logger
logger = get_logger(__name__)

def main():
	logger.info(f"项目名称：{APP_NAME}")
	logger.info(f"项目版本：{APP_VERSION}")
	logger.info(f"当前环境：{APP_ENV}")
	logger.info(f"Embedding 提供方：{EMBEDDING_PROVIDER}")
	logger.info(f"Answer 提供方：{ANSWER_PROVIDER}")
	
	run_rag_pipeline( 
		question="怎么读取文档内容？",
		file_path="data/sample.txt",
	)


if __name__ =="__main__":
	main()