"""Source-grounded conversation with staged writes and read-only scenarios."""
from copy import deepcopy
import re
import time
from .domain import quote, document_check, clean_fields, ValidationError
from .knowledge import retrieve, references
from .tracking import track, SAMPLE
from . import model

FIELD_LABELS = {
    "origin_province": "起运地", "destination_country": "目的地国家", "destination_city": "目的地城市",
    "destination_state": "目的地州", "destination_zip": "目的地邮编", "goods": "货品",
    "weight_kg": "实际重量", "length_cm": "长度", "width_cm": "宽度", "height_cm": "高度",
    "budget_cny": "预算", "deadline": "期望送达日",
}
QUOTE_FIELDS = {"origin_province", "destination_country", "destination_state", "destination_city", "destination_zip", "goods", "weight_kg", "length_cm", "width_cm", "height_cm", "budget_cny", "deadline", "oda_tier", "residential", "fuel_percent"}
ORIGINS = [
    ("上海", "Shanghai"), ("shanghai", "Shanghai"), ("北京", "Beijing"), ("beijing", "Beijing"),
    ("广东", "Guangdong"), ("guangdong", "Guangdong"), ("福建", "Fujian"), ("fujian", "Fujian"),
    ("杭州", "Hangzhou"), ("hangzhou", "Hangzhou"), ("宁波", "Ningbo"), ("ningbo", "Ningbo"),
    ("深圳", "Shenzhen"), ("shenzhen", "Shenzhen"), ("广州", "Guangzhou"), ("guangzhou", "Guangzhou"),
    ("成都", "Chengdu"), ("chengdu", "Chengdu"), ("南京", "Nanjing"), ("nanjing", "Nanjing"),
    ("武汉", "Wuhan"), ("wuhan", "Wuhan"), ("天津", "Tianjin"), ("tianjin", "Tianjin"),
]
CITIES = [
    (["洛杉矶", "los angeles"], "Los Angeles", "CA"),
    (["纽约", "new york"], "New York", "NY"),
    (["西雅图", "seattle"], "Seattle", "WA"),
    (["旧金山", "san francisco"], "San Francisco", "CA"),
    (["芝加哥", "chicago"], "Chicago", "IL"),
    (["波士顿", "boston"], "Boston", "MA"),
]
HYPOTHETICAL = re.compile(r"如果|假如|假设|要是|设想|例如|举例|比较|对比|\b(?:if|suppose|hypothetical|compare)\b", re.I)
NEGATED = re.compile(r"不要|先不|暂不|不修改|不更新|不改动|保持原|维持原|不(?:想|打算|需要).{0,12}(?:改|修改|更新|调整|设置)|(?:别|不(?:用|必|需要|打算|想|应|能)?)(?:再|先|给我|帮我)?(?:改|修改|更新|调整|更正|换|设置)|\b(?:don['’]?t|do not|never|without (?:changing|updating|saving|modifying)|keep (?:the )?(?:original|current))\b", re.I)
QUESTION = re.compile(r"[?？]|怎么|如何|是否|能否|多少|哪个|哪种|区别|为什么|吗|够不够|能不能|可不可以|会不会|行不行|可否|\b(?:how|why|which|what|would|could|can|is|does|are)\b", re.I)
CHANGE = re.compile(r"改成|改为|改到|修改|更新|更正|换成|换到|调整|设置|\b(?:change|update|set|correct|replace)\b", re.I)
QUOTE_INTENT = re.compile(r"报价|运费|多少钱|估算|便宜|费用|\b(?:quote|cost|price|estimate|cheaper)\b", re.I)
TRACKING_INTENT = re.compile(r"运单|单号|跟踪|签收|物流(?:查询|状态|进度|轨迹|节点)|(?:查|查询|查看|查一下).{0,12}物流|物流.{0,12}(?:到哪|在哪里|在哪|状态|进度)|\b(?:tracking|track|delivered|shipment status)\b", re.I)
DOCUMENT_INTENT = re.compile(r"发票|单证|装箱|\b(?:invoice|document|packing)\b", re.I)
CHECK_INTENT = re.compile(r"检查|核对|\b(?:check|validate)\b", re.I)
CHECK_REQUEST = re.compile(r"^(?:检查|核对)|(?:请|帮我|替我|现在|立即|重新|再).{0,10}(?:检查|核对)|\b(?:please|can you|could you|would you).{0,20}(?:check|validate)\b|^(?:check|validate)\b", re.I)
SHIPPING_TOPIC = re.compile(r"寄件|寄送|包裹|快递|起运|目的地|运费|运输|物流|体积重|计费重|重量|尺寸|预算|邮编|住宅|偏远|燃油|海关|清关|申报|税费|单证|发票|装箱|运单|HS\s*编码|\b(?:parcel|shipping|shipment|freight|dimensional|billable|budget|invoice|packing|customs|tracking|zip|fedex|ship24|IE|IP|IPE)\b", re.I)


