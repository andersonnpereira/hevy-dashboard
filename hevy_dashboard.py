
import os
import math
import requests
import pandas as pd
import streamlit as st
import plotly.express as px
from datetime import datetime

BASE_URL = "https://api.hevyapp.com/v1"

st.set_page_config(page_title="Hevy — Painel de Evolução", page_icon="🏋️", layout="wide")

def api_get(path, api_key, params=None):
    headers = {"api-key": api_key, "accept": "application/json"}
    r = requests.get(f"{BASE_URL}{path}", headers=headers, params=params or {}, timeout=30)
    if r.status_code in (401, 403):
        raise RuntimeError("Chave de API inválida, revogada ou sem permissão.")
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=300, show_spinner=False)
def get_user(api_key):
    return api_get("/user/info", api_key)

@st.cache_data(ttl=300, show_spinner=False)
def get_all_workouts(api_key):
    rows = []
    page = 1
    while True:
        data = api_get("/workouts", api_key, {"page": page, "pageSize": 10})
        batch = data.get("workouts", [])
        rows.extend(batch)
        page_count = data.get("page_count") or data.get("pageCount")
        if not batch:
            break
        if page_count and page >= page_count:
            break
        if len(batch) < 10:
            break
        page += 1
        if page > 500:
            break
    return rows

@st.cache_data(ttl=300, show_spinner=False)
def get_all_measurements(api_key):
    rows = []
    page = 1
    while True:
        data = api_get("/body_measurements", api_key, {"page": page, "pageSize": 10})
        batch = data.get("body_measurements", [])
        rows.extend(batch)
        page_count = data.get("page_count") or data.get("pageCount")
        if not batch:
            break
        if page_count and page >= page_count:
            break
        if len(batch) < 10:
            break
        page += 1
        if page > 500:
            break
    return rows

def to_dt(x):
    if not x:
        return pd.NaT
    return pd.to_datetime(x, utc=True, errors="coerce")

def flatten_sets(workouts):
    rows = []
    for w in workouts:
        wid = w.get("id")
        title = w.get("title", "Treino")
        start = to_dt(w.get("start_time"))
        end = to_dt(w.get("end_time"))
        for ex in w.get("exercises", []) or []:
            ex_name = ex.get("title") or ex.get("exercise_template_title") or ex.get("name") or ex.get("exercise_template_id", "Exercício")
            ex_id = ex.get("exercise_template_id")
            for s in ex.get("sets", []) or []:
                weight = s.get("weight_kg")
                reps = s.get("reps")
                set_type = s.get("type") or s.get("set_type") or "normal"
                volume = None
                if isinstance(weight, (int, float)) and isinstance(reps, int):
                    volume = float(weight) * int(reps)
                e1rm = None
                if isinstance(weight, (int, float)) and isinstance(reps, int) and reps > 0:
                    # Fórmula de Epley — estimativa, não medição real.
                    e1rm = float(weight) * (1 + reps / 30)
                rows.append({
                    "workout_id": wid,
                    "workout": title,
                    "date": start,
                    "end": end,
                    "exercise": ex_name,
                    "exercise_template_id": ex_id,
                    "set_index": s.get("index"),
                    "set_type": set_type,
                    "weight_kg": weight,
                    "reps": reps,
                    "volume_kg": volume,
                    "e1rm_kg": e1rm,
                    "rpe": s.get("rpe"),
                })
    return pd.DataFrame(rows)

def workouts_df(workouts):
    rows = []
    for w in workouts:
        start = to_dt(w.get("start_time"))
        end = to_dt(w.get("end_time"))
        mins = None
        if pd.notna(start) and pd.notna(end):
            mins = (end - start).total_seconds() / 60
        rows.append({
            "date": start,
            "workout": w.get("title", "Treino"),
            "duration_min": mins,
            "exercise_count": len(w.get("exercises", []) or []),
            "id": w.get("id"),
        })
    return pd.DataFrame(rows)

