"""Deterministic parcel estimates and document consistency checks."""
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP, InvalidOperation
import html
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RATES = json.loads((ROOT / "data/parcel/rates.json").read_text())
WEST = [(80000,81699,"CO"),(83200,83999,"ID"),(84000,84799,"UT"),(85000,86599,"AZ"),
        (89000,89899,"NV"),(90000,96699,"CA"),(97000,97999,"OR"),(98000,99499,"WA")]
NUMERIC = {"weight_kg","length_cm","width_cm","height_cm","budget_cny","fuel_percent","invoice_total"}
TEXT = {"origin_province","destination_country","destination_state","destination_city","destination_zip",
        "goods","deadline","oda_tier","sender_name","sender_address","sender_phone","recipient_name",
        "recipient_address","recipient_phone","currency","country_of_origin","invoice_number","ship_date"}
ALLOWED = TEXT | NUMERIC | {"residential","items"}
LABELS = {"weight_kg":"实际重量","length_cm":"长度","width_cm":"宽度","height_cm":"高度","destination_zip":"美国邮编","origin_province":"起运省市","goods":"货品描述"}
ITEM_TEXT = {"description", "hs_code"}
ITEM_NUMERIC = {"quantity", "packing_quantity", "unit_price"}
SHIPMENT_REQUIRED = ["origin_province", "destination_zip", "goods", "weight_kg", "length_cm", "width_cm", "height_cm"]


class ValidationError(ValueError):
    pass


def number(value, name="数值", positive=True):
    try:
        if isinstance(value, bool): raise InvalidOperation
        value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError(name + "需要填写有效数字。")
    if not value.is_finite() or (value <= 0 if positive else value < 0):
        raise ValidationError(name + ("必须大于零。" if positive else "不能小于零。"))
    if value > Decimal("1000000000"): raise ValidationError(name + "超出支持范围。")
    return value


def money(value):
    return float(Decimal(value).quantize(Decimal(".01"), rounding=ROUND_HALF_UP))


def clean_fields(fields):
    if not isinstance(fields, dict): raise ValidationError("需求应为字段对象。")
    result = {}
    for key, value in fields.items():
        if key not in ALLOWED: raise ValidationError("不支持的字段：" + str(key))
        if value is None or value == "": result[key] = None
        elif key in NUMERIC:
            result[key] = float(number(value, LABELS.get(key,key), positive=key not in {"fuel_percent","budget_cny","invoice_total"}))
        elif key == "residential":
            if not isinstance(value,bool): raise ValidationError("住宅选项应为是、否或未知。")
            result[key] = value
        elif key == "items":
            if not isinstance(value,list) or len(value)>100: raise ValidationError("最多支持 100 行货品。")
            result[key] = []
            for index, item in enumerate(value, 1):
                if not isinstance(item, dict) or set(item) - (ITEM_TEXT | ITEM_NUMERIC):
                    raise ValidationError(f"第 {index} 行货品字段格式无效。")
                cleaned = {}
                for field, content in item.items():
                    if content is None or content == "": cleaned[field] = None
                    elif field in ITEM_NUMERIC:
                        # Incomplete drafts and zero quantities can be saved and located by
                        # document checks. Nested objects and non-finite values cannot persist.
                        cleaned[field] = float(number(content, f"第 {index} 行 {field}", positive=False))
                    elif not isinstance(content, str) or len(content) > 2000:
                        raise ValidationError(f"第 {index} 行 {field} 需要有效文本。")
                    else: cleaned[field] = content.strip()
                result[key].append(cleaned)
        else:
            if not isinstance(value,str) or len(value)>2000: raise ValidationError("文本字段过长或格式错误。")
            result[key] = value.strip()
    if result.get("fuel_percent") is not None and result["fuel_percent"]>100:
        raise ValidationError("燃油情景百分比应在 0–100 之间。")
    if result.get("oda_tier") not in {None,"unknown","none","A","B","C"}:
        raise ValidationError("偏远地区档位无效。")
    for key in ["deadline","ship_date"]:
        if result.get(key):
            try: date.fromisoformat(result[key])
            except ValueError: raise ValidationError("日期应为 YYYY-MM-DD。")
    return result


