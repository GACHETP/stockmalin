"""StockMalin: scheduled price capture from explicitly supplied product URLs.
No checkout or purchasing capabilities. Standard-library only.
"""
import json, re, html, unicodedata, urllib.request, urllib.parse, datetime, pathlib, time, sys, xml.etree.ElementTree as ET
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


# Experimental discovery from indexed web results. Search engines and merchants may
# throttle requests; candidates without verifiable structured prices are discarded.
ALLOWED_SHOPS = {'amazon.fr':'Amazon','carrefour.fr':'Carrefour','auchan.fr':'Auchan',
                 'cdiscount.com':'Cdiscount','coursesu.com':'Courses U',
                 'monoprix.fr':'Monoprix','intermarche.com':'Intermarché',
                 'leclercdrive.fr':'Leclerc Drive','e.leclerc':'E.Leclerc'}

def shop_name(url):
    host=(urllib.parse.urlparse(url).hostname or '').lower()
    for domain,label in ALLOWED_SHOPS.items():
        if host==domain or host.endswith('.'+domain): return label
    return None

def discover_candidates(name, max_results=18):
    """Discover candidate product pages via public indexed RSS, not a price API.
    Return both URL and search-engine title to diagnose inaccessible merchants.
    """
    queries=[f'"{name}" acheter prix', f'{name} lessive capsules promotion site:carrefour.fr OR site:auchan.fr',
             f'{name} site:amazon.fr OR site:cdiscount.com']
    candidates=[]; seen=set()
    for query in queries:
        try:
            endpoint='https://www.bing.com/search?'+urllib.parse.urlencode({'q':query,'format':'rss'})
            request=urllib.request.Request(endpoint,headers={'User-Agent':'Mozilla/5.0','Accept-Language':'fr-FR,fr;q=0.9'})
            with urllib.request.urlopen(request,timeout=12) as response: payload=response.read(500000)
            root=ET.fromstring(payload)
            for item in root.findall('.//item'):
                link=(item.findtext('link') or '').strip()
                title=(item.findtext('title') or '').strip()
                if not link.startswith('https://') or not shop_name(link) or link in seen: continue
                if not product_match(name,title):continue
                seen.add(link);candidates.append({'url':link,'title':title,'shop':shop_name(link)})
                if len(candidates)>=max_results:return candidates
        except (ValueError,ET.ParseError,OSError):continue
    return candidates

def discover_urls(name,max_results=12):
    return [x['url'] for x in discover_candidates(name,max_results)]

def normalized(value):
    value=unicodedata.normalize('NFKD',value.casefold())
    return ''.join(ch for ch in value if not unicodedata.combining(ch))

def product_match(search, title):
    skip={'lessive','capsules','capsule','lavage','lave','vaisselle','liquide','pour','avec','lot','pack','de','des','le','la','les','x','en','0','prix','promotion'}
    def tokens(v):return [x for x in re.findall(r'[a-z0-9]+',normalized(v)) if x not in skip and len(x)>2]
    wanted=tokens(search); found=tokens(title)
    if not wanted:return False
    # Name variants can have minor plural/suffix differences; require all identifying terms.
    return all(any(a==b or (len(a)>=5 and len(b)>=5 and a[:5]==b[:5]) for b in found) for a in wanted)

def infer_pack(title, name):
    text=normalized(title+' '+name)
    # Do not treat bottle volume in ml as number of washes.
    multi=re.search(r'\b(\d{1,2})\s*[x×]\s*(\d{1,3})\s*(lavages?|capsules?)\b',text)
    if multi:return int(multi.group(1))*int(multi.group(2)), 'lavage' if 'lavage' in multi.group(3) else 'capsule'
    patterns=[(r'(?:\b(?:lot|pack)\s+de\s+)?(\d{1,3})\s*(?:lavages?|doses?)\b','lavage'),
              (r'(?:\b(?:lot|pack)\s+de\s+)?(\d{1,4})\s*(?:capsules?|tablettes?|pods?)\b','capsule'),
              (r'\b(?:x|lot de|pack de)\s*(\d{1,3})\s*(?:rouleaux?)\b','rouleau')]
    for pattern,unit in patterns:
        hits=re.findall(pattern,text)
        if hits:
            qty=int(hits[0]);return (qty,unit) if 1<=qty<=1000 else (None,None)
    # For explicitly stated multi-packs (e.g. 2 x 42 lavages).
    m=re.search(r'\b(\d{1,2})\s*[x×]\s*(\d{1,3})\s*(lavages?|capsules?)\b',text)
    if m:return int(m.group(1))*int(m.group(2)), 'lavage' if 'lavage' in m.group(3) else 'capsule'
    return None,None

