"""Deterministic parcel estimates and document consistency checks."""
from collections import Counter
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
LABELS = {"weight_kg":"实际重量","length_cm":"长度","width_cm":"宽度","height_cm":"高度","destination_zip":"美国邮编","origin_province":"起运省市"}


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
            result[key] = value
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
    missing = [k for k in ["origin_province","destination_zip","goods","weight_kg","length_cm","width_cm","height_cm"] if not f.get(k)]
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
    def issue(code,message): issues.append({"code":code,"message":message})
    for key,label in [("sender_name","寄件人姓名"),("sender_address","寄件人地址"),("sender_phone","寄件人电话"),
                      ("recipient_name","收件人姓名"),("recipient_address","收件人地址"),("recipient_phone","收件人电话"),("currency","申报币种"),("country_of_origin","货品原产地")]:
        if not f.get(key): issue("missing_"+key,"缺少"+label)
    items=f.get("items") or []
    if not items: issue("missing_items","请添加货品明细。")
    total=Decimal(0); invoice_qty=Counter(); packing_qty=Counter(); lines=[]
    for index,item in enumerate(items,1):
        if not isinstance(item,dict): issue("invalid_item",f"第 {index} 行格式错误。"); continue
        name=str(item.get("description") or "").strip()
        if not name: issue("missing_description",f"第 {index} 行缺少货品描述。")
        elif name.lower() in {"gift","gifts","parts","礼物","配件"}: issue("vague_description",f"第 {index} 行描述过于笼统，请补充材质与用途。")
        try:
            qty=number(item.get("quantity"),f"第 {index} 行发票数量"); pack=number(item.get("packing_quantity"),f"第 {index} 行装箱数量")
            price=number(item.get("unit_price"),f"第 {index} 行单价",positive=False)
            if qty!=qty.to_integral_value() or pack!=pack.to_integral_value(): raise ValidationError("件数需要是整数。")
            line=Decimal(str(money(qty*price))); total+=line
            invoice_qty[name.casefold()]+=qty; packing_qty[name.casefold()]+=pack
            lines.append({"description":name,"quantity":int(qty),"packing_quantity":int(pack),"unit_price":money(price),"line_total":money(line),"hs_code":str(item.get("hs_code") or "")})
        except ValidationError as error: issue("invalid_item",str(error))
    for name in sorted(invoice_qty.keys()|packing_qty.keys()):
        if invoice_qty[name]!=packing_qty[name]: issue("quantity_mismatch",f"{name}：发票 {invoice_qty[name]} 件，装箱单 {packing_qty[name]} 件。")
    if f.get("invoice_total") is not None and Decimal(str(f["invoice_total"])).quantize(Decimal(".01"))!=total:
        issue("total_mismatch",f"填写合计与逐行计算结果 {money(total):.2f} 不一致。")
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
