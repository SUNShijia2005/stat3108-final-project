"""Parcel Desk: dependency-free local application. Run: python3 app.py"""
import argparse
import csv
from datetime import date
import io
import json
import mimetypes
import os
from pathlib import Path
import threading
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlsplit,parse_qs

ROOT=Path(__file__).resolve().parent
from parcel.config import load_local_config,model_settings,save_model_settings
CONFIG_PATH=ROOT/".env.local"
load_local_config(CONFIG_PATH)

from parcel.domain import quote,document_check,document_html,summary_html,select_service,task_progress,ValidationError,RATES
from parcel.assistant import chat,update
from parcel.knowledge import retrieve,DOCS
from parcel.storage import Store
from parcel.tracking import track,configured as tracking_configured
from parcel.model import configured as model_configured

LOCK=threading.RLock()
STORE=None


def public_task(task):
    result=dict(task)
    result.setdefault("selected_service",None)
    result.setdefault("is_demo",False)
    result["progress"]=task_progress(task)
    return result


def import_csv(fields,text,kind):
    if kind not in {"invoice","packing"}: raise ValidationError("导入类型无效。")
    if not isinstance(text,str) or len(text)>100000: raise ValidationError("CSV 文件过大。")
    reader=csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if reader.fieldnames and len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ValidationError("CSV 列名不能重复。")
    if not {"description","quantity"}.issubset(set(reader.fieldnames or [])):
        raise ValidationError("CSV 需要 description、quantity 列；发票还需要 unit_price 列。")
    if kind=="invoice" and "unit_price" not in reader.fieldnames: raise ValidationError("发票 CSV 缺少 unit_price 列。")
    rows=list(reader)
    if not rows or len(rows)>100: raise ValidationError("CSV 需要 1–100 行货品。")
    incoming={}
    for row in rows:
        if None in row: raise ValidationError("CSV 数据列数与表头不一致。")
        name=(row.get("description") or "").strip(); key=name.casefold()
        if not name or key in incoming: raise ValidationError("CSV 货品描述不能为空或重复，请先合并同名货品。")
        incoming[key]=row
    old_rows=[r for r in (fields.get("items") or []) if isinstance(r,dict)]
    old={str(r.get("description","")).strip().casefold():r for r in old_rows}
    if len(old)!=len(old_rows): raise ValidationError("现有明细含同名货品，请先合并后再导入 CSV。")
    items=[]
    for key in sorted(old.keys()|incoming.keys()):
        item=dict(old.get(key,{})); row=incoming.get(key)
        if row:
            item["description"]=row["description"].strip()
            item["quantity" if kind=="invoice" else "packing_quantity"]=row["quantity"]
            if kind=="invoice": item["unit_price"]=row.get("unit_price"); item["hs_code"]=row.get("hs_code","")
        elif kind=="invoice": item["quantity"]=0
        else: item["packing_quantity"]=0
        items.append(item)
    return items


