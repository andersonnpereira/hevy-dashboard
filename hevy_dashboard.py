import os, json, re, hashlib
from datetime import date, datetime, timedelta, timezone
import requests, pandas as pd, streamlit as st, plotly.express as px

HEVY_BASE='https://api.hevyapp.com/v1'; GROQ_URL='https://api.groq.com/openai/v1/chat/completions'; GROQ_MODEL='llama-3.3-70b-versatile'
st.set_page_config(page_title='Minha Evolução',page_icon='⚡',layout='wide',initial_sidebar_state='collapsed')
st.markdown('''<style>
.block-container{max-width:1080px;padding-top:.55rem;padding-bottom:4rem}[data-testid="stMetric"]{border:1px solid rgba(127,127,127,.15);border-radius:18px;padding:11px 13px;background:linear-gradient(145deg,rgba(127,127,127,.04),rgba(127,127,127,.015));box-shadow:0 8px 26px rgba(0,0,0,.04)}[data-testid="stMetricValue"]{font-size:1.3rem;font-weight:760}.hero{border:1px solid rgba(127,127,127,.15);border-radius:24px;padding:17px;background:radial-gradient(circle at top right,rgba(124,92,255,.18),transparent 35%),linear-gradient(145deg,rgba(127,127,127,.04),rgba(127,127,127,.015));margin-bottom:10px}.hero-title{font-size:1.55rem;font-weight:800}.hero-sub{font-size:.86rem;opacity:.72;margin-top:4px}.card{border:1px solid rgba(127,127,127,.15);border-radius:17px;padding:13px 14px;margin:8px 0;background:rgba(127,127,127,.025)}.ok{border-left:4px solid #26a269}.att{border-left:4px solid #e5a50a}.bad{border-left:4px solid #c01c28}.info{border-left:4px solid #3584e4}.ct{font-weight:750}.cs{font-size:.84rem;opacity:.75;margin-top:3px}.section{font-size:1.08rem;font-weight:780;margin:14px 0 7px}div[data-testid="stTabs"] button{font-weight:700}@media(max-width:720px){.block-container{padding-left:.42rem;padding-right:.42rem}.hero{padding:13px;border-radius:19px}.hero-title{font-size:1.32rem}[data-testid="stMetric"]{padding:8px 9px;border-radius:14px}[data-testid="stMetricValue"]{font-size:1.02rem}div[data-testid="stTabs"] button{font-size:.76rem;padding-left:.4rem;padding-right:.4rem}.stButton button{min-height:2.7rem;border-radius:14px}}</style>''',unsafe_allow_html=True)

def secret(n):
    try:
        if n in st.secrets:return st.secrets[n]
    except:pass
    return os.getenv(n)
HEVY_API_KEY=secret('HEVY_API_KEY');GROQ_API_KEY=secret('GROQ_API_KEY');APP_PASSWORD=secret('APP_PASSWORD');SUPABASE_URL=secret('SUPABASE_URL');SUPABASE_KEY=secret('SUPABASE_KEY')

def login():
    if not APP_PASSWORD: st.error('Configure APP_PASSWORD nos Secrets.'); st.stop()
    if st.session_state.get('auth'): return
    st.markdown('<div class="hero"><div class="hero-title">⚡ Minha Evolução</div><div class="hero-sub">Treino, alimentação e evolução em um só lugar.</div></div>',unsafe_allow_html=True)
    p=st.text_input('Senha',type='password')
    if st.button('Entrar',type='primary',use_container_width=True):
        if p and hashlib.sha256(p.encode()).hexdigest()==hashlib.sha256(str(APP_PASSWORD).encode()).hexdigest():st.session_state['auth']=True;st.rerun()
        st.error('Senha incorreta.')
    st.stop()
login()

def sh(prefer=None):
    h={'apikey':SUPABASE_KEY,'Authorization':f'Bearer {SUPABASE_KEY}','Content-Type':'application/json'}
    if prefer:h['Prefer']=prefer
    return h
def su(t):return f"{SUPABASE_URL.rstrip('/')}/rest/v1/{t}"
def db_select(t,order=None,limit=None):
    p={'select':'*'}
    if order:p['order']=order
    if limit:p['limit']=str(limit)
    r=requests.get(su(t),headers=sh(),params=p,timeout=20);r.raise_for_status();return r.json()
def db_insert(t,row):
    r=requests.post(su(t),headers=sh('return=representation'),json=row,timeout=20);r.raise_for_status();d=r.json();return d[0] if d else row
def db_upsert_profile(row):
    row=dict(row);row['id']='me';r=requests.post(su('profile'),headers=sh('resolution=merge-duplicates,return=representation'),params={'on_conflict':'id'},json=row,timeout=20);r.raise_for_status()
def profile():
    x=db_select('profile');return x[0] if x else {}

