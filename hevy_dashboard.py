import os
import json
import hashlib
import sqlite3
from datetime import date, datetime, timedelta, timezone

import requests
import pandas as pd
import streamlit as st
import plotly.express as px

HEVY_BASE = "https://api.hevyapp.com/v1"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
LOCAL_DB = "app_data.db"
WEEKLY_PLAN = {"B": 2, "A": 2, "C": 1}

st.set_page_config(page_title="Minha Evolução", page_icon="💪", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""
<style>
.block-container{padding-top:.65rem;padding-bottom:4rem;max-width:1120px}
[data-testid="stMetric"]{border:1px solid rgba(128,128,128,.16);background:rgba(128,128,128,.035);padding:10px 12px;border-radius:16px}
[data-testid="stMetricLabel"]{font-size:.78rem}[data-testid="stMetricValue"]{font-size:1.45rem;font-weight:750}
h1{font-size:1.75rem!important;margin-bottom:.1rem!important}h2{font-size:1.22rem!important}h3{font-size:1.02rem!important}
.app-card{border:1px solid rgba(128,128,128,.16);border-radius:16px;padding:12px 14px;margin:7px 0;background:rgba(128,128,128,.025)}
.good{border-left:4px solid #2e7d32}.warn{border-left:4px solid #f9a825}.info{border-left:4px solid #1976d2}.bad{border-left:4px solid #c62828}.small{font-size:.82rem;opacity:.72}
@media(max-width:720px){.block-container{padding-left:.45rem;padding-right:.45rem}[data-testid="stMetric"]{padding:8px 9px}[data-testid="stMetricValue"]{font-size:1.08rem}h1{font-size:1.48rem!important}.stButton button{min-height:2.65rem}}
</style>
""", unsafe_allow_html=True)

def secret(name):
    try:
        if name in st.secrets: return st.secrets[name]
    except Exception: pass
    return os.getenv(name)

HEVY_API_KEY=secret("HEVY_API_KEY")
GROQ_API_KEY=secret("GROQ_API_KEY")
APP_PASSWORD=secret("APP_PASSWORD")
SUPABASE_URL=secret("SUPABASE_URL")
SUPABASE_KEY=secret("SUPABASE_KEY")

def password_gate():
    if not APP_PASSWORD:
        st.error("Configure `APP_PASSWORD` nos Secrets para proteger o painel.")
        st.code('APP_PASSWORD = "sua-senha-forte"', language="toml"); st.stop()
    if st.session_state.get("authenticated"): return
    st.title("🔒 Minha Evolução"); st.caption("Painel pessoal protegido")
    pwd=st.text_input("Senha", type="password")
    if st.button("Entrar", use_container_width=True, type="primary"):
        a=hashlib.sha256((pwd or "").encode()).hexdigest(); b=hashlib.sha256(str(APP_PASSWORD).encode()).hexdigest()
        if pwd and a==b:
            st.session_state["authenticated"]=True; st.rerun()
        st.error("Senha incorreta.")
    st.stop()
password_gate()

TABLES=["profile","diet_plan","meal_log","manual_workout","manual_exercise"]
def using_supabase(): return bool(SUPABASE_URL and SUPABASE_KEY)
def supa_headers(prefer=None):
    h={"apikey":SUPABASE_KEY,"Authorization":f"Bearer {SUPABASE_KEY}","Content-Type":"application/json"}
    if prefer: h["Prefer"]=prefer
    return h
def supa_url(table): return f"{SUPABASE_URL.rstrip('/')}/rest/v1/{table}"

def init_local_db():
    con=sqlite3.connect(LOCAL_DB); c=con.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS profile (id TEXT PRIMARY KEY, sex TEXT, age INTEGER, height_cm REAL, activity_factor REAL, gym_met REAL, target_deficit REAL, updated_at TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS diet_plan (id INTEGER PRIMARY KEY AUTOINCREMENT, meal_name TEXT, description TEXT, kcal REAL, protein REAL, carbs REAL, fat REAL)")
    c.execute("CREATE TABLE IF NOT EXISTS meal_log (id INTEGER PRIMARY KEY AUTOINCREMENT, eaten_at TEXT, meal_name TEXT, description TEXT, kcal REAL, protein REAL, carbs REAL, fat REAL, source TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS manual_workout (id INTEGER PRIMARY KEY AUTOINCREMENT, workout_date TEXT, title TEXT, duration_min REAL, intensity TEXT, notes TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS manual_exercise (id INTEGER PRIMARY KEY AUTOINCREMENT, workout_id INTEGER, exercise TEXT, muscle TEXT, sets_count INTEGER, reps INTEGER, weight_kg REAL)")
    con.commit(); con.close()
if not using_supabase(): init_local_db()

def db_select(table, order=None, limit=None):
    if using_supabase():
        params={"select":"*"}
        if order: params["order"]=order
        if limit: params["limit"]=str(limit)
        r=requests.get(supa_url(table),headers=supa_headers(),params=params,timeout=20); r.raise_for_status(); return r.json()
    con=sqlite3.connect(LOCAL_DB); q=f"SELECT * FROM {table}"
    if order:
        col,direction=order.split(".",1); q+=f" ORDER BY {col} {'DESC' if direction.lower()=='desc' else 'ASC'}"
    if limit: q+=f" LIMIT {int(limit)}"
    df=pd.read_sql_query(q,con); con.close(); return df.to_dict("records")

def db_insert(table,row):
    if using_supabase():
        r=requests.post(supa_url(table),headers=supa_headers("return=representation"),json=row,timeout=20); r.raise_for_status(); data=r.json(); return data[0] if data else row
    con=sqlite3.connect(LOCAL_DB); cols=list(row.keys()); marks=",".join(["?"]*len(cols)); cur=con.cursor(); cur.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({marks})",[row[c] for c in cols]); new_id=cur.lastrowid; con.commit(); con.close(); out=dict(row); out["id"]=new_id; return out

def db_upsert_profile(row):
    row=dict(row); row["id"]="me"
    if using_supabase():
        r=requests.post(supa_url("profile"),headers=supa_headers("resolution=merge-duplicates,return=representation"),params={"on_conflict":"id"},json=row,timeout=20); r.raise_for_status(); return
    con=sqlite3.connect(LOCAL_DB)
    con.execute("""INSERT INTO profile (id,sex,age,height_cm,activity_factor,gym_met,target_deficit,updated_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET sex=excluded.sex,age=excluded.age,height_cm=excluded.height_cm,activity_factor=excluded.activity_factor,gym_met=excluded.gym_met,target_deficit=excluded.target_deficit,updated_at=excluded.updated_at""",("me",row.get("sex"),row.get("age"),row.get("height_cm"),row.get("activity_factor"),row.get("gym_met"),row.get("target_deficit"),row.get("updated_at")))
    con.commit(); con.close()
def all_backup(): return {t:db_select(t) for t in TABLES}

# Hevy API (optional)
def hevy_get(path,params=None):
    if not HEVY_API_KEY:return {}
    r=requests.get(f"{HEVY_BASE}{path}",headers={"api-key":HEVY_API_KEY,"accept":"application/json"},params=params or {},timeout=30)
    if r.status_code in (401,403): raise RuntimeError("A chave do Hevy foi recusada.")
    r.raise_for_status(); return r.json()
@st.cache_data(ttl=300,show_spinner=False)
def get_hevy_workouts():
    if not HEVY_API_KEY:return []
    rows=[]; page=1
    while True:
        data=hevy_get("/workouts",{"page":page,"pageSize":10}); batch=data.get("workouts",[]); rows.extend(batch); pc=data.get("page_count") or data.get("pageCount")
        if not batch or (pc and page>=pc) or len(batch)<10: break
        page+=1
        if page>500: break
    return rows
@st.cache_data(ttl=300,show_spinner=False)
def get_hevy_measurements():
    if not HEVY_API_KEY:return []
    rows=[]; page=1
    while True:
        data=hevy_get("/body_measurements",{"page":page,"pageSize":10}); batch=data.get("body_measurements",[]); rows.extend(batch); pc=data.get("page_count") or data.get("pageCount")
        if not batch or (pc and page>=pc) or len(batch)<10: break
        page+=1
        if page>500: break
    return rows

def dt(x): return pd.to_datetime(x,utc=True,errors="coerce")
def workout_code(title):
    t=str(title or "").strip().upper()
    for c in ("A","B","C"):
        if t==c or t.startswith(c+" ") or t.startswith("TREINO "+c): return c
    return None

def infer_muscle(name):
    n=str(name or "").lower(); rules=[(("supino","crucifixo","peck","voador"),"Peito"),(("puxada","pulldown","remada","barra fixa"),"Costas"),(("elevação lateral","elevacao lateral","desenvolvimento","ombro","crucifixo inverso"),"Ombros"),(("tríceps","triceps"),"Tríceps"),(("rosca","curl"),"Bíceps"),(("hack","leg press","extensora","agachamento","squat"),"Quadríceps"),(("flexora","stiff","rdl","romeno","deadlift"),"Posteriores"),(("panturrilha","calf"),"Panturrilhas"),(("abdominal","abdômen","abdomen","crunch"),"Abdômen"),(("encolhimento","shrug"),"Trapézio")]
    for keys,m in rules:
        if any(k in n for k in keys): return m
    return "Outros"

def hevy_workout_frames(raw):
    workouts=[]; sets=[]
    for w in raw:
        start,end=dt(w.get("start_time")),dt(w.get("end_time")); duration=(end-start).total_seconds()/60 if pd.notna(start) and pd.notna(end) else None; title=w.get("title","Treino")
        workouts.append({"date":start,"workout":title,"code":workout_code(title),"duration_min":duration,"intensity":"Hevy","source":"Hevy","id":str(w.get("id"))})
        for ex in w.get("exercises",[]) or []:
            name=ex.get("title") or ex.get("exercise_template_title") or ex.get("name") or "Exercício"; muscle=infer_muscle(name)
            for s in ex.get("sets",[]) or []:
                weight,reps=s.get("weight_kg"),s.get("reps"); volume=weight*reps if isinstance(weight,(int,float)) and isinstance(reps,int) else None; e1rm=weight*(1+reps/30) if isinstance(weight,(int,float)) and isinstance(reps,int) and reps>0 else None
                sets.append({"date":start,"workout":title,"exercise":name,"muscle":muscle,"weight_kg":weight,"reps":reps,"volume_kg":volume,"e1rm_kg":e1rm,"sets_count":1,"source":"Hevy"})
    return pd.DataFrame(workouts),pd.DataFrame(sets)

def manual_frames():
    w=pd.DataFrame(db_select("manual_workout",order="workout_date.asc")); e=pd.DataFrame(db_select("manual_exercise"))
    if w.empty:return pd.DataFrame(),pd.DataFrame()
    w["date"]=pd.to_datetime(w["workout_date"],utc=True,errors="coerce"); w["workout"]=w["title"]; w["code"]=w["title"].map(workout_code); w["source"]="Manual"; w["id"]=w["id"].astype(str); w=w[["date","workout","code","duration_min","intensity","source","id"]]
    if e.empty:return w,pd.DataFrame()
    e["workout_id"]=e["workout_id"].astype(str); merged=e.merge(w[["id","date","workout"]],left_on="workout_id",right_on="id",how="left")
    merged["volume_kg"]=pd.to_numeric(merged["weight_kg"],errors="coerce")*pd.to_numeric(merged["reps"],errors="coerce")*pd.to_numeric(merged["sets_count"],errors="coerce")
    merged["e1rm_kg"]=pd.to_numeric(merged["weight_kg"],errors="coerce")*(1+pd.to_numeric(merged["reps"],errors="coerce")/30); merged["source"]="Manual"
    return w,merged[["date","workout","exercise","muscle","weight_kg","reps","volume_kg","e1rm_kg","sets_count","source"]]

def get_profile():
    rows=db_select("profile"); return rows[0] if rows else {}
def current_weight(mdf):
    if not mdf.empty and "weight_kg" in mdf.columns:
        d=mdf[["date","weight_kg"]].dropna().sort_values("date")
        if not d.empty:return float(d.iloc[-1]["weight_kg"])
    return None
def mifflin_ree(weight,height,age,sex):
    if not all([weight,height,age,sex]):return None
    base=10*weight+6.25*height-5*age; return base+5 if sex=="Masculino" else base-161
def workout_met(intensity,profile_met):
    return {"Leve":3.5,"Moderada":5.0,"Vigorosa":6.0}.get(intensity,float(profile_met or 5.0))
def workout_calories(duration,weight,met):
    if not duration or not weight or not met:return 0.0
    return float(duration)*(float(met)*3.5*float(weight)/200)
def daily_energy_summary(day,profile,weight,wdf,meals):
    ree=mifflin_ree(weight,float(profile.get("height_cm") or 0),int(profile.get("age") or 0),profile.get("sex")); factor=float(profile.get("activity_factor") or 1.2); base=ree*factor if ree else None; exercise=0.0
    if not wdf.empty:
        x=wdf.copy(); x["local_date"]=pd.to_datetime(x["date"],utc=True).dt.tz_convert(None).dt.date; x=x[x["local_date"]==day]
        for _,r in x.iterrows(): exercise+=workout_calories(r.get("duration_min"),weight,workout_met(r.get("intensity"),profile.get("gym_met")))
    intake=0.0
    if not meals.empty:
        x=meals.copy(); x["eaten_at"]=pd.to_datetime(x["eaten_at"],errors="coerce"); x=x[x["eaten_at"].dt.date==day]; intake=pd.to_numeric(x["kcal"],errors="coerce").fillna(0).sum()
    total=(base+exercise) if base is not None else None; deficit=(total-intake) if total is not None and intake>0 else None
    return {"ree":ree,"base_expenditure":base,"exercise":exercise,"total_expenditure":total,"intake":float(intake),"deficit":deficit}
def deficit_assessment(deficit,intake,target):
    if deficit is None or intake<=0:return "info","Dados insuficientes","Registre o consumo do dia e complete o perfil para estimar o balanço energético."
    if intake<1000:return "bad","Consumo muito baixo para uma estimativa genérica","O valor registrado ficou abaixo de 1.000 kcal. Revise o registro e não use o painel como autorização para restrição extrema."
    if deficit<-150:return "info","Superávit estimado",f"Saldo aproximado de {abs(deficit):.0f} kcal acima do gasto."
    if deficit<150:return "info","Próximo da manutenção",f"Déficit estimado de {deficit:.0f} kcal."
    if deficit<=750:
        return ("good" if abs(deficit-float(target or 500))<=200 else "info"),"Déficit moderado estimado",f"Déficit aproximado de {deficit:.0f} kcal. Compare com peso, medidas, fome e desempenho ao longo de semanas."
    if deficit<=1000:return "warn","Déficit elevado estimado",f"Déficit aproximado de {deficit:.0f} kcal. Revise recuperação, fome, desempenho e aderência."
    return "bad","Déficit muito agressivo estimado",f"Déficit aproximado de {deficit:.0f} kcal. Não trate esta estimativa como meta automática."

def preset_dates(label):
    today=date.today(); mapping={"Hoje":0,"7 dias":7,"14 dias":14,"30 dias":30,"60 dias":60,"90 dias":90,"180 dias":180,"365 dias":365}
    if label=="Tudo":return None,None
    days=mapping[label]; return (today if days==0 else today-timedelta(days=days-1)),today
def filter_dates(df,start,end,col="date"):
    if df.empty or start is None:return df.copy()
    x=df.copy(); d=pd.to_datetime(x[col],errors="coerce",utc=True); return x[(d.dt.date>=start)&(d.dt.date<=end)].copy()
def exercise_progress(sf):
    if sf.empty:return pd.DataFrame()
    w=sf.copy(); w["day"]=pd.to_datetime(w["date"],utc=True).dt.date; daily=w.groupby(["exercise","day"],as_index=False).agg(best_load=("weight_kg","max"),best_e1rm=("e1rm_kg","max"),volume=("volume_kg","sum"),sets=("sets_count","sum")); rows=[]
    for ex,g in daily.groupby("exercise"):
        g=g.sort_values("day")
        if len(g)<2:continue
        a,b=g.iloc[0],g.iloc[-1]; pct=None
        if pd.notna(a["best_e1rm"]) and a["best_e1rm"] not in (0,None) and pd.notna(b["best_e1rm"]): pct=(b["best_e1rm"]-a["best_e1rm"])/a["best_e1rm"]*100
        rows.append({"exercise":ex,"sessions":len(g),"e1rm_start":a["best_e1rm"],"e1rm_now":b["best_e1rm"],"change_pct":pct})
    return pd.DataFrame(rows)
def weekly_adherence(wf):
    if wf.empty:return pd.DataFrame()
    x=wf.copy(); x["week"]=pd.to_datetime(x["date"],utc=True).dt.tz_convert(None).dt.to_period("W-MON").astype(str); rows=[]
    for week,g in x.groupby("week"):
        counts=g["code"].value_counts().to_dict(); done=sum(min(counts.get(c,0),target) for c,target in WEEKLY_PLAN.items()); rows.append({"week":week,"A":counts.get("A",0),"B":counts.get("B",0),"C":counts.get("C",0),"aderencia_pct":done/5*100})
    return pd.DataFrame(rows)

def groq_chat(system,user,max_tokens=2200):
    if not GROQ_API_KEY:raise RuntimeError("GROQ_API_KEY não configurada.")
    r=requests.post(GROQ_URL,headers={"Authorization":f"Bearer {GROQ_API_KEY}","Content-Type":"application/json"},json={"model":GROQ_MODEL,"messages":[{"role":"system","content":system},{"role":"user","content":user}],"temperature":0.15,"max_completion_tokens":max_tokens},timeout=60); r.raise_for_status(); return r.json()["choices"][0]["message"]["content"]
def estimate_meal_ai(description):
    system="Você estima nutrição de refeições a partir de descrições textuais. A estimativa é aproximada. Responda SOMENTE JSON válido, sem markdown."
    user=f'''Estime a refeição abaixo. Considere porções informadas; se faltarem quantidades, faça uma estimativa conservadora e aumente a incerteza. Retorne exatamente: {{"kcal": número, "protein": número, "carbs": número, "fat": número, "confidence": "baixa|media|alta", "note": "texto curto"}}\nREFEIÇÃO:\n{description}'''
    raw=groq_chat(system,user,max_tokens=500).strip().replace("```json","").replace("```","").strip(); return json.loads(raw)
def integrated_ai_payload(wf,sf,meals,profile,energy,start,end):
    prog=exercise_progress(sf); payload={"periodo":{"inicio":str(start),"fim":str(end)},"treinos":{"quantidade":len(wf),"duracao_media":round(float(pd.to_numeric(wf.get("duration_min"),errors="coerce").dropna().mean()),1) if not wf.empty else None,"aderencia":weekly_adherence(wf).tail(8).to_dict("records") if not wf.empty else []},"performance":[],"nutricao":{"media_kcal_registrada":None,"dias_registrados":0,"balanco_hoje":energy,"meta_deficit":profile.get("target_deficit")}}
    if not prog.empty:
        for _,r in prog.sort_values("change_pct",ascending=False).head(20).iterrows():payload["performance"].append({"exercicio":r["exercise"],"sessoes":int(r["sessions"]),"variacao_e1rm_pct":None if pd.isna(r["change_pct"]) else round(float(r["change_pct"]),1)})
    if not meals.empty:
        m=meals.copy(); m["eaten_at"]=pd.to_datetime(m["eaten_at"],errors="coerce"); daily=m.groupby(m["eaten_at"].dt.date)["kcal"].sum(); payload["nutricao"]["media_kcal_registrada"]=round(float(daily.mean()),0) if not daily.empty else None; payload["nutricao"]["dias_registrados"]=int(len(daily))
    return payload

try: raw_hevy=get_hevy_workouts(); raw_measurements=get_hevy_measurements()
except Exception as e: st.warning(f"Hevy indisponível: {e}"); raw_hevy=[]; raw_measurements=[]
h_wdf,h_sdf=hevy_workout_frames(raw_hevy); m_wdf,m_sdf=manual_frames(); wdf=pd.concat([h_wdf,m_wdf],ignore_index=True) if not h_wdf.empty or not m_wdf.empty else pd.DataFrame(); sdf=pd.concat([h_sdf,m_sdf],ignore_index=True) if not h_sdf.empty or not m_sdf.empty else pd.DataFrame(); mdf=pd.DataFrame(raw_measurements)
if not mdf.empty and "date" in mdf.columns: mdf["date"]=pd.to_datetime(mdf["date"],errors="coerce")
meals=pd.DataFrame(db_select("meal_log",order="eaten_at.asc")); plan=pd.DataFrame(db_select("diet_plan")); profile=get_profile(); weight=current_weight(mdf)

c1,c2=st.columns([5,1])
with c1:
    st.title("💪 Minha Evolução"); src=[]
    if HEVY_API_KEY:src.append("Hevy")
    if not m_wdf.empty:src.append("Manual")
    st.caption("Treino • nutrição • balanço energético • IA"+(f" · dados: {' + '.join(src)}" if src else ""))
with c2:
    if st.button("Sair",use_container_width=True):st.session_state.pop("authenticated",None);st.rerun()

period_choice=st.selectbox("Período da análise",["Hoje","7 dias","14 dias","30 dias","60 dias","90 dias","180 dias","365 dias","Personalizado","Tudo"],index=3)
if period_choice=="Personalizado":
    p1,p2=st.columns(2); start=p1.date_input("De",value=date.today()-timedelta(days=29)); end=p2.date_input("Até",value=date.today())
else:start,end=preset_dates(period_choice)
wf=filter_dates(wdf,start,end) if not wdf.empty else wdf; sf=filter_dates(sdf,start,end) if not sdf.empty else sdf
if not meals.empty and start is not None:
    meals_period=meals.copy(); meals_period["eaten_at"]=pd.to_datetime(meals_period["eaten_at"],errors="coerce"); meals_period=meals_period[(meals_period["eaten_at"].dt.date>=start)&(meals_period["eaten_at"].dt.date<=end)]
else:meals_period=meals.copy()
nav=st.radio("Navegação",["Hoje","Treinos","Nutrição","Evolução","IA","Dados"],horizontal=True,label_visibility="collapsed")
energy_today=daily_energy_summary(date.today(),profile,weight,wdf,meals)

if nav=="Hoje":
    st.subheader("Hoje"); target=float(profile.get("target_deficit") or 500); target_intake=energy_today["total_expenditure"]-target if energy_today["total_expenditure"] is not None else None
    k1,k2,k3,k4=st.columns(4); k1.metric("Consumido",f"{energy_today['intake']:.0f} kcal" if energy_today["intake"] else "—"); k2.metric("Gasto estimado",f"{energy_today['total_expenditure']:.0f} kcal" if energy_today["total_expenditure"] else "—"); k3.metric("Treino hoje",f"{energy_today['exercise']:.0f} kcal" if energy_today["exercise"] else "—"); k4.metric("Meta ingestão",f"{target_intake:.0f} kcal" if target_intake else "—")
    cls,title,text=deficit_assessment(energy_today["deficit"],energy_today["intake"],target); st.markdown(f'<div class="app-card {cls}"><b>{title}</b><br>{text}</div>',unsafe_allow_html=True)
    if energy_today["ree"]:
        x1,x2,x3=st.columns(3); x1.metric("Repouso estimado",f"{energy_today['ree']:.0f} kcal/d"); x2.metric("Base do dia",f"{energy_today['base_expenditure']:.0f} kcal/d"); x3.metric("Déficit meta",f"{target:.0f} kcal/d")
    week_start=date.today()-timedelta(days=date.today().weekday()); workouts_week=filter_dates(wdf,week_start,date.today()) if not wdf.empty else pd.DataFrame(); a1,a2,a3=st.columns(3); a1.metric("Treinos na semana",len(workouts_week)); a2.metric("Duração média",f"{pd.to_numeric(workouts_week['duration_min'],errors='coerce').mean():.0f} min" if not workouts_week.empty else "—"); a3.metric("Peso atual",f"{weight:.1f} kg" if weight else "—")
    if not meals.empty:
        temp=meals.copy(); temp["eaten_at"]=pd.to_datetime(temp["eaten_at"],errors="coerce"); today_meals=temp[temp["eaten_at"].dt.date==date.today()]
        if not today_meals.empty:
            st.subheader("Refeições de hoje"); show=today_meals[["meal_name","kcal","protein","carbs","fat"]].copy(); show.columns=["Refeição","kcal","Proteína","Carbo","Gordura"]; st.dataframe(show,use_container_width=True,hide_index=True)

elif nav=="Treinos":
    st.subheader("Treinos"); t1,t2=st.tabs(["Análise","Cadastro manual"])
    with t1:
        if wf.empty:st.info("Nenhum treino no período selecionado.")
        else:
            a1,a2,a3=st.columns(3); a1.metric("Sessões",len(wf)); a2.metric("Minutos/sessão",f"{pd.to_numeric(wf['duration_min'],errors='coerce').mean():.0f}"); a3.metric("Fonte","Hevy + Manual" if {"Hevy","Manual"}.issubset(set(wf["source"])) else str(wf["source"].iloc[0]))
            adh=weekly_adherence(wf)
            if not adh.empty:
                fig=px.line(adh,x="week",y="aderencia_pct",markers=True,title="Aderência ao B-A-C-B-A"); fig.update_layout(height=300,margin=dict(l=10,r=10,t=45,b=10),yaxis_range=[0,105]); st.plotly_chart(fig,use_container_width=True)
            if not sf.empty:
                by=sf.groupby("muscle",as_index=False).agg(series=("sets_count","sum"),volume=("volume_kg","sum")); by=by[by["muscle"]!="Outros"].sort_values("series",ascending=False); fig=px.bar(by,x="muscle",y="series",title="Séries por grupo muscular"); fig.update_layout(height=310,margin=dict(l=10,r=10,t=45,b=10)); st.plotly_chart(fig,use_container_width=True)
                prog=exercise_progress(sf)
                if not prog.empty:
                    st.subheader("Quem mais evoluiu"); show=prog.sort_values("change_pct",ascending=False).head(10)[["exercise","sessions","e1rm_start","e1rm_now","change_pct"]].copy(); show.columns=["Exercício","Sessões","1RM inicial","1RM atual","Variação %"]; st.dataframe(show,use_container_width=True,hide_index=True)
    with t2:
        st.caption("Use este cadastro quando não houver integração com aplicativo ou para registrar uma sessão fora do Hevy.")
        with st.form("mw",clear_on_submit=True):
            d=st.date_input("Data",value=date.today()); title=st.text_input("Nome do treino",placeholder="Ex.: B - Costas e bíceps"); duration=st.number_input("Duração (min)",1,300,60); intensity=st.selectbox("Intensidade",["Leve","Moderada","Vigorosa"],index=1); notes=st.text_area("Observações"); save=st.form_submit_button("Salvar treino",use_container_width=True)
            if save and title:db_insert("manual_workout",{"workout_date":str(d),"title":title,"duration_min":float(duration),"intensity":intensity,"notes":notes});st.success("Treino salvo.");st.rerun()
        recent=pd.DataFrame(db_select("manual_workout",order="workout_date.desc",limit=20))
        if not recent.empty:
            labels={int(r["id"]):f"{r['workout_date']} · {r['title']}" for _,r in recent.iterrows()}; selected_id=st.selectbox("Adicionar exercício ao treino",list(labels.keys()),format_func=lambda x:labels[x])
            with st.form("me",clear_on_submit=True):
                ex=st.text_input("Exercício"); muscle=st.selectbox("Grupo muscular",["Peito","Costas","Ombros","Bíceps","Tríceps","Quadríceps","Posteriores","Panturrilhas","Abdômen","Trapézio","Outros"]); s=st.number_input("Séries",1,20,3); reps=st.number_input("Repetições médias",1,100,10); kg=st.number_input("Carga (kg)",0.0,1000.0,0.0,step=1.0); save_ex=st.form_submit_button("Salvar exercício",use_container_width=True)
                if save_ex and ex:db_insert("manual_exercise",{"workout_id":int(selected_id),"exercise":ex,"muscle":muscle,"sets_count":int(s),"reps":int(reps),"weight_kg":float(kg)});st.success("Exercício salvo.");st.rerun()

elif nav=="Nutrição":
    st.subheader("Nutrição"); n1,n2,n3=st.tabs(["Hoje / diário","Dieta planejada","Metabolismo"])
    with n1:
        meal_name=st.selectbox("Refeição",["Café da manhã","Lanche manhã","Almoço","Lanche tarde","Jantar","Ceia","Outra"]); description=st.text_area("O que você consumiu?",placeholder="Ex.: 150 g arroz, 100 g feijão, 150 g frango grelhado e salada")
        if st.button("✨ Estimar calorias e macros com IA",use_container_width=True):
            if not description:st.warning("Descreva a refeição primeiro.")
            elif not GROQ_API_KEY:st.warning("GROQ_API_KEY não configurada.")
            else:
                try:
                    with st.spinner("Estimando a refeição..."):st.session_state["meal_est"]=estimate_meal_ai(description)
                except Exception as e:st.error(f"Não foi possível estimar: {e}")
        est=st.session_state.get("meal_est",{})
        if est:st.markdown(f'<div class="app-card info"><b>Estimativa IA</b><br>{est.get("kcal",0):.0f} kcal · {est.get("protein",0):.0f} g proteína · {est.get("carbs",0):.0f} g carbo · {est.get("fat",0):.0f} g gordura<div class="small">Confiança: {est.get("confidence","—")} · {est.get("note","")}</div></div>',unsafe_allow_html=True)
        with st.form("meal_save"):
            m1,m2=st.columns(2); eaten_day=m1.date_input("Data",value=date.today()); eaten_time=m2.time_input("Hora",value=datetime.now().time().replace(second=0,microsecond=0)); kcal=st.number_input("Calorias",0.0,10000.0,float(est.get("kcal",0) or 0),step=10.0); p1,p2,p3=st.columns(3); protein=p1.number_input("Proteína (g)",0.0,1000.0,float(est.get("protein",0) or 0)); carbs=p2.number_input("Carbo (g)",0.0,1500.0,float(est.get("carbs",0) or 0)); fat=p3.number_input("Gordura (g)",0.0,1000.0,float(est.get("fat",0) or 0)); save=st.form_submit_button("Salvar refeição consumida",use_container_width=True)
            if save and description:db_insert("meal_log",{"eaten_at":datetime.combine(eaten_day,eaten_time).isoformat(),"meal_name":meal_name,"description":description,"kcal":float(kcal),"protein":float(protein),"carbs":float(carbs),"fat":float(fat),"source":"IA" if est else "Manual"});st.session_state.pop("meal_est",None);st.success("Refeição salva.");st.rerun()
        if not meals_period.empty:
            x=meals_period.copy();x["eaten_at"]=pd.to_datetime(x["eaten_at"],errors="coerce");daily=x.groupby(x["eaten_at"].dt.date,as_index=False).agg(kcal=("kcal","sum"),protein=("protein","sum"),carbs=("carbs","sum"),fat=("fat","sum"));fig=px.bar(daily,x="eaten_at",y="kcal",title="Calorias registradas por dia");fig.update_layout(height=300,margin=dict(l=10,r=10,t=45,b=10));st.plotly_chart(fig,use_container_width=True)
    with n2:
        with st.form("diet_plan",clear_on_submit=True):
            name=st.text_input("Nome da refeição",placeholder="Ex.: Almoço");desc=st.text_area("Composição planejada");kcal=st.number_input("kcal planejadas",0.0,5000.0,0.0,step=10.0);a,b,c=st.columns(3);prot=a.number_input("Proteína",0.0,500.0,0.0);carb=b.number_input("Carbo",0.0,1000.0,0.0);fat=c.number_input("Gordura",0.0,500.0,0.0);save=st.form_submit_button("Adicionar à dieta",use_container_width=True)
            if save and name:db_insert("diet_plan",{"meal_name":name,"description":desc,"kcal":float(kcal),"protein":float(prot),"carbs":float(carb),"fat":float(fat)});st.rerun()
        plan_now=pd.DataFrame(db_select("diet_plan"))
        if not plan_now.empty:
            st.metric("Total diário planejado",f"{pd.to_numeric(plan_now['kcal'],errors='coerce').fillna(0).sum():.0f} kcal");st.dataframe(plan_now[["meal_name","description","kcal","protein","carbs","fat"]],use_container_width=True,hide_index=True)
            if not meals.empty:
                tl=meals.copy();tl["eaten_at"]=pd.to_datetime(tl["eaten_at"],errors="coerce");tl=tl[tl["eaten_at"].dt.date==date.today()]
                if not tl.empty:
                    actual=tl.groupby("meal_name",as_index=False)["kcal"].sum().rename(columns={"kcal":"Consumido"});planned=plan_now.groupby("meal_name",as_index=False)["kcal"].sum().rename(columns={"kcal":"Planejado"});comp=planned.merge(actual,on="meal_name",how="outer").fillna(0);comp["Diferença"]=comp["Consumido"]-comp["Planejado"];comp.columns=["Refeição","Planejado","Consumido","Diferença"];st.subheader("Planejado x consumido hoje");st.dataframe(comp,use_container_width=True,hide_index=True)
    with n3:
        st.caption("Repouso: Mifflin–St Jeor. Gasto total e treino são aproximações, não calorimetria."); sex_opts=["Masculino","Feminino"];default=profile.get("sex") if profile.get("sex") in sex_opts else "Masculino"
        with st.form("profile"):
            sex=st.selectbox("Sexo usado na equação",sex_opts,index=sex_opts.index(default));age=st.number_input("Idade",18,100,int(profile.get("age") or 35));height=st.number_input("Altura (cm)",120.0,230.0,float(profile.get("height_cm") or 175.0),step=.5);activity_factor=st.select_slider("Rotina fora do treino",options=[1.20,1.25,1.30,1.35,1.40,1.45],value=float(profile.get("activity_factor") or 1.25),format_func=lambda x:{1.20:"Muito sedentária",1.25:"Sedentária",1.30:"Levemente ativa",1.35:"Ativa",1.40:"Bem ativa",1.45:"Muito ativa"}[x]);gym_met=st.select_slider("Intensidade média da musculação",options=[3.5,5.0,6.0],value=float(profile.get("gym_met") or 5.0),format_func=lambda x:{3.5:"Leve/variada",5.0:"Moderada",6.0:"Vigorosa"}[x]);target_deficit=st.number_input("Meta de déficit diário (kcal)",0,1000,int(profile.get("target_deficit") or 500),step=50);save=st.form_submit_button("Salvar perfil metabólico",use_container_width=True)
            if save:db_upsert_profile({"sex":sex,"age":int(age),"height_cm":float(height),"activity_factor":float(activity_factor),"gym_met":float(gym_met),"target_deficit":float(target_deficit),"updated_at":datetime.now(timezone.utc).isoformat()});st.success("Perfil salvo.");st.rerun()
        if weight:
            ree=mifflin_ree(weight,float(profile.get("height_cm") or 0),int(profile.get("age") or 0),profile.get("sex"))
            if ree:
                c1,c2,c3=st.columns(3);c1.metric("Peso usado",f"{weight:.1f} kg");c2.metric("Repouso estimado",f"{ree:.0f} kcal/d");c3.metric("Meta déficit",f"{float(profile.get('target_deficit') or 500):.0f} kcal/d")

elif nav=="Evolução":
    st.subheader("Evolução");e1,e2,e3=st.tabs(["Corpo","Performance","Balanço energético"])
    with e1:
        if mdf.empty:st.info("Sem medidas corporais da API do Hevy.")
        else:
            available=[c for c in mdf.columns if c not in ("date","id") and pd.to_numeric(mdf[c],errors="coerce").notna().any()]
            if available:
                selected=st.selectbox("Medida",available,format_func=lambda x:x.replace("_"," ").title());d=filter_dates(mdf[["date",selected]].dropna().sort_values("date"),start,end)
                if not d.empty:fig=px.line(d,x="date",y=selected,markers=True,title="Tendência corporal");fig.update_layout(height=320,margin=dict(l=10,r=10,t=45,b=10));st.plotly_chart(fig,use_container_width=True)
    with e2:
        if sf.empty:st.info("Sem dados de exercícios no período.")
        else:
            exercise=st.selectbox("Exercício",sorted(sf["exercise"].dropna().unique()));x=sf[sf["exercise"]==exercise].copy();x["day"]=pd.to_datetime(x["date"],utc=True).dt.date;daily=x.groupby("day",as_index=False).agg(carga=("weight_kg","max"),e1rm=("e1rm_kg","max"),volume=("volume_kg","sum"),series=("sets_count","sum"));metric=st.selectbox("Indicador",["e1rm","carga","volume","series"]);fig=px.line(daily,x="day",y=metric,markers=True,title=f"{exercise} · {metric}");fig.update_layout(height=320,margin=dict(l=10,r=10,t=45,b=10));st.plotly_chart(fig,use_container_width=True)
    with e3:
        if meals.empty or not profile:st.info("Cadastre refeições e complete o perfil metabólico para acompanhar o balanço energético.")
        else:
            days=pd.date_range(start or (date.today()-timedelta(days=29)),end or date.today(),freq="D");rows=[]
            for day_ts in days:
                sm=daily_energy_summary(day_ts.date(),profile,weight,wdf,meals);rows.append({"Data":day_ts.date(),"Consumo":sm["intake"],"Gasto":sm["total_expenditure"],"Déficit":sm["deficit"]})
            energy_df=pd.DataFrame(rows);fig=px.line(energy_df,x="Data",y=["Consumo","Gasto"],markers=True,title="Consumo x gasto estimado");fig.update_layout(height=320,margin=dict(l=10,r=10,t=45,b=10));st.plotly_chart(fig,use_container_width=True);st.caption("Dias sem alimentação registrada aparecem com consumo zero; isso não significa jejum.")

elif nav=="IA":
    st.subheader("Análises por IA");st.caption("A IA interpreta dados agregados. Cálculos principais são feitos localmente pelo painel.")
    if not GROQ_API_KEY:st.warning("Configure `GROQ_API_KEY` nos Secrets.")
    else:
        mode=st.selectbox("Tipo de análise",["Geral","Hipertrofia","Recomposição corporal","Nutrição e déficit","Exercício específico"]);selected_ex=None
        if mode=="Exercício específico" and not sf.empty:selected_ex=st.selectbox("Exercício",sorted(sf["exercise"].dropna().unique()))
        if st.button("✨ Gerar análise completa",use_container_width=True,type="primary"):
            try:
                payload=integrated_ai_payload(wf,sf,meals_period,profile,energy_today,start,end)
                if selected_ex:
                    prog=exercise_progress(sf);payload["exercicio_foco"]=prog[prog["exercise"]==selected_ex].to_dict("records")
                focus={"Geral":"Integre treino, aderência, performance, alimentação e balanço energético.","Hipertrofia":"Priorize progressão de carga/1RM estimado, volume, frequência e recuperação.","Recomposição corporal":"Cruze desempenho com peso/medidas e balanço energético sem afirmar perda localizada de gordura.","Nutrição e déficit":"Analise ingestão registrada, dieta planejada, gasto estimado e sustentabilidade do déficit. Não prescreva dieta clínica.","Exercício específico":"Analise apenas o exercício selecionado e sua tendência."}[mode]
                system="Você é um analista de dados de treino e nutrição para acompanhamento pessoal. Use somente os dados fornecidos. Não diagnostique doenças, não prescreva medicamentos, não trate estimativas de calorias como exatas e não recomende restrição extrema. Quando faltarem dados, diga explicitamente. Responda em português do Brasil."
                user=f'''FOCO: {focus}\n\nEstruture: 1. Resumo executivo 2. O que está evoluindo bem 3. Pontos de atenção 4. Análises individuais relevantes 5. Integração treino + alimentação + corpo 6. Próximos 14 dias: prioridades objetivas 7. Dados que faltam\n\nDADOS:\n{json.dumps(payload,ensure_ascii=False,default=str)}'''
                with st.spinner("Analisando seus dados..."):st.session_state["ai_analysis"]=groq_chat(system,user)
            except Exception as e:st.error(f"Erro na análise: {e}")
        if st.session_state.get("ai_analysis"):
            st.markdown(st.session_state["ai_analysis"]);st.download_button("Baixar análise",st.session_state["ai_analysis"],file_name="analise_evolucao.txt",mime="text/plain",use_container_width=True)

elif nav=="Dados":
    st.subheader("Dados e configuração");s1,s2,s3=st.columns(3);s1.metric("Hevy API","Conectada" if HEVY_API_KEY else "Manual");s2.metric("IA Groq","Ativa" if GROQ_API_KEY else "Desativada");s3.metric("Banco","Supabase" if using_supabase() else "Local")
    if not using_supabase():st.warning("Você está usando armazenamento local. No Streamlit Community Cloud, arquivos gerados em execução não têm persistência garantida. Para diário nutricional e treinos manuais, configure Supabase.")
    backup_json=json.dumps(all_backup(),ensure_ascii=False,indent=2,default=str);st.download_button("⬇️ Baixar backup JSON",backup_json,file_name=f"backup_evolucao_{date.today()}.json",mime="application/json",use_container_width=True)
    st.subheader("Secrets esperados");st.code('''HEVY_API_KEY = "opcional"\nGROQ_API_KEY = "opcional, necessário para IA"\nAPP_PASSWORD = "obrigatório"\nSUPABASE_URL = "https://SEU-PROJETO.supabase.co"\nSUPABASE_KEY = "SUA_CHAVE"''',language="toml")
    if st.button("🔄 Limpar cache das APIs",use_container_width=True):st.cache_data.clear();st.rerun()

st.divider();st.caption("Estimativas de calorias, gasto energético e metabolismo servem para acompanhar tendências. Não substituem calorimetria, avaliação nutricional ou orientação médica.")
