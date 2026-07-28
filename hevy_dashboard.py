
import os, json, math
import requests
import pandas as pd
import streamlit as st
import plotly.express as px

HEVY_BASE = "https://api.hevyapp.com/v1"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

st.set_page_config(
    page_title="Minha Evolução Pro",
    page_icon="💪",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
.block-container {padding-top: 1rem; padding-bottom: 3rem; max-width: 1180px;}
[data-testid="stMetric"] {
    border: 1px solid rgba(128,128,128,.18);
    background: rgba(128,128,128,.035);
    padding: 12px 14px;
    border-radius: 16px;
}
[data-testid="stMetricValue"] {font-weight: 700;}
h1 {font-size: 1.9rem !important;}
h2 {font-size: 1.32rem !important;}
h3 {font-size: 1.08rem !important;}
div[data-testid="stTabs"] button {font-weight: 600;}
.insight {
  border: 1px solid rgba(128,128,128,.18);
  border-radius: 14px;
  padding: 12px 14px;
  margin-bottom: 8px;
}
.good {border-left: 4px solid #2e7d32;}
.warn {border-left: 4px solid #f9a825;}
.info {border-left: 4px solid #1976d2;}
@media (max-width: 700px) {
    .block-container {padding-left: .65rem; padding-right: .65rem;}
    [data-testid="stMetricValue"] {font-size: 1.18rem;}
}
</style>
""", unsafe_allow_html=True)

def secret(name):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name)

HEVY_API_KEY = secret("HEVY_API_KEY")
GROQ_API_KEY = secret("GROQ_API_KEY")

if not HEVY_API_KEY:
    st.error("HEVY_API_KEY não configurada nos Secrets.")
    st.stop()

def hevy_get(path, params=None):
    r = requests.get(
        f"{HEVY_BASE}{path}",
        headers={"api-key": HEVY_API_KEY, "accept": "application/json"},
        params=params or {},
        timeout=30,
    )
    if r.status_code in (401, 403):
        raise RuntimeError("A chave da API Hevy foi recusada.")
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=300, show_spinner=False)
def get_all_workouts():
    rows, page = [], 1
    while True:
        data = hevy_get("/workouts", {"page": page, "pageSize": 10})
        batch = data.get("workouts", [])
        rows.extend(batch)
        page_count = data.get("page_count") or data.get("pageCount")
        if not batch or (page_count and page >= page_count) or len(batch) < 10:
            break
        page += 1
        if page > 500:
            break
    return rows

@st.cache_data(ttl=300, show_spinner=False)
def get_all_measurements():
    rows, page = [], 1
    while True:
        data = hevy_get("/body_measurements", {"page": page, "pageSize": 10})
        batch = data.get("body_measurements", [])
        rows.extend(batch)
        page_count = data.get("page_count") or data.get("pageCount")
        if not batch or (page_count and page >= page_count) or len(batch) < 10:
            break
        page += 1
        if page > 500:
            break
    return rows

def dt(x):
    return pd.to_datetime(x, utc=True, errors="coerce")

def workout_df(workouts):
    out = []
    for w in workouts:
        start, end = dt(w.get("start_time")), dt(w.get("end_time"))
        dur = (end-start).total_seconds()/60 if pd.notna(start) and pd.notna(end) else None
        out.append({
            "date": start,
            "workout": w.get("title", "Treino"),
            "duration_min": dur,
            "exercise_count": len(w.get("exercises", []) or []),
            "id": w.get("id"),
        })
    return pd.DataFrame(out)

def sets_df(workouts):
    out = []
    for w in workouts:
        date = dt(w.get("start_time"))
        workout_title = w.get("title", "Treino")
        for ex in w.get("exercises", []) or []:
            name = ex.get("title") or ex.get("exercise_template_title") or ex.get("name") or ex.get("exercise_template_id", "Exercício")
            exid = ex.get("exercise_template_id")
            for s in ex.get("sets", []) or []:
                weight, reps = s.get("weight_kg"), s.get("reps")
                volume = weight * reps if isinstance(weight,(int,float)) and isinstance(reps,int) else None
                e1rm = weight*(1+reps/30) if isinstance(weight,(int,float)) and isinstance(reps,int) and reps > 0 else None
                out.append({
                    "date": date,
                    "workout": workout_title,
                    "exercise": name,
                    "exercise_id": exid,
                    "weight_kg": weight,
                    "reps": reps,
                    "volume_kg": volume,
                    "e1rm_kg": e1rm,
                    "rpe": s.get("rpe"),
                    "set_type": str(s.get("type") or s.get("set_type") or "normal").lower(),
                })
    return pd.DataFrame(out)

LABELS = {
    "weight_kg":"Peso", "lean_mass_kg":"Massa magra", "fat_percent":"Gordura corporal",
    "neck_cm":"Pescoço", "shoulder_cm":"Ombros", "chest_cm":"Tórax",
    "left_bicep_cm":"Braço E", "right_bicep_cm":"Braço D",
    "left_forearm_cm":"Antebraço E", "right_forearm_cm":"Antebraço D",
    "abdomen":"Abdômen", "waist":"Cintura", "hips":"Quadril",
    "left_thigh":"Coxa E", "right_thigh":"Coxa D",
    "left_calf":"Panturrilha E", "right_calf":"Panturrilha D",
}
UNITS = {"weight_kg":"kg", "lean_mass_kg":"kg", "fat_percent":"%"}

def format_value(v, key):
    if v is None or pd.isna(v):
        return "—"
    return f"{float(v):.1f} {UNITS.get(key,'cm')}"

def safe_delta(df, col):
    if df.empty or col not in df.columns:
        return None
    d = df[["date",col]].dropna().sort_values("date")
    if len(d) < 2:
        return None
    return float(d.iloc[-1][col]-d.iloc[0][col])

def pct_change(a,b):
    if a is None or b is None or pd.isna(a) or pd.isna(b) or a == 0:
        return None
    return (b-a)/a*100

def latest_nonnull(df, col):
    if df.empty or col not in df.columns:
        return None
    x = df[["date",col]].dropna().sort_values("date")
    return None if x.empty else float(x.iloc[-1][col])

def first_nonnull(df, col):
    if df.empty or col not in df.columns:
        return None
    x = df[["date",col]].dropna().sort_values("date")
    return None if x.empty else float(x.iloc[0][col])

def period_filter(wdf, sdf, mdf, days):
    if days == "Tudo":
        return wdf.copy(), sdf.copy(), mdf.copy()
    utc_cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=int(days))
    naive_cutoff = pd.Timestamp.now() - pd.Timedelta(days=int(days))
    wf = wdf[wdf["date"] >= utc_cutoff].copy() if not wdf.empty else wdf
    sf = sdf[sdf["date"] >= utc_cutoff].copy() if not sdf.empty else sdf
    mf = mdf[mdf["date"] >= naive_cutoff].copy() if not mdf.empty else mdf
    return wf, sf, mf

def exercise_progress(sf):
    if sf.empty:
        return pd.DataFrame()
    work = sf[~sf["set_type"].isin(["warmup","aquecimento"])].copy()
    if work.empty:
        return pd.DataFrame()
    work["day"] = work["date"].dt.date
    daily = work.groupby(["exercise","day"], as_index=False).agg(
        best_load=("weight_kg","max"),
        best_e1rm=("e1rm_kg","max"),
        volume=("volume_kg","sum"),
        reps=("reps","sum"),
    )
    rows = []
    for ex, g in daily.groupby("exercise"):
        g = g.sort_values("day")
        if len(g) < 2:
            continue
        a, b = g.iloc[0], g.iloc[-1]
        rows.append({
            "exercise": ex,
            "sessions": len(g),
            "e1rm_start": a["best_e1rm"],
            "e1rm_now": b["best_e1rm"],
            "e1rm_change_pct": pct_change(a["best_e1rm"], b["best_e1rm"]),
            "load_start": a["best_load"],
            "load_now": b["best_load"],
        })
    return pd.DataFrame(rows)

def deterministic_insights(wf, sf, mf):
    insights = []
    if not wf.empty:
        span_days = max(1, (wf["date"].max()-wf["date"].min()).days + 1)
        avg_week = len(wf)/(span_days/7)
        if avg_week >= 4.5:
            insights.append(("good","Consistência alta",f"Média aproximada de {avg_week:.1f} treinos por semana."))
        elif avg_week >= 3:
            insights.append(("info","Consistência razoável",f"Média aproximada de {avg_week:.1f} treinos por semana."))
        else:
            insights.append(("warn","Frequência abaixo do planejado",f"Média aproximada de {avg_week:.1f} treinos por semana."))

    if not wf.empty and wf["duration_min"].notna().any():
        avg = wf["duration_min"].dropna().mean()
        if 45 <= avg <= 65:
            insights.append(("good","Duração bem alinhada",f"Seus treinos duram em média {avg:.0f} min."))
        elif avg < 40:
            insights.append(("info","Treinos curtos",f"Média de {avg:.0f} min. Confira se o volume planejado está sendo concluído."))
        else:
            insights.append(("warn","Sessões longas",f"Média de {avg:.0f} min. Pode haver espera excessiva ou volume alto."))

    for col, name in [("waist","Cintura"),("abdomen","Abdômen"),("weight_kg","Peso")]:
        d = safe_delta(mf,col)
        if d is not None:
            if col in ("waist","abdomen"):
                cls = "good" if d < 0 else ("warn" if d > 0.5 else "info")
            else:
                cls = "info"
            insights.append((cls,f"Evolução de {name}",f"Variação no período: {d:+.1f} {UNITS.get(col,'cm')}."))

    prog = exercise_progress(sf)
    if not prog.empty and prog["e1rm_change_pct"].notna().any():
        p = prog.dropna(subset=["e1rm_change_pct"])
        improving = (p["e1rm_change_pct"] > 2).sum()
        declining = (p["e1rm_change_pct"] < -2).sum()
        if improving > 0:
            insights.append(("good","Performance em alta",f"{improving} exercícios melhoraram o 1RM estimado em mais de 2%."))
        if declining >= 2:
            insights.append(("warn","Queda em alguns exercícios",f"{declining} exercícios caíram mais de 2% no 1RM estimado."))

    return insights

def build_ai_payload(wf, sf, mf, days):
    prog = exercise_progress(sf)
    payload = {
        "periodo": str(days),
        "treinos": {
            "quantidade": int(len(wf)),
            "duracao_media_min": round(float(wf["duration_min"].dropna().mean()),1) if not wf.empty and wf["duration_min"].notna().any() else None,
            "frequencia_por_treino": wf["workout"].value_counts().head(10).to_dict() if not wf.empty else {}
        },
        "medidas": {},
        "performance": [],
    }
    for col, label in LABELS.items():
        if col in mf.columns and mf[col].notna().any():
            start = first_nonnull(mf,col)
            end = latest_nonnull(mf,col)
            payload["medidas"][label] = {
                "inicial": start,
                "atual": end,
                "variacao": None if start is None or end is None else round(end-start,2),
                "unidade": UNITS.get(col,"cm")
            }
    if not prog.empty:
        for _, r in prog.sort_values("e1rm_change_pct", ascending=False).head(30).iterrows():
            payload["performance"].append({
                "exercicio": r["exercise"],
                "sessoes": int(r["sessions"]),
                "e1rm_inicial": None if pd.isna(r["e1rm_start"]) else round(float(r["e1rm_start"]),1),
                "e1rm_atual": None if pd.isna(r["e1rm_now"]) else round(float(r["e1rm_now"]),1),
                "variacao_pct": None if pd.isna(r["e1rm_change_pct"]) else round(float(r["e1rm_change_pct"]),1),
            })
    return payload

def call_groq(payload):
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY não configurada.")

    system = """
Você é um analista de evolução de treinamento físico.
Analise SOMENTE os dados fornecidos.
Não diagnostique doenças, não prescreva medicamentos, não altere dieta clínica e não trate estimativas como medições exatas.
O objetivo é interpretar hipertrofia, performance, aderência e evolução corporal de forma prática.
Quando faltarem dados, diga explicitamente que não há dados suficientes.
Responda em português do Brasil.
"""

    user = f"""
Analise os dados agregados abaixo.

Entregue exatamente estas seções:
1. Resumo executivo
2. O que está evoluindo bem
3. Pontos de atenção
4. Análise de performance por exercícios
5. Análise corporal integrada
6. Recomendações objetivas para as próximas 2 semanas
7. Dados que vale registrar melhor

Regras:
- 1RM é estimado, não real;
- pequenas oscilações de peso podem refletir água/glicogênio;
- redução de cintura/abdômen deve ser interpretada junto com peso e performance;
- não invente conclusões quando faltarem dados;
- não faça recomendações médicas.

DADOS:
{json.dumps(payload, ensure_ascii=False)}
"""

    r = requests.post(
        GROQ_URL,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_completion_tokens": 2200,
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]

try:
    with st.spinner("Sincronizando dados com o Hevy..."):
        workouts = get_all_workouts()
        measures = get_all_measurements()
except Exception as e:
    st.error(f"Erro ao acessar o Hevy: {e}")
    st.stop()

wdf = workout_df(workouts)
sdf = sets_df(workouts)
mdf = pd.DataFrame(measures)
if not mdf.empty and "date" in mdf.columns:
    mdf["date"] = pd.to_datetime(mdf["date"], errors="coerce")
    mdf = mdf.sort_values("date")

st.title("💪 Minha Evolução Pro")
st.caption("Treino • hipertrofia • composição corporal • análise inteligente")

top1, top2 = st.columns([3,1])
with top1:
    period = st.segmented_control("Período", [30,60,90,180,"Tudo"], default=30)
with top2:
    if st.button("🔄 Sincronizar", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

wf, sf, mf = period_filter(wdf,sdf,mdf,period)

tabs = st.tabs(["Visão geral","Corpo","Performance","Carga de treino","Análise IA"])

with tabs[0]:
    latest = mdf.iloc[-1] if not mdf.empty else pd.Series(dtype=float)
    cols = st.columns(4)
    cols[0].metric("Peso", format_value(latest.get("weight_kg"),"weight_kg"))
    cols[1].metric("Cintura", format_value(latest.get("waist"),"waist"))
    cols[2].metric("Abdômen", format_value(latest.get("abdomen"),"abdomen"))
    cols[3].metric("Treinos", len(wf))

    if not wf.empty:
        c1,c2,c3 = st.columns(3)
        c1.metric("Duração média", f"{wf['duration_min'].dropna().mean():.0f} min" if wf["duration_min"].notna().any() else "—")
        c2.metric("Exercícios/sessão", f"{wf['exercise_count'].mean():.1f}")
        total_vol = sf["volume_kg"].dropna().sum() if not sf.empty else 0
        c3.metric("Volume registrado", f"{total_vol:,.0f} kg".replace(",","."))

    st.subheader("Leitura automática")
    insights = deterministic_insights(wf,sf,mf)
    if not insights:
        st.info("Ainda faltam dados para gerar insights automáticos.")
    for cls,title,text in insights:
        st.markdown(f'<div class="insight {cls}"><b>{title}</b><br>{text}</div>', unsafe_allow_html=True)

    if not wf.empty:
        weekly = (wf.assign(week=wf["date"].dt.tz_convert(None).dt.to_period("W").astype(str))
                    .groupby("week",as_index=False)
                    .agg(treinos=("id","count"), minutos=("duration_min","sum")))
        fig = px.bar(weekly,x="week",y="treinos",title="Frequência semanal")
        fig.update_layout(height=310,margin=dict(l=10,r=10,t=45,b=10))
        st.plotly_chart(fig,use_container_width=True)

with tabs[1]:
    st.subheader("Composição e medidas")
    if mdf.empty:
        st.info("Registre suas medidas no Hevy para preencher esta área.")
    else:
        available = [k for k in LABELS if k in mdf.columns and mdf[k].notna().any()]
        selected = st.multiselect(
            "Indicadores",
            available,
            default=[x for x in ["weight_kg","waist","abdomen","fat_percent"] if x in available],
            format_func=lambda x: LABELS[x],
        )
        for key in selected:
            d = mf[["date",key]].dropna() if key in mf else pd.DataFrame()
            if not d.empty:
                fig = px.line(d,x="date",y=key,markers=True,title=f"{LABELS[key]} ({UNITS.get(key,'cm')})")
                fig.update_layout(height=300,margin=dict(l=10,r=10,t=45,b=10),showlegend=False)
                st.plotly_chart(fig,use_container_width=True)

        if len(mdf) >= 2:
            rows=[]
            for k in available:
                a,b=first_nonnull(mdf,k),latest_nonnull(mdf,k)
                if a is not None and b is not None:
                    rows.append({"Indicador":LABELS[k],"Inicial":a,"Atual":b,"Variação":b-a,"Unidade":UNITS.get(k,"cm")})
            st.dataframe(pd.DataFrame(rows),use_container_width=True,hide_index=True)

with tabs[2]:
    st.subheader("Progressão por exercício")
    if sdf.empty:
        st.info("Sem séries retornadas pela API.")
    else:
        exercises=sorted(sdf["exercise"].dropna().unique())
        chosen=st.selectbox("Exercício",exercises)
        ex=sf[(sf["exercise"]==chosen) & (~sf["set_type"].isin(["warmup","aquecimento"]))].copy()
        if ex.empty:
            st.info("Sem dados desse exercício no período.")
        else:
            ex["day"]=ex["date"].dt.date
            daily=ex.groupby("day",as_index=False).agg(
                melhor_carga=("weight_kg","max"),
                melhor_e1rm=("e1rm_kg","max"),
                volume=("volume_kg","sum"),
                reps=("reps","sum")
            )
            c1,c2,c3=st.columns(3)
            c1.metric("Melhor carga",f"{daily['melhor_carga'].max():.1f} kg" if daily["melhor_carga"].notna().any() else "—")
            c2.metric("1RM estimado",f"{daily['melhor_e1rm'].max():.1f} kg" if daily["melhor_e1rm"].notna().any() else "—")
            c3.metric("Sessões",len(daily))
            metric=st.segmented_control("Indicador",["1RM estimado","Melhor carga","Volume"],default="1RM estimado")
            col={"1RM estimado":"melhor_e1rm","Melhor carga":"melhor_carga","Volume":"volume"}[metric]
            fig=px.line(daily,x="day",y=col,markers=True,title=f"{chosen} — {metric}")
            fig.update_layout(height=330,margin=dict(l=10,r=10,t=45,b=10))
            st.plotly_chart(fig,use_container_width=True)

        prog=exercise_progress(sf)
        if not prog.empty:
            st.subheader("Ranking de evolução")
            show=prog.sort_values("e1rm_change_pct",ascending=False)[["exercise","sessions","e1rm_start","e1rm_now","e1rm_change_pct"]]
            show.columns=["Exercício","Sessões","1RM inicial","1RM atual","Variação %"]
            st.dataframe(show,use_container_width=True,hide_index=True)

with tabs[3]:
    st.subheader("Carga e consistência")
    if sf.empty:
        st.info("Sem dados suficientes.")
    else:
        temp=sf.copy()
        temp["week"]=temp["date"].dt.tz_convert(None).dt.to_period("W").astype(str)
        weekly=(temp.groupby("week",as_index=False)
                .agg(volume_kg=("volume_kg","sum"),series=("exercise","count")))
        fig=px.line(weekly,x="week",y="volume_kg",markers=True,title="Volume registrado por semana")
        fig.update_layout(height=320,margin=dict(l=10,r=10,t=45,b=10))
        st.plotly_chart(fig,use_container_width=True)
        st.caption("Volume (kg × repetições) é apenas um indicador. Não substitui intensidade, proximidade da falha e qualidade da execução.")

    if not wf.empty:
        by_title=wf["workout"].value_counts().rename_axis("Treino").reset_index(name="Sessões")
        st.dataframe(by_title,use_container_width=True,hide_index=True)

with tabs[4]:
    st.subheader("Análise integrada por IA")
    st.write("A IA recebe apenas um resumo numérico dos seus dados do período. Ela não recebe sua chave do Hevy.")

    if not GROQ_API_KEY:
        st.warning("Configure `GROQ_API_KEY` nos Secrets para habilitar a análise por IA.")
        st.code('GROQ_API_KEY = "SUA_CHAVE_GROQ"', language="toml")
    else:
        st.success(f"IA configurada: {GROQ_MODEL}")
        st.caption("A análise é complementar e não substitui acompanhamento médico, nutricional ou de profissional de educação física.")
        if st.button("✨ Gerar análise completa",use_container_width=True,type="primary"):
            payload=build_ai_payload(wf,sf,mf,period)
            try:
                with st.spinner("Analisando treino, performance e medidas..."):
                    answer=call_groq(payload)
                st.session_state["ai_analysis"]=answer
            except requests.HTTPError as e:
                msg = e.response.text if e.response is not None else str(e)
                st.error(f"Erro da Groq: {msg}")
            except Exception as e:
                st.error(f"Não foi possível gerar a análise: {e}")

        if st.session_state.get("ai_analysis"):
            st.markdown(st.session_state["ai_analysis"])
            st.download_button(
                "Baixar análise em TXT",
                st.session_state["ai_analysis"],
                file_name="analise_hevy.txt",
                mime="text/plain",
                use_container_width=True,
            )

st.divider()
st.caption("Painel somente leitura. Dados de treino vêm do Hevy; a análise por IA usa apenas dados agregados do período selecionado.")