def groq(system,user,max_tokens=1600):
    if not GROQ_API_KEY: raise RuntimeError('GROQ_API_KEY não configurada.')
    r=requests.post(GROQ_URL,headers={'Authorization':f'Bearer {GROQ_API_KEY}','Content-Type':'application/json'},json={'model':GROQ_MODEL,'messages':[{'role':'system','content':system},{'role':'user','content':user}],'temperature':.1,'max_completion_tokens':max_tokens},timeout=60);r.raise_for_status();return r.json()['choices'][0]['message']['content']

def nutrition_ai(text):
    if not re.search(r'\b\d+([.,]\d+)?\s*(g|kg|ml|l|unidade|unidades|fatia|fatias|colher|colheres|xícara|xicara)\b',text.lower()):return {'needs':True,'confidence':'baixa','note':'Informe quantidades e, quando relevante, o modo de preparo.'}
    s="Você estima nutrição de forma conservadora. Responda SOMENTE JSON. Só use confiança alta quando quantidades, alimento e preparo estiverem suficientemente claros."
    u=f'''Estime a refeição: {text}\nRetorne exatamente {{"kcal":numero,"protein":numero,"carbs":numero,"fat":numero,"confidence":"alta|media|baixa","note":"texto curto em português"}}'''
    raw=groq(s,u,500).replace('```json','').replace('```','').strip();d=json.loads(raw);k,p,c,f=[float(d.get(x) or 0) for x in ['kcal','protein','carbs','fat']];calc=p*4+c*4+f*9
    conf=str(d.get('confidence','baixa')).lower();note=str(d.get('note',''))
    if k and abs(calc-k)/k>.18 and conf=='alta':conf='media';note+=' A coerência entre kcal e macros reduziu a confiança.'
    return {'kcal':k,'protein':p,'carbs':c,'fat':f,'confidence':conf,'note':note,'needs':False}

def hevy_get(path,params=None):
    if not HEVY_API_KEY:return {}
    r=requests.get(HEVY_BASE+path,headers={'api-key':HEVY_API_KEY,'accept':'application/json'},params=params or {},timeout=30);r.raise_for_status();return r.json()
@st.cache_data(ttl=300,show_spinner=False)
def hevy_workouts():
    if not HEVY_API_KEY:return []
    rows=[];page=1
    while True:
        d=hevy_get('/workouts',{'page':page,'pageSize':10});b=d.get('workouts',[]);rows+=b;pc=d.get('page_count') or d.get('pageCount')
        if not b or (pc and page>=pc) or len(b)<10:break
        page+=1
    return rows
@st.cache_data(ttl=300,show_spinner=False)
def hevy_measures():
    if not HEVY_API_KEY:return []
    rows=[];page=1
    while True:
        d=hevy_get('/body_measurements',{'page':page,'pageSize':10});b=d.get('body_measurements',[]);rows+=b;pc=d.get('page_count') or d.get('pageCount')
        if not b or (pc and page>=pc) or len(b)<10:break
        page+=1
    return rows

def muscle(n):
    n=str(n or '').lower(); rules=[(('supino','crucifixo','voador'),'Peito'),(('puxada','pulldown','remada','barra fixa'),'Costas'),(('desenvolvimento','elevação lateral','elevacao lateral','crucifixo inverso'),'Ombros'),(('tríceps','triceps'),'Tríceps'),(('rosca','curl'),'Bíceps'),(('hack','leg press','extensora','agachamento'),'Quadríceps'),(('flexora','stiff','rdl','romeno'),'Posteriores'),(('panturrilha','calf'),'Panturrilhas'),(('abdominal','abdômen','abdomen','crunch'),'Abdômen'),(('encolhimento','shrug'),'Trapézio')]
    for ks,m in rules:
        if any(k in n for k in ks):return m
    return 'Outros'

def frames(raw):
    W=[];S=[]
    for w in raw:
        a=pd.to_datetime(w.get('start_time'),utc=True,errors='coerce');b=pd.to_datetime(w.get('end_time'),utc=True,errors='coerce');dur=(b-a).total_seconds()/60 if pd.notna(a) and pd.notna(b) else None;t=w.get('title','Treino')
        W.append({'date':a,'title':t,'activity_type':'Musculação','duration_min':dur,'intensity':'Moderada','source':'Hevy'})
        for e in w.get('exercises',[]) or []:
            nm=e.get('title') or e.get('exercise_template_title') or e.get('name') or 'Exercício'
            for s in e.get('sets',[]) or []:
                kg=s.get('weight_kg');rp=s.get('reps');vol=kg*rp if isinstance(kg,(int,float)) and isinstance(rp,int) else None;e1=kg*(1+rp/30) if isinstance(kg,(int,float)) and isinstance(rp,int) and rp>0 else None
                S.append({'date':a,'title':t,'exercise':nm,'muscle':muscle(nm),'weight_kg':kg,'reps':rp,'sets_count':1,'volume_kg':vol,'e1rm_kg':e1,'source':'Hevy'})
    return pd.DataFrame(W),pd.DataFrame(S)