def quote(fields):
    f = clean_fields(fields)
    missing = [k for k in SHIPMENT_REQUIRED if not f.get(k)]
    if missing:
        return {"status":"needs_input","missing":missing,"message":"请补充："+"、".join(LABELS.get(k,k) for k in missing),"options":[]}
    if (f.get("destination_country") or "US").upper() != "US":
        return {"status":"needs_review","message":"当前核算范围为中国出口至美国。","options":[]}
    origin = f["origin_province"].lower()
    if any(p in origin for p in ["广东","福建","guangdong","fujian","广州","深圳","厦门","guangzhou","shenzhen","xiamen"]):
        return {"status":"needs_review","message":"广东和福建需要对应地区费率表，当前保留表不适用。","options":[]}
    origins="北京 天津 河北 山西 内蒙古 辽宁 吉林 黑龙江 上海 江苏 浙江 安徽 江西 山东 河南 湖北 湖南 广西 海南 重庆 四川 贵州 云南 西藏 陕西 甘肃 青海 宁夏 新疆 杭州 宁波 苏州 南京 成都 武汉 beijing tianjin hebei shanxi inner mongolia liaoning jilin heilongjiang shanghai jiangsu zhejiang anhui jiangxi shandong henan hubei hunan guangxi hainan chongqing sichuan guizhou yunnan tibet shaanxi gansu qinghai ningxia xinjiang hangzhou ningbo suzhou nanjing chengdu wuhan".split()
    if not any(p in origin for p in origins):
        return {"status":"needs_review","message":"请确认中国大陆起运省市；当前起运地尚未匹配到适用范围。","options":[]}
    if re.search(r"电池|液体|危险品|battery|batteries|liquid|dangerous",f.get("goods", ""),re.I):
        return {"status":"needs_review","message":"该货品需要先核对类别、包装与承运条件，再提供服务方案。","options":[],"source_ids":["dangerous"]}
    zip_code = str(f["destination_zip"])
    if not re.fullmatch(r"\d{5}(?:-\d{4})?",zip_code) or zip_code[:5]=="00000":
        raise ValidationError("美国邮编应为 5 位，可附加 4 位扩展码。")
    zip_int = int(zip_code[:5])
    zone = "1" if any(lo<=zip_int<=hi for lo,hi,s in WEST) else "2"
    state = (f.get("destination_state") or "").upper()
    west_state = next((s for lo,hi,s in WEST if lo<=zip_int<=hi),None)
    if state and ((west_state and state != west_state) or (state in {s for lo,hi,s in WEST} and state!=west_state)):
        raise ValidationError("州与邮编分区不一致，请核对后再计算。")
    city = re.sub(r"[\s,.-]+", " ", (f.get("destination_city") or "").strip().lower())
    known_cities = {"los angeles":"CA", "洛杉矶":"CA", "seattle":"WA", "西雅图":"WA", "new york":"NY", "new york city":"NY", "纽约":"NY"}
    city_state = known_cities.get(city)
    if city_state and state and state != city_state:
        raise ValidationError("城市与州代码不一致，请核对目的地。")
    if city_state and ((city_state in {"CA", "WA"} and west_state != city_state) or (city_state == "NY" and not 10000 <= zip_int <= 14999)):
        raise ValidationError("城市与邮编不一致，请核对目的地。")
    dims = [number(f[k]) for k in ["length_cm","width_cm","height_cm"]]
    ordered = sorted(dims, reverse=True); volume = dims[0]*dims[1]*dims[2]
    if ordered[0]>121 or ordered[1]>76 or ordered[0]+2*(ordered[1]+ordered[2])>266 or volume>169901:
        return {"status":"needs_review","message":"尺寸触发非标准小包条件，需要额外操作费与最低计费重量核算。","options":[]}
    actual = number(f["weight_kg"]); volumetric = volume/Decimal(5000)
    billable = (max(actual,volumetric)*2).to_integral_value(rounding=ROUND_CEILING)/2
    if billable>Decimal("20.5"):
        return {"status":"needs_review","message":"计费重量超过已提取的 20.5kg 普通小包档位。","billable_kg":float(billable),"options":[]}
    pending = ["税费、清关服务费及其他特殊费用","取件偏远地区资格","账户价格资格与当前服务覆盖"]
    fees = [{"label":"美国入境处理费（来源版本）","amount":19.30,"source":"inbound"}]
    tier = f.get("oda_tier") or "unknown"
    if tier in {"A","B","C"}:
        amount = Decimal(23) if tier=="A" else max(Decimal(171 if tier=="B" else 222),billable*Decimal("3.9" if tier=="B" else "5.1"))
        fees.append({"label":"派送偏远地区费 "+tier+"（用户确认）","amount":money(amount),"source":"remote"})
    elif tier=="none":
        if f.get("residential") is True: fees.append({"label":"美国住宅派送费","amount":24,"source":"remote"})
        elif f.get("residential") is None: pending.append("住宅地址属性")
    else: pending.append("派送偏远地区档位及住宅费适用性")
    fuel = f.get("fuel_percent")
    if fuel is None: pending.append("当期燃油附加费")
    if f.get("deadline"): pending.append("是否满足 "+f["deadline"]+" 的时效要求")
    options=[]
    for service in RATES["services"]:
        row = next(r for r in service["rates"] if r["weight_kg"]==float(billable))
        base = Decimal(str(row["zones"][zone]))
        components = [{"label":"公开表基础运费","amount":money(base),"source_page":service["source_page"]}] + fees.copy()
        if fuel is not None:
            components.append({"label":f"基础运费燃油情景 {fuel:g}%（未在线核验）","amount":money(base*Decimal(str(fuel))/100),"source":"fuel"})
        subtotal = sum(Decimal(str(c["amount"])) for c in components)
        options.append({"service":service["code"],"name":service["name"],"base_charge":money(base),"components":components,
                        "known_subtotal":money(subtotal),"budget_status":"unknown" if f.get("budget_cny") is None else "over" if subtotal>Decimal(str(f["budget_cny"])) else "within_known_cost",
                        "source_url":RATES["source_url"],"source_page":service["source_page"],"arrival_confirmed":False})
    options.sort(key=lambda o:o["known_subtotal"])
    return {"status":"estimated","zone":zone,"actual_kg":float(actual),"volumetric_kg":round(float(volumetric),4),
            "billable_kg":float(billable),"currency":"CNY","effective_from":RATES["effective_from"],"source_collected_on":RATES["collected_on"],
            "options":options,"pending":pending,"price_label":"公开参考费用估算 · 已知项目小计","fuel_verified":False,
            "source_ids":["rate-scope","weight","us-zone","inbound","remote","fuel"],"message":"已按分区与计费重量计算三种服务。"}


