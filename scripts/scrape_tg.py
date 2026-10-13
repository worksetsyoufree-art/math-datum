import pathlib, re, json, time, requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
S=requests.Session()
def get(u):
    for _ in range(4):
        try:
            r=S.get(u,timeout=30)
            if r.status_code==200: return r.text
            if r.status_code==404: return None
        except Exception: pass
        time.sleep(2)
pages={}
links={}
u='https://terraingis.ru/category/dannye-dlya-gis/msk'
for p in range(1,10):
    html=get(u if p==1 else f'{u}/page/{p}')
    if not html: break
    s=BeautifulSoup(html,'lxml')
    n=0
    for a in s.find_all('a',href=True):
        h=a['href']; t=a.get_text(strip=True)
        if re.search(r'terraingis\.ru/[^/]*(msk|mggt|sk-)[^/]*\.html$',h,re.I) and h not in links:
            links[h]=t; n+=1
    print('page',p,n)
    if n==0: break
print(len(links))
def fetch(h): return h,get(h)
with ThreadPoolExecutor(6) as ex: res=list(ex.map(fetch,links))
out=[]
for h,html in res:
    if not html: print('FAIL',h); continue
    s=BeautifulSoup(html,'lxml')
    title=s.find('h1').get_text(strip=True) if s.find('h1') else links[h]
    txt=s.get_text('\n')
    lines=[l.strip() for l in txt.split('\n') if re.match(r'^\s*[«"“].+[»"”]\s*,\s*8\s*,',l)]
    out.append({'title':title,'url':h,'lines':lines})
json.dump(out,open(pathlib.Path(__file__).resolve().parent.parent/'data/raw/tg_raw.json','w'),ensure_ascii=False,indent=1)
print(len(out),sum(len(o['lines']) for o in out),[o['title'] for o in out if not o['lines']])