def manual_frames():
    w=pd.DataFrame(db_select('manual_workout',order='workout_date.asc'));e=pd.DataFrame(db_select('manual_exercise'))
    if w.empty:return pd.DataFrame(),pd.DataFrame()
    w['date']=pd.to_datetime(w['workout_date'],utc=True,errors='coerce');w['source']='Manual';w=w[['id','date','title','activity_type','duration_min','intensity','source']]
    if e.empty:return w,pd.DataFrame()
    e['workout_id']=e['workout_id'].astype(str);w2=w.copy();w2['id']=w2['id'].astype(str);x=e.merge(w2[['id','date','title']],left_on='workout_id',right_on='id',how='left');x['volume_kg']=pd.to_numeric(x['weight_kg'],errors='coerce').fillna(0)*pd.to_numeric(x['reps'],errors='coerce').fillna(0)*pd.to_numeric(x['sets_count'],errors='coerce').fillna(0);x['e1rm_kg']=pd.to_numeric(x['weight_kg'],errors='coerce')*(1+pd.to_numeric(x['reps'],errors='coerce')/30);x['source']='Manual';return w,x[['date','title','exercise','muscle','weight_kg','reps','sets_count','volume_kg','e1rm_kg','source']]

MET={('Musculação','Leve'):3.5,('Musculação','Moderada'):5,('Musculação','Vigorosa'):6,('Caminhada','Leve'):2.8,('Caminhada','Moderada'):3.8,('Caminhada','Vigorosa'):5,('Corrida','Leve'):6,('Corrida','Moderada'):8.3,('Corrida','Vigorosa'):10,('Bicicleta','Leve'):4,('Bicicleta','Moderada'):6.8,('Bicicleta','Vigorosa'):8,('Esporte','Leve'):4,('Esporte','Moderada'):6,('Esporte','Vigorosa'):8,('Outro','Leve'):3.5,('Outro','Moderada'):5,('Outro','Vigorosa'):7}
def mifflin(w,h,a,s):
    if not all([w,h,a,s]):return None
    b=10*w+6.25*h-5*a;return b+5 if s=='Masculino' else b-161
def act_kcal(w,minu,met):return float(minu)*(float(met)*3.5*float(w)/200) if w and minu and met else 0
def pweight(p,mdf):
    if not mdf.empty and 'weight_kg' in mdf:
        d=mdf[['date','weight_kg']].dropna().sort_values('date')
        if not d.empty:return float(d.iloc[-1].weight_kg)
    return float(p.get('weight_kg')) if p.get('weight_kg') not in (None,'') else None
def planned_daily(w):
    x=pd.DataFrame(db_select('activity_plan'))
    if x.empty or not w:return 0
    return sum(act_kcal(w,r.minutes_session,float(r.met or MET.get((r.activity_type,r.intensity),5)))*float(r.days_week or 0) for _,r in x.iterrows())/7
def actual_day(w,wdf,d):
    if wdf.empty or not w:return 0
    x=wdf.copy();x['d']=pd.to_datetime(x['date'],utc=True).dt.tz_convert(None).dt.date;x=x[x.d==d];return sum(act_kcal(w,r.duration_min,MET.get((r.activity_type,r.intensity),5)) for _,r in x.iterrows())
def intake_day(meals,d):
    if meals.empty:return 0
    x=meals.copy();x['eaten_at']=pd.to_datetime(x['eaten_at'],errors='coerce');x=x[x.eaten_at.dt.date==d];return float(pd.to_numeric(x.kcal,errors='coerce').fillna(0).sum())
def energy(p,w,wdf,meals,d):
    ree=mifflin(w,float(p.get('height_cm') or 0),int(p.get('age') or 0),p.get('sex'));base=ree*float(p.get('activity_factor') or 1.2) if ree else None;act=actual_day(w,wdf,d);act=act if act>0 else planned_daily(w);tdee=base+act if base else None;inn=intake_day(meals,d);return {'ree':ree,'tdee':tdee,'exercise':act,'intake':inn,'deficit':tdee-inn if tdee is not None and inn>0 else None}

def period(choice):
    if choice=='Tudo':return None,None
    n={'7 dias':7,'14 dias':14,'30 dias':30,'60 dias':60,'90 dias':90,'6 meses':180,'1 ano':365}[choice];return date.today()-timedelta(days=n-1),date.today()
def filt(df,a,b,col='date'):
    if df.empty or a is None:return df.copy()
    d=pd.to_datetime(df[col],utc=True,errors='coerce');return df[(d.dt.date>=a)&(d.dt.date<=b)].copy()
