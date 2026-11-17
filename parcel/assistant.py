"""Inspectable fallback workflow plus optional model-driven tool execution."""
import json
import re
import time
from .domain import quote,document_check,clean_fields,ValidationError
from .knowledge import retrieve,references
from .tracking import track
from . import model


def extract_fields(message):
    f={}; s=message.lower()
    for pattern,key in [(r"(\d+(?:\.\d+)?)\s*(?:kg|公斤|千克)","weight_kg"),(r"(?:预算|budget)[^\d]{0,8}(\d+(?:\.\d+)?)","budget_cny")]:
        m=re.search(pattern,s)
        if m: f[key]=float(m.group(1))
    m=re.search(r"(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*(?:cm|厘米)?",s)
    if m: f.update(dict(zip(["length_cm","width_cm","height_cm"],map(float,m.groups()))))
    m=re.search(r"(?:邮编|zip(?:\s*code)?)[\s:：]*(\d{5}(?:-\d{4})?)",s)
    if m: f["destination_zip"]=m.group(1)
    m=re.search(r"\b(20\d{2}-\d{2}-\d{2})\b",s)
    if m: f["deadline"]=m.group(1)
    for word,province in [("上海","Shanghai"),("shanghai","Shanghai"),("北京","Beijing"),("beijing","Beijing"),("广东","Guangdong"),("guangdong","Guangdong"),("福建","Fujian")]:
        if word in s: f["origin_province"]=province; break
    for words,city,state in [(["洛杉矶","los angeles"],"Los Angeles","CA"),(["纽约","new york"],"New York","NY"),(["西雅图","seattle"],"Seattle","WA")]:
        if any(w in s for w in words): f.update(destination_city=city,destination_state=state,destination_country="US"); break
    for words,goods in [(["衣服","衣物","t-shirt","cotton","clothes"],"Cotton clothing"),(["书籍","书本","books"],"Printed books"),(["电池","battery"],"Battery-containing goods")]:
        if any(w in s for w in words): f["goods"]=goods; break
    return f


def update(task,fields):
    fields=clean_fields(fields)
    changed={k for k,v in fields.items() if task["fields"].get(k)!=v}
    if changed:
        quote_fields={"origin_province","destination_country","destination_state","destination_zip","goods","weight_kg","length_cm","width_cm","height_cm","budget_cny","deadline","oda_tier","residential","fuel_percent"}
        task["fields"].update(fields)
        if changed & quote_fields: task["quote"]=None
        task["checks"]=None
    return task["fields"]


def chat(task,message):
    if not isinstance(message,str) or not message.strip() or len(message)>6000: raise ValidationError("请输入 1–6000 字的问题。")
    trace=[]; citations=[]
    def execute(name,args):
        started=time.perf_counter()
        if name=="update_shipment": result=update(task,args)
        elif name=="estimate_rates":
            result=quote(task["fields"]); task["quote"]=result; citations.extend(references(result.get("source_ids",[])))
        elif name=="check_documents":
            result=document_check(task["fields"]); task["checks"]=result; citations.extend(references(result.get("source_ids",[])))
        elif name=="track_demo": result=track(); task["tracking"]=result
        elif name=="search_rules":
            result=retrieve(str(args.get("query",""))); citations.extend(result)
        else: raise ValidationError("该工具不在可执行列表。")
        trace.append({"tool":name,"arguments":args,"duration_ms":round((time.perf_counter()-started)*1000,2),"result_status":result.get("status","saved") if isinstance(result,dict) else "retrieved"})
        return result
    text=None; model_error=None
    if model.configured():
        try: text=model.respond(message,task,execute)
        except RuntimeError as error: model_error=str(error)
    mode="model" if text else "workflow"
    english=not bool(re.search(r"[\u4e00-\u9fff]",message))
    if not text:
        extracted=extract_fields(message)
        if extracted: execute("update_shipment",extracted)
        if re.search(r"物流|运单|跟踪|tracking|track|签收",message,re.I):
            result=execute("track_demo",{})
            text=("Official sample: delivered, with four recorded events. This is the saved synthetic example." if english else "官方示例运单已送达，共有 4 个物流节点。你可以在物流页面查看时间线；这份记录是已保存的模拟示例。")
        elif re.search(r"检查|核对|check|validate",message,re.I) and re.search(r"发票|单证|装箱|invoice|document|packing",message,re.I):
            result=execute("check_documents",{})
            text=("Document check: "+str(len(result["issues"]))+" issues. Review the Documents page." if english else "已核对单证，发现 "+str(len(result["issues"]))+" 项待处理信息。请到单证页面查看具体行和修正项。")
        elif extracted or re.search(r"报价|运费|多少钱|估算|quote|cost|price|estimate",message,re.I):
            result=execute("estimate_rates",{})
            if result["status"]=="estimated":
                options="；".join(o["service"]+" ¥"+format(o["known_subtotal"],",.2f") for o in result["options"])
                text=(f"Billable weight {result['billable_kg']:g} kg, zone {result['zone']}. Known reference costs: {options}. Fuel and other pending charges remain to be confirmed; arrival is not verified." if english else f"已更新当前需求。计费重量 {result['billable_kg']:g}kg，目的地区 {result['zone']}。已知参考费用：{options}。费用页面列有明细及待确认项目；送达日期尚未核验。")
                citations.extend(references(["rate-scope","weight"]))
            else: text=result["message"] if not english else "More information or manual review is needed: "+", ".join(result.get("missing",[]))
        else:
            docs=execute("search_rules",{"query":message})
            text="\n\n".join(d.get("text_en",d["text"])+" ["+d["id"]+"]" if english else d["text"]+" ["+d["id"]+"]" for d in docs[:2]) if docs else ("Please provide shipment details, or ask about dimensional weight, charges, invoices or tracking." if english else "可以告诉我寄件地、美国邮编、重量和尺寸，也可以询问体积重、附加费、发票或物流状态。")
    if model_error: text+=("\n\n模型连接暂不可用，本轮使用本地流程。" if not english else "\n\nModel unavailable; local workflow used.")
    unique={d["id"]:d for d in citations}
    task["messages"].extend([{"role":"user","text":message},{"role":"assistant","text":text,"mode":mode,"trace":trace,"citations":list(unique.values())}])
    task["messages"]=task["messages"][-80:]
    return {"text":text,"mode":mode,"trace":trace,"citations":list(unique.values()),"model_error":model_error}