def _local_conversation(message, task, english):
    """Small offline affordances; never pretend templates are a language model."""
    text = message.strip().strip("。.!！?？~～ ").lower()
    if re.fullmatch(r"你好(?:呀|啊|哇)?|您好|嗨|哈[喽啰]|早上好|晚上好|hi|hello|hey", text):
        return "Hi! What would you like to talk about?" if english else "你好呀！想聊点什么？"
    if re.fullmatch(r"谢谢(?:你|啦|啊)?|多谢|thanks(?: a lot)?|thank you", text):
        return "You're welcome!" if english else "不客气！"
    if re.search(r"你(?:是|叫)谁|你叫什么|who are you|what(?:'s| is) your name", text):
        return "I'm Parcel Desk, the assistant on this page. AI chat can be connected in the chat settings." if english else "我是 Parcel Desk，这个页面里的助手。接通 AI 对话后，我就可以回答更开放的问题。"
    if re.search(r"(?:刚才|之前|目前|现在|当前).{0,12}(?:需求|寄什么|多少|多重|重量|预算|目的地)|(?:还)?记得.{0,12}(?:寄|包裹|需求)|what did i|my (?:current|saved) shipment", text):
        f = task["fields"]
        if not f:
            return "You haven't added parcel details to this task yet." if english else "这个任务里还没填包裹信息。"
        route = (f.get("origin_province") or "待填起运地") + " → " + (f.get("destination_city") or "待填目的地")
        weight = str(f.get("weight_kg", "待填")) + " kg"
        return (f"Your current parcel: {f.get('goods') or 'goods not provided'}, {weight}, {route}." if english else f"你这次准备寄 {f.get('goods') or '待填写的货品'}，{weight}，路线是 {route}。")
    if re.search(r"你(?:能|可以)(?:做|帮)|有什么功能|what can you do|how can you help", text):
        return ("I can calculate reference shipping costs, compare parcel options and check invoice details. Connect AI chat here for open-ended conversation and writing help." if english else "我现在能算参考运费、比较寄件方案、核对发票和装箱单。接通 AI 对话后，也能自由聊天、解释问题和帮你写东西。")
    return None


def _target_text(message):
    """Prefer an explicit new value over the old value in '10kg 改成 8kg'."""
    target = re.search(r"(?:改成|改为|改到|换成|调整为|更正为|而是|\b(?:to|with)\b)\s*([^。；;!?？]+)", message, re.I)
    return target.group(1) if target else message


