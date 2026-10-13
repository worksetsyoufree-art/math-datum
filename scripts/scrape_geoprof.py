import pathlib, re, json, sys, time, requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
base='https://geoprof.nethouse.ru'
r=requests.get(base+'/parametry-mestnyh-sistem-koordinat',timeout=30)
s=BeautifulSoup(r.text,'lxml')
links=[]
for a in s.find_all('a',href=True):
    t=a.get_text(strip=True)
    if t.startswith(('МСК-','МГГТ')):
        h=a['href']
        if not h.startswith('http'): h=base+'/'+h.lstrip('/')
        h=h.replace('http://','https://')
        links.append((t,h))
print(len(links))
def get(x):
    t,h=x
    for _ in range(4):
        try:
            r=requests.get(h,timeout=30)
            if r.status_code==200: return t,h,r.text
        except Exception as e: pass
        time.sleep(2)
    return t,h,None
with ThreadPoolExecutor(6) as ex: res=list(ex.map(get,links))
out=[]
for t,h,html in res:
    if html is None: print('FAIL',t,h); continue
    txt=BeautifulSoup(html,'lxml').get_text('\n')
    lines=[l.strip() for l in txt.split('\n') if l.strip().startswith('"')]
    out.append({'title':t,'url':h,'lines':lines})
json.dump(out,open(pathlib.Path(__file__).resolve().parent.parent/'data/raw/geoprof_raw.json','w'),ensure_ascii=False,indent=1)
print(len(out), sum(len(o['lines']) for o in out), [o['title'] for o in out if not o['lines']])
