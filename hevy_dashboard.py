
import os
import requests
import pandas as pd
import streamlit as st
import plotly.express as px

BASE_URL = "https://api.hevyapp.com/v1"

st.set_page_config(
    page_title="Minha Evolução",
    page_icon="💪",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
.block-container {padding-top: 1.1rem; padding-bottom: 3rem; max-width: 760px;}
[data-testid="stMetric"] {
    border: 1px solid rgba(128,128,128,.20);
    padding: 12px;
    border-radius: 14px;
}
h1 {font-size: 1.8rem !important;}
h2 {font-size: 1.25rem !important;}
div[data-testid="stHorizontalBlock"] {gap: .5rem;}
@media (max-width: 640px) {
    .block-container {padding-left: .75rem; padding-right: .75rem;}
    [data-testid="stMetricValue"] {font-size: 1.25rem;}
}
</style>
""", unsafe_allow_html=True)

def get_api_key():
    try:
        if "HEVY_API_KEY" in st.secrets:
            return st.secrets["HEVY_API_KEY"]
    except Exception:
        pass
    return os.getenv("HEVY_API_KEY")

API_KEY = get_api_key()
if not API_KEY:
    st.error("HEVY_API_KEY não foi configurada nos Secrets do Streamlit.")
    st.stop()

def api_get(path, params=None):
    headers = {"api-key": API_KEY, "accept": "application/json"}
    r = requests.get(f"{BASE_URL}{path}", headers=headers, params=params or {}, timeout=30)
    if r.status_code in (401, 403):
        raise RuntimeError("A chave da API Hevy foi recusada.")
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=300, show_spinner=False)
def get_all_workouts():
    rows, page = [], 1
    while True:
        data = api_get("/workouts", {"page": page, "pageSize": 10})
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
        data = api_get("/body_measurements", {"page": page, "pageSize": 10})
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

def workout_table(workouts):
    rows = []
    for w in workouts:
        start, end = dt(w.get("start_time")), dt(w.get("end_time"))
        duration = (end-start).total_seconds()/60 if pd.notna(start) and pd.notna(end) else None
        rows.append({
            "date": start,
            "workout": w.get("title", "Treino"),
            "duration": duration,
            "id": w.get("id")
        })
    return pd.DataFrame(rows)

def set_table(workouts):
    rows = []
    for w in workouts:
        date = dt(w.get("start_time"))
        for ex in w.get("exercises", []) or []:
            name = ex.get("title") or ex.get("exercise_template_title") or ex.get("name") or ex.get("exercise_template_id", "Exercício")
            for s in ex.get("sets", []) or []:
                weight, reps = s.get("weight_kg"), s.get("reps")
                volume = weight * reps if isinstance(weight,(int,float)) and isinstance(reps,int) else None
                e1rm = weight*(1+reps/30) if isinstance(weight,(int,float)) and isinstance(reps,int) and reps > 0 else None
                rows.append({
                    "date": date, "exercise": name, "weight": weight, "reps": reps,
                    "volume": volume, "e1rm": e1rm,
                    "set_type": str(s.get("type") or s.get("set_type") or "normal").lower()
                })
    return pd.DataFrame(rows)

LABELS = {
    "weight_kg":"Peso", "lean_mass_kg":"Massa magra", "fat_percent":"Gordura %",
    "neck_cm":"Pescoço", "shoulder_cm":"Ombros", "chest_cm":"Tórax",
    "left_bicep_cm":"Braço E", "right_bicep_cm":"Braço D",
    "left_forearm_cm":"Antebraço E", "right_forearm_cm":"Antebraço D",
    "abdomen":"Abdômen", "waist":"Cintura", "hips":"Quadril",
    "left_thigh":"Coxa E", "right_thigh":"Coxa D",
    "left_calf":"Panturrilha E", "right_calf":"Panturrilha D",
}
UNITS = {"weight_kg":"kg", "lean_mass_kg":"kg", "fat_percent":"%"}

def fmt(v, key):
    if pd.isna(v): return "—"
    return f"{v:.1f} {UNITS.get(key,'cm')}"

def delta_for(df, col):
    vals = df[["date",col]].dropna().sort_values("date")
    if len(vals) < 2: return None
    return float(vals.iloc[-1][col] - vals.iloc[0][col])

try:
    with st.spinner("Sincronizando com o Hevy..."):
        workouts = get_all_workouts()
        measures = get_all_measurements()
except Exception as e:
    st.error(f"Erro ao acessar o Hevy: {e}")
    st.stop()

wdf = workout_table(workouts)
sdf = set_table(workouts)
mdf = pd.DataFrame(measures)
if not mdf.empty and "date" in mdf:
    mdf["date"] = pd.to_datetime(mdf["date"], errors="coerce")
    mdf = mdf.sort_values("date")

st.title("💪 Minha Evolução")
st.caption("Hipertrofia • performance • composição corporal")

period = st.segmented_control("Período", [30, 60, 90, 180, "Tudo"], default=30)
if period != "Tudo":
    cutoff_utc = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=int(period))
    cutoff_naive = pd.Timestamp.now() - pd.Timedelta(days=int(period))
    wf = wdf[wdf["date"] >= cutoff_utc].copy() if not wdf.empty else wdf
    sf = sdf[sdf["date"] >= cutoff_utc].copy() if not sdf.empty else sdf
    mf = mdf[mdf["date"] >= cutoff_naive].copy() if not mdf.empty else mdf
else:
    wf, sf, mf = wdf.copy(), sdf.copy(), mdf.copy()

tab1, tab2, tab3 = st.tabs(["Resumo", "Medidas", "Força"])

with tab1:
    latest = mdf.iloc[-1] if not mdf.empty else pd.Series(dtype=float)
    c1, c2 = st.columns(2)
    c1.metric("Peso", fmt(latest.get("weight_kg"), "weight_kg"),
              f"{delta_for(mf,'weight_kg'):+.1f} kg" if not mf.empty and "weight_kg" in mf and delta_for(mf,"weight_kg") is not None else None)
    abd_key = "abdomen" if "abdomen" in mdf.columns else None
    c2.metric("Abdômen", fmt(latest.get(abd_key), abd_key) if abd_key else "—",
              f"{delta_for(mf,abd_key):+.1f} cm" if abd_key and abd_key in mf and delta_for(mf,abd_key) is not None else None)

    c3, c4 = st.columns(2)
    waist_key = "waist" if "waist" in mdf.columns else None
    c3.metric("Cintura", fmt(latest.get(waist_key), waist_key) if waist_key else "—",
              f"{delta_for(mf,waist_key):+.1f} cm" if waist_key and waist_key in mf and delta_for(mf,waist_key) is not None else None)
    c4.metric("Treinos", len(wf))

    if not wf.empty:
        avg = wf["duration"].dropna().mean()
        st.metric("Duração média dos treinos", f"{avg:.0f} min" if pd.notna(avg) else "—")

        week = (wf.assign(semana=wf["date"].dt.tz_convert(None).dt.to_period("W").astype(str))
                  .groupby("semana", as_index=False).size()
                  .rename(columns={"size":"Treinos"}))
        fig = px.bar(week, x="semana", y="Treinos", title="Consistência semanal")
        fig.update_layout(margin=dict(l=10,r=10,t=45,b=10), height=300)
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    if mdf.empty:
        st.info("Registre medidas no Hevy para começar o acompanhamento.")
    else:
        available = [k for k in LABELS if k in mdf.columns and mdf[k].notna().any()]
        defaults = [x for x in ["weight_kg","waist","abdomen"] if x in available]
        selected = st.multiselect("Mostrar", available, default=defaults,
                                  format_func=lambda x: f"{LABELS[x]} ({UNITS.get(x,'cm')})")
        for key in selected:
            d = mf[["date",key]].dropna() if key in mf else pd.DataFrame()
            if not d.empty:
                fig = px.line(d, x="date", y=key, markers=True,
                              title=f"{LABELS[key]} ({UNITS.get(key,'cm')})")
                fig.update_layout(margin=dict(l=10,r=10,t=45,b=10), height=300,
                                  showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        st.subheader("Últimas medidas")
        show = ["date"] + available
        display = mdf[show].sort_values("date", ascending=False).head(10).rename(columns=LABELS)
        st.dataframe(display, use_container_width=True, hide_index=True)

with tab3:
    if sdf.empty:
        st.info("Ainda não encontrei séries de exercícios.")
    else:
        exercises = sorted(sdf["exercise"].dropna().unique())
        chosen = st.selectbox("Exercício", exercises)
        ex = sf[sf["exercise"] == chosen].copy()
        ex = ex[~ex["set_type"].isin(["warmup","aquecimento"])]
        if ex.empty:
            st.info("Sem dados desse exercício no período selecionado.")
        else:
            ex["dia"] = ex["date"].dt.date
            daily = ex.groupby("dia", as_index=False).agg(
                carga=("weight","max"), e1rm=("e1rm","max"), volume=("volume","sum")
            )
            c1,c2 = st.columns(2)
            c1.metric("Melhor carga", f"{daily['carga'].max():.1f} kg" if daily["carga"].notna().any() else "—")
            c2.metric("Melhor 1RM estimado", f"{daily['e1rm'].max():.1f} kg" if daily["e1rm"].notna().any() else "—")
            metric = st.segmented_control("Indicador", ["1RM estimado","Carga","Volume"], default="1RM estimado")
            col = {"1RM estimado":"e1rm","Carga":"carga","Volume":"volume"}[metric]
            fig = px.line(daily, x="dia", y=col, markers=True, title=f"{chosen} — {metric}")
            fig.update_layout(margin=dict(l=10,r=10,t=45,b=10), height=320)
            st.plotly_chart(fig, use_container_width=True)
            st.caption("O 1RM é uma estimativa pela fórmula de Epley e serve para acompanhar tendência.")

if st.button("🔄 Atualizar agora", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.caption("Dados lidos diretamente da API do Hevy. O painel não altera seus registros.")