def document_check(fields):
    f=clean_fields(fields); issues=[]
    def issue(code,message,field=None,item_index=None,related_fields=None):
        row={"code":code,"message":message}
        if field is not None: row["field"]=field
        if item_index is not None: row["item_index"]=item_index
        if related_fields: row["related_fields"]=related_fields
        issues.append(row)
    for key,label in [("invoice_number","发票编号"),("ship_date","寄件日期"),("sender_name","寄件人姓名"),("sender_address","寄件人地址"),("sender_phone","寄件人电话"),
                      ("recipient_name","收件人姓名"),("recipient_address","收件人地址"),("recipient_phone","收件人电话"),("currency","申报币种"),("country_of_origin","货品原产地")]:
        if not f.get(key): issue("missing_"+key,"缺少"+label,key)
    items=f.get("items") or []
    if not items: issue("missing_items","请添加货品明细。","items")
    total=Decimal(0); lines=[]
    for index,item in enumerate(items,1):
        name=str(item.get("description") or "").strip()
        if not name: issue("missing_description",f"第 {index} 行缺少货品描述。","description",index-1)
        elif name.lower() in {"gift","gifts","parts","礼物","配件"}: issue("vague_description",f"第 {index} 行描述过于笼统，请补充材质与用途。","description",index-1)
        parsed={}
        for field,label in [("quantity","发票数量"),("packing_quantity","装箱数量"),("unit_price","单价")]:
            try:
                parsed[field]=number(item.get(field),f"第 {index} 行{label}",positive=field!="unit_price")
                if field!="unit_price" and parsed[field]!=parsed[field].to_integral_value():
                    raise ValidationError(f"第 {index} 行{label}需要是整数。")
                if field=="unit_price" and parsed[field] != parsed[field].quantize(Decimal(".01")):
                    raise ValidationError(f"第 {index} 行单价最多保留两位小数。")
                if field=="unit_price" and parsed[field]==0:
                    issue("zero_value",f"第 {index} 行单价为零，请填写有效申报价值或先核对。",field,index-1)
            except ValidationError as error:
                parsed.pop(field,None)
                issue("invalid_item",str(error),field,index-1)
        if len(parsed)!=3: continue
        qty,pack,price=(parsed[k] for k in ["quantity","packing_quantity","unit_price"])
        line=Decimal(str(money(qty*price))); total+=line
        if qty!=pack:
            issue("quantity_mismatch",f"第 {index} 行 {name}：发票 {qty} 件，装箱单 {pack} 件。","packing_quantity",index-1,["quantity","packing_quantity"])
        lines.append({"description":name,"quantity":int(qty),"packing_quantity":int(pack),"unit_price":money(price),"line_total":money(line),"hs_code":str(item.get("hs_code") or "")})
    if f.get("invoice_total") is not None:
        declared=Decimal(str(f["invoice_total"]))
        if declared != declared.quantize(Decimal(".01")):
            issue("invalid_total_precision","发票合计最多保留两位小数。","invoice_total")
        elif declared!=total:
            issue("total_mismatch",f"填写合计与逐行计算结果 {money(total):.2f} 不一致。","invoice_total")
    return {"status":"needs_correction" if issues else "checked","issues":issues,"calculated_total":money(total),"currency":f.get("currency"),"lines":lines,
            "review_items":["进口人信息与适用文件要求","HS 编码、签字与最终申报信息"],"source_ids":["invoice","description","packing"]}


