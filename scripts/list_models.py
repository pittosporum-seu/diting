"""查询百炼可用模型列表（验证 token + 获取正确模型名）。"""
import os
import json
import urllib.request

api_key = os.environ.get("AI_API_KEY", "")
base = os.environ.get("AI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")

req = urllib.request.Request(
    f"{base}/models",
    headers={"Authorization": f"Bearer {api_key}"},
)
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    models = [m.get("id") for m in data.get("data", [])]
    print("token 有效，可用模型数:", len(models))
    # 打印含 qwen 的模型
    qwen = [m for m in models if "qwen" in m.lower()]
    print("qwen 系列模型:")
    for m in sorted(qwen):
        print("  ", m)
    if not qwen:
        print("全部模型:")
        for m in sorted(models)[:50]:
            print("  ", m)
except Exception as e:
    print("FAILED:", str(e)[:500])
