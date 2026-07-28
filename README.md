
# Hevy — Painel de Evolução

Painel local para acompanhar **treinos + medidas corporais** usando a API oficial do Hevy.

## Segurança primeiro

A chave de API que foi publicada anteriormente deve ser **revogada** no Hevy.
Gere uma chave nova e **não a coloque em chats, prints ou arquivos compartilhados**.

O painel pede a chave em um campo de senha e não grava a chave em arquivo.

## O que o painel mostra

- Treinos registrados e frequência nos últimos 30 dias
- Duração média dos treinos
- Peso, cintura, abdômen, percentual de gordura e demais medidas do Hevy
- Variação entre primeira e última medição
- Histórico de treinos por semana
- Progressão por exercício
- Melhor carga
- Volume total
- 1RM estimado (fórmula de Epley)

## Instalação no Windows

1. Instale Python 3.11 ou superior: https://www.python.org/downloads/
2. Extraia esta pasta.
3. Dê dois cliques em `instalar.bat`.
4. Depois dê dois cliques em `abrir_painel.bat`.
5. O navegador abrirá o painel local.
6. Cole **a nova chave** da API apenas no campo da barra lateral.

## Uso

Continue registrando normalmente seus treinos e medidas no Hevy.
Clique em **Atualizar dados** no painel quando quiser atualizar os gráficos.

## Observações

- O painel é somente leitura.
- A API oficial do Hevy usa o cabeçalho `api-key`.
- A API atualmente é experimental e pode mudar.
- O endpoint de medidas permite acompanhar peso, massa magra, percentual de gordura e diversas circunferências.