def document_html(fields,kind="invoice"):
    f=clean_fields(fields); checked=document_check(f); esc=lambda x:html.escape(str(x or "待填写"))
    title="COMMERCIAL INVOICE" if kind=="invoice" else "PACKING LIST"
    rows="".join("<tr><td>"+esc(row["description"])+"</td><td>"+esc(row["hs_code"])+"</td><td>"+str(row["quantity"] if kind=="invoice" else row["packing_quantity"])+"</td>"+(f"<td>{row['unit_price']:.2f}</td><td>{row['line_total']:.2f}</td>" if kind=="invoice" else "")+"</tr>" for row in checked["lines"])
    issues="".join("<li>"+esc(i["message"])+"</li>" for i in checked["issues"])
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{title} · draft</title><style>
body{{font:14px/1.6 Arial,sans-serif;color:#182b35;max-width:850px;margin:40px auto;padding:30px}}h1{{font-size:29px;letter-spacing:2px}}.draft{{color:#876027}}.parties{{display:grid;grid-template-columns:1fr 1fr;gap:40px}}table{{width:100%;border-collapse:collapse;margin:24px 0}}th,td{{border:1px solid #ccd4d7;padding:12px;text-align:left}}th{{background:#f0f4f4}}button{{padding:10px 20px}}@media print{{button{{display:none}}body{{margin:0;max-width:none}}}}</style>
<button onclick="window.print()">打印 / 另存为 PDF</button><p class="draft">DRAFT · 待客户与承运人核对的文件草稿</p><h1>{title}</h1>
<p>Reference: {esc(f.get('invoice_number'))}　Date: {esc(f.get('ship_date'))}</p><div class="parties"><section><h3>SHIPPER / EXPORTER</h3><p>{esc(f.get('sender_name'))}<br>{esc(f.get('sender_address'))}<br>{esc(f.get('sender_phone'))}</p></section><section><h3>CONSIGNEE</h3><p>{esc(f.get('recipient_name'))}<br>{esc(f.get('recipient_address'))}<br>{esc(f.get('recipient_phone'))}</p></section></div>
<p>Country of origin: {esc(f.get('country_of_origin'))}　Currency: {esc(f.get('currency'))}</p><p>Packages: 1 · Gross weight: {esc(f.get('weight_kg'))} kg · Dimensions: {esc(f.get('length_cm'))} × {esc(f.get('width_cm'))} × {esc(f.get('height_cm'))} cm</p><table><thead><tr><th>Description</th><th>HS code (review)</th><th>Quantity</th>{'<th>Unit price</th><th>Amount</th>' if kind=='invoice' else ''}</tr></thead><tbody>{rows}</tbody></table>
{'<h3>Total: '+str(checked['calculated_total'])+' '+esc(f.get('currency'))+'</h3>' if kind=='invoice' else ''}
<p>Importer / HS codes / signature: review before use.</p>{'<h3>待补充与修正</h3><ul>'+issues+'</ul>' if issues else '<p>基础字段、金额和数量一致性检查已通过。</p>'}<p>Prepared by Parcel Desk · Document draft, subject to final review.</p></html>'''


def select_service(task, service):
    """Select an existing estimate; callers cannot supply a price or a service object."""
    if not isinstance(service, str) or service not in {'IE', 'IP', 'IPE'}:
        raise ValidationError('请选择有效的运输服务。')
    estimate = task.get('quote') or {}
    if estimate.get('status') != 'estimated':
        raise ValidationError('请先保存包裹需求并计算参考费用，再选择方案。')
    option = next((row for row in estimate.get('options', []) if row.get('service') == service), None)
    if not option:
        raise ValidationError('该方案不在当前估算中，请重新计算。')
    task['selected_service'] = json.loads(json.dumps(option))
    return task['selected_service']


def task_progress(task):
    """Progress means preparation, never a booking or verified carrier acceptance."""
    fields = task.get('fields') or {}
    estimate = task.get('quote') or {}
    selected = task.get('selected_service') or {}
    checks = task.get('checks') or {}
    missing = [key for key in SHIPMENT_REQUIRED if not fields.get(key)]
    details_done = not missing and estimate.get('status') == 'estimated'
    selected_done = details_done and any(
        row.get('service') == selected.get('service') and
        row.get('known_subtotal') == selected.get('known_subtotal')
        for row in estimate.get('options', [])
    )
    documents_done = checks.get('status') == 'checked'
    ready = bool(details_done and selected_done and documents_done)
    done = [details_done, selected_done, documents_done, ready]
    descriptions = [
        '包裹信息与计费重量已核对' if details_done else estimate.get('message') or ('请补充：' + '、'.join(LABELS.get(key, key) for key in missing) if missing else '保存需求并计算参考费用'),
        '已选择 ' + str(selected.get('service')) if selected_done else '比较费用与适用条件，再选定参考服务',
        '基本字段、金额与数量一致性已通过' if documents_done else ('发现 ' + str(len(checks.get('issues', []))) + ' 项需要修正' if checks else '补充收寄件人与货品明细，并检查一致性'),
        '可导出准备清单，继续核对承运条件' if ready else '完成需求、方案选择与单证检查后生成清单',
    ]
    first_pending = next((index for index, complete in enumerate(done) if not complete), None)
    steps = [
        {'id': step_id, 'title': title,
         'status': 'complete' if complete else 'current' if index == first_pending else 'pending',
         'description': descriptions[index]}
        for index, (step_id, title, complete) in enumerate(zip(
            ['details', 'service', 'documents', 'summary'],
            ['补齐需求', '选择方案', '核对单证', '准备清单'], done))
    ]
    next_view = 'rates' if not selected_done else 'documents' if not documents_done else 'summary'
    return {'steps': steps, 'next_view': next_view, 'ready_for_summary': ready,
            'missing_fields': missing, 'document_issue_count': len(checks.get('issues', [])) if checks else None}


def summary_html(task):
    """Original printable preparation checklist, with all user-controlled text escaped."""
    esc = lambda value: html.escape(str(value if value is not None and value != '' else '待填写'))
    fields = task.get('fields') or {}
    progress = task_progress(task)
    estimate = task.get('quote') or {}
    selected = task.get('selected_service') or {}
    checks = task.get('checks') or {}
    selected_valid = progress['steps'][1]['status'] == 'complete'
    route = esc(fields.get('origin_province')) + ' → ' + esc(fields.get('destination_city') or fields.get('destination_country') or 'US')
    facts = [('货品', fields.get('goods')), ('目的地邮编', fields.get('destination_zip')),
             ('实际重量（kg）', fields.get('weight_kg')),
             ('尺寸（cm）', ' × '.join(str(fields.get(key) or '待填写') for key in ['length_cm','width_cm','height_cm'])),
             ('预算（CNY）', fields.get('budget_cny')), ('期望送达日期', fields.get('deadline'))]
    rows = ''.join('<tr><th>' + esc(label) + '</th><td>' + esc(value) + '</td></tr>' for label, value in facts)
    steps = ''.join('<li><strong>' + esc(step['title']) + '</strong>：' + esc(step['description']) + '</li>' for step in progress['steps'])
    if selected_valid:
        cost = '<p><strong>' + esc(selected.get('service')) + ' · ' + esc(selected.get('name')) + '</strong></p><p>已知参考费用小计：<strong>CNY ' + format(selected['known_subtotal'], ',.2f') + '</strong></p>'
        cost += '<p>计费重量：' + esc(estimate.get('billable_kg')) + ' kg；美国分区：' + esc(estimate.get('zone')) + '</p>'
    else: cost = '<p>尚未选定当前有效的参考运输方案。</p>'
    pending = list(estimate.get('pending') or [])
    pending.extend(issue['message'] for issue in checks.get('issues', []))
    pending.extend(checks.get('review_items') or ['进口人、HS 编码、签字及最终申报信息'])
    pending.extend('补充' + LABELS.get(key, key) for key in progress['missing_fields'])
    pending = list(dict.fromkeys(pending))
    outstanding = ''.join('<li>' + esc(item) + '</li>' for item in pending)
    document_status = '基础一致性检查通过' if checks.get('status') == 'checked' else '需修正或尚未检查'
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>寄件准备清单 · Parcel Desk</title><style>
body{font:15px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#17323b;max-width:850px;margin:32px auto;padding:30px}h1{font-size:28px}h2{font-size:20px;margin-top:28px}table{width:100%;border-collapse:collapse}th,td{border:1px solid #dfe5e0;padding:10px;text-align:left}th{width:32%;background:#f4f6f3}li{margin:7px 0}.note{padding:14px;background:#f3f6ef}button{padding:10px 16px}@media print{button{display:none}body{margin:0;padding:15px;max-width:none}}</style>
<button onclick="window.print()">打印 / 另存为 PDF</button><h1>寄件准备清单</h1><p>''' + route + '</p><p>任务：' + esc(task.get('id')) + ' · 更新时间：' + esc(task.get('updated_at')) + '</p><table>' + rows + '</table><h2>任务进度</h2><ol>' + steps + '</ol><h2>已选参考方案</h2>' + cost + '<h2>单证检查</h2><p>' + document_status + '</p><h2>继续核对</h2><ul>' + outstanding + '</ul><p class="note">这是寄件准备资料，尚未订舱、付款或提交海关文件。参考费用不等于当期账户最终报价；承运覆盖、实际附加费和送达日期仍需承运人确认。</p><p>Parcel Desk · Preparation checklist</p></html>'
