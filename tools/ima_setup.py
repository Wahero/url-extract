#!/usr/bin/env python3
"""
URL Extract + IMA — 凭证引导配置 v2.0
不持久化存储凭证，仅在当前会话设置环境变量。
凭证来源：用户手动提供（从 https://ima.qq.com/agent-interface 获取）。
"""

import os
import sys


def print_guide():
    """打印 IMA 凭证获取指引。"""
    print("=" * 56)
    print("  URL Extract + IMA — 凭证配置引导")
    print("=" * 56)
    print()
    print("IMA OpenAPI ��要两个凭证：")
    print()
    print("  1. Client ID  — 应用标识")
    print("  2. API Key     — 访问密钥（与 Client ID 不同）")
    print()
    print("获取步骤：")
    print()
    print("  ① 打开 https://ima.qq.com/agent-interface")
    print("  ② 微信扫码登录")
    print("  ③ 页面显示 Client ID（自动生成）")
    print("  ④ 点击「获取 API Key」按钮生成 API Key")
    print("  ⑤ 复制这两个值")
    print()
    print("-" * 56)
    print()


def interactive_setup():
    """交互式引导用户提供凭证，设置到当前会话环境变量。"""
    print_guide()

    client_id = input("请输入 Client ID: ").strip()
    if not client_id:
        print("[ERROR] Client ID 不能为空，已取消。")
        sys.exit(1)

    api_key = input("请输入 API Key: ").strip()
    if not api_key:
        print("[ERROR] API Key 不能为空，已取消。")
        sys.exit(1)

    if client_id == api_key:
        print()
        print("[WARNING] Client ID 和 API Key 相同！")
        print("  这两个通常是不同的值。")
        print("  请确认你是否已点击「获取 API Key」按钮生成 API Key。")
        print()
        confirm = input("确认使用相同值继续？(y/N): ").strip().lower()
        if confirm != 'y':
            print("已取消。请重新获取 API Key 后再运行。")
            sys.exit(0)

    # 仅设置当前会话环境变量（不写入文件）
    os.environ["IMA_OPENAPI_CLIENTID"] = client_id
    os.environ["IMA_OPENAPI_APIKEY"] = api_key

    print()
    print("=" * 56)
    print("  ✅ 凭证已设置（仅当前会话有效）")
    print()
    print("  ⚠️  凭证不会写入任何文件，重启后需重新配置。")
    print()
    print("  如需持久化，请手动在 shell 配置文件中添加：")
    print(f'    export IMA_OPENAPI_CLIENTID="{client_id[:8]}..."')
    print(f'    export IMA_OPENAPI_APIKEY="{api_key[:8]}..."')
    print()
    print("  验证命令: python ima_client.py")
    print("=" * 56)

    return client_id, api_key


def main():
    # 如果已有环境变量，提示跳过
    existing_cid = os.environ.get("IMA_OPENAPI_CLIENTID")
    existing_key = os.environ.get("IMA_OPENAPI_APIKEY")
    if existing_cid and existing_key:
        print("检测到已有 IMA 凭证环境变量。")
        print(f"  Client ID: {existing_cid[:8]}...")
        print(f"  API Key:   {existing_key[:8]}...")
        print()
        choice = input("是否重新配置？(y/N): ").strip().lower()
        if choice != 'y':
            print("保持现有凭证，跳过配置。")
            return

    interactive_setup()


if __name__ == "__main__":
    main()
