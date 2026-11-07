# AI Customer Service Agent for Cross-Border Parcel Shipping

Project idea for **STAT3108 Applied Deep Learning and AI**.
**Status:** Proposal stage. The system and evaluation described below are planned work.

## 1. Background

Before sending goods overseas, individual customers and small online sellers need to know what they can send, how much it costs, and how long it takes. After shipping, they may need to check the progress or deal with delays and missing information. Finding these answers often means checking different websites or asking customer service several times.

This project will simulate a small logistics company and build an AI customer service agent. Customers could ask questions in Chinese or English. The agent would ask for missing details, calculate shipping costs, check test shipments, and help fill in shipping documents. The first version would focus on a few product types and selected small-shipment services from China to the US, Japan, and Australia.

## 2. Questions

1. Can the agent ask useful follow-up questions when customers provide incomplete information?
2. Can it calculate shipping costs correctly and recommend options that fit the customer's budget and deadline?
3. Can it identify shipment delays or other problems and suggest what to do next?
4. Can it help fill in commercial invoices and packing lists, and find missing or inconsistent information?
5. Can it recognize when a question needs help from a staff member?

## 3. Data Sources

The project will use three types of data: public information, simulated company data, and test cases.

For public information, some FedEx rates and charging rules, sea shipping fees, and service notices have already been collected. Commercial invoice templates, examples, and packing list templates have also been found. Product restrictions can be checked on official websites, but the rules for the products included in the project still need to be organized and checked. Ship and flight schedules may be useful for reference, but they do not give complete small-parcel prices.

For company data, the project will use a simulated logistics company with several shipping options. Each option would have its own price rules, estimated delivery time, and rules about accepted goods. About 20 test shipments would be prepared with tracking histories and planned events. **All demo quotes, simulated company rules, and tracking records will be clearly marked as simulated.** Company acceptance rules and official import requirements will be kept separate.

For testing, the project will use fictional customers and goods. Some cases would have missing dimensions, wrong totals, or different quantities on the invoice and packing list. Others would include delays or requests for more information. Expected answers would be prepared to check the agent's results.

## 4. Methods

The system will use an existing language model together with several tools. The model would understand customer questions, ask follow-up questions, choose tools, and explain results. The tools would do the calculations, look up shipments, fill in documents, and check information.

For a shipping request, the agent would collect the origin, destination, goods, weight, dimensions, budget, and deadline. Once it has enough information, a calculation tool would work out the costs using the simulated rate table. The agent would compare suitable sea, air, or express options and explain its recommendation. Comparisons would use the same goods and service scope. If no option fits, it would explain why.

For tracking questions, the agent would read the matching test shipment. A simulated delay or request for documents would trigger an alert. The agent would explain what happened and suggest the next step. If staff help is needed, it would prepare a short summary of the customer's request and the remaining problem. Human handoff would initially be represented by a saved record for staff review.

For documents, the system would fill in a commercial invoice and packing list using the customer's information. It would check totals, quantities, and missing details, then ask the customer to confirm the result. Missing values would be requested rather than invented. The first version would support basic document preparation and checking, rather than formal customs filing.

The webpage is planned in Python, with SQLite used to save tasks, rates, and shipment records. It would include customer chat, shipping comparisons, tracking information, and document previews.

## 5. Evaluation

The agent would be tested with a small set of customer questions and compared with a chatbot using the same model, reference material, and business information. The chatbot would answer directly, while the agent could use the calculation, search, checking, and task-record tools.

The tests would check whether the system calculates prices correctly, recommends suitable options, notices missing information or shipment problems, and asks for staff help when needed. Expected answers would be fixed before evaluation, and final test cases would be separate from development examples. The results would include errors and examples of tasks the system could not complete. Simulated test results would not be presented as real shipping savings or customs clearance success rates.

## 6. Planned Demo

The demo would show one customer sending a small package from China to the US.

The agent would ask for missing details, compare simulated shipping options, and help fill in a commercial invoice and packing list. After the customer chooses an option, the system would save the task and show its test tracking record.

A simulated delay or request for more information would then be triggered. The webpage would show an alert, and the agent would explain the next step. If it cannot handle the problem, it would prepare a summary for a staff member.

All prices and shipment records in the demo would be clearly marked as simulated.

## 7. Expected Results and Value

The planned results include a working webpage, reference materials with sources, simulated company data, shipping document templates, test cases, comparison results, a course report, and a code repository showing the development process.

The project would explore whether an AI can use conversation and tools to help with several connected logistics tasks. It could help customers spend less time searching and filling in forms, and help logistics companies handle repeated questions and basic checks.

Real prices, live tracking, and booking services could be added later if access to a logistics company's system becomes available.

## References

1. [FedEx: China Shipping Rates and Charging Information](https://www.fedex.com/en-cn/shipping/rates.html)
2. [FedEx: Commercial Invoice Templates, Examples, and Shipping Documents](https://www.fedex.com/en-us/shipping/international/create-documents.html)
3. [Flexport: Packing List Template](https://www.flexport.com/help/packing-list-template-blank/)
4. [Japan Customs: Prohibited and Restricted Goods](https://www.customs.go.jp/english/summary/prohibit.htm)
5. [Australian Border Force: Categories of Prohibited Goods](https://www.abf.gov.au/importing-exporting-and-manufacturing/prohibited-goods/categories)
6. [Maersk: Service Advisories](https://www.maersk.com.cn/news/category/advisories)

US rules and requirements for specific products still need to be collected and checked during development.