def progress(sf):
    if sf.empty:return pd.DataFrame()
    x=sf.copy();x['day']=pd.to_datetime(x.date,utc=True).dt.date;d=x.groupby(['exercise','day'],as_index=False).agg(load=('weight_kg','max'),e1=('e1rm_kg','max'),volume=('volume_kg','sum'),sets=('sets_count','sum'));rows=[]
    for ex,g in d.groupby('exercise'):
        g=g.sort_values('day')
        if len(g)<2:continue
        a,b=g.iloc[0],g.iloc[-1];ch=(b.e1-a.e1)/a.e1*100 if pd.notna(a.e1) and a.e1 and pd.notna(b.e1) else None;rows.append({'Exercício':ex,'Sessões':len(g),'1RM inicial':a.e1,'1RM atual':b.e1,'Variação %':ch})
    return pd.DataFrame(rows)
try:hraw=hevy_workouts();mraw=hevy_measures()
except Exception as e:hraw=[];mraw=[];st.toast(f'Hevy indisponível: {e}')
hw,hs=frames(hraw);mw,ms=manual_frames();wdf=pd.concat([hw,mw],ignore_index=True) if not hw.empty or not mw.empty else pd.DataFrame();sdf=pd.concat([hs,ms],ignore_index=True) if not hs.empty or not ms.empty else pd.DataFrame();mdf=pd.DataFrame(mraw)
if not mdf.empty and 'date' in mdf:mdf['date']=pd.to_datetime(mdf.date,errors='coerce')
meals=pd.DataFrame(db_select('meal_log',order='eaten_at.asc'));diet=pd.DataFrame(db_select('diet_plan'));prof=profile();weight=pweight(prof,mdf)

c1,c2=st.columns([5,1])
with c1:st.markdown('<div class="hero"><div class="hero-title">⚡ Minha Evolução</div><div class="hero-sub">Treino, alimentação, composição corporal e inteligência em um só lugar.</div></div>',unsafe_allow_html=True)
with c2:
    with st.popover('⚙️'):
        st.markdown('#### Perfil')
        sexes=['Masculino','Feminino'];sx=prof.get('sex') if prof.get('sex') in sexes else 'Masculino';sex=st.selectbox('Sexo para cálculo',sexes,index=sexes.index(sx));age=st.number_input('Idade',18,100,int(prof.get('age') or 35));height=st.number_input('Altura (cm)',120.,230.,float(prof.get('height_cm') or 175),step=.5);pw=st.number_input('Peso manual (kg)',35.,300.,float(prof.get('weight_kg') or weight or 80),step=.1,help='Usado quando o Hevy não fornece peso.');goals=['Reduzir gordura','Recomposição corporal','Ganhar massa','Manter'];g0=prof.get('goal') if prof.get('goal') in goals else 'Recomposição corporal';goal=st.selectbox('Objetivo',goals,index=goals.index(g0));factors=[1.20,1.25,1.30,1.35];fv=float(prof.get('activity_factor') or 1.20);af=st.selectbox('Rotina diária fora dos exercícios',factors,index=factors.index(fv) if fv in factors else 0,format_func=lambda x:{1.20:'Predominantemente sentado',1.25:'Pouco ativo',1.30:'Moderadamente ativo',1.35:'Bem ativo'}[x]);td=st.number_input('Meta de déficit (kcal/dia)',0,1000,int(prof.get('target_deficit') or 500),step=50)
        if st.button('Salvar perfil',use_container_width=True):db_upsert_profile({'sex':sex,'age':int(age),'height_cm':float(height),'weight_kg':float(pw),'goal':goal,'activity_factor':float(af),'target_deficit':float(td),'updated_at':datetime.now(timezone.utc).isoformat()});st.rerun()
        st.divider();st.caption(f"Hevy: {'conectado' if HEVY_API_KEY else 'manual'} · IA: {'ativa' if GROQ_API_KEY else 'off'} · Banco: Supabase")
        if st.button('Sair',use_container_width=True):st.session_state.pop('auth',None);st.rerun()

t0,t1,t2,t3,t4=st.tabs(['🏠 Início','🍽️ Alimentação','🏋️ Treinos','📈 Evolução','✨ IA'])

