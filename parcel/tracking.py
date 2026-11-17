"""Cached official example plus explicit opt-in live tracking."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
from urllib.request import Request,build_opener
from urllib.error import HTTPError,URLError
from urllib.parse import quote
import re
from ship24_connection_check import NoRedirect
from .domain import ValidationError

ROOT=Path(__file__).resolve().parents[1]
SAMPLE="SHIP24_SAMPLE_DELIVERED_000"


def key_path():
    candidates=[ROOT/"ship24_key.txt",ROOT.parent.parent/"ship24_key.txt"]
    return next((p for p in candidates if p.is_file()),None)


def configured():
    return bool(os.environ.get("SHIP24_API_KEY") or key_path())


def summarize(result,data_type,queried_at):
    rows=result.get("data",{}).get("trackings",[])
    if not rows: raise ValidationError("尚未取得物流事件。")
    t=rows[0]; shipment=t.get("shipment") or {}; tracker=t.get("tracker") or {}
    events=[{k:e.get(k) for k in ["status","statusMilestone","occurrenceDatetime","location"]} for e in t.get("events",[])]
    def event_time(event):
        try:
            value=datetime.fromisoformat((event.get("occurrenceDatetime") or "").replace("Z","+00:00"))
            return value.replace(tzinfo=value.tzinfo or timezone.utc).timestamp()
        except (ValueError,TypeError): return float("-inf")
    events.sort(key=event_time,reverse=True)
    return {"tracking_number":tracker.get("trackingNumber"),"status":shipment.get("statusMilestone"),"events":events,
            "data_type":data_type,"queried_at":queried_at,"source_url":"https://docs.ship24.com/status"}


def track(number=SAMPLE,allow_live=False):
    if not isinstance(number,str) or not re.fullmatch(r"[A-Za-z0-9_-]{5,100}",number): raise ValidationError("运单号格式无效。")
    if number==SAMPLE:
        d=json.loads((ROOT/"data/ship24/official_sample_delivered.json").read_text())
        return summarize(d["api_response"],"official_synthetic_sample",d["queried_at_utc"])
    if not allow_live: raise ValidationError("真实运单请在物流页面启用实时查询；该操作会使用 Ship24 额度。")
    key=os.environ.get("SHIP24_API_KEY","").strip()
    if not key:
        p=key_path()
        if p: key=p.read_text(encoding="utf-8-sig").strip()
    if not key: raise ValidationError("本地尚未配置 Ship24 Key。")
    if not key.isascii() or any(c.isspace() for c in key): raise ValidationError("Ship24 Key 格式需要检查。")
    req=Request("https://api.ship24.com/public/v1/trackers/track",data=json.dumps({"trackingNumber":number}).encode(),
                headers={"Authorization":"Bearer "+key,"Content-Type":"application/json","Accept":"application/json"},method="POST")
    try:
        with build_opener(NoRedirect()).open(req,timeout=60) as response: data=json.load(response)
    except HTTPError as error: raise ValidationError("Ship24 查询未成功（HTTP "+str(error.code)+"）。")
    except (URLError,TimeoutError,ValueError): raise ValidationError("物流服务暂时不可用，请稍后重试。")
    return summarize(data,"live_api",datetime.now(timezone.utc).isoformat())
