# ConPrev — Análise de Restrições (Web)

Interface web para análise de Relatórios de Restrições (RFB/PGFN),
hospedável gratuitamente no **Streamlit Community Cloud**.

---

## 🗂 Estrutura do repositório

```
conprev_app/
├── app.py                          ← Interface web (este projeto)
├── relatorio_restricoes_module.py  ← Módulo de análise (seu arquivo existente)
├── requirements.txt
├── .streamlit/
│   └── config.toml                 ← Tema dark ConPrev
└── README.md
```

> ⚠️ O arquivo `relatorio_restricoes_module.py` **deve estar na raiz do repositório**
> junto com `app.py`. O módulo não precisa de nenhuma modificação.

---

## 🚀 Deploy no Streamlit Cloud (gratuito)

### 1. Crie um repositório no GitHub

```bash
git init
git add .
git commit -m "ConPrev web app"
git remote add origin https://github.com/SEU_USUARIO/conprev-restricoes.git
git push -u origin main
```

### 2. Acesse https://streamlit.io/cloud

1. Clique em **"New app"**
2. Selecione o repositório `conprev-restricoes`
3. Branch: `main`
4. Main file path: `app.py`
5. Clique em **"Deploy!"**

O deploy leva ~2 minutos. A URL gerada é algo como:
`https://seu-usuario-conprev-restricoes-app-xxxx.streamlit.app`

### 3. Senha de acesso

A senha padrão é **`conprev2026`**.

Para alterar:
```python
# Calcule o SHA-256 da nova senha e substitua _PWD_HASH em app.py
import hashlib
print(hashlib.sha256("nova_senha".encode()).hexdigest())
```

---

## 💻 Execução local

```bash
# Instalar dependências
pip install -r requirements.txt

# Rodar
streamlit run app.py
```

---

## 🖼 Logo nos PDFs gerados

Para que a logo ConPrev apareça nos PDFs, você tem duas opções:

**Opção A — Upload via interface**: ao abrir o app, faça upload da
`logo_conprev.png` no painel "Logo para os PDFs gerados".

**Opção B — Variável de ambiente** (Streamlit Cloud → Settings → Secrets):
```toml
CONPREV_LOGO = "/caminho/para/logo_conprev.png"
```

---

## 📦 O que a análise gera

Ao clicar em "Analisar", o app processa os PDFs enviados e disponibiliza
um **ZIP para download** contendo:

```
Análise de Restrições/
├── Relatórios de Restrições/
│   ├── [PDFs copiados dos municípios selecionados]
│   └── RESTRICOES_Unificado.pdf
└── Relatórios Analisados/
    ├── RELATORIO_RESTRICOES_<timestamp>.txt   ← TXT geral
    ├── RELATORIO_RESTRICOES_<MUNICIPIO>.pdf   ← PDF por município
    └── ...
```

---

## ⚠️ Limites do plano gratuito (Streamlit Cloud)

| Recurso | Limite |
|---------|--------|
| Memória RAM | ~1 GB |
| Arquivos por upload | Sem limite de quantidade |
| Tamanho total de upload | ~200 MB por sessão |
| Apps simultâneos | 3 apps públicos |

Para volumes maiores de PDF, considere o plano pago ou hospedagem própria (Railway, Render, etc.).