with t0:
    en=energy(prof,weight,wdf,meals,date.today());target=float(prof.get('target_deficit') or 500);goal_k=en['tdee']-target if en['tdee'] else None
    st.markdown('<div class="section">Seu dia em números</div>',unsafe_allow_html=True);a,b,c,d=st.columns(4);a.metric('Consumido',f"{en['intake']:.0f} kcal" if en['intake'] else '—');b.metric('Gasto estimado',f"{en['tdee']:.0f} kcal" if en['tdee'] else '—');c.metric('Exercícios',f"{en['exercise']:.0f} kcal" if en['exercise'] else '—');d.metric('Meta de ingestão',f'{goal_k:.0f} kcal' if goal_k else '—')
    if en['deficit'] is None:cls,ttl,txt='info','Registros incompletos','Registre as refeições do dia para calcular o balanço energético.'
    elif en['deficit']<150:cls,ttl,txt='info','Próximo da manutenção',f"Saldo estimado: {en['deficit']:.0f} kcal."
    elif en['deficit']<=750:cls,ttl,txt='ok','Déficit moderado',f"Déficit aproximado de {en['deficit']:.0f} kcal. Observe a tendência semanal, desempenho e recuperação."
    elif en['deficit']<=1000:cls,ttl,txt='att','Déficit elevado',f"Déficit aproximado de {en['deficit']:.0f} kcal. Vale revisar fome, recuperação e rendimento."
    else:cls,ttl,txt='bad','Déficit muito agressivo',f"Déficit aproximado de {en['deficit']:.0f} kcal. Não use esta estimativa como meta automática."
    st.markdown(f'<div class="card {cls}"><div class="ct">{ttl}</div><div class="cs">{txt}</div></div>',unsafe_allow_html=True)
    ws=date.today()-timedelta(days=date.today().weekday());ww=filt(wdf,ws,date.today()) if not wdf.empty else pd.DataFrame();st.markdown('<div class="section">Visão rápida</div>',unsafe_allow_html=True);a,b,c=st.columns(3);a.metric('Treinos na semana',len(ww));b.metric('Peso atual',f'{weight:.1f} kg' if weight else '—');c.metric('Repouso estimado',f"{en['ree']:.0f} kcal" if en['ree'] else '—')

with t1:
    mode=st.segmented_control('Área',['Diário','Plano alimentar'],default='Diário',label_visibility='collapsed')
    if mode=='Diário':
        st.markdown('<div class="section">Registrar refeição consumida</div>',unsafe_allow_html=True);st.caption('Informe quantidades e preparo. Ex.: 150 g de arroz cozido, 100 g de feijão e 150 g de frango grelhado.')
        mn=st.selectbox('Refeição',['Café da manhã','Lanche da manhã','Almoço','Lanche da tarde','Jantar','Ceia','Outra']);desc=st.text_area('O que você comeu?',height=100,key='logdesc')
        if st.button('✨ Calcular com IA',use_container_width=True,type='primary',key='logcalc'):
            if not desc.strip():st.warning('Descreva a refeição.')
            else:
                try:
                    with st.spinner('Calculando...'):st.session_state['mealest']=nutrition_ai(desc)
                except Exception as e:st.error(str(e))
        est=st.session_state.get('mealest')
        if est:
            if est.get('needs'):st.markdown(f'<div class="card att"><div class="ct">Precisamos de mais detalhes</div><div class="cs">{est["note"]}</div></div>',unsafe_allow_html=True)
            else:
                cf=est['confidence'];st.markdown(f'<div class="card {"ok" if cf=="alta" else "att"}"><div class="ct">Estimativa · confiança {cf}</div><div class="cs"><b>{est["kcal"]:.0f} kcal</b> · {est["protein"]:.0f} g proteína · {est["carbs"]:.0f} g carbo · {est["fat"]:.0f} g gordura<br>{est["note"]}</div></div>',unsafe_allow_html=True);allow=cf=='alta' or st.checkbox('Salvar mesmo sem confiança alta.',key='ovlog')
                if st.button('Salvar refeição',use_container_width=True,disabled=not allow,key='savelog'):db_insert('meal_log',{'eaten_at':datetime.now().isoformat(),'meal_name':mn,'description':desc,'kcal':est['kcal'],'protein':est['protein'],'carbs':est['carbs'],'fat':est['fat'],'confidence':cf,'source':'IA Groq'});st.session_state.pop('mealest',None);st.rerun()
        if not meals.empty:
            x=meals.copy();x['eaten_at']=pd.to_datetime(x.eaten_at,errors='coerce');x=x[x.eaten_at.dt.date==date.today()]
            if not x.empty:
                st.markdown('<div class="section">Hoje</div>',unsafe_allow_html=True);a,b,c,d=st.columns(4);a.metric('Calorias',f'{pd.to_numeric(x.kcal,errors="coerce").fillna(0).sum():.0f}');b.metric('Proteína',f'{pd.to_numeric(x.protein,errors="coerce").fillna(0).sum():.0f} g');c.metric('Carbo',f'{pd.to_numeric(x.carbs,errors="coerce").fillna(0).sum():.0f} g');d.metric('Gordura',f'{pd.to_numeric(x.fat,errors="coerce").fillna(0).sum():.0f} g');show=x[['meal_name','description','kcal','confidence']].copy();show.columns=['Refeição','Descrição','kcal','Confiança'];st.dataframe(show,use_container_width=True,hide_index=True)
    else:
        st.markdown('<div class="section">Montar plano alimentar com IA</div>',unsafe_allow_html=True);st.caption('Você informa a refeição e porções; calorias e macros são preenchidos automaticamente. Confiança alta exige quantidades claras e preparo quando relevante.')
        pn=st.text_input('Nome da refeição',placeholder='Ex.: Almoço');pdsc=st.text_area('Composição planejada',placeholder='Ex.: 170 g arroz cozido, 130 g feijão cozido, 150 g peito de frango grelhado e 120 g legumes',height=110)
        if st.button('✨ Analisar refeição do plano',use_container_width=True,type='primary'):
            if not pn.strip() or not pdsc.strip():st.warning('Informe nome e composição.')
            else:
                try:
                    with st.spinner('Calculando...'):st.session_state['planest']=nutrition_ai(pdsc)
                except Exception as e:st.error(str(e))
        pe=st.session_state.get('planest')
        if pe:
            if pe.get('needs'):st.markdown(f'<div class="card att"><div class="ct">Detalhe melhor as porções</div><div class="cs">{pe["note"]}</div></div>',unsafe_allow_html=True)
            else:
                cf=pe['confidence'];st.markdown(f'<div class="card {"ok" if cf=="alta" else "att"}"><div class="ct">Cálculo automático · confiança {cf}</div><div class="cs"><b>{pe["kcal"]:.0f} kcal</b> · {pe["protein"]:.0f} g proteína · {pe["carbs"]:.0f} g carbo · {pe["fat"]:.0f} g gordura<br>{pe["note"]}</div></div>',unsafe_allow_html=True);allow=cf=='alta' or st.checkbox('Salvar mesmo sem confiança alta.',key='ovplan')
                if st.button('Adicionar ao plano',use_container_width=True,disabled=not allow):db_insert('diet_plan',{'meal_name':pn,'description':pdsc,'kcal':pe['kcal'],'protein':pe['protein'],'carbs':pe['carbs'],'fat':pe['fat'],'confidence':cf});st.session_state.pop('planest',None);st.rerun()
        dn=pd.DataFrame(db_select('diet_plan'))
        if not dn.empty:st.markdown('<div class="section">Seu plano</div>',unsafe_allow_html=True);a,b=st.columns(2);a.metric('Total planejado',f'{pd.to_numeric(dn.kcal,errors="coerce").fillna(0).sum():.0f} kcal');b.metric('Proteína planejada',f'{pd.to_numeric(dn.protein,errors="coerce").fillna(0).sum():.0f} g');show=dn[['meal_name','description','kcal','protein','carbs','fat','confidence']].copy();show.columns=['Refeição','Composição','kcal','Proteína','Carbo','Gordura','Confiança'];st.dataframe(show,use_container_width=True,hide_index=True)

