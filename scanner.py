"""StockMalin: scheduled price capture from explicitly supplied product URLs.
No checkout or purchasing capabilities. Standard-library only.
"""
import json, re, html, urllib.request, urllib.parse, datetime, pathlib, time, sys
from html.parser import HTMLParser

ROOT=pathlib.Path(__file__).resolve().parent
DATA=ROOT/'data'

def load(p, fallback):
    try: return json.loads(p.read_text(encoding='utf-8'))
    except (OSError, ValueError): return fallback

def save(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def as_price(value):
    if isinstance(value, (int,float)): return float(value) if 0 < float(value) < 100000 else None
    if not isinstance(value,str): return None
    v=value.strip().replace('\u202f','').replace('\xa0','').replace(' ','').replace('€','')
    if ',' in v and '.' in v: v=v.replace('.','').replace(',','.') if v.rfind(',')>v.rfind('.') else v.replace(',','')
    elif ',' in v: v=v.replace(',','.')
    try:
        v=float(re.search(r'\d+(?:\.\d+)?',v).group())
        return v if 0<v<100000 else None
    except (AttributeError,ValueError): return None

class MetaPriceParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.meta=[]; self.scripts=[]; self._script=False; self._buf=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='meta': self.meta.append(a)
        if tag=='script' and a.get('type','').lower()=='application/ld+json': self._script=True; self._buf=[]
    def handle_data(self,data):
        if self._script: self._buf.append(data)
    def handle_endtag(self,tag):
        if tag=='script' and self._script: self.scripts.append(''.join(self._buf)); self._script=False

def json_prices(obj):
    if isinstance(obj,list):
        for item in obj: yield from json_prices(item)
    elif isinstance(obj,dict):
        typ=obj.get('@type',[])
        typ=[typ] if isinstance(typ,str) else typ
        if 'Offer' in typ or 'AggregateOffer' in typ:
            p=as_price(obj.get('price') or obj.get('lowPrice'))
            if p: yield p
        for k,v in obj.items():
            if isinstance(v,(dict,list)): yield from json_prices(v)

def fetch_price(url):
    parts=urllib.parse.urlparse(url)
    if parts.scheme!='https' or not parts.hostname: raise ValueError('URL HTTPS obligatoire')
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; StockMalin/1.0; price monitor)','Accept-Language':'fr-FR,fr;q=0.9'})
    with urllib.request.urlopen(req,timeout=18) as response:
        if response.status!=200: raise ValueError('HTTP '+str(response.status))
        content=response.read(2_500_000).decode('utf-8',errors='replace')
    p=MetaPriceParser(); p.feed(content)
    for raw in p.scripts:
        try:
            prices=list(json_prices(json.loads(raw)))
            if prices: return min(prices),'JSON-LD'
        except (ValueError,TypeError): pass
    for item in p.meta:
        key=(item.get('property') or item.get('name') or item.get('itemprop') or '').lower()
        if key in ('product:price:amount','og:price:amount','price','twitter:data1'):
            val=as_price(html.unescape(item.get('content','')))
            if val: return val,'METADATA'
    raise ValueError('Prix structuré introuvable : saisie manuelle ou autre source nécessaire')

def scan():
    products=load(ROOT/'products.json',[])
    history=load(DATA/'history.json',[])
    stamp=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    results=[]; seen={(r.get('id'),r.get('url'),r.get('timestamp')) for r in history}
    for product in products:
        for offer in product.get('offers',[]):
            url=offer.get('url','').strip()
            if not url: continue
            label=offer.get('shop','Marchand')
            try:
                price,method=fetch_price(url)
                qty=int(offer.get('quantity') or product.get('quantity') or 1)
                if qty<=0: raise ValueError('quantité invalide')
                shipping=float(offer.get('shipping',0) or 0)
                total=round(price+shipping,2)
                record={'timestamp':stamp,'id':product['id'],'name':product['name'],'shop':label,'url':url,'quantity':qty,'price':round(price,2),'shipping':shipping,'total':total,'unit_price':round(total/qty,5),'method':method}
                if (record['id'],url,stamp) not in seen: history.append(record)
                results.append({'product':product['name'],'shop':label,'status':'OK','unit_price':record['unit_price']})
            except Exception as exc:
                results.append({'product':product.get('name','?'),'shop':label,'status':'ERREUR','detail':str(exc)[:180]})
            time.sleep(1)
    save(DATA/'history.json',history[-50000:])
    save(DATA/'last_scan.json',{'timestamp':stamp,'results':results})
    for result in results: print(result)
    print(f'{len(results)} offres analysées; {sum(x["status"]=="OK" for x in results)} prix obtenus')

if __name__=='__main__': scan()
