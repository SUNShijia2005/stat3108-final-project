"""Inspectable local retrieval: BM25 plus character/word TF-IDF, fused by rank."""
from collections import Counter
import json
import math
from pathlib import Path
import re

DOCS=json.loads((Path(__file__).resolve().parents[1]/"data/parcel/knowledge.json").read_text())
for doc in DOCS:
    doc["source_url"]=doc["url"]
    doc["source_date"]=doc["date"]


def tokens(text):
    text=text.lower(); words=re.findall(r"[a-z0-9]+",text)
    for run in re.findall(r"[\u4e00-\u9fff]+",text):
        words.extend(run[i:i+2] for i in range(len(run)-1))
    return words


COUNTS=[Counter(tokens(d["title"]+" "+d["keywords"]+" "+d["text"]+" "+d.get("text_en",""))) for d in DOCS]
DF=Counter(t for c in COUNTS for t in c)
AVG=sum(sum(c.values()) for c in COUNTS)/len(COUNTS)


def retrieve(query,method="hybrid",limit=3):
    if not isinstance(query,str) or not query.strip(): return []
    if method not in {"keyword","bm25","hybrid"}: raise ValueError("Unknown retrieval method")
    q=Counter(tokens(query)); bm=[]; tf=[]; kw=[]; n=len(DOCS)
    idf=lambda t:math.log(1+(n-DF[t]+.5)/(DF[t]+.5))
    for i,c in enumerate(COUNTS):
        overlap=q.keys()&c.keys()
        if not overlap: continue
        score=sum(idf(t)*c[t]*2.2/(c[t]+1.2*(.25+.75*sum(c.values())/AVG)) for t in overlap)
        dot=sum(q[t]*c[t]*idf(t)**2 for t in overlap)
        norm=math.sqrt(sum((v*idf(t))**2 for t,v in q.items())*sum((v*idf(t))**2 for t,v in c.items()))
        bm.append((i,score)); tf.append((i,dot/norm if norm else 0)); kw.append((i,len(overlap)))
    bm.sort(key=lambda x:(-x[1],x[0])); tf.sort(key=lambda x:(-x[1],x[0])); kw.sort(key=lambda x:(-x[1],x[0]))
    if method=="hybrid":
        fused=Counter()
        for ranking in [bm,tf]:
            for rank,(i,s) in enumerate(ranking,1): fused[i]+=1/(60+rank)
        ranking=sorted(fused.items(),key=lambda x:(-x[1],x[0]))
    else: ranking=kw if method=="keyword" else bm
    return [dict(DOCS[i],score=round(score,5),retrieval_method=method) for i,score in ranking[:max(1,min(limit,8))]]


def references(ids):
    return [d for d in DOCS if d["id"] in ids]