with t2:
    tm=st.segmented_control('Área',['Visão geral','Rotina semanal','Cadastro manual'],default='Visão geral',label_visibility='collapsed')
    if tm=='Visão geral':
        pr=st.selectbox('Período',['7 dias','14 dias','30 dias','60 dias','90 dias','6 meses','1 ano','Tudo'],index=2,key='tp');a0,b0=period(pr);wf=filt(wdf,a0,b0);sf=filt(sdf,a0,b0)
        if wf.empty:st.info('Ainda não há treinos neste período.')
        else:
            a,b,c=st.columns(3);a.metric('Sessões',len(wf));b.metric('Min/sessão',f'{pd.to_numeric(wf.duration_min,errors="coerce").mean():.0f}');c.metric('Fonte','Hevy + Manual' if len(set(wf.source))>1 else str(wf.source.iloc[0]));x=wf.copy();x['Semana']=pd.to_datetime(x.date,utc=True).dt.tz_convert(None).dt.to_period('W').astype(str);wc=x.groupby('Semana',as_index=False).size().rename(columns={'size':'Sessões'});fig=px.bar(wc,x='Semana',y='Sessões',title='Frequência semanal');fig.update_layout(height=290,margin=dict(l=10,r=10,t=45,b=10));st.plotly_chart(fig,use_container_width=True)
            if not sf.empty:
                bm=sf.groupby('muscle',as_index=False).agg(Séries=('sets_count','sum'));bm=bm[bm.muscle!='Outros'].sort_values('Séries',ascending=False);fig=px.bar(bm,x='muscle',y='Séries',title='Séries por grupo muscular');fig.update_layout(height=300,margin=dict(l=10,r=10,t=45,b=10),xaxis_title='');st.plotly_chart(fig,use_container_width=True);pg=progress(sf)
                if not pg.empty:st.markdown('<div class="section">Evolução dos exercícios</div>',unsafe_allow_html=True);st.dataframe(pg.sort_values('Variação %',ascending=False),use_container_width=True,hide_index=True)
    elif tm=='Rotina semanal':
        st.markdown('<div class="section">Sua rotina de atividades</div>',unsafe_allow_html=True);st.caption('Cadastre musculação, corrida, bicicleta, esportes ou outras atividades. Frequência, duração e intensidade entram no cálculo energético e na IA.')
        with st.form('routine',clear_on_submit=True):
            typ=st.selectbox('Tipo de atividade',['Musculação','Caminhada','Corrida','Bicicleta','Esporte','Outro']);days=st.number_input('Vezes por semana',1,7,3);mins=st.number_input('Duração média (min)',10,300,60,step=5);inte=st.selectbox('Intensidade',['Leve','Moderada','Vigorosa'],index=1);sv=st.form_submit_button('Adicionar à rotina',use_container_width=True)
            if sv:db_insert('activity_plan',{'activity_type':typ,'days_week':float(days),'minutes_session':float(mins),'intensity':inte,'met':float(MET[(typ,inte)])});st.rerun()
        rt=pd.DataFrame(db_select('activity_plan'))
        if not rt.empty:
            show=pd.DataFrame([{'Atividade':r.activity_type,'Frequência':f'{int(float(r.days_week))}x/sem','Duração':f'{int(float(r.minutes_session))} min','Intensidade':r.intensity} for _,r in rt.iterrows()]);st.dataframe(show,use_container_width=True,hide_index=True)
            if weight:st.markdown(f'<div class="card info"><div class="ct">Impacto energético médio</div><div class="cs">A rotina cadastrada representa aproximadamente <b>{planned_daily(weight):.0f} kcal/dia</b> quando o gasto semanal é distribuído pela semana.</div></div>',unsafe_allow_html=True)
    else:
        st.markdown('<div class="section">Registrar treino sem aplicativo</div>',unsafe_allow_html=True)
        with st.form('mw',clear_on_submit=True):
            d=st.date_input('Data',date.today());title=st.text_input('Nome do treino');typ=st.selectbox('Tipo',['Musculação','Caminhada','Corrida','Bicicleta','Esporte','Outro']);dur=st.number_input('Duração (min)',1,300,60);inte=st.selectbox('Intensidade',['Leve','Moderada','Vigorosa'],index=1);notes=st.text_area('Observações',height=70);sv=st.form_submit_button('Salvar sessão',use_container_width=True)
            if sv and title.strip():db_insert('manual_workout',{'workout_date':str(d),'title':title,'activity_type':typ,'duration_min':float(dur),'intensity':inte,'notes':notes});st.rerun()
        recent=pd.DataFrame(db_select('manual_workout',order='workout_date.desc',limit=20))
        if not recent.empty:
            labs={int(r.id):f'{r.workout_date} · {r.title}' for _,r in recent.iterrows()};wid=st.selectbox('Adicionar exercício em:',list(labs),format_func=lambda x:labs[x])
            with st.form('mex',clear_on_submit=True):
                ex=st.text_input('Exercício');mu=st.selectbox('Grupo muscular',['Peito','Costas','Ombros','Bíceps','Tríceps','Quadríceps','Posteriores','Panturrilhas','Abdômen','Trapézio','Outros']);se=st.number_input('Séries',1,20,3);rp=st.number_input('Repetições',1,100,10);kg=st.number_input('Carga (kg)',0.,1000.,0.,step=1.);ss=st.form_submit_button('Salvar exercício',use_container_width=True)
                if ss and ex.strip():db_insert('manual_exercise',{'workout_id':int(wid),'exercise':ex,'muscle':mu,'sets_count':int(se),'reps':int(rp),'weight_kg':float(kg)});st.rerun()

