"""StockMalin desktop (Tkinter, standard library). All purchasing is manual."""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
import pathlib, json, csv, datetime, urllib.request, urllib.parse, re, os

APPDIR=pathlib.Path(os.environ.get('APPDATA',str(pathlib.Path.home()))) / 'StockMalin'
APPDIR.mkdir(parents=True,exist_ok=True)
STATE=APPDIR/'state.json'
BLUE='#2563eb'; DARK='#15213b'; BG='#f4f7fb'; GREEN='#167d57'
INITIAL={'repo':'','products':[{'id':'fairy-platinum-plus-30min','name':'Fairy Platinum Plus 30 minutes','unit':'capsule','quantity':130,'target_unit_price':0.13,'offers':[]}],'purchases':[{'id':'fairy-platinum-plus-30min','date':'2026-10-06','shop':'Achat de référence','quantity':130,'paid':22.0}],'history':[]}

def load(path,default):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError): return default

def store(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def euro(x,digits=2): return f'{x:.{digits}f}'.replace('.',',')+' €'

def valid_repo(s): return bool(re.fullmatch(r'[\w.-]+/[\w.-]+',s))

class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title('StockMalin • Comparateur et stock'); self.geometry('1130x750'); self.minsize(860,570)
        self.configure(bg=BG)
        self.state_data=load(STATE,INITIAL)
        style=ttk.Style(self); style.theme_use('clam')
        style.configure('TFrame',background=BG); style.configure('TLabel',background=BG,foreground=DARK,font=('Segoe UI',10)); style.configure('TButton',font=('Segoe UI',10),padding=8)
        style.configure('Treeview',font=('Segoe UI',10),rowheight=29); style.configure('Treeview.Heading',font=('Segoe UI',10,'bold'))
        style.configure('TNotebook',background=BG); style.configure('TNotebook.Tab',font=('Segoe UI',10),padding=(20,10))
        ttk.Label(self,text='STOCKMALIN',font=('Segoe UI',23,'bold'),foreground=BLUE).pack(anchor='w',padx=22,pady=(15,0))
        ttk.Label(self,text='Achetez au bon prix. Aucun achat automatique.',foreground='#66758e').pack(anchor='w',padx=24,pady=(0,10))
        self.tabs=ttk.Notebook(self);self.tabs.pack(fill='both',expand=True,padx=18,pady=(0,16))
        self.frames={}
        for key in ('Tableau de bord','Mes produits','Mes achats','Offres et historique','Paramètres'):
            frame=ttk.Frame(self.tabs,padding=14);self.tabs.add(frame,text=key);self.frames[key]=frame
        self.make_dashboard(); self.make_products();self.make_purchases();self.make_history();self.make_settings();self.refresh()
    def save(self): store(STATE,self.state_data)
    def tree(self,parent,cols,widths=None):
        holder=ttk.Frame(parent);holder.pack(fill='both',expand=True,pady=8)
        t=ttk.Treeview(holder,columns=cols,show='headings',selectmode='browse')
        for n,c in enumerate(cols): t.heading(c,text=c);t.column(c,width=(widths or {}).get(c,130),anchor='w')
        sc=ttk.Scrollbar(holder,orient='vertical',command=t.yview);t.configure(yscrollcommand=sc.set);t.pack(side='left',fill='both',expand=True);sc.pack(side='right',fill='y');return t
    def row(self,parent,*items):
        r=ttk.Frame(parent);r.pack(fill='x',pady=5)
        for item in items: item(r)
        return r
    def btn(self,label,cmd): return lambda p: ttk.Button(p,text=label,command=cmd).pack(side='left',padx=(0,8))
    def make_dashboard(self):
        f=self.frames['Tableau de bord'];self.stats=ttk.Label(f,text='',font=('Segoe UI',16,'bold'));self.stats.pack(anchor='w',pady=12)
        ttk.Label(f,text='Sélectionnez un produit pour afficher son historique de prix à l’unité.').pack(anchor='w')
        self.current_product=tk.StringVar();self.selector=ttk.Combobox(f,textvariable=self.current_product,state='readonly',width=52)
        self.selector.pack(anchor='w',pady=10);self.selector.bind('<<ComboboxSelected>>',lambda e:self.draw_chart())
        self.chart=tk.Canvas(f,height=285,bg='white',highlightthickness=1,highlightbackground='#dce4f0');self.chart.pack(fill='x',pady=5)
        self.detail=ttk.Label(f,text='',justify='left',font=('Segoe UI',11));self.detail.pack(anchor='w',pady=10)
        ttk.Label(f,text='Les prix collectés sont indicatifs : vérifier le panier, la livraison et les coupons avant achat.',foreground='#66758e').pack(anchor='w')
        self.chart.bind('<Configure>',lambda e:self.draw_chart())
    def make_products(self):
        f=self.frames['Mes produits'];self.row(f,self.btn('＋ Ajouter un produit',self.add_product),self.btn('✎ Modifier',self.edit_product),self.btn('Supprimer',self.delete_product),self.btn('Exporter products.json',self.export_products),self.btn('Importer products.json',self.import_products))
        self.products_tree=self.tree(f,('Produit','Unité','Format','Seuil / unité','Liens suivis'))
        ttk.Label(f,text='Pour la surveillance distante, exportez products.json puis mettez-le à jour dans le dépôt GitHub.',foreground='#66758e').pack(anchor='w',pady=6)
    def product_form(self,product=None):
        w=tk.Toplevel(self);w.title('Fiche produit');w.transient(self);w.grab_set();w.geometry('690x510')
        fields=[('Nom du produit','name'),('Unité (capsule, rouleau, litre...)','unit'),('Nombre d’unités par paquet','quantity'),('Seuil d’alerte en € par unité','target_unit_price')]
        vars={}
        for label,key in fields:
            row=ttk.Frame(w,padding=(14,7));row.pack(fill='x');ttk.Label(row,text=label,width=34).pack(side='left');v=tk.StringVar(value=str((product or {}).get(key,'')));ttk.Entry(row,textvariable=v,width=35).pack(side='left');vars[key]=v
        ttk.Label(w,text='Liens marchands : un par ligne sous la forme Boutique | URL HTTPS | Quantité | Livraison (€)',wraplength=630).pack(anchor='w',padx=14,pady=8)
        txt=tk.Text(w,height=9,font=('Consolas',10));txt.pack(fill='both',expand=True,padx=14)
        if product:
            txt.insert('1.0','\n'.join(f"{o.get('shop','Boutique')} | {o.get('url','')} | {o.get('quantity',product.get('quantity',1))} | {o.get('shipping',0)}" for o in product.get('offers',[])))
        def submit():
            try:
                name=vars['name'].get().strip();unit=vars['unit'].get().strip() or 'unité';q=int(vars['quantity'].get());target=float(vars['target_unit_price'].get().replace(',','.'))
                if not name or q<=0 or target<=0: raise ValueError('Nom, quantité et seuil doivent être valides')
                offers=[]
                for line in txt.get('1.0','end').splitlines():
                    if not line.strip():continue
                    parts=[x.strip() for x in line.split('|')]
                    if len(parts)!=4 or not parts[1].startswith('https://'):raise ValueError('Format de lien incorrect : Boutique | https://... | quantité | livraison')
                    count=int(parts[2]);shipping=float(parts[3].replace(',','.'))
                    if count<=0 or shipping<0:raise ValueError('Quantité ou frais invalides')
                    offers.append({'shop':parts[0],'url':parts[1],'quantity':count,'shipping':shipping})
                ident=(product or {}).get('id') or re.sub('[^a-z0-9]+','-',name.lower()).strip('-')+'-'+str(len(self.state_data['products'])+1)
                obj={'id':ident,'name':name,'unit':unit,'quantity':q,'target_unit_price':target,'offers':offers}
                if product: self.state_data['products'][self.state_data['products'].index(product)]=obj
                else:self.state_data['products'].append(obj)
                self.save();self.refresh();w.destroy()
            except Exception as e: messagebox.showerror('Fiche produit',str(e),parent=w)
        ttk.Button(w,text='Enregistrer',command=submit).pack(pady=12)
        self.wait_window(w)
    def selected_product(self):
        ids=self.products_tree.selection()
        if not ids:return None
        idx=int(ids[0]);return self.state_data['products'][idx]
    def add_product(self):self.product_form()
    def edit_product(self):
        p=self.selected_product()
        if p:self.product_form(p)
    def delete_product(self):
        p=self.selected_product()
        if p and messagebox.askyesno('Suppression','Supprimer ce produit ? Les achats et prix historiques resteront conservés.'):
            self.state_data['products'].remove(p);self.save();self.refresh()
    def export_products(self):
        path=filedialog.asksaveasfilename(defaultextension='.json',initialfile='products.json',filetypes=[('JSON','*.json')])
        if path:store(pathlib.Path(path),self.state_data['products']);messagebox.showinfo('Export','Fichier exporté. Déposez-le dans votre dépôt GitHub.')
    def import_products(self):
        path=filedialog.askopenfilename(filetypes=[('JSON','*.json')])
        if path:
            items=load(pathlib.Path(path),None)
            if not isinstance(items,list) or not all(isinstance(p,dict) and p.get('id') and p.get('name') for p in items):return messagebox.showerror('Import','Format de fichier invalide')
            self.state_data['products']=items;self.save();self.refresh()
    def make_purchases(self):
        f=self.frames['Mes achats'];self.row(f,self.btn('＋ Ajouter un achat',self.add_purchase),self.btn('Supprimer la ligne',self.delete_purchase),self.btn('Exporter CSV',self.export_csv))
        self.purchase_tree=self.tree(f,('Date','Produit','Boutique','Quantité','Total','Prix / unité'))
    def add_purchase(self):
        products=self.state_data['products']
        if not products:return messagebox.showinfo('Achats','Ajoutez d’abord un produit.')
        win=tk.Toplevel(self);win.title('Ajouter un achat');win.transient(self);win.grab_set();win.geometry('480x340')
        values={};names=[x['name'] for x in products]
        for label,value in [('Produit',names[0]),('Date (AAAA-MM-JJ)',datetime.date.today().isoformat()),('Boutique',''),('Nombre d’unités','130'),('Montant payé (€)','22')]:
            r=ttk.Frame(win,padding=9);r.pack(fill='x');ttk.Label(r,text=label,width=22).pack(side='left');v=tk.StringVar(value=value);values[label]=v
            widget=ttk.Combobox(r,textvariable=v,values=names,state='readonly') if label=='Produit' else ttk.Entry(r,textvariable=v)
            widget.pack(side='left',fill='x',expand=True)
        def submit():
            try:
                date=datetime.date.fromisoformat(values['Date (AAAA-MM-JJ)'].get()).isoformat()
                qty=int(values['Nombre d’unités'].get());paid=float(values['Montant payé (€)'].get().replace(',','.'))
                if qty<=0 or paid<=0:raise ValueError('Quantité et prix doivent être positifs')
                name=values['Produit'].get();p=next(p for p in products if p['name']==name)
                self.state_data['purchases'].append({'id':p['id'],'date':date,'shop':values['Boutique'].get(),'quantity':qty,'paid':paid})
                self.save();self.refresh();win.destroy()
            except Exception as e:messagebox.showerror('Achat',str(e),parent=win)
        ttk.Button(win,text='Enregistrer',command=submit).pack(pady=10);self.wait_window(win)
    def delete_purchase(self):
        sel=self.purchase_tree.selection()
        if sel and messagebox.askyesno('Supprimer','Supprimer cet achat ?'):
            self.state_data['purchases'].pop(int(sel[0]));self.save();self.refresh()
    def export_csv(self):
        filename=filedialog.asksaveasfilename(defaultextension='.csv',initialfile='achats_stockmalin.csv')
        if filename:
            with open(filename,'w',encoding='utf-8-sig',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=['date','id','shop','quantity','paid']);writer.writeheader();writer.writerows(self.state_data['purchases'])
    def make_history(self):
        f=self.frames['Offres et historique'];self.row(f,self.btn('Synchroniser depuis GitHub',self.sync),self.btn('Importer un historique JSON',self.import_history),self.btn('Exporter CSV',self.export_history))
        self.history_tree=self.tree(f,('Date','Produit','Marchand','Quantité','Total','Prix / unité','Écart à mon achat'))
        ttk.Label(f,text='Le scanner enregistre uniquement les prix qu’il réussit à lire : une erreur n’est pas une offre à 0 €.',foreground='#66758e').pack(anchor='w')
    def import_history(self):
        path=filedialog.askopenfilename(filetypes=[('JSON','*.json')])
        if path:
            items=load(pathlib.Path(path),None)
            if not isinstance(items,list):return messagebox.showerror('Import','Historique invalide')
            self.state_data['history']=items;self.save();self.refresh()
    def export_history(self):
        path=filedialog.asksaveasfilename(defaultextension='.csv',initialfile='prix_stockmalin.csv')
        if path:
            cols=['timestamp','id','name','shop','url','quantity','price','shipping','total','unit_price','method']
            with open(path,'w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore');w.writeheader();w.writerows(self.state_data['history'])
    def make_settings(self):
        f=self.frames['Paramètres'];ttk.Label(f,text='Dépôt GitHub PUBLIC contenant le scanner et les historiques',font=('Segoe UI',11,'bold')).pack(anchor='w',pady=9)
        self.repo_var=tk.StringVar(value=self.state_data.get('repo',''));ttk.Entry(f,textvariable=self.repo_var,width=50).pack(anchor='w',pady=5)
        ttk.Label(f,text='Format : utilisateur/nom-du-depot. Ne mettez aucune donnée privée dans le dépôt public.').pack(anchor='w')
        self.row(f,self.btn('Enregistrer',self.save_settings),self.btn('Synchroniser maintenant',self.sync))
        ttk.Label(f,text='Fonctionnement : GitHub surveille les URL configurées. Ce logiciel lit les résultats lorsque vous cliquez sur Synchroniser.',wraplength=760).pack(anchor='w',pady=15)
        ttk.Label(f,text='Vos achats sont uniquement enregistrés sur cet ordinateur dans le dossier AppData/StockMalin.',foreground='#66758e').pack(anchor='w')
        ttk.Label(f,text='Aucun panier, aucune commande, aucun paiement automatique.',foreground=GREEN,font=('Segoe UI',10,'bold')).pack(anchor='w',pady=15)
    def save_settings(self):
        repo=self.repo_var.get().strip()
        if repo and not valid_repo(repo):return messagebox.showerror('Dépôt','Format attendu : utilisateur/depot')
        self.state_data['repo']=repo;self.save();messagebox.showinfo('Enregistré','Configuration enregistrée.')
    def sync(self):
        repo=self.repo_var.get().strip()
        if not valid_repo(repo):return messagebox.showwarning('Synchronisation','Configurez utilisateur/depot dans Paramètres.')
        url='https://raw.githubusercontent.com/'+repo+'/main/data/history.json'
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'StockMalin/1.0'})
            with urllib.request.urlopen(req,timeout=15) as f: items=json.load(f)
            if not isinstance(items,list):raise ValueError('Historique distant non valide')
            # Avoid importing datasets larger than reasonable for a desktop MVP.
            if len(items)>50000:raise ValueError('Historique trop volumineux')
            self.state_data['history']=items;self.state_data['repo']=repo;self.save();self.refresh()
            messagebox.showinfo('Synchronisation',f'{len(items)} relevés chargés.')
        except Exception as exc: messagebox.showerror('Synchronisation',f'Impossible de lire {url}\n\n{exc}\n\nVérifiez que le dépôt est public et utilise la branche main.')
    def refresh(self):
        products=self.state_data['products']; purchases=self.state_data['purchases'];history=self.state_data['history'];mapping={p['id']:p for p in products}
        self.stats.config(text=f'{len(products)} produits suivis     •     {len(history)} relevés de prix     •     {len(purchases)} achats enregistrés')
        self.selector['values']=[p['name'] for p in products]
        if products and self.current_product.get() not in [p['name'] for p in products]:self.current_product.set(products[0]['name'])
        for t in (self.products_tree,self.purchase_tree,self.history_tree):
            for item in t.get_children():t.delete(item)
        for i,p in enumerate(products):self.products_tree.insert('', 'end',iid=str(i),values=(p['name'],p.get('unit','unité'),p.get('quantity',1),euro(float(p.get('target_unit_price',0)),3),len(p.get('offers',[]))))
        for i,p in enumerate(purchases):
            q=p.get('quantity',1);self.purchase_tree.insert('','end',iid=str(i),values=(p.get('date'),mapping.get(p.get('id'),{}).get('name',p.get('id')),p.get('shop'),q,euro(float(p['paid'])),euro(float(p['paid'])/q,3)))
        baselines={}
        for p in purchases:
            if p.get('quantity',0)>0:baselines.setdefault(p['id'],[]).append(float(p['paid'])/p['quantity'])
        for i,p in enumerate(sorted(history,key=lambda x:x.get('timestamp',''),reverse=True)):
            try:
                unit=float(p['unit_price']);base=min(baselines.get(p.get('id'),[]) or [unit]);delta=(unit/base-1)*100
                self.history_tree.insert('','end',iid=str(i),values=(p.get('timestamp','')[:16].replace('T',' '),p.get('name'),p.get('shop'),p.get('quantity'),euro(float(p.get('total',0))),euro(unit,3),f'{delta:+.1f} %'))
            except (ValueError,TypeError,ZeroDivisionError,KeyError):pass
        self.draw_chart()
    def draw_chart(self):
        if not hasattr(self,'chart'):return
        c=self.chart;c.delete('all');w=max(c.winfo_width(),300);h=max(c.winfo_height(),220)
        p=next((x for x in self.state_data['products'] if x['name']==self.current_product.get()),None)
        if not p:return
        rows=[r for r in self.state_data['history'] if r.get('id')==p['id'] and isinstance(r.get('unit_price'),(int,float))]
        purchases=[r for r in self.state_data['purchases'] if r.get('id')==p['id'] and r.get('quantity',0)>0]
        points=sorted([(str(r['timestamp'])[:10],float(r['unit_price']),'Relevé') for r in rows]+[(str(r['date']),float(r['paid'])/float(r['quantity']),'Achat') for r in purchases],key=lambda r:r[0])
        if not points:
            c.create_text(w/2,h/2,text='Aucune donnée de prix. Ajoutez un achat ou synchronisez les relevés.',fill='#66758e',font=('Segoe UI',12));self.detail.config(text='');return
        vals=[v for _,v,_ in points];minimum=max(0,min(vals)*0.85);maximum=max(vals)*1.12
        if maximum==minimum:maximum=minimum+0.1
        l,r,t,b=70,w-26,23,h-55
        for i in range(5):
            val=minimum+(maximum-minimum)*i/4;y=b-(b-t)*i/4
            c.create_line(l,y,r,y,fill='#e5eaf2');c.create_text(l-8,y,text=f'{val:.3f} €',anchor='e',fill='#66758e',font=('Segoe UI',9))
        xy=[]
        for i,(_,val,kind) in enumerate(points):
            x=l+(r-l)*(i/(len(points)-1) if len(points)>1 else 0.5);y=b-(val-minimum)/(maximum-minimum)*(b-t);xy.append((x,y))
        if len(xy)>1:c.create_line(*[i for pair in xy for i in pair],fill=BLUE,width=2,smooth=False)
        for (x,y),(_,val,kind) in zip(xy,points):c.create_oval(x-4,y-4,x+4,y+4,fill=GREEN if kind=='Achat' else BLUE,outline='white')
        for idx in sorted({0,len(points)//2,len(points)-1}):
            x=xy[idx][0];c.create_text(x,b+20,text=points[idx][0],fill='#66758e',font=('Segoe UI',9))
        baseline=min((float(x['paid'])/x['quantity'] for x in purchases),default=None)
        latest=min((float(x['unit_price']) for x in rows if x.get('timestamp','')[:10]==max(str(q.get('timestamp',''))[:10] for q in rows)),default=None) if rows else None
        target=float(p.get('target_unit_price',0))
        detail=f'Seuil d’alerte : {euro(target,3)}/{p.get("unit","unité")}   |   Meilleur achat enregistré : {euro(baseline,3) if baseline else "—"}'
        if latest is not None:detail+=f'   |   Meilleure offre du dernier jour relevé : {euro(latest,3)}'
        self.detail.config(text=detail)

if __name__=='__main__':App().mainloop()