class Handler(BaseHTTPRequestHandler):
    server_version="ParcelDesk/0.1"
    def log_message(self,format,*args):
        pass

    def send(self,data,status=200,ctype="application/json; charset=utf-8",download=None):
        body=(json.dumps(data,ensure_ascii=False,allow_nan=False).encode() if ctype.startswith("application/json") else data.encode() if isinstance(data,str) else data)
        self.send_response(status)
        self.send_header("Content-Type",ctype); self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store"); self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        printable = urlsplit(self.path).path in {"/api/document", "/api/export/summary"} and ctype.startswith("text/html")
        ancestors = "'self'" if printable else "'none'"
        self.send_header("Content-Security-Policy","default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:; frame-ancestors "+ancestors+"; base-uri 'none'")
        if download: self.send_header("Content-Disposition",f'attachment; filename="{download}"')
        self.end_headers(); self.wfile.write(body)

    def valid_host(self):
        return self.headers.get("Host","") in {f"localhost:{self.server.server_port}",f"127.0.0.1:{self.server.server_port}"}

    def do_GET(self):
        try:
            if not self.valid_host(): return self.send({"error":"Invalid local host"},403)
            url=urlsplit(self.path); params=parse_qs(url.query); path=url.path
            if path=="/api/health": return self.send({"status":"ok","model_configured":model_configured(),"model":model_settings()["model"],"api_style":model_settings()["api_style"],"tracking_configured":tracking_configured(),"mode":"model" if model_configured() else "workflow","rate_count":1230,"document_count":len(DOCS),"database":"local SQLite"})
            if path=="/api/model/settings": return self.send(model_settings())
            if path=="/api/tasks": return self.send({"tasks":STORE.list()})
            if path=="/api/task": return self.send(public_task(STORE.get(params.get("id",[""])[0])))
            if path=="/api/sources": return self.send({"documents":DOCS,"rates_metadata":{k:v for k,v in RATES.items() if k!="services"}})
            if path=="/api/evaluation":
                p=ROOT/"results/evaluation.json"
                return self.send(json.loads(p.read_text()) if p.exists() else {"status":"not_run","cases":[]})
            if path=="/api/document":
                task=STORE.get(params.get("id",[""])[0]); kind=params.get("kind",["invoice"])[0]
                if kind not in {"invoice","packing"}: raise ValidationError("文件类型无效。")
                return self.send(document_html(task["fields"],kind),ctype="text/html; charset=utf-8")
            if path=="/api/export/task":
                return self.send(public_task(STORE.get(params.get("id",[""])[0])),download="parcel-task.json")
            if path=="/api/export/summary":
                task=STORE.get(params.get("id",[""])[0])
                return self.send(summary_html(task),ctype="text/html; charset=utf-8")
            if path=="/api/csv-template":
                kind=params.get("kind",["invoice"])[0]
                text="description,quantity,unit_price,hs_code\nCotton T-shirt,2,25,\n" if kind=="invoice" else "description,quantity\nCotton T-shirt,2\n"
                return self.send(text,ctype="text/csv; charset=utf-8",download=kind+"-template.csv")
            static={"/":"index.html","/app.js":"app.js","/drafts.js":"drafts.js","/style.css":"style.css"}
            if path in static:
                f=ROOT/"static"/static[path]
                return self.send(f.read_bytes(),ctype=(mimetypes.guess_type(f.name)[0] or "text/plain")+"; charset=utf-8")
            self.send({"error":"Not found"},404)
        except KeyError: self.send({"error":"运输任务不存在。"},404)
        except (ValidationError,ValueError) as error: self.send({"error":str(error)},400)
        except (BrokenPipeError,ConnectionResetError): pass
        except Exception: self.send({"error":"本地服务处理失败，请检查运行终端。"},500)

    def do_POST(self):
        try:
            if not self.valid_host(): return self.send({"error":"Invalid local host"},403)
            origin=self.headers.get("Origin")
            if origin and origin not in {f"http://localhost:{self.server.server_port}",f"http://127.0.0.1:{self.server.server_port}"}:
                return self.send({"error":"Cross-origin requests are not accepted"},403)
            if not self.headers.get("Content-Type","").startswith("application/json"): return self.send({"error":"JSON required"},415)
            length=int(self.headers.get("Content-Length","0"))
            if length<=0 or length>512000: return self.send({"error":"请求大小无效。"},413)
            body=json.loads(self.rfile.read(length))
            if not isinstance(body,dict): raise ValidationError("请求必须为对象。")
            path=urlsplit(self.path).path
            if path=="/api/model/settings":
                with LOCK:
                    return self.send(save_model_settings(CONFIG_PATH,body))
            if path=="/api/tasks": return self.send(public_task(STORE.create(demo=body.get("demo") is True)),201)
            if path=="/api/search": return self.send({"results":retrieve(body.get("query",""),body.get("method","hybrid"))})
            if path not in {"/api/task","/api/chat","/api/quote","/api/documents/check","/api/track","/api/import","/api/select"}: return self.send({"error":"Not found"},404)
            with LOCK:
                task=STORE.get(body.get("id",""))
                if body.get("version")!=task["version"]: return self.send({"error":"任务已在其他请求中更新，请刷新后重试。","task":public_task(task)},409)
                if "fields" in body: update(task,body["fields"])
                output={}
                if path=="/api/chat": output=chat(task,body.get("message",""))
                elif path=="/api/quote": task["quote"]=quote(task["fields"])
                elif path=="/api/documents/check": task["checks"]=document_check(task["fields"])
                elif path=="/api/track": task["tracking"]=track(body.get("number",""),body.get("allow_live") is True)
                elif path=="/api/import": update(task,{"items":import_csv(task["fields"],body.get("text",""),body.get("kind"))})
                elif path=="/api/select": output=select_service(task,body.get("service"))
                task["version"]+=1; STORE.save(task)
                self.send({"task":public_task(task),"output":output})
        except KeyError: self.send({"error":"运输任务不存在。"},404)
        except (ValidationError,ValueError,TypeError) as error: self.send({"error":str(error)},400)
        except (BrokenPipeError,ConnectionResetError): pass
        except Exception: self.send({"error":"本地服务处理失败，请检查配置和输入。"},500)


def main():
    global STORE
    parser=argparse.ArgumentParser(); parser.add_argument("--port",type=int,default=8765); parser.add_argument("--database",type=Path,default=ROOT/"var/parcel.sqlite3")
    args=parser.parse_args(); STORE=Store(args.database)
    server=ThreadingHTTPServer(("127.0.0.1",args.port),Handler)
    print(f"Parcel Desk ready: http://127.0.0.1:{args.port}",flush=True)
    print("Mode: "+("model + tools" if model_configured() else "local workflow + tools"),flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__=="__main__": main()