with t3:
    pr=st.selectbox('Período',['7 dias','14 dias','30 dias','60 dias','90 dias','6 meses','1 ano','Tudo'],index=4,key='ep');a0,b0=period(pr);wf=filt(wdf,a0,b0);sf=filt(sdf,a0,b0);e1,e2,e3=st.tabs(['Corpo','Performance','Energia'])
    labels={'weight_kg':'Peso','fat_percent':'Gordura corporal','lean_mass_kg':'Massa magra','neck_cm':'Pescoço','shoulder_cm':'Ombros','chest_cm':'Peitoral','left_bicep_cm':'Braço esquerdo','right_bicep_cm':'Braço direito','left_forearm_cm':'Antebraço esquerdo','right_forearm_cm':'Antebraço direito','waist':'Cintura','waist_cm':'Cintura','abdomen':'Abdômen','abdomen_cm':'Abdômen','hips':'Quadril','hips_cm':'Quadril','left_thigh':'Coxa esquerda','right_thigh':'Coxa direita','left_calf':'Panturrilha esquerda','right_calf':'Panturrilha direita'}
    with e1:
        if mdf.empty:st.info('Sem medidas corporais do Hevy. O peso manual continua no perfil.')
        else:
            av=[c for c in mdf.columns if c not in ('date','id') and pd.to_numeric(mdf[c],errors='coerce').notna().any()]
            if av:
                sel=st.selectbox('Medida corporal',av,format_func=lambda x:labels.get(x,x.replace('_',' ').title()));d=mdf[['date',sel]].copy();d[sel]=pd.to_numeric(d[sel],errors='coerce');d=d.dropna();d=filt(d,a0,b0)
                if not d.empty:fig=px.line(d,x='date',y=sel,markers=True,title=labels.get(sel,sel));fig.update_layout(height=310,margin=dict(l=10,r=10,t=45,b=10),xaxis_title='',yaxis_title='');st.plotly_chart(fig,use_container_width=True)
    with e2:
        if sf.empty:st.info('Sem dados de exercícios.')
        else:
            ex=st.selectbox('Exercício',sorted(sf.exercise.dropna().unique()),key='evex');x=sf[sf.exercise==ex].copy();x['Dia']=pd.to_datetime(x.date,utc=True).dt.date;dd=x.groupby('Dia',as_index=False).agg(**{'Melhor carga':('weight_kg','max'),'1RM estimado':('e1rm_kg','max'),'Volume':('volume_kg','sum'),'Séries':('sets_count','sum')});met=st.segmented_control('Indicador',['1RM estimado','Melhor carga','Volume','Séries'],default='1RM estimado');fig=px.line(dd,x='Dia',y=met,markers=True,title=f'{ex} · {met}');fig.update_layout(height=310,margin=dict(l=10,r=10,t=45,b=10),xaxis_title='',yaxis_title='');st.plotly_chart(fig,use_container_width=True)
    with e3:
        if meals.empty or not prof:st.info('Complete o perfil e registre alimentação para visualizar o balanço energético.')
        else:
            d0=a0 or date.today()-timedelta(days=29);d1=b0 or date.today();rows=[]
            for ts in pd.date_range(d0,d1,freq='D'):
                en=energy(prof,weight,wdf,meals,ts.date())
                if en['intake']>0:rows.append({'Data':ts.date(),'Consumo':en['intake'],'Gasto estimado':en['tdee']})
            if rows:ed=pd.DataFrame(rows);fig=px.line(ed,x='Data',y=['Consumo','Gasto estimado'],markers=True,title='Consumo x gasto estimado');fig.update_layout(height=310,margin=dict(l=10,r=10,t=45,b=10),yaxis_title='kcal');st.plotly_chart(fig,use_container_width=True)
            else:st.info('Sem dias completos com alimentação registrada.')

