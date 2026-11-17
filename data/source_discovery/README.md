# 国际海运 Agent：数据可行性核查

核查日期：2026-11-05（美国东部时间）。这是第一批来源与少量人工核对样本，不是完整报价数据库。

## 已取得的原始文件

- `raw/hl_china_local_charges_oct2026.pdf`：Hapag-Lloyd 中国当地收费，4 页，下载成功。
- `raw/hl_usa_local_charges_oct2026.pdf`：Hapag-Lloyd 美国当地收费，8 页，2026-10-01 版，下载成功；尚未逐条结构化核对。
- `download_manifest.json`：原始 URL、下载状态、文件校验值。

官方下载目录：
https://www.hapag-lloyd.com/en/online-business/quotation/tariffs/local-charges-service-fees.html

这些是特定船公司的公开费用表，不能跨船公司套用，也不等于完整海运基础运费或门到门总价。是否适用必须检查方向、地点、计费单位、有效日期与备注。公开可读不表示具有开放再分发许可；提交公开仓库前核实文件使用条款，必要时仅保存来源和获取说明。

## 已核实的其他来源

### 官方标准航线与运输时间

Hapag-Lloyd WC2 Eastbound：
https://www.hapag-lloyd.com/en/services-information/routes-trades/gemini-cogh/route-finder.html/asia/north_america_west/WC2.html

页面标注最后更新 2026-05-11、weekly；列出 Yangshan（上海洋山）至 Los Angeles 16 天、至 Oakland 24 天。这是标准服务运输时间，不是指定船次的 ETD/ETA、实时舱位或保证到货日期。表格本次通过该官方页面的搜索索引读到；直接打开页面只返回动态应用外壳。本地仅保存少量人工核对的索引快照数值，后续接入时需再次核对。

OOCL PCC1 历史船期：
https://www.oocl.com/SiteCollectionDocuments/OOCL/eServices/Sailing%20Schedule%20by%20Service/PCC1_LT.pdf

搜索结果可读到船名、航次、港口与到离港日期，版本日期为 2026-05-19。只作为历史来源候选，尚未本地下载或逐表核对。Long Beach 与 Los Angeles 必须保留为不同港口。

### 市场运价基准（不能当作可成交报价）

Freightos Baltic Index (FBX)：
https://www.freightos.com/enterprise/terminal/freightos-baltic-index-global-container-pricing-index/

FBX01 覆盖中国/东亚至北美西海岸，按 40 英尺箱统计。官方说明部分指标可免费查看；导出和更细数据需要付费账户。本轮未取得该航线可直接使用的免费历史数据文件。

Shanghai Shipping Exchange / SCFI：
https://en.sse.net.cn/indices/scfinew.jsp
https://en.sse.net.cn/eninfo/marketreport/index.shtml

本轮指数表没有读到数值；点击 2026-10-17 至 10-23 周报后返回 Please Login。因此目前不是已经获取的数据。

### 未来可尝试的船期 API

Maersk Developer Portal：
https://developer.maersk.com/support/faqs

官方说明需要注册开发者账户、创建集成并获取 Consumer Key；Customer APIs 另有客户代码等要求，产品权限和收费需逐项核实。本轮未注册、申请权限或成功调用 API。

## 核对样本

`verified_samples.json` 保存 8 条 WC2 标准运输时间和 3 条中国当地收费样本，均附来源与适用条件。样本没有基础海运费，没有模拟报价。

费用核查示例：对满足该船公司适用条件的一份出口单证、两个 40 英尺上海箱，仅样本中的 Export Service Fee 与 Document Charge 小计为 2 × 305 + 400 = 1010 CNY。这个小计不包含基础海运费、其他附加费、目的港费用、清关、税费和内陆运输，不能显示为总价。

## 对项目范围的建议

第一版定位为“读取用户上传的报价表，结合公开航线与费用规则完成核算、检查和比较”。

- 已有真实资料可支撑检索、按来源回答、单位计算与日期有效性检查。
- 基础海运费来自用户上传的真实报价，必须记录船公司、航线、箱型、币种、包含项、排除项、有效期与舱位条件。
- 无报价时仅给出资料中有依据的费用项目与待补字段；不能生成声称可成交的价格。
- 市场指数独立作为参考信息，不能用它为不同船公司编造独立报价，或重复加上指数已经包含的费用。
- 测试情景可以人工编写，需与真实原始资料区分，并人工核对参考答案。
