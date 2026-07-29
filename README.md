# Minha Evolução Pro v3

Dashboard mobile-first de treino + nutrição + IA.

## Novidades
- Navegação: Hoje, Treinos, Nutrição, Evolução, IA e Dados.
- Filtros: Hoje, 7, 14, 30, 60, 90, 180 e 365 dias, personalizado e tudo.
- Hevy opcional; sem API, use cadastro manual.
- Cadastro manual de treinos e exercícios.
- Dieta planejada x consumida.
- Estimativa de calorias e macros por Groq.
- Mifflin–St Jeor para gasto de repouso.
- Gasto de musculação por MET (estimativa).
- Consumo x gasto e déficit estimado.
- Meta de déficit configurável.
- IA integrada preservada.
- Supabase recomendado para persistência.

## Secrets
```toml
APP_PASSWORD = "SUA_SENHA"
HEVY_API_KEY = "SUA_CHAVE_HEVY" # opcional
GROQ_API_KEY = "SUA_CHAVE_GROQ" # opcional
SUPABASE_URL = "https://SEU-PROJETO.supabase.co"
SUPABASE_KEY = "SUA_CHAVE_SUPABASE"
```

## Persistência
Sem Supabase o app usa SQLite local como fallback. No Streamlit Community Cloud, arquivos criados durante a execução não têm persistência garantida.

Para Supabase: crie um projeto, abra SQL Editor, execute `supabase_setup.sql`, adicione URL/chave aos Secrets e reinicie o app.