with t4:
    st.markdown('<div class="section">Análise inteligente</div>',unsafe_allow_html=True);st.caption('A IA interpreta dados agregados; cálculos principais são feitos pelo painel.')
    mode=st.selectbox('O que analisar?',['Visão geral','Hipertrofia','Perda de gordura / recomposição','Alimentação e déficit','Treinos e recuperação','Exercício específico']);pr=st.selectbox('Período',['7 dias','14 dias','30 dias','60 dias','90 dias','6 meses','1 ano','Tudo'],index=2,key='aip');a0,b0=period(pr);wf=filt(wdf,a0,b0);sf=filt(sdf,a0,b0);focus=None
    if mode=='Exercício específico' and not sf.empty:focus=st.selectbox('Exercício',sorted(sf.exercise.dropna().unique()),key='aiex')
    if st.button('✨ Gerar análise',type='primary',use_container_width=True):
        try:
            pg=progress(sf);en=energy(prof,weight,wdf,meals,date.today());payload={'objetivo':prof.get('goal'),'periodo':{'inicio':str(a0),'fim':str(b0)},'perfil':{'peso_kg':weight,'altura_cm':prof.get('height_cm'),'idade':prof.get('age'),'meta_deficit':prof.get('target_deficit')},'rotina_atividades':db_select('activity_plan'),'treinos':{'sessoes':len(wf),'duracao_media_min':round(float(pd.to_numeric(wf.duration_min,errors='coerce').mean()),1) if not wf.empty else None},'performance':pg.to_dict('records') if not pg.empty else [],'plano_alimentar':db_select('diet_plan'),'energia_hoje':en}
            if focus and not pg.empty:payload['performance']=pg[pg['Exercício']==focus].to_dict('records')
            sys='Você analisa dados de treino e nutrição. Use somente os dados fornecidos. Não diagnostique, não prescreva medicamentos, não trate calorias como exatas e não recomende restrições extremas. Responda integralmente em português do Brasil.';usr=f'''FOCO: {mode}\nEntregue: 1 Resumo executivo; 2 O que vai bem; 3 Pontos de atenção; 4 Análises individuais; 5 Integração treino+alimentação+corpo; 6 Prioridades para 14 dias; 7 Dados que aumentariam a confiança.\nDADOS:{json.dumps(payload,ensure_ascii=False,default=str)}'''
            with st.spinner('Analisando...'):st.session_state['aires']=groq(sys,usr,2300)
        except Exception as e:st.error(f'Erro: {e}')
    if st.session_state.get('aires'):st.markdown(st.session_state['aires']);st.download_button('Baixar análise',st.session_state['aires'],file_name='analise_evolucao.txt',mime='text/plain',use_container_width=True)

st.divider();st.caption('Calorias, metabolismo, gasto de exercício e macronutrientes são estimativas. Use tendências de vários dias e semanas, não um único número.')
