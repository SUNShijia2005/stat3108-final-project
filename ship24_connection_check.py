"""Read-only connection check; does not create shipment trackers.

API contract: https://docs.ship24.com/couriers
Credentials: https://docs.ship24.com/getting-started
"""

import json
import os
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    key = os.environ.get("SHIP24_API_KEY", "").strip()
    if not key:
        path = Path(__file__).with_name("ship24_key.txt")
        if not path.exists():
            print("请先将 API Key 保存到 ship24_key.txt。")
            return 2
        key = path.read_text(encoding="utf-8-sig").strip()
    if not key or key == "PASTE_YOUR_SHIP24_API_KEY_HERE":
        print("配置文件已准备好，等待你粘贴并保存 API Key。")
        return 2
    if any(char.isspace() for char in key) or not key.isascii():
        print("Key 格式需要检查：文件中只保留 Key 本身，不含说明或空格。")
        return 2
    request = Request(
        "https://api.ship24.com/public/v1/couriers",
        headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
        method="GET",
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=25) as response:
            result = json.load(response)
        if not isinstance(result, dict) or not isinstance(result.get("data"), dict):
            print("服务器有响应，但返回结构需要进一步核对。")
            return 1
        couriers = result["data"].get("couriers")
        if not isinstance(couriers, list):
            print("服务器有响应，但没有取得预期的承运商列表。")
            return 1
        print("连接成功：已通过 Ship24 授权并取得承运商列表。")
        print("本次仅检查连接，没有创建包裹追踪任务。")
        return 0
    except HTTPError as error:
        hints = {
            401: "请核对 Key 是否完整、有效。",
            403: "请核对 API Key 权限及 Tracking API 套餐状态。",
            429: "调用频率受限，请稍后重试。",
        }
        print("连接未成功，HTTP 状态码：" + str(error.code))
        print(hints.get(error.code, "需要进一步核对服务端响应。"))
        return 1
    except URLError:
        print("暂时无法连接 Ship24，请检查网络连接。")
        return 1
    except (TimeoutError, OSError, ValueError):
        print("连接超时或返回格式异常，需要重试并核对。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
