"""Create private per-install settings once, without copying the packager's data."""
from __future__ import annotations
import argparse
import base64
import json
from pathlib import Path
import secrets


def initialize(root:Path)->bool:
    root=root.resolve()
    if not (root/"apps/api/main.py").is_file():
        raise ValueError("Not an OpenTutor installation")
    data=root/"native-data"
    for name in ("data","uploads","logs"):
        (data/name).mkdir(parents=True,exist_ok=True)
    settings=data/"settings.env"
    if settings.exists():return False
    values={
        "ENVIRONMENT":"development", "AUTH_ENABLED":"false", "DEPLOYMENT_MODE":"single_user",
        "DATABASE_URL":"sqlite+aiosqlite:///"+(data/"data/opentutor.db").as_posix(),
        "UPLOAD_DIR":(data/"uploads").as_posix(),
        "CORS_ORIGINS":"http://localhost:3001,http://127.0.0.1:3001",
        "LLM_PROVIDER":"deepseek", "LLM_MODEL":"deepseek-chat", "LLM_REQUIRED":"true",
        "OPENAI_API_KEY":"", "ANTHROPIC_API_KEY":"", "DEEPSEEK_API_KEY":"",
        "OPENROUTER_API_KEY":"", "GEMINI_API_KEY":"", "GROQ_API_KEY":"",
        "CUSTOM_LLM_API_KEY":"", "CUSTOM_LLM_BASE_URL":"", "CUSTOM_LLM_MODEL":"",
        "JWT_SECRET_KEY":secrets.token_hex(32),
        "ENCRYPTION_KEY":base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "APP_AUTO_CREATE_TABLES":"true", "APP_AUTO_SEED_SYSTEM":"true", "APP_AUTO_SEED_DEMO":"false",
        "APP_RUN_SCHEDULER":"false", "APP_RUN_ACTIVITY_ENGINE":"false",
        "CODE_SANDBOX_BACKEND":"disabled", "ALLOW_INSECURE_PROCESS_SANDBOX":"false",
        "ENABLE_EXPERIMENTAL_LECTOR":"false", "ENABLE_EXPERIMENTAL_LOOM":"false",
    }
    # Exclusive creation prevents simultaneous first launches from replacing keys.
    try:
        with settings.open("x",encoding="utf-8",newline="\n") as stream:
            stream.write("# Private local configuration. Do not share this file.\n")
            for key,value in values.items():stream.write(key+"="+json.dumps(value,ensure_ascii=False)+"\n")
    except FileExistsError:return False
    return True

if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args()
    print(json.dumps({"initialized":initialize(args.root)},ensure_ascii=False))
