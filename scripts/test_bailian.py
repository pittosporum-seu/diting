"""验证阿里云百炼连通性（token 从环境变量 AI_API_KEY 读取，不入仓库）。"""
import os
import sys

sys.path.insert(0, "src")

from diting.ai.client import AIClient

api_key = os.environ.get("AI_API_KEY", "")
api_base = os.environ.get("AI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
model = os.environ.get("AI_MODEL", "qwen3.8")

if not api_key:
    print("ERROR: AI_API_KEY not set")
    sys.exit(1)

print(f"model={model}")
print(f"api_base={api_base}")

client = AIClient(model=model, api_key=api_key, api_base=api_base, max_tokens=50)
try:
    resp = client.complete(system="你是助手", user="只回复两个字：你好")
    print("SUCCESS:", resp[:100])
except Exception as e:
    print("FAILED:", str(e)[:500])
