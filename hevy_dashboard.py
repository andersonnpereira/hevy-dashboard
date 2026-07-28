
import os
import json
import math
import hashlib

import requests
import pandas as pd
import streamlit as st
import plotly.express as px

HEVY_BASE = "https://api.hevyapp.com/v1"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
WEEKLY_PLAN = {"B": 2, "A": 2, "C": 1}

st.set_page_config(
    page_title="Minha Evolução Pro",
    page_icon="💪",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
.block-container {padding-top: .9rem; padding-bottom: 4rem; max-width: 1180px;}
[data-testid="stMetric"] {
    border: 1px solid rgba(128,128,128,.16);
    background: rgba(128,128,128,.035);
    padding: 12px 14px;
    border-radius: 18px;
}
[data-testid="stMetricValue"] {font-weight: 750;}
h1 {font-size: 1.9rem !important; margin-bottom: .15rem !important;}
h2 {font-size: 1.30rem !important;}
h3 {font-size: 1.05rem !important;}
div[data-testid="stTabs"] button {font-weight: 650;}
.insight {
    border: 1px solid rgba(128,128,128,.16);
    border-radius: 14px;
    padding: 12px 14px;
    margin-bottom: 8px;
}
.good {border-left: 4px solid #2e7d32;}
.warn {border-left: 4px solid #f9a825;}
.info {border-left: 4px solid #1976d2;}
@media (max-width:700px){
    .block-container {padding-left:.55rem; padding-right:.55rem;}
    [data-testid="stMetricValue"] {font-size:1.08rem;}
    h1 {font-size:1.65rem !important;}
    div[data-testid="stTabs"] button {font-size:.78rem; padding-left:.55rem; padding-right:.55rem;}
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
APP_PASSWORD = secret("APP_PASSWORD")


def password_gate():
    if not APP_PASSWORD:
        st.error("🔒 Configure `APP_PASSWORD` nos Secrets do Streamlit para proteger seus dados.")
        st.code('APP_PASSWORD = "crie-uma-senha-forte"', language="toml")
        st.stop()

    if st.session_state.get("authenticated"):
        return

    st.title("🔒 Minha Evolução Pro")
    st.caption("Painel pessoal protegido")
    pwd = st.text_input("Senha", type="password", placeholder="Digite sua senha")

    if st.button("Entrar", use_container_width=True, type="primary"):
        a = hashlib.sha256((pwd or "").encode()).hexdigest()
        b = hashlib.sha256(str(APP_PASSWORD).encode()).hexdigest()
        if pwd and a == b:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("Senha incorreta.")
    st.stop()


password_gate()

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


def workout_code(title):
    t = str(title or "").strip().upper()
    for code in ("A", "B", "C"):
        if t == code or t.startswith(code + " ") or t.startswith("TREINO " + code):
            return code
    return None


def workout_df(workouts):
    out = []
    for w in workouts:
        start, end = dt(w.get("start_time")), dt(w.get("end_time"))
        dur = (end - start).total_seconds() / 60 if pd.notna(start) and pd.notna(end) else None
        title = w.get("title", "Treino")
        out.append({
            "date": start,
            "workout": title,
            "code": workout_code(title),
            "duration_min": dur,
            "exercise_count": len(w.get("exercises", []) or []),
            "id": w.get("id"),
        })
    return pd.DataFrame(out)


def infer_muscle(name):
    n = str(name or "").lower()
    rules = [
        (("supino", "crucifixo", "peck", "voador"), "Peito"),
        (("puxada", "pulldown", "remada", "pull up", "barra fixa"), "Costas"),
        (("elevação lateral", "elevacao lateral", "desenvolvimento", "ombro", "crucifixo inverso", "reverse fly"), "Ombros"),
        (("tríceps", "triceps"), "Tríceps"),
        (("rosca", "curl"), "Bíceps"),
        (("hack", "leg press", "extensora", "agachamento", "squat"), "Quadríceps"),
        (("flexora", "stiff", "rdl", "romeno", "deadlift"), "Posteriores"),
        (("panturrilha", "calf"), "Panturrilhas"),
        (("abdominal", "abdômen", "abdomen", "crunch"), "Abdômen"),
        (("encolhimento", "shrug"), "Trapézio"),
    ]
    for keys, muscle in rules:
        if any(k in n for k in keys):
            return muscle
    return "Outros"


def sets_df(workouts):
    out = []
    for w in workouts:
        date = dt(w.get("start_time"))
        title = w.get("title", "Treino")
        for ex in w.get("exercises", []) or []:
            name = (
                ex.get("title")
                or ex.get("exercise_template_title")
                or ex.get("name")
                or ex.get("exercise_template_id", "Exercício")
            )
            exid = ex.get("exercise_template_id")
            muscle = infer_muscle(name)

            for s in ex.get("sets", []) or []:
                weight, reps = s.get("weight_kg"), s.get("reps")
                volume = weight * reps if isinstance(weight, (int, float)) and isinstance(reps, int) else None
                e1rm = weight * (1 + reps / 30) if isinstance(weight, (int, float)) and isinstance(reps, int) and reps > 0 else None

                out.append({
                    "date": date,
                    "workout": title,
                    "code": workout_code(title),
                    "exercise": name,
                    "exercise_id": exid,
                    "muscle": muscle,
                    "weight_kg": weight,
                    "reps": reps,
                    "volume_kg": volume,
                    "e1rm_kg": e1rm,
                    "rpe": s.get("rpe"),
                    "set_type": str(s.get("type") or s.get("set_type") or "normal").lower(),
                })

    return pd.DataFrame(out)


LABELS = {
    "weight_kg": "Peso",
    "lean_mass_kg": "Massa magra",
    "fat_percent": "Gordura corporal",
    "neck_cm": "Pescoço",
    "shoulder_cm": "Ombros",
    "chest_cm": "Tórax",
    "left_bicep_cm": "Braço E",
    "right_bicep_cm": "Braço D",
    "left_forearm_cm": "Antebraço E",
    "right_forearm_cm": "Antebraço D",
    "abdomen": "Abdômen",
    "waist": "Cintura",
    "hips": "Quadril",
    "left_thigh": "Coxa E",
    "right_thigh": "Coxa D",
    "left_calf": "Panturrilha E",
    "right_calf": "Panturrilha D",
}
UNITS = {"weight_kg": "kg", "lean_mass_kg": "kg", "fat_percent": "%"}


def format_value(v, key):
    if v is None or pd.isna(v):
        return "—"
    return f"{float(v):.1f} {UNITS.get(key, 'cm')}"


def first_nonnull(df, col):
    if df.empty or col not in df.columns:
        return None
    x = df[["date", col]].dropna().sort_values("date")
    return None if x.empty else float(x.iloc[0][col])


def latest_nonnull(df, col):
    if df.empty or col not in df.columns:
        return None
    x = df[["date", col]].dropna().sort_values("date")
    return None if x.empty else float(x.iloc[-1][col])


def delta(df, col):
    a, b = first_nonnull(df, col), latest_nonnull(df, col)
    return None if a is None or b is None else b - a


def pct_change(a, b):
    if a is None or b is None or pd.isna(a) or pd.isna(b) or a == 0:
        return None
    return (b - a) / a * 100


def period_filter(wdf, sdf, mdf, days):
    if days == "Tudo":
        return wdf.copy(), sdf.copy(), mdf.copy()

    utc_cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=int(days))
    naive_cutoff = pd.Timestamp.now() - pd.Timedelta(days=int(days))

    return (
        wdf[wdf["date"] >= utc_cutoff].copy() if not wdf.empty else wdf,
        sdf[sdf["date"] >= utc_cutoff].copy() if not sdf.empty else sdf,
        mdf[mdf["date"] >= naive_cutoff].copy() if not mdf.empty else mdf,
    )


def exercise_progress(sf):
    if sf.empty:
        return pd.DataFrame()

    work = sf[~sf["set_type"].isin(["warmup", "aquecimento"])].copy()
    if work.empty:
        return pd.DataFrame()

    work["day"] = work["date"].dt.date
    daily = work.groupby(["exercise", "day"], as_index=False).agg(
        best_load=("weight_kg", "max"),
        best_e1rm=("e1rm_kg", "max"),
        volume=("volume_kg", "sum"),
        sets=("exercise", "size"),
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


def weekly_adherence(wf):
    if wf.empty:
        return pd.DataFrame()

    x = wf.copy()
    x["week"] = x["date"].dt.tz_convert(None).dt.to_period("W-MON").astype(str)

    rows = []
    for week, g in x.groupby("week"):
        counts = g["code"].value_counts().to_dict()
        done = sum(min(counts.get(c, 0), target) for c, target in WEEKLY_PLAN.items())
        total = sum(WEEKLY_PLAN.values())
        rows.append({
            "week": week,
            "A": counts.get("A", 0),
            "B": counts.get("B", 0),
            "C": counts.get("C", 0),
            "aderencia_pct": done / total * 100,
        })

    return pd.DataFrame(rows)


def score_components(wf, sf, mf):
    adh = weekly_adherence(wf)
    adherence = float(adh["aderencia_pct"].mean()) if not adh.empty else None

    prog = exercise_progress(sf)
    performance = None
    if not prog.empty and prog["e1rm_change_pct"].notna().any():
        med = float(prog["e1rm_change_pct"].dropna().median())
        performance = max(0, min(100, 50 + med * 5))

    body = None
    wd, ad = delta(mf, "waist"), delta(mf, "abdomen")
    vals = [x for x in [wd, ad] if x is not None]
    if vals:
        avg = sum(vals) / len(vals)
        body = max(0, min(100, 50 - avg * 12.5))

    pieces = [x for x in [adherence, performance, body] if x is not None]
    overall = sum(pieces) / len(pieces) if pieces else None
    return adherence, performance, body, overall


def auto_insights(wf, sf, mf):
    out = []

    adh = weekly_adherence(wf)
    if not adh.empty:
        a = adh["aderencia_pct"].mean()
        out.append((
            "good" if a >= 85 else "warn" if a < 65 else "info",
            "Aderência ao plano",
            f"Média de {a:.0f}% do B-A-C-B-A planejado no período.",
        ))

    if not wf.empty and wf["duration_min"].notna().any():
        avg = wf["duration_min"].dropna().mean()
        out.append((
            "good" if 45 <= avg <= 65 else "info",
            "Duração das sessões",
            f"Média de {avg:.0f} minutos por treino.",
        ))

    for c, nm in [("waist", "Cintura"), ("abdomen", "Abdômen")]:
        d = delta(mf, c)
        if d is not None:
            out.append((
                "good" if d < 0 else "warn" if d > 0.5 else "info",
                nm,
                f"Variação de {d:+.1f} cm no período.",
            ))

    prog = exercise_progress(sf)
    if not prog.empty:
        p = prog.dropna(subset=["e1rm_change_pct"])
        if not p.empty:
            up = (p["e1rm_change_pct"] > 2).sum()
            down = (p["e1rm_change_pct"] < -2).sum()
            out.append((
                "good" if up >= down else "warn",
                "Tendência de performance",
                f"{up} exercícios em alta (>2%) e {down} em queda (<-2%) no 1RM estimado.",
            ))

    return out


def build_ai_payload(wf, sf, mf, period, mode, exercise=None):
    prog = exercise_progress(sf)

    payload = {
        "periodo": str(period),
        "modo": mode,
        "plano_semanal": "B-A-C-B-A",
        "treinos": {
            "quantidade": int(len(wf)),
            "duracao_media_min": round(float(wf["duration_min"].dropna().mean()), 1)
            if not wf.empty and wf["duration_min"].notna().any()
            else None,
            "frequencia_por_tipo": wf["code"].value_counts(dropna=True).to_dict() if not wf.empty else {},
        },
        "aderencia": weekly_adherence(wf).tail(8).to_dict("records") if not wf.empty else [],
        "medidas": {},
        "performance": [],
        "volume_por_musculo": {},
    }

    for c, label in LABELS.items():
        if c in mf.columns and mf[c].notna().any():
            a, b = first_nonnull(mf, c), latest_nonnull(mf, c)
            payload["medidas"][label] = {
                "inicial": a,
                "atual": b,
                "variacao": None if a is None or b is None else round(b - a, 2),
                "unidade": UNITS.get(c, "cm"),
            }

    if not sf.empty:
        work = sf[~sf["set_type"].isin(["warmup", "aquecimento"])].copy()
        by_muscle = work.groupby("muscle")["volume_kg"].sum(min_count=1).dropna().to_dict()
        payload["volume_por_musculo"] = {k: round(float(v), 1) for k, v in by_muscle.items()}

    if not prog.empty:
        q = prog.copy()
        if exercise:
            q = q[q["exercise"] == exercise]

        for _, r in q.sort_values("e1rm_change_pct", ascending=False).head(30).iterrows():
            payload["performance"].append({
                "exercicio": r["exercise"],
                "sessoes": int(r["sessions"]),
                "e1rm_inicial": None if pd.isna(r["e1rm_start"]) else round(float(r["e1rm_start"]), 1),
                "e1rm_atual": None if pd.isna(r["e1rm_now"]) else round(float(r["e1rm_now"]), 1),
                "variacao_pct": None if pd.isna(r["e1rm_change_pct"]) else round(float(r["e1rm_change_pct"]), 1),
            })

    return payload


def call_groq(payload, mode):
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY não configurada.")

    focus = {
        "Geral": "integre aderência, performance, volume e medidas corporais",
        "Hipertrofia": "priorize progressão de performance, consistência, distribuição de volume e sinais indiretos de ganho muscular",
        "Recomposição": "priorize peso, cintura, abdômen e preservação/ganho de performance; não assuma perda localizada de gordura",
        "Exercício": "analise detalhadamente o exercício selecionado, evolução, tendência e possíveis sinais de estagnação",
    }[mode]

    system = (
        "Você é um analista de dados de treinamento físico. "
        "Use apenas os dados fornecidos. Não diagnostique doenças, não prescreva medicamentos e não altere dieta clínica. "
        "1RM é estimado. Volume em kg é um indicador auxiliar. Se faltarem dados, diga isso. "
        "Responda em português do Brasil, de modo prático e criterioso."
    )

    user = f"""
Objetivo desta análise: {focus}.

Estruture em:
1. Resumo executivo
2. Evidências positivas
3. Pontos de atenção
4. Análise individual dos exercícios relevantes
5. Leitura integrada corpo + performance
6. Recomendações objetivas para 14 dias
7. Dados que faltam

Não invente informações.

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
            "max_completion_tokens": 2400,
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


try:
    with st.spinner("Sincronizando com o Hevy..."):
        workouts = get_all_workouts()
        measurements = get_all_measurements()
except Exception as e:
    st.error(f"Erro ao acessar o Hevy: {e}")
    st.stop()


wdf = workout_df(workouts)
sdf = sets_df(workouts)
mdf = pd.DataFrame(measurements)

if not mdf.empty and "date" in mdf.columns:
    mdf["date"] = pd.to_datetime(mdf["date"], errors="coerce")
    mdf = mdf.sort_values("date")


head1, head2 = st.columns([5, 1])
with head1:
    st.title("💪 Minha Evolução Pro")
    st.caption("Dashboard pessoal de hipertrofia, performance e recomposição corporal")
with head2:
    if st.button("Sair", use_container_width=True):
        st.session_state.pop("authenticated", None)
        st.rerun()

c1, c2 = st.columns([4, 1])
with c1:
    period = st.segmented_control("Período", [30, 60, 90, 180, "Tudo"], default=30)
with c2:
    if st.button("🔄 Sincronizar", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

wf, sf, mf = period_filter(wdf, sdf, mdf, period)

tabs = st.tabs(["Resumo", "Corpo", "Performance", "Músculos", "Aderência", "IA"])


with tabs[0]:
    latest = mdf.iloc[-1] if not mdf.empty else pd.Series(dtype=float)

    a, b, c, d = st.columns(4)
    a.metric(
        "Peso",
        format_value(latest.get("weight_kg"), "weight_kg"),
        f"{delta(mf, 'weight_kg'):+.1f} kg" if delta(mf, "weight_kg") is not None else None,
    )
    b.metric(
        "Cintura",
        format_value(latest.get("waist"), "waist"),
        f"{delta(mf, 'waist'):+.1f} cm" if delta(mf, "waist") is not None else None,
    )
    c.metric(
        "Abdômen",
        format_value(latest.get("abdomen"), "abdomen"),
        f"{delta(mf, 'abdomen'):+.1f} cm" if delta(mf, "abdomen") is not None else None,
    )
    d.metric("Treinos", len(wf))

    adh, perf, body, overall = score_components(wf, sf, mf)

    st.subheader("Painel de evolução")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Aderência", f"{adh:.0f}%" if adh is not None else "—")
    s2.metric("Performance", f"{perf:.0f}/100" if perf is not None else "—")
    s3.metric("Corpo", f"{body:.0f}/100" if body is not None else "—")
    s4.metric("Índice geral", f"{overall:.0f}/100" if overall is not None else "—")
    st.caption("Índices calculados por regras transparentes do painel; não são avaliações médicas nem notas de condicionamento físico.")

    st.subheader("Leitura automática")
    insights = auto_insights(wf, sf, mf)
    if not insights:
        st.info("Ainda faltam dados para gerar insights automáticos.")
    for cls, title, text in insights:
        st.markdown(
            f'<div class="insight {cls}"><b>{title}</b><br>{text}</div>',
            unsafe_allow_html=True,
        )

    if not wf.empty:
        weekly = (
            wf.assign(week=wf["date"].dt.tz_convert(None).dt.to_period("W-MON").astype(str))
            .groupby("week", as_index=False)
            .agg(treinos=("id", "count"), minutos=("duration_min", "sum"))
        )
        fig = px.bar(weekly, x="week", y="treinos", title="Treinos por semana")
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=45, b=10))
        st.plotly_chart(fig, use_container_width=True)


with tabs[1]:
    st.subheader("Composição e medidas")

    if mdf.empty:
        st.info("Registre medidas no Hevy para preencher esta área.")
    else:
        available = [k for k in LABELS if k in mdf.columns and mdf[k].notna().any()]
        selected = st.multiselect(
            "Indicadores",
            available,
            default=[x for x in ["weight_kg", "waist", "abdomen", "fat_percent"] if x in available],
            format_func=lambda x: LABELS[x],
        )

        for key in selected:
            dd = mf[["date", key]].dropna() if key in mf else pd.DataFrame()
            if not dd.empty:
                fig = px.line(
                    dd,
                    x="date",
                    y=key,
                    markers=True,
                    title=f"{LABELS[key]} ({UNITS.get(key, 'cm')})",
                )
                fig.update_layout(height=280, margin=dict(l=10, r=10, t=45, b=10), showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

        if len(mdf) >= 2:
            rows = []
            for k in available:
                x, y = first_nonnull(mdf, k), latest_nonnull(mdf, k)
                if x is not None and y is not None:
                    rows.append({
                        "Indicador": LABELS[k],
                        "Inicial": x,
                        "Atual": y,
                        "Variação": y - x,
                        "Unidade": UNITS.get(k, "cm"),
                    })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


with tabs[2]:
    st.subheader("Performance por exercício")

    if sdf.empty:
        st.info("Sem séries retornadas pela API.")
    else:
        exercises = sorted(sdf["exercise"].dropna().unique())
        chosen = st.selectbox("Exercício", exercises)

        ex = sf[
            (sf["exercise"] == chosen)
            & (~sf["set_type"].isin(["warmup", "aquecimento"]))
        ].copy()

        if ex.empty:
            st.info("Sem dados desse exercício no período.")
        else:
            ex["day"] = ex["date"].dt.date
            daily = ex.groupby("day", as_index=False).agg(
                melhor_carga=("weight_kg", "max"),
                melhor_e1rm=("e1rm_kg", "max"),
                volume=("volume_kg", "sum"),
                series=("exercise", "size"),
            )

            x1, x2, x3 = st.columns(3)
            x1.metric(
                "Melhor carga",
                f"{daily['melhor_carga'].max():.1f} kg" if daily["melhor_carga"].notna().any() else "—",
            )
            x2.metric(
                "Melhor 1RM est.",
                f"{daily['melhor_e1rm'].max():.1f} kg" if daily["melhor_e1rm"].notna().any() else "—",
            )
            x3.metric("Sessões", len(daily))

            metric = st.segmented_control(
                "Indicador",
                ["1RM estimado", "Melhor carga", "Volume"],
                default="1RM estimado",
            )
            col = {
                "1RM estimado": "melhor_e1rm",
                "Melhor carga": "melhor_carga",
                "Volume": "volume",
            }[metric]

            fig = px.line(daily, x="day", y=col, markers=True, title=f"{chosen} — {metric}")
            fig.update_layout(height=330, margin=dict(l=10, r=10, t=45, b=10))
            st.plotly_chart(fig, use_container_width=True)

        prog = exercise_progress(sf)
        if not prog.empty:
            st.subheader("Ranking de evolução")
            show = prog.sort_values("e1rm_change_pct", ascending=False)[
                ["exercise", "sessions", "e1rm_start", "e1rm_now", "e1rm_change_pct"]
            ].copy()
            show.columns = ["Exercício", "Sessões", "1RM inicial", "1RM atual", "Variação %"]
            st.dataframe(show, use_container_width=True, hide_index=True)


with tabs[3]:
    st.subheader("Distribuição por grupo muscular")

    if sf.empty:
        st.info("Sem dados suficientes.")
    else:
        work = sf[~sf["set_type"].isin(["warmup", "aquecimento"])].copy()
        muscle = work.groupby("muscle", as_index=False).agg(
            series=("exercise", "size"),
            volume_kg=("volume_kg", "sum"),
        )
        muscle = muscle[muscle["muscle"] != "Outros"].sort_values("series", ascending=False)

        fig = px.bar(
            muscle,
            x="muscle",
            y="series",
            title="Séries registradas por grupo muscular",
        )
        fig.update_layout(height=330, margin=dict(l=10, r=10, t=45, b=10))
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            muscle.rename(columns={
                "muscle": "Grupo",
                "series": "Séries",
                "volume_kg": "Volume (kg)",
            }),
            use_container_width=True,
            hide_index=True,
        )

        st.caption("A classificação muscular é inferida pelo nome do exercício e pode exigir ajustes para exercícios com nomes incomuns.")


with tabs[4]:
    st.subheader("Aderência ao plano B-A-C-B-A")

    adhdf = weekly_adherence(wf)

    if adhdf.empty:
        st.info("Sem dados suficientes.")
    else:
        fig = px.line(
            adhdf,
            x="week",
            y="aderencia_pct",
            markers=True,
            title="Aderência semanal (%)",
            range_y=[0, 105],
        )
        fig.update_layout(height=310, margin=dict(l=10, r=10, t=45, b=10))
        st.plotly_chart(fig, use_container_width=True)

        st.dataframe(
            adhdf.rename(columns={"week": "Semana", "aderencia_pct": "Aderência %"}),
            use_container_width=True,
            hide_index=True,
        )

    if not wf.empty:
        st.subheader("Histórico recente")
        hist = wf[["date", "workout", "duration_min", "exercise_count"]].sort_values("date", ascending=False).head(30).copy()
        hist.columns = ["Data", "Treino", "Minutos", "Exercícios"]
        st.dataframe(hist, use_container_width=True, hide_index=True)


with tabs[5]:
    st.subheader("Análise integrada por IA")
    st.caption("A Groq recebe apenas dados agregados do período selecionado. Chaves e credenciais não são enviadas ao modelo.")

    if not GROQ_API_KEY:
        st.warning("Configure `GROQ_API_KEY` nos Secrets.")
    else:
        mode = st.segmented_control(
            "Tipo de análise",
            ["Geral", "Hipertrofia", "Recomposição", "Exercício"],
            default="Geral",
        )

        exercise = None
        if mode == "Exercício" and not sdf.empty:
            exercise = st.selectbox(
                "Escolha o exercício para a IA",
                sorted(sdf["exercise"].dropna().unique()),
                key="ai_exercise",
            )

        if st.button("✨ Gerar análise", use_container_width=True, type="primary"):
            try:
                payload = build_ai_payload(wf, sf, mf, period, mode, exercise)
                with st.spinner("Analisando seus dados..."):
                    st.session_state["ai_analysis"] = call_groq(payload, mode)
            except requests.HTTPError as e:
                detail = e.response.text if e.response is not None else str(e)
                st.error(f"Erro da Groq: {detail}")
            except Exception as e:
                st.error(f"Não foi possível gerar a análise: {e}")

        if st.session_state.get("ai_analysis"):
            st.markdown(st.session_state["ai_analysis"])
            st.download_button(
                "Baixar análise",
                st.session_state["ai_analysis"],
                file_name="analise_hevy.txt",
                mime="text/plain",
                use_container_width=True,
            )

st.divider()
st.caption("Painel somente leitura. Dados vêm do Hevy. Índices e estimativas servem para acompanhar tendências, não para diagnóstico clínico.")