MEASURE_LABELS = {
    "weight_kg": "Peso (kg)",
    "lean_mass_kg": "Massa magra (kg)",
    "fat_percent": "Gordura corporal (%)",
    "neck_cm": "Pescoço (cm)",
    "shoulder_cm": "Ombros (cm)",
    "chest_cm": "Tórax (cm)",
    "left_bicep_cm": "Braço E (cm)",
    "right_bicep_cm": "Braço D (cm)",
    "left_forearm_cm": "Antebraço E (cm)",
    "right_forearm_cm": "Antebraço D (cm)",
    "abdomen": "Abdômen (cm)",
    "waist": "Cintura (cm)",
    "hips": "Quadril (cm)",
    "left_thigh": "Coxa E (cm)",
    "right_thigh": "Coxa D (cm)",
    "left_calf": "Panturrilha E (cm)",
    "right_calf": "Panturrilha D (cm)",
}

def measurements_df(rows):
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.sort_values("date")
    return df

st.title("🏋️ Hevy — Painel de Evolução")
st.caption("Treinos + medidas corporais em um único painel. A chave fica apenas na sessão local do app.")

with st.sidebar:
    st.header("Conexão")
    api_key = st.text_input("Chave da API Hevy", type="password", value=os.getenv("HEVY_API_KEY", ""))
    st.caption("Recomendação: use uma chave nova e nunca publique/cole a chave em chats ou prints.")
    refresh = st.button("Atualizar dados")
    if refresh:
        st.cache_data.clear()

if not api_key:
    st.info("Informe sua chave da API Hevy na barra lateral para carregar seus dados.")
    st.stop()

try:
    with st.spinner("Carregando dados do Hevy..."):
        user = get_user(api_key)
        workouts = get_all_workouts(api_key)
        measurements = get_all_measurements(api_key)
except Exception as e:
    st.error(f"Não foi possível acessar a API: {e}")
    st.stop()

wdf = workouts_df(workouts)
sdf = flatten_sets(workouts)
mdf = measurements_df(measurements)

tabs = st.tabs(["Visão geral", "Medidas", "Treinos", "Exercícios"])

with tabs[0]:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Treinos registrados", len(wdf))
    if not wdf.empty:
        last30 = wdf[wdf["date"] >= (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=30))]
        c2.metric("Treinos — 30 dias", len(last30))
        avg_duration = last30["duration_min"].dropna().mean()
        c3.metric("Duração média — 30 dias", f"{avg_duration:.0f} min" if pd.notna(avg_duration) else "—")
    else:
        c2.metric("Treinos — 30 dias", 0)
        c3.metric("Duração média — 30 dias", "—")
    if not mdf.empty and "weight_kg" in mdf:
        latest_weight = mdf["weight_kg"].dropna()
        c4.metric("Peso mais recente", f"{latest_weight.iloc[-1]:.1f} kg" if not latest_weight.empty else "—")
    else:
        c4.metric("Peso mais recente", "—")

    if not mdf.empty:
        cols = [x for x in ["weight_kg", "waist", "abdomen", "fat_percent"] if x in mdf.columns and mdf[x].notna().any()]
        if cols:
            long = mdf[["date"] + cols].melt("date", var_name="medida", value_name="valor")
            long["medida"] = long["medida"].map(MEASURE_LABELS)
            fig = px.line(long, x="date", y="valor", color="medida", markers=True, title="Evolução corporal")
            st.plotly_chart(fig, use_container_width=True)