def extract_fields(message):
    """Extract candidates only; the intent gate decides whether they can be saved."""
    fields = {}
    text = message.lower()
    target = _target_text(text)
    for pattern, key in [
        (r"(?<![\d.])(-?\d+(?:\.\d+)?)\s*(?:kg|公斤|千克)", "weight_kg"),
        (r"(?:预算|budget)[^\d-]{0,12}(-?\d+(?:\.\d+)?)", "budget_cny"),
    ]:
        match = re.search(pattern, target) or re.search(pattern, text)
        if match:
            fields[key] = float(match.group(1))
    new_budget = re.search(r"(?:预算|budget).{0,25}?(?:改成|改为|调整为|\bto\b)\s*(-?\d+(?:\.\d+)?)", text)
    if new_budget:
        fields["budget_cny"] = float(new_budget.group(1))
    dims = re.search(r"(?<![\d.])(-?\d+(?:\.\d+)?)\s*[x×*]\s*(-?\d+(?:\.\d+)?)\s*[x×*]\s*(-?\d+(?:\.\d+)?)\s*(cm|厘米|inches?|英寸|mm|毫米|m|米)?", target)
    if dims and dims.group(4) in {None, "cm", "厘米"}:
        fields.update(dict(zip(["length_cm", "width_cm", "height_cm"], map(float, dims.groups()[:3]))))
    match = re.search(r"(?:邮编|zip(?:\s*code)?)[\s:：]*(\d{5}(?:-\d{4})?)", text)
    if match:
        fields["destination_zip"] = match.group(1)
    match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", target)
    if match and (re.search(r"截止|送达|到达|月底|deadline|arriv|deliver|before|by", text) or CHANGE.search(text)):
        fields["deadline"] = match.group(1)
    for word, province in ORIGINS:
        if word in target:
            fields["origin_province"] = province
            break
    if "origin_province" not in fields:
        for word, province in ORIGINS:
            if word in text:
                fields["origin_province"] = province
                break
    for words, city, state in CITIES:
        if any(word in target for word in words):
            fields.update(destination_city=city, destination_state=state, destination_country="US")
            break
    if "destination_city" not in fields:
        for words, city, state in CITIES:
            if any(word in text for word in words):
                fields.update(destination_city=city, destination_state=state, destination_country="US")
                break
    for words, goods in [
        (["衣服", "衣物", "t-shirt", "cotton", "clothes"], "Cotton clothing"),
        (["书籍", "书本", "books"], "Printed books"),
        (["电池", "battery", "batteries"], "Battery-containing goods"),
        (["液体", "liquid"], "Liquid goods"),
    ]:
        if any(word in text for word in words):
            fields["goods"] = goods
            break
    return fields


def update(task, fields):
    """Apply a validated patch, clearing dependent results and stale destinations."""
    fields = clean_fields(fields)
    previous = task["fields"]
    city_changed = "destination_city" in fields and fields["destination_city"] != previous.get("destination_city")
    state_changed = "destination_state" in fields and fields["destination_state"] != previous.get("destination_state")
    country_changed = "destination_country" in fields and fields["destination_country"] != previous.get("destination_country")
    if city_changed or state_changed or country_changed:
        # A previously saved postcode must not silently travel to a new address.
        if "destination_zip" not in fields or fields.get("destination_zip") == previous.get("destination_zip"):
            fields["destination_zip"] = None
        if city_changed and "destination_state" not in fields:
            fields["destination_state"] = None
        if (state_changed or country_changed) and "destination_city" not in fields:
            fields["destination_city"] = None
        if country_changed and "destination_state" not in fields:
            fields["destination_state"] = None
    changed = {key for key, value in fields.items() if previous.get(key) != value}
    if changed:
        previous.update(fields)
        if changed & QUOTE_FIELDS:
            task["quote"] = None
            task["selected_service"] = None
        task["checks"] = None
    return task["fields"]


def _follow_up(message, task, extracted):
    """Accept a short missing-field answer only after that field was requested."""
    missing = (task.get("quote") or {}).get("missing", [])
    if not missing or not task.get("messages"):
        return extracted, False
    text = message.strip()
    if re.fullmatch(r"\d{5}(?:-\d{4})?", text) and "destination_zip" in missing:
        return {"destination_zip": text}, True
    if extracted and set(extracted).issubset(set(missing)) and len(text) <= 100:
        return extracted, True
    return extracted, False


