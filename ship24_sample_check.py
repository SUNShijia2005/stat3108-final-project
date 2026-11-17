"""Query one official synthetic shipment; cache its response for demonstrations.

Sample source: https://docs.ship24.com/status#ship24-sample-tracking-numbers
Endpoint: https://docs.ship24.com/trackers
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from ship24_connection_check import NoRedirect

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "data" / "ship24" / "official_sample_delivered.json"
TRACKING_NUMBER = "SHIP24_SAMPLE_DELIVERED_000"


def main():
    if OUTPUT.exists():
        print("官方示例结果已保存；本次读取本地记录，没有再次调用 API。")
        return 0
    key = os.environ.get("SHIP24_API_KEY", "").strip()
    if not key:
        key = (ROOT / "ship24_key.txt").read_text(encoding="utf-8-sig").strip()
    if not key or key == "PASTE_YOUR_SHIP24_API_KEY_HERE" or any(c.isspace() for c in key):
        print("请先检查本地 API Key 配置。")
        return 2
    request = Request(
        "https://api.ship24.com/public/v1/trackers/track",
        data=json.dumps({"trackingNumber": TRACKING_NUMBER}).encode("utf-8"),
        headers={
            "Authorization": "Bearer " + key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with build_opener(NoRedirect()).open(request, timeout=60) as response:
            result = json.load(response)
    except HTTPError as error:
        print("示例查询未成功，HTTP 状态码：" + str(error.code))
        return 1
    except (URLError, TimeoutError):
        print("网络连接失败或超时。")
        return 1
    except ValueError:
        print("服务端返回格式异常。")
        return 1
    if not isinstance(result, dict) or not isinstance(result.get("data"), dict):
        print("服务端返回结构不符合预期。")
        return 1
    trackings = result["data"].get("trackings")
    if not isinstance(trackings, list) or not trackings:
        print("接口已响应，但未取得追踪结果；需要核对 API 返回。")
        return 1
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps({
        "data_type": "official_synthetic_sample",
        "description": "Ship24 官方模拟运单，仅用于接口与界面测试。",
        "source": "https://docs.ship24.com/status#ship24-sample-tracking-numbers",
        "queried_at_utc": datetime.now(timezone.utc).isoformat(),
        "tracking_number": TRACKING_NUMBER,
        "api_response": result,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("官方示例查询成功，结果已保存。")
    for tracking in trackings:
        shipment = tracking.get("shipment") or {}
        events = tracking.get("events") or []
        print(json.dumps({
            "sample": True,
            "status": shipment.get("statusMilestone"),
            "event_count": len(events),
            "latest_event": events[0].get("status") if events else None,
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
