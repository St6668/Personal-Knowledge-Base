"""
启动脚本 —— 使用 uvicorn 运行 FastAPI 应用

用法:
    python run.py              # 开发模式（热重载）
    python run.py --no-reload  # 生产模式（单进程，Ctrl+C 干净退出）
"""
import os
import sys
import yaml

# ── 必须在所有 app 导入之前设置 HF_ENDPOINT ──
# 国内用户需要通过镜像下载 HuggingFace 模型
_config_path = os.path.join(os.path.dirname(__file__), "config.yaml")
with open(_config_path, "r", encoding="utf-8") as f:
    _config = yaml.safe_load(f)

_hf_endpoint = _config.get("embedding", {}).get("hf_endpoint", "")
if _hf_endpoint:
    os.environ["HF_ENDPOINT"] = _hf_endpoint
    print(f"[启动] 使用 HuggingFace 镜像: {_hf_endpoint}")

import uvicorn

if __name__ == "__main__":
    # --no-reload 参数禁用热重载，单进程运行，Ctrl+C 干净退出，不产生僵尸进程
    use_reload = "--no-reload" not in sys.argv

    if use_reload:
        print("[启动] 开发模式（热重载已启用）")
        print("[提示] 如遇僵尸进程，请用 python run.py --no-reload 启动，或执行 taskkill /F /IM python.exe 清理")
    else:
        print("[启动] 生产模式（单进程，Ctrl+C 安全退出）")

    uvicorn.run(
        "app.main:app",
        host=_config["server"]["host"],
        port=_config["server"]["port"],
        reload=use_reload,
    )