def _classify(message, task):
    extracted = extract_fields(message)
    proposed, follow_up = _follow_up(message, task, extracted)
    hypothetical = bool(HYPOTHETICAL.search(message))
    negated = bool(NEGATED.search(message))
    question = bool(QUESTION.search(message))
    demo = bool(SAMPLE in message or re.search(r"(?:官方|模拟|演示|示例|sample|demo|synthetic).*(?:运单|物流|tracking|track)|(?:tracking|track).*(?:sample|demo|synthetic)", message, re.I))
    tracking = bool(TRACKING_INTENT.search(message) or SAMPLE in message or demo)
    if tracking:
        return {"intent": "tracking", "fields": {}, "can_update": False, "allow_demo": demo and not negated and not hypothetical}
    if DOCUMENT_INTENT.search(message) and CHECK_INTENT.search(message):
        procedural = bool(re.search(r"怎么|如何|怎样|哪些|什么|\b(?:how|what|which)\b", message, re.I))
        execute_check = not negated and not hypothetical and not procedural and bool(CHECK_REQUEST.search(message))
        return {"intent": "documents" if execute_check else "consultation", "fields": {}, "can_update": False, "allow_demo": False}
    measure = bool(re.search(r"\d\s*(?:kg|公斤|千克)|\d\s*[x×*]\s*\d", message, re.I))
    shipment_topic = bool(SHIPPING_TOPIC.search(message) or re.search(r"(?:我想|我要|准备|需要)寄|寄.{0,25}(?:到|往)|从.{0,25}寄|\b(?:ship|send a parcel)\b", message, re.I))
    if proposed and (hypothetical or (question and QUOTE_INTENT.search(message))) and (shipment_topic or measure):
        return {"intent": "scenario", "fields": proposed, "can_update": False, "allow_demo": False}
    if negated or question:
        return {"intent": "consultation", "fields": {}, "can_update": False, "allow_demo": False}
    declaration = bool(re.search(r"我想|我要|我需要|寄往|寄到|从.+寄|重量(?:是|为)|尺寸(?:是|为)|预算(?:是|为|[\s:：]*\d)|\b(?:i want|i need|send|ship|weight is|dimensions are|budget is)\b", message, re.I))
    can_update = bool(proposed and (follow_up or CHANGE.search(message) and (shipment_topic or measure) or declaration and shipment_topic))
    return {"intent": "update" if can_update else "consultation", "fields": proposed if can_update else {}, "can_update": can_update, "allow_demo": False}


def _quote_text(result, english, prefix=""):
    if result["status"] != "estimated":
        if english:
            missing = result.get("missing", [])
            return prefix + ("Please provide: " + ", ".join(missing) if missing else "The shipment needs eligibility or service-acceptance review. See the rate details.")
        return prefix + result["message"]
    options = "; ".join(option["service"] + " ¥" + format(option["known_subtotal"], ",.2f") for option in result["options"])
    return prefix + (
        f"Billable weight {result['billable_kg']:g} kg, zone {result['zone']}. Known reference costs: {options}. Fuel and remaining charges need confirmation."
        if english else f"计费重量 {result['billable_kg']:g}kg，目的地区 {result['zone']}。已知参考费用：{options}。燃油及其他待确认项目见费用明细。"
    )