with tabs[1]:
    st.subheader("Medidas corporais")
    if mdf.empty:
        st.warning("Ainda não há medidas corporais retornadas pela API.")
    else:
        available = [c for c in MEASURE_LABELS if c in mdf.columns and mdf[c].notna().any()]
        selected = st.multiselect(
            "Medidas para o gráfico",
            available,
            default=[c for c in ["weight_kg", "waist", "abdomen"] if c in available],
            format_func=lambda x: MEASURE_LABELS.get(x, x),
        )
        if selected:
            long = mdf[["date"] + selected].melt("date", var_name="medida", value_name="valor")
            long["medida"] = long["medida"].map(MEASURE_LABELS)
            fig = px.line(long, x="date", y="valor", color="medida", markers=True)
            st.plotly_chart(fig, use_container_width=True)

        show_cols = ["date"] + available
        display = mdf[show_cols].rename(columns=MEASURE_LABELS)
        st.dataframe(display.sort_values("date", ascending=False), use_container_width=True, hide_index=True)

        if len(mdf) >= 2:
            st.subheader("Variação entre a primeira e a última medição")
            first, last = mdf.iloc[0], mdf.iloc[-1]
            deltas = []
            for c in available:
                if pd.notna(first.get(c)) and pd.notna(last.get(c)):
                    deltas.append({
                        "Medida": MEASURE_LABELS[c],
                        "Inicial": first[c],
                        "Atual": last[c],
                        "Variação": last[c] - first[c],
                    })
            st.dataframe(pd.DataFrame(deltas), use_container_width=True, hide_index=True)

with tabs[2]:
    st.subheader("Histórico de treinos")
    if wdf.empty:
        st.warning("Nenhum treino retornado.")
    else:
        temp = wdf.copy()
        temp["dia"] = temp["date"].dt.date
        by_week = (
            temp.assign(semana=temp["date"].dt.to_period("W").astype(str))
                .groupby("semana", as_index=False)
                .agg(treinos=("id", "count"), minutos=("duration_min", "sum"))
        )
        fig = px.bar(by_week, x="semana", y="treinos", title="Treinos por semana")
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            temp[["date", "workout", "duration_min", "exercise_count"]]
                .sort_values("date", ascending=False),
            use_container_width=True,
            hide_index=True,
        )

with tabs[3]:
    st.subheader("Progressão por exercício")
    if sdf.empty:
        st.warning("Não encontrei séries nos treinos.")
    else:
        exercises = sorted(sdf["exercise"].dropna().unique().tolist())
        chosen = st.selectbox("Exercício", exercises)
        ex = sdf[sdf["exercise"] == chosen].copy()
        ex = ex[~ex["set_type"].astype(str).str.lower().isin(["warmup", "aquecimento"])]
        ex["day"] = ex["date"].dt.date

        daily = ex.groupby("day", as_index=False).agg(
            melhor_carga=("weight_kg", "max"),
            melhor_e1rm=("e1rm_kg", "max"),
            volume=("volume_kg", "sum"),
            reps_totais=("reps", "sum"),
        )

        c1, c2, c3 = st.columns(3)
        if not daily.empty:
            c1.metric("Melhor carga", f"{daily['melhor_carga'].max():.1f} kg" if daily["melhor_carga"].notna().any() else "—")
            c2.metric("Melhor 1RM estimado", f"{daily['melhor_e1rm'].max():.1f} kg" if daily["melhor_e1rm"].notna().any() else "—")
            c3.metric("Sessões", len(daily))

            metric = st.radio("Mostrar", ["1RM estimado", "Melhor carga", "Volume"], horizontal=True)
            col = {"1RM estimado": "melhor_e1rm", "Melhor carga": "melhor_carga", "Volume": "volume"}[metric]
            fig = px.line(daily, x="day", y=col, markers=True, title=f"{chosen} — {metric}")
            st.plotly_chart(fig, use_container_width=True)

        st.caption("1RM estimado usa a fórmula de Epley e serve apenas como indicador de tendência.")
        st.dataframe(
            ex[["date", "weight_kg", "reps", "set_type", "rpe", "volume_kg", "e1rm_kg"]]
                .sort_values(["date", "set_index"], ascending=[False, True]),
            use_container_width=True,
            hide_index=True,
        )

st.divider()
st.caption("Painel somente leitura: ele consulta seus dados e não altera treinos ou medidas no Hevy.")