def fetch_offer(url):
    parts=urllib.parse.urlparse(url)
    if parts.scheme!='https' or not shop_name(url):raise ValueError('Marchand non pris en charge')
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (compatible; StockMalin/1.0)','Accept-Language':'fr-FR,fr;q=0.9'})
    with urllib.request.urlopen(req,timeout=18) as response:
        if response.status!=200:raise ValueError('HTTP '+str(response.status))
        content=response.read(2500000).decode('utf-8',errors='replace')
    parser=MetaPriceParser();parser.feed(content)
    page_title=None
    for item in parser.meta:
        if (item.get('property') or item.get('name') or '').lower() in ('og:title','twitter:title'):
            page_title=html.unescape(item.get('content',''));break
    if not page_title:
        m=re.search(r'<title[^>]*>(.*?)</title>',content,re.I|re.S)
        if m:page_title=html.unescape(re.sub('<[^>]*>','',m.group(1)))
    price,method=fetch_price(url)
    return price,method,page_title or ''

def discover_prices(product):
    """Return checked prices AND visibly flagged candidate pages.
    An inaccessible page or unverifiable price is never treated as a deal.
    """
    candidates=discover_candidates(product['name'])
    known={o.get('url'):o for o in product.get('offers',[]) if o.get('url')}
    for url in known:
        if url not in {x['url'] for x in candidates}:
            candidates.append({'url':url,'title':product['name'],'shop':shop_name(url) or known[url].get('shop','Marchand')})
    results=[]
    for item in candidates:
        url=item['url']; title=item['title']; shop=item['shop']
        base={'url':url,'shop':shop,'title':title,'price':None,'quantity':None,'unit':None,'unit_price':None,'shipping':None,'method':None,'status':'À vérifier','detail':''}
        try:
            price,method,page_title=fetch_offer(url)
            if page_title and not product_match(product['name'],page_title):
                base['detail']='Référence potentiellement différente';results.append(base);continue
            title=page_title or title
            qty,unit=infer_pack(title,'')
            if not qty and url in known:
                qty=int(known[url].get('quantity') or 0) or None
                unit=product.get('unit') if qty else None
            shipping=known[url].get('shipping') if url in known else None
            base.update({'title':title,'price':round(price,2),'quantity':qty,'unit':unit,'shipping':shipping,'method':method})
            if not qty:
                base['detail']='Prix détecté, mais quantité non identifiée'
            elif shipping is None:
                base['detail']='Prix hors livraison; promotions à vérifier'
                base['unit_price']=round(price/qty,5)
                base['status']='Prix hors livraison'
            else:
                base['unit_price']=round((price+float(shipping))/qty,5)
                base['status']='Prix vérifié (livraison déclarée)'
        except Exception as exc:
            base['detail']=str(exc)[:150]
        results.append(base)
        time.sleep(0.25)
    return sorted(results,key=lambda x:(x['unit_price'] is None,x['unit_price'] if x['unit_price'] is not None else float('inf')))

def scan():
    products=load(ROOT/'products.json',[])
    history=load(DATA/'history.json',[])
    stamp=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    results=[]; seen={(r.get('id'),r.get('url'),r.get('timestamp')) for r in history}
    for product in products:
        found=discover_prices(product) if product.get('auto_search',True) else []
        for offer in found:
            if offer['unit_price'] is None or offer['shipping'] is None:
                results.append({'product':product['name'],'shop':offer['shop'],'status':'A_VERIFIER','url':offer['url'],'price':offer['price'],'detail':offer['detail']})
                continue
            record={'timestamp':stamp,'id':product['id'],'name':product['name'],'shop':offer['shop'],'url':offer['url'],'title':offer['title'],'quantity':offer['quantity'],'unit':offer['unit'],'price':offer['price'],'shipping':offer['shipping'],'total':round(offer['price']+offer['shipping'],2),'unit_price':offer['unit_price'],'method':offer['method']}
            if (record['id'],record['url'],stamp) not in seen:history.append(record)
            results.append({'product':product['name'],'shop':offer['shop'],'status':'OK','unit_price':record['unit_price'],'url':offer['url']})
    save(DATA/'history.json',history[-50000:])
    save(DATA/'last_scan.json',{'timestamp':stamp,'results':results})
    for result in results: print(result)
    print(f'{len(results)} offres analysées; {sum(x["status"]=="OK" for x in results)} prix obtenus')

if __name__=='__main__': scan()