def chat(task, message):
    if not isinstance(message, str) or not message.strip() or len(message) > 6000:
        raise ValidationError("请输入 1–6000 字的问题。")
    message = message.strip()
    original = deepcopy(task)
    working = deepcopy(task)
    decision = _classify(message, original)
    english = not bool(re.search(r"[\u4e00-\u9fff]", message))
    trace, citations = [], []
    scenario = None
    violation = False

    def execute(name, args):
        nonlocal violation
        started = time.perf_counter()
        if name == "update_shipment":
            approved = decision["fields"]
            patch = clean_fields(args)
            if not decision["can_update"] or any(key not in approved or value != approved[key] for key, value in patch.items()):
                violation = True
                raise ValidationError("本轮没有授权这些需求修改；请保留已保存信息。")
            result = update(working, patch)
        elif name == "estimate_rates":
            estimate_fields = deepcopy(working["fields"])
            if decision["intent"] == "scenario":
                candidate = {"fields": estimate_fields, "quote": None, "checks": None}
                update(candidate, decision["fields"])
                estimate_fields = candidate["fields"]
            result = quote(estimate_fields)
            if decision["intent"] != "scenario":
                working["quote"] = result
            citations.extend(references(result.get("source_ids", [])))
        elif name == "check_documents":
            if decision["intent"] != "documents":
                violation = True
                raise ValidationError("本轮没有请求执行单证检查；请保留已保存检查结果。")
            result = document_check(working["fields"])
            working["checks"] = result
            citations.extend(references(result.get("source_ids", [])))
        elif name == "track_demo":
            if not decision["allow_demo"]:
                violation = True
                raise ValidationError("当前问题没有请求官方模拟运单。")
            result = track()
            working["tracking"] = result
        elif name == "search_rules":
            result = retrieve(str(args.get("query", "")))
            citations.extend(result)
        else:
            raise ValidationError("该工具不在可执行列表。")
        trace.append({"tool": name, "arguments": args, "duration_ms": round((time.perf_counter() - started) * 1000, 2), "result_status": result.get("status", "saved") if isinstance(result, dict) else "retrieved"})
        return result

    def apply_explicit_fields():
        if decision["can_update"]:
            execute("update_shipment", decision["fields"])

    def prepare_scenario():
        nonlocal scenario
        candidate = {"fields": deepcopy(original["fields"]), "quote": None, "checks": None}
        update(candidate, decision["fields"])
        result = execute("estimate_rates", {})
        baseline = quote(original["fields"])
        before = {row["service"]: row["known_subtotal"] for row in baseline.get("options", [])}
        differences = [{"service": row["service"], "before": before[row["service"]], "after": row["known_subtotal"], "delta": round(row["known_subtotal"] - before[row["service"]], 2)} for row in result.get("options", []) if row["service"] in before]
        scenario = {"fields": candidate["fields"], "quote": result, "baseline": baseline, "differences": differences}
        return result

    text, model_error = None, None
    quote_requested = bool(QUOTE_INTENT.search(message)) and bool(SHIPPING_TOPIC.search(message) or decision["fields"] or re.fullmatch(r"(?:多少[钱费用]?|费用是多少|报价|贵吗|便宜点吗|how much|quote|cost)[?？。.!！ ]*", message, re.I))
    # Every topic can reach a configured model; executable writes remain intent-gated.
    use_model = model.configured()
    if use_model:
        try:
            apply_explicit_fields()
            if decision["intent"] == "scenario":
                prepare_scenario()
            model_task = {**working, "_turn_context": {"intent": decision["intent"], "scenario": scenario}}
            text = model.respond(message, model_task, execute)
            if violation:
                raise RuntimeError("模型工具请求与本轮意图不一致。")
            if text and (decision["can_update"] or quote_requested) and not any(row["tool"] == "estimate_rates" for row in trace):
                raise RuntimeError("模型未执行本轮费用核算。")
            if text and decision["intent"] == "documents" and not any(row["tool"] == "check_documents" for row in trace):
                raise RuntimeError("模型没有完成文件核对，已改用本机检查。")
            if text and decision["allow_demo"] and not any(row["tool"] == "track_demo" for row in trace):
                raise RuntimeError("模型没有读取物流示例，已改用缓存结果。")
        except (RuntimeError, ValidationError, TypeError, KeyError) as error:
            model_error = str(error)
            text = None
        if not text:
            # Never reuse partly updated state or traces from an unsuccessful model round.
            working = deepcopy(original)
            trace.clear()
            citations.clear()
            scenario = None
    mode = "model" if text else "workflow"
    connection_required = False
    if not text:
        apply_explicit_fields()
        if decision["intent"] == "scenario":
            result = prepare_scenario()
            differences = scenario["differences"]
            text = _quote_text(result, english, "Scenario estimate: " if english else "按这个条件试算：")
            if differences:
                delta_text = "; ".join(row["service"] + (f" -¥{abs(row['delta']):,.2f}" if row["delta"] < 0 else f" +¥{row['delta']:,.2f}" if row["delta"] > 0 else " ¥0.00") for row in differences)
                text += ("\nCompared with your current parcel: " if english else "\n比你当前这票包裹：") + delta_text
        elif decision["intent"] == "tracking":
            if decision["allow_demo"]:
                result = execute("track_demo", {})
                text = ("Official synthetic sample: delivered, with four French events. It is unrelated to your shipment." if english else "官方模拟运单共有 4 个法国物流节点，状态为已送达。这份示例与当前运输任务无关联。")
            else:
                text = ("Open Tracking, enter your tracking number and enable the Ship24 lookup to see its latest events." if english else "可以，到「查询物流」填写运单号，再勾选 Ship24 查询，就能查看这票包裹的轨迹。")
        elif decision["intent"] == "documents":
            result = execute("check_documents", {})
            text = (f"Document check: {len(result['issues'])} issues. Review the highlighted fields on Documents." if english else f"已核对单证，发现 {len(result['issues'])} 项待处理信息。请到单证页查看对应字段和货品行。")
        elif decision["can_update"] or quote_requested:
            result = execute("estimate_rates", {})
            text = _quote_text(result, english, ("Got it. " if english else "好的，") if decision["can_update"] else "")
        elif CHANGE.search(message) and not NEGATED.search(message) and not QUESTION.search(message):
            text = ("Which parcel detail would you like to change, and what should the new value be?" if english else "你想改哪一项、改成什么？可以直接说，比如“把重量改成8kg”。")
        else:
            text = _local_conversation(message, working, english)
            if not text and SHIPPING_TOPIC.search(message):
                docs = execute("search_rules", {"query": message})
                text = "\n\n".join((doc.get("text_en", doc["text"]) if english else doc["text"]) + " [" + doc["id"] + "]" for doc in docs[:2]) if docs else None
            if not text:
                connection_required = not use_model
                text = ("AI chat isn't connected yet, so I can't answer this open-ended question. You can connect a model using ‘Enable AI chat’ above." if english else "这个问题需要接通 AI 对话才能回答。你可以点上方“启用 AI 对话”，接入模型后继续聊。") if not use_model else ("The AI connection failed. Check the model settings and try again." if english else "AI 暂时没连上。检查一下模型设置，再试着发给我。")
    if decision["intent"] == "scenario":
        # Explicit invariant even if a future tool or model branch changes incidental state.
        for key in ["fields", "quote", "checks", "selected_service", "tracking"]:
            if key in original:
                working[key] = deepcopy(original[key])
            else:
                working.pop(key, None)
    changes = [{"field": key, "label": FIELD_LABELS.get(key, key), "before": original["fields"].get(key), "after": working["fields"].get(key)} for key in sorted(original["fields"].keys() | working["fields"].keys()) if original["fields"].get(key) != working["fields"].get(key)]
    unique = {doc["id"]: doc for doc in citations}
    answer = {"role": "assistant", "text": text, "mode": mode, "intent": decision["intent"], "changes": changes, "scenario": scenario, "trace": trace, "citations": list(unique.values()), "connection_required": connection_required, "model_error": model_error}
    working.setdefault("messages", []).extend([{"role": "user", "text": message}, answer])
    working["messages"] = working["messages"][-80:]
    task.clear()
    task.update(working)
    return {key: answer[key] for key in ["text", "mode", "intent", "changes", "scenario", "trace", "citations"]} | {"model_error": model_error}
