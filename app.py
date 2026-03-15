"""
ConPrev — Análise de Restrições  ·  Interface Web (Streamlit)
=============================================================
v4: seleção multi-UF, relatório unificado, painel de estatísticas.
"""
from __future__ import annotations
import hashlib, io, os, shutil, sys, tempfile, time, zipfile
from pathlib import Path
from unittest.mock import MagicMock
import streamlit as st

for _stub in ("tkinter","tkinter.filedialog","tkinter.messagebox"):
    sys.modules.setdefault(_stub, MagicMock())

try:
    from relatorio_restricoes_module import MUNICIPIOS_POR_UF, analisar_restricoes
    try:
        from restricoes_patches import (
            patch_analisar_restricoes, set_decl_filter, get_last_stats,
        )
        patch_analisar_restricoes()
    except Exception:
        set_decl_filter = None   # type: ignore[assignment]
        get_last_stats  = None   # type: ignore[assignment]
except Exception as _import_err:
    _IMPORT_ERROR: str | None = str(_import_err)
    MUNICIPIOS_POR_UF = {}
    analisar_restricoes = None
    set_decl_filter = None
    get_last_stats  = None
else:
    _IMPORT_ERROR = None

st.set_page_config(
    page_title="ConPrev — Análise de Restrições",
    page_icon="🛡️", layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root{
  --navy:#0B1E33; --navy2:#0f2540; --navy3:#1c3f60; --navy4:#0d2035;
  --blue:#1a6faf; --sky:#2d8fd4; --sky-dim:rgba(45,143,212,.12);
  --amber:#F29F05; --amber2:#d78904; --amber-dim:rgba(242,159,5,.12);
  --red:#d63b3b; --red-dim:rgba(214,59,59,.12);
  --green:#2a9c6b; --green-dim:rgba(42,156,107,.12);
  --yellow:#e8a020; --yellow-dim:rgba(232,160,32,.12);
  --text:#dce8f2; --text2:#b0c4d8; --muted:#7a95ad;
  --card:rgba(255,255,255,.035); --card2:rgba(255,255,255,.055);
  --border:rgba(255,255,255,.07); --border2:rgba(255,255,255,.13);
  --radius:12px;
}

/* ── Base ── */
.stApp,[data-testid="stAppViewContainer"],[data-testid="stMain"],
section[data-testid="stMain"]{background:var(--navy)!important}
[data-testid="stHeader"]{background:var(--navy2)!important;border-bottom:1px solid var(--border)!important}
html,body,.stApp,.stMarkdown,p,span,div,label,li{font-family:'Sora',sans-serif!important;color:var(--text)}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--navy)}
::-webkit-scrollbar-thumb{background:var(--navy3);border-radius:4px}

/* ── Tabs ── */
[data-baseweb="tab-list"]{background:transparent!important;border-bottom:1px solid var(--border)!important;gap:0!important}
[data-baseweb="tab"]{background:transparent!important;border:none!important;
  color:var(--muted)!important;font-size:12.5px!important;font-weight:600!important;
  padding:8px 18px!important;border-radius:8px 8px 0 0!important;
  font-family:'Sora',sans-serif!important;transition:all .15s!important}
[data-baseweb="tab"]:hover{color:var(--amber)!important;background:var(--amber-dim)!important}
[aria-selected="true"][data-baseweb="tab"]{
  color:var(--amber)!important;background:rgba(242,159,5,.08)!important;
  border-bottom:2px solid var(--amber)!important}
[data-baseweb="tab-panel"]{padding-top:12px!important}

/* ── Input ── */
.stTextInput>div>div>input{background:rgba(255,255,255,.05)!important;
  border:1px solid var(--border2)!important;border-radius:var(--radius)!important;
  color:var(--text)!important;font-size:14px!important;transition:all .2s!important}
.stTextInput>div>div>input[type="password"]{
  font-family:'IBM Plex Mono',monospace!important;letter-spacing:6px;font-size:20px!important}
.stTextInput>div>div>input:focus{border-color:var(--sky)!important;
  box-shadow:0 0 0 3px rgba(45,143,212,.18)!important}
.stTextInput>label{color:var(--muted)!important;font-size:11px!important;
  font-weight:600!important;text-transform:uppercase;letter-spacing:1px}

/* ── Botão primário ── */
.stButton>button[kind="primary"],button[data-testid="baseButton-primary"]{
  background:linear-gradient(135deg,var(--amber),var(--amber2))!important;
  color:#0B1E33!important;font-weight:700!important;border:none!important;
  border-radius:var(--radius)!important;padding:12px 28px!important;font-size:14px!important;
  font-family:'Sora',sans-serif!important;box-shadow:0 4px 16px rgba(242,159,5,.3)!important;
  transition:all .2s!important}
.stButton>button[kind="primary"]:hover{background:linear-gradient(135deg,#ffb41a,var(--amber))!important;
  box-shadow:0 6px 20px rgba(242,159,5,.45)!important;transform:translateY(-1px)!important}
.stButton>button[kind="primary"]:active{transform:scale(.98)!important}
.stButton>button[kind="primary"]:disabled{opacity:.45!important;box-shadow:none!important;transform:none!important}

/* ── Botão secundário ── */
.stButton>button:not([kind="primary"]){background:var(--card)!important;
  border:1px solid var(--border2)!important;color:var(--text2)!important;
  border-radius:8px!important;font-family:'Sora',sans-serif!important;
  font-size:13px!important;transition:all .2s!important}
.stButton>button:not([kind="primary"]):hover{border-color:var(--amber)!important;
  color:var(--amber)!important;background:var(--amber-dim)!important}

/* ── Checkbox ── */
.stCheckbox>label{color:var(--text2)!important;font-size:13px!important;cursor:pointer}
.stCheckbox{margin-bottom:2px!important}
[data-baseweb="checkbox"]>div:first-child{border-color:var(--border2)!important;
  background:transparent!important;border-radius:4px!important;transition:all .15s!important}
[data-baseweb="checkbox"][aria-checked="true"]>div:first-child{
  background:var(--amber)!important;border-color:var(--amber)!important}

/* ── Multiselect ── */
[data-baseweb="select"]>div{background:rgba(255,255,255,.05)!important;
  border:1px solid var(--border2)!important;border-radius:var(--radius)!important;
  color:var(--text)!important}
[data-baseweb="select"]>div:focus-within{border-color:var(--sky)!important;
  box-shadow:0 0 0 3px rgba(45,143,212,.18)!important}
[data-baseweb="tag"]{background:var(--sky-dim)!important;
  border:1px solid rgba(45,143,212,.3)!important;border-radius:6px!important;color:var(--sky)!important}
[data-baseweb="menu"]{background:var(--navy4)!important;
  border:1px solid var(--border2)!important;border-radius:var(--radius)!important}
[data-baseweb="menu"] li:hover{background:var(--sky-dim)!important}
.stMultiSelect>label{color:var(--muted)!important;font-size:11px!important;
  font-weight:600!important;text-transform:uppercase;letter-spacing:1px}

/* ── File uploader ── */
[data-testid="stFileUploader"]{background:rgba(255,255,255,.025)!important;
  border:1.5px dashed rgba(45,143,212,.3)!important;border-radius:var(--radius)!important;
  transition:all .2s!important}
[data-testid="stFileUploader"]:hover{border-color:rgba(45,143,212,.6)!important;
  background:var(--sky-dim)!important}
[data-testid="stFileUploader"] section,[data-testid="stFileUploaderDropzone"]{background:transparent!important}

/* ── Download ── */
.stDownloadButton>button{background:var(--green-dim)!important;color:#4dd8a0!important;
  border:1px solid rgba(42,156,107,.35)!important;border-radius:var(--radius)!important;
  font-weight:700!important;font-size:14px!important;font-family:'Sora',sans-serif!important;
  padding:13px 24px!important;box-shadow:0 4px 16px rgba(42,156,107,.2)!important;transition:all .2s!important}
.stDownloadButton>button:hover{background:rgba(42,156,107,.22)!important;
  box-shadow:0 6px 20px rgba(42,156,107,.35)!important;transform:translateY(-1px)!important}

/* ── Misc ── */
.stAlert{border-radius:var(--radius)!important}
.stCodeBlock pre,pre,code{background:rgba(5,12,22,.7)!important;color:#56e39f!important;
  font-family:'IBM Plex Mono',monospace!important;font-size:11.5px!important;
  border-radius:10px!important;border:1px solid rgba(86,227,159,.12)!important;line-height:1.65!important}
hr{border:none!important;border-top:1px solid var(--border)!important;margin:18px 0!important}
[data-testid="stSpinner"]>div{color:var(--amber)!important}
[data-testid="stExpander"]{background:var(--card)!important;
  border:1px solid var(--border)!important;border-radius:var(--radius)!important}
#MainMenu,footer,[data-testid="stDecoration"],[data-testid="stToolbar"]{display:none!important}
.block-container{padding-top:1.4rem!important;padding-bottom:2rem!important;max-width:1320px!important}

/* ── Metric cards (estatísticas) ── */
.stat-card{background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);
  border-radius:12px;padding:16px 20px;text-align:center}
.stat-value{font-size:28px;font-weight:800;line-height:1.1;font-family:'Sora',sans-serif}
.stat-label{font-size:10.5px;font-weight:600;color:#7a95ad;
  text-transform:uppercase;letter-spacing:1px;margin-top:4px}
.stat-sub{font-size:11px;color:#7a95ad;margin-top:3px}
</style>
"""
st.markdown(_CSS, unsafe_allow_html=True)

# ── Constantes ────────────────────────────────────────────────────────────────
_PWD_HASH   = "d8def52178c00ca7dd0e4a0a144cdc84d3e0c1ce48a61aacafa0ae0eccc3cb8b"
_REF_DATE   = "12/03/2026"
_UFS        = ("GO", "TO", "MS")
_DECL_OPTIONS = ["DCTF","DCTFWEB","SISOBRA","GFIP","ECF","EFD","DEFIS",
                 "DESTDA","DIRPF","PGDAS","REINF","EFD-REINF","GIA-ST","PGFN","SPED"]

def _sha256(t): return hashlib.sha256(t.encode()).hexdigest()
def _brl_fmt(v): return f"R$ {v:,.2f}".replace(",","X").replace(".",",").replace("X",".")

ss = st.session_state
ss.setdefault("authenticated",    False)
ss.setdefault("result_zip_bytes", None)
ss.setdefault("result_file_count",0)
ss.setdefault("analysis_done",    False)
ss.setdefault("last_stats",       None)

# ── Helpers UI ────────────────────────────────────────────────────────────────
def _section(title, icon="", accent="#F29F05"):
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:10px;
        padding:13px 18px 11px;background:rgba(255,255,255,.03);
        border:1px solid rgba(255,255,255,.07);border-left:3px solid {accent};
        border-radius:10px;margin-bottom:10px">
      <span style="font-size:15px">{icon}</span>
      <span style="font-size:11.5px;font-weight:700;color:#b0c4d8;
          text-transform:uppercase;letter-spacing:1.2px">{title}</span>
    </div>""", unsafe_allow_html=True)

def _pill(text, rgb="45,143,212"):
    return (f'<span style="display:inline-flex;align-items:center;font-family:'
            f'IBM Plex Mono,monospace;font-size:11px;font-weight:600;padding:2px 9px;'
            f'border-radius:20px;background:rgba({rgb},.13);'
            f'border:1px solid rgba({rgb},.28);color:rgb({rgb})">{text}</span>')

def _hr_label(label):
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;margin:16px 0 10px">'
        f'<div style="flex:1;height:1px;background:rgba(255,255,255,.06)"></div>'
        f'<span style="font-size:10.5px;font-weight:600;color:#7a95ad;'
        f'text-transform:uppercase;letter-spacing:1px">{label}</span>'
        f'<div style="flex:1;height:1px;background:rgba(255,255,255,.06)"></div>'
        f'</div>', unsafe_allow_html=True)

def _stat_card(value, label, sub="", color="#F29F05"):
    st.markdown(
        f'<div class="stat-card">'
        f'<div class="stat-value" style="color:{color}">{value}</div>'
        f'<div class="stat-label">{label}</div>'
        f'{"<div class=stat-sub>"+sub+"</div>" if sub else ""}'
        f'</div>', unsafe_allow_html=True)

# ── Login ─────────────────────────────────────────────────────────────────────
def render_login():
    _,col,_ = st.columns([1.4,1,1.4])
    with col:
        st.markdown("""
        <div style="text-align:center;margin:56px 0 32px">
          <div style="width:62px;height:62px;
              background:linear-gradient(145deg,#1a6faf,#2d8fd4);border-radius:16px;
              display:inline-flex;align-items:center;justify-content:center;font-size:28px;
              box-shadow:0 8px 32px rgba(26,111,175,.45);margin-bottom:16px">🛡️</div>
          <h2 style="font-size:24px;font-weight:800;color:#dce8f2;margin:0 0 6px">ConPrev</h2>
          <p style="font-size:11px;color:#7a95ad;letter-spacing:1.4px;text-transform:uppercase;margin:0">
            Análise de Restrições &middot; Acesso Restrito</p>
        </div>""", unsafe_allow_html=True)
        pwd = st.text_input("Senha de acesso", type="password", placeholder="••••••••")
        if st.button("Entrar", type="primary", use_container_width=True):
            if _sha256(pwd) == _PWD_HASH:
                ss.authenticated = True; st.rerun()
            else:
                st.error("⚠️ Senha incorreta. Tente novamente.")
        st.markdown('<p style="text-align:center;font-size:11px;color:#7a95ad;margin-top:22px">'
                    '🔒 Dados restritos &middot; Conprev Assessoria Municipal</p>',
                    unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────────
def render_header():
    left, right = st.columns([5,1])
    with left:
        st.markdown("""
        <div style="display:flex;align-items:center;gap:14px;padding:6px 0 2px">
          <div style="width:42px;height:42px;flex-shrink:0;
              background:linear-gradient(145deg,#1a6faf,#2d8fd4);border-radius:10px;
              display:flex;align-items:center;justify-content:center;font-size:20px;
              box-shadow:0 4px 14px rgba(26,111,175,.4)">🛡️</div>
          <div>
            <div style="font-size:18px;font-weight:800;color:#dce8f2;line-height:1.2">
              ConPrev
              <span style="font-weight:400;color:#7a95ad;font-size:14px;margin-left:6px">
                Análise de Restrições</span>
            </div>
            <div style="font-size:11px;color:#7a95ad;margin-top:2px">
              Relatórios de Restrições (RFB / PGFN) &nbsp;·&nbsp; GO &nbsp;/&nbsp; MS &nbsp;/&nbsp; TO
            </div>
          </div>
        </div>""", unsafe_allow_html=True)
    with right:
        st.markdown(
            f'<div style="text-align:right;padding-top:10px">'
            f'<span style="font-family:\'IBM Plex Mono\',monospace;font-size:10.5px;'
            f'color:#7a95ad;background:rgba(255,255,255,.04);'
            f'border:1px solid rgba(255,255,255,.08);border-radius:6px;padding:4px 10px">'
            f'Ref.&nbsp;{_REF_DATE}</span></div>', unsafe_allow_html=True)
        if st.button("↩ Sair", key="logout_btn"):
            ss.authenticated = False; ss.result_zip_bytes = None
            ss.analysis_done = False; ss.last_stats = None; st.rerun()

# ── Análise ───────────────────────────────────────────────────────────────────
def _save_uploads(files):
    tmp = Path(tempfile.mkdtemp())
    for uf in files:
        data = uf.read()
        if uf.name.lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for m in zf.namelist():
                    if m.lower().endswith(".pdf"): zf.extract(m, tmp)
        else:
            (tmp / uf.name).write_bytes(data)
    return tmp

def _zip_dir(directory):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(directory.rglob("*")):
            if p.is_file(): zf.write(p, p.relative_to(directory))
    return buf.getvalue()

def run_analysis(uploaded, municipios, log_ph, logo_bytes=None, filtro_decl=None):
    if analisar_restricoes is None:
        st.error(f"❌ Módulo não carregado: {_IMPORT_ERROR}"); return None
    if set_decl_filter:
        set_decl_filter(filtro_decl if filtro_decl else None)
    lines=[]
    def log_cb(msg):
        lines.append(str(msg)); log_ph.code("\n".join(lines), language=None)
    base=out=logo_tmp=None
    try:
        if logo_bytes:
            logo_tmp = Path(tempfile.mkdtemp()) / "logo_conprev.png"
            logo_tmp.write_bytes(logo_bytes)
            os.environ["CONPREV_LOGO"] = str(logo_tmp)
        else:
            os.environ.pop("CONPREV_LOGO",None)
        base = _save_uploads(uploaded)
        out  = Path(tempfile.mkdtemp())
        out_dir,*_ = analisar_restricoes(
            base_dir=base, municipios_escolhidos=municipios,
            incluir_subpastas=True, out_root=out, log_cb=log_cb)
        fc  = sum(1 for p in out_dir.rglob("*") if p.is_file())
        zb  = _zip_dir(out_dir)
        stats = get_last_stats() if get_last_stats else None
        log_cb(f"\n✅ Concluído — {fc} arquivo(s) gerado(s).")
        return zb, fc, stats
    except RuntimeError as e:
        st.error(f"❌ {e}"); log_cb(f"\n❌ Erro: {e}"); return None
    except Exception as e:
        st.error(f"❌ Erro inesperado: {e}"); log_cb(f"\n❌ {e}"); return None
    finally:
        for d in (base, out, logo_tmp.parent if logo_tmp else None):
            if d and d.is_dir(): shutil.rmtree(d, ignore_errors=True)

# ── Painel de estatísticas ────────────────────────────────────────────────────
def render_stats(stats: dict) -> None:
    if not stats: return
    totais = stats.get("totais", {})
    cnd    = stats.get("cnd_status", {})
    top    = stats.get("top_devedores", [])
    bd     = stats.get("decl_breakdown", {})
    por_m  = stats.get("por_municipio", [])

    st.markdown(
        '<div style="height:1px;background:linear-gradient(90deg,'
        'transparent,rgba(242,159,5,.4),transparent);margin:24px 0 20px"></div>',
        unsafe_allow_html=True)

    _section("📊 Painel de Acompanhamento", accent="#2d8fd4")

    # ── Linha 1: métricas macro ──────────────────────────────────────────────
    c1,c2,c3,c4,c5 = st.columns(5)
    n_total = stats.get("total_municipios",0)
    n_limpos = n_total - max(totais.get("muns_dev",0), totais.get("muns_maed",0),
                             totais.get("muns_omiss",0), totais.get("muns_pf",0))
    with c1: _stat_card(str(n_total),    "Municípios Analisados", color="#dce8f2")
    with c2: _stat_card(str(totais.get("muns_dev",0)),  "Com DEVEDOR",
                        sub=_brl_fmt(totais.get("v_devedor",0)), color="#d63b3b")
    with c3: _stat_card(str(totais.get("muns_maed",0)), "Com MAED",
                        sub=_brl_fmt(totais.get("v_maed",0)), color="#e8a020")
    with c4: _stat_card(str(totais.get("muns_omiss",0)), "Com Omissões",
                        sub=f"{totais.get('n_omiss',0)} itens", color="#2d8fd4")
    with c5: _stat_card(str(totais.get("muns_pf",0)), "Processo Fiscal",
                        sub=f"{totais.get('n_pf',0)} itens", color="#8b5cf6")

    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)

    # ── Linha 2: CND + Top Devedores + Declarações ──────────────────────────
    col_cnd, col_top, col_bd = st.columns([1, 1.4, 1])

    with col_cnd:
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#7a95ad;'
            'text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">'
            '🔐 Status das CNDs</p>', unsafe_allow_html=True)
        cnd_rows = [
            (cnd.get("vencidas",0), "Vencidas",       "#d63b3b"),
            (cnd.get("urgente",0),  "Vencem em 30d",  "#F29F05"),
            (cnd.get("atencao",0),  "Vencem em 90d",  "#e8a020"),
            (cnd.get("ok",0),       "Válidas (+90d)",  "#2a9c6b"),
        ]
        for n, lbl, col in cnd_rows:
            total_cnd = sum(r[0] for r in cnd_rows) or 1
            pct = n / total_cnd * 100
            st.markdown(
                f'<div style="margin-bottom:6px">'
                f'<div style="display:flex;justify-content:space-between;'
                f'font-size:11.5px;margin-bottom:2px">'
                f'<span style="color:#b0c4d8">{lbl}</span>'
                f'<span style="color:{col};font-weight:700">{n}</span></div>'
                f'<div style="background:rgba(255,255,255,.06);border-radius:4px;height:5px">'
                f'<div style="background:{col};width:{pct:.0f}%;height:5px;border-radius:4px"></div>'
                f'</div></div>', unsafe_allow_html=True)

    with col_top:
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#7a95ad;'
            'text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">'
            '🏆 Top Devedores (valor consolidado)</p>', unsafe_allow_html=True)
        if top:
            max_val = top[0]["valor"] if top else 1
            for i, r in enumerate(top[:8]):
                pct = r["valor"] / max_val * 100 if max_val else 0
                rank_col = ["#d63b3b","#d63b3b","#F29F05","#F29F05",
                            "#e8a020","#e8a020","#7a95ad","#7a95ad"][i]
                nome_short = r["nome"][:28] + ("…" if len(r["nome"])>28 else "")
                st.markdown(
                    f'<div style="margin-bottom:5px">'
                    f'<div style="display:flex;justify-content:space-between;'
                    f'font-size:11px;margin-bottom:2px">'
                    f'<span style="color:#b0c4d8">'
                    f'<span style="color:{rank_col};font-weight:700;margin-right:5px">'
                    f'#{i+1}</span>{nome_short}</span>'
                    f'<span style="color:{rank_col};font-weight:700;'
                    f'font-family:\'IBM Plex Mono\',monospace;font-size:10.5px">'
                    f'{_brl_fmt(r["valor"])}</span></div>'
                    f'<div style="background:rgba(255,255,255,.06);border-radius:3px;height:4px">'
                    f'<div style="background:{rank_col};width:{pct:.0f}%;'
                    f'height:4px;border-radius:3px;opacity:.75"></div>'
                    f'</div></div>', unsafe_allow_html=True)
        else:
            st.markdown('<p style="font-size:12px;color:#7a95ad">Nenhum devedor encontrado.</p>',
                        unsafe_allow_html=True)

    with col_bd:
        st.markdown(
            '<p style="font-size:11px;font-weight:700;color:#7a95ad;'
            'text-transform:uppercase;letter-spacing:1px;margin-bottom:8px">'
            '📋 Omissões por Declaração</p>', unsafe_allow_html=True)
        if bd:
            total_bd = sum(bd.values()) or 1
            decl_colors = {"DCTF":"#1a6faf","DCTFWEB":"#2d8fd4","SISOBRA":"#2a9c6b",
                           "GFIP":"#8b5cf6","ECF":"#10b981","PGFN":"#d63b3b"}
            for decl, cnt in list(bd.items())[:8]:
                pct = cnt / total_bd * 100
                col_d = decl_colors.get(decl, "#7a95ad")
                st.markdown(
                    f'<div style="margin-bottom:5px">'
                    f'<div style="display:flex;justify-content:space-between;'
                    f'font-size:11px;margin-bottom:2px">'
                    f'<span style="color:#b0c4d8">{decl}</span>'
                    f'<span style="color:{col_d};font-weight:700">{cnt}</span></div>'
                    f'<div style="background:rgba(255,255,255,.06);border-radius:3px;height:4px">'
                    f'<div style="background:{col_d};width:{pct:.0f}%;'
                    f'height:4px;border-radius:3px"></div>'
                    f'</div></div>', unsafe_allow_html=True)
        else:
            st.markdown('<p style="font-size:12px;color:#7a95ad">Nenhuma omissão encontrada.</p>',
                        unsafe_allow_html=True)

    # ── Tabela detalhada por município ───────────────────────────────────────
    if por_m:
        _hr_label("Detalhamento por Município")
        # Cabeçalho
        hc = st.columns([2.8, .8, 1.3, .8, 1.3, .8, .6])
        labels = ["Município","Devedor","Valor Dev.","MAED","Valor MAED","Omissões","P.F."]
        for col, lbl in zip(hc, labels):
            col.markdown(
                f'<p style="font-size:10px;font-weight:700;color:#7a95ad;'
                f'text-transform:uppercase;letter-spacing:.8px;margin:0;padding:2px 0">'
                f'{lbl}</p>', unsafe_allow_html=True)
        st.markdown(
            '<div style="height:1px;background:rgba(255,255,255,.09);margin:4px 0 6px"></div>',
            unsafe_allow_html=True)

        for i, r in enumerate(por_m):
            has_any = r["n_dev"] or r["n_maed"] or r["n_omiss"] or r["n_pf"]
            bg = "rgba(255,255,255,.025)" if i%2==0 else "transparent"
            with st.container():
                rc = st.columns([2.8,.8,1.3,.8,1.3,.8,.6])
                # Nome
                status_dot = ("🔴" if r["n_dev"]>0
                              else "🟡" if (r["n_maed"] or r["n_omiss"])>0
                              else "🟢")
                rc[0].markdown(
                    f'<p style="font-size:12px;color:#dce8f2;margin:0;padding:3px 0">'
                    f'{status_dot} {r["nome"]}</p>', unsafe_allow_html=True)
                # n_dev
                rc[1].markdown(
                    f'<p style="font-size:12px;font-weight:{"700" if r["n_dev"] else "400"};'
                    f'color:{"#d63b3b" if r["n_dev"] else "#7a95ad"};margin:0;padding:3px 0">'
                    f'{r["n_dev"] or "—"}</p>', unsafe_allow_html=True)
                # v_dev
                rc[2].markdown(
                    f'<p style="font-size:11px;font-family:\'IBM Plex Mono\',monospace;'
                    f'color:{"#d63b3b" if r["v_dev"]>0 else "#7a95ad"};margin:0;padding:3px 0">'
                    f'{"<b>"+_brl_fmt(r["v_dev"])+"</b>" if r["v_dev"]>0 else "—"}</p>',
                    unsafe_allow_html=True)
                # n_maed
                rc[3].markdown(
                    f'<p style="font-size:12px;font-weight:{"700" if r["n_maed"] else "400"};'
                    f'color:{"#e8a020" if r["n_maed"] else "#7a95ad"};margin:0;padding:3px 0">'
                    f'{r["n_maed"] or "—"}</p>', unsafe_allow_html=True)
                # v_maed
                rc[4].markdown(
                    f'<p style="font-size:11px;font-family:\'IBM Plex Mono\',monospace;'
                    f'color:{"#e8a020" if r["v_maed"]>0 else "#7a95ad"};margin:0;padding:3px 0">'
                    f'{"<b>"+_brl_fmt(r["v_maed"])+"</b>" if r["v_maed"]>0 else "—"}</p>',
                    unsafe_allow_html=True)
                # omiss
                rc[5].markdown(
                    f'<p style="font-size:12px;color:{"#2d8fd4" if r["n_omiss"] else "#7a95ad"};'
                    f'margin:0;padding:3px 0">{r["n_omiss"] or "—"}</p>',
                    unsafe_allow_html=True)
                # pf
                rc[6].markdown(
                    f'<p style="font-size:12px;color:{"#8b5cf6" if r["n_pf"] else "#7a95ad"};'
                    f'margin:0;padding:3px 0">{r["n_pf"] or "—"}</p>',
                    unsafe_allow_html=True)


# ── App principal ─────────────────────────────────────────────────────────────
def render_app():
    if _IMPORT_ERROR:
        st.error(f"❌ `relatorio_restricoes_module.py` não encontrado:\n\n`{_IMPORT_ERROR}`")
        return

    render_header()
    st.markdown(
        '<div style="height:1px;background:linear-gradient(90deg,'
        'transparent,rgba(242,159,5,.35),transparent);margin:10px 0 18px"></div>',
        unsafe_allow_html=True)

    col_left, col_right = st.columns([1.2, 1], gap="large")

    # ══════════════════════════════════════════════════════════════════════════
    # PAINEL ESQUERDO — Seleção multi-UF com tabs
    # ══════════════════════════════════════════════════════════════════════════
    with col_left:
        _section("Seleção de Municípios", "🗂", accent="#F29F05")

        # Inicializa estado por UF
        for uf in _UFS:
            sel_key = f"mun_sel_{uf}"
            if sel_key not in ss:
                ss[sel_key] = {m: False for m in MUNICIPIOS_POR_UF.get(uf,[])}

        # Contador total cross-UF
        total_sel = sum(
            sum(ss.get(f"mun_sel_{uf}",{}).values())
            for uf in _UFS
        )
        total_muns = sum(len(MUNICIPIOS_POR_UF.get(uf,[])) for uf in _UFS)
        st.markdown(
            f'<div style="margin-bottom:10px;padding:8px 14px;'
            f'background:rgba(242,159,5,.07);border:1px solid rgba(242,159,5,.18);'
            f'border-radius:8px;display:flex;justify-content:space-between;align-items:center">'
            f'<span style="font-size:12px;color:#b0c4d8">Total selecionado</span>'
            f'<span style="font-size:16px;font-weight:800;color:#F29F05">'
            f'{total_sel}</span>'
            f'<span style="font-size:11px;color:#7a95ad">de {total_muns} municípios</span>'
            f'</div>', unsafe_allow_html=True)

        # Botões globais
        gb1, gb2 = st.columns(2)
        with gb1:
            if st.button("✅ Todos (GO+TO+MS)", key="all_global", use_container_width=True):
                for uf in _UFS:
                    muns = MUNICIPIOS_POR_UF.get(uf,[])
                    ss[f"mun_sel_{uf}"] = {m: True for m in muns}
                st.rerun()
        with gb2:
            if st.button("✗ Limpar tudo", key="clr_global", use_container_width=True):
                for uf in _UFS:
                    muns = MUNICIPIOS_POR_UF.get(uf,[])
                    ss[f"mun_sel_{uf}"] = {m: False for m in muns}
                st.rerun()

        # Tabs por UF
        tab_go, tab_to, tab_ms = st.tabs(["🟡  GO  (Goiás)", "🔵  TO  (Tocantins)", "🟢  MS  (Mato Grosso do Sul)"])
        tab_map = {"GO": tab_go, "TO": tab_to, "MS": tab_ms}

        for uf in _UFS:
            with tab_map[uf]:
                muns = MUNICIPIOS_POR_UF.get(uf, [])
                sel_key = f"mun_sel_{uf}"
                n_uf_sel = sum(ss[sel_key].values())

                b1, b2, _ = st.columns([1,1,2])
                with b1:
                    if st.button(f"✅ Todos ({uf})", key=f"all_{uf}", use_container_width=True):
                        ss[sel_key] = {m: True for m in muns}; st.rerun()
                with b2:
                    if st.button(f"✗ Limpar", key=f"clr_{uf}", use_container_width=True):
                        ss[sel_key] = {m: False for m in muns}; st.rerun()

                grid = st.columns(3)
                for i, m in enumerate(muns):
                    with grid[i % 3]:
                        ss[sel_key][m] = st.checkbox(
                            m, value=ss[sel_key].get(m,False),
                            key=f"cb_{uf}_{m}")

                st.markdown(
                    f'<p style="font-size:11.5px;color:#7a95ad;margin-top:6px">'
                    f'<b style="color:#F29F05">{n_uf_sel}</b> de {len(muns)} selecionados em {uf}</p>',
                    unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════════
    # PAINEL DIREITO — Upload + Filtros
    # ══════════════════════════════════════════════════════════════════════════
    with col_right:
        _section("Upload dos Relatórios de Restrições", "📤", accent="#2d8fd4")
        uploaded = st.file_uploader(
            "PDFs ou ZIP com os relatórios", type=["pdf","zip"],
            accept_multiple_files=True, label_visibility="collapsed",
            help="Selecione os PDFs de restrições (RFB/PGFN) ou um .zip com todos.")
        if uploaded:
            n_pdf = sum(1 for f in uploaded if f.name.lower().endswith(".pdf"))
            n_zip = sum(1 for f in uploaded if f.name.lower().endswith(".zip"))
            parts = []
            if n_pdf: parts.append(f"**{n_pdf}** PDF(s)")
            if n_zip: parts.append(f"**{n_zip}** ZIP(s)")
            st.success(f"📎 Recebido: {', '.join(parts)}")

        _hr_label("Filtro · Relatório de Omissões")
        st.markdown(
            '<p style="font-size:12px;color:#7a95ad;margin:-4px 0 8px;line-height:1.55">'
            'Filtra quais declarações aparecem no <b style="color:#2d8fd4">Relatório de Omissões</b>. '
            'Vazio = todos os tipos.</p>', unsafe_allow_html=True)
        filtro_decl = st.multiselect(
            "Tipos de declaração", options=_DECL_OPTIONS, default=[],
            key="filtro_decl_select", placeholder="Todos os tipos incluídos",
            help="DCTF, DCTFWeb, SISOBRA, GFIP e outros.")
        if filtro_decl:
            pills = " ".join(_pill(t) for t in filtro_decl)
            st.markdown(
                f'<div style="margin:5px 0 2px;display:flex;flex-wrap:wrap;gap:5px;align-items:center">'
                f'<span style="font-size:11px;color:#7a95ad">Ativo:</span>{pills}</div>',
                unsafe_allow_html=True)
        else:
            st.markdown(
                '<div style="font-size:11.5px;color:#7a95ad;margin:5px 0 2px">'
                '<span style="color:#2a9c6b">●</span> Sem filtro — todas as omissões serão incluídas</div>',
                unsafe_allow_html=True)

        _hr_label("Logo para os PDFs (opcional)")
        logo_file = st.file_uploader("logo_conprev.png", type=["png"],
            key="logo_upload", label_visibility="collapsed",
            help="Aparece no cabeçalho de todos os PDFs gerados.")
        if logo_file: st.success("✓ Logo carregada")

    # ── Botão analisar ────────────────────────────────────────────────────────
    st.markdown(
        '<div style="height:1px;background:linear-gradient(90deg,'
        'transparent,rgba(255,255,255,.07),transparent);margin:20px 0 16px"></div>',
        unsafe_allow_html=True)

    # Coleta municípios selecionados de TODAS as UFs
    selected_muns = [
        m for uf in _UFS
        for m in MUNICIPIOS_POR_UF.get(uf,[])
        if ss.get(f"mun_sel_{uf}",{}).get(m,False)
    ]
    n_upl    = len(uploaded) if uploaded else 0
    can_run  = bool(selected_muns and n_upl)

    lbl_parts = []
    if selected_muns: lbl_parts.append(f"{len(selected_muns)} município(s)")
    if n_upl:         lbl_parts.append(f"{n_upl} arquivo(s)")
    if filtro_decl:   lbl_parts.append(f"filtro: {', '.join(filtro_decl)}")
    btn_label = ("🔍 Analisar — " + " · ".join(lbl_parts)) if can_run else "🔍 Analisar Restrições"

    if st.button(btn_label, type="primary", use_container_width=True, disabled=not can_run):
        ss.result_zip_bytes = None; ss.analysis_done = False; ss.last_stats = None
        logo_bytes = logo_file.read() if logo_file else None
        log_ph = st.empty()
        with st.spinner("Processando PDFs…"):
            result = run_analysis(uploaded, selected_muns, log_ph,
                                  logo_bytes=logo_bytes, filtro_decl=filtro_decl or None)
        if result:
            ss.result_zip_bytes, ss.result_file_count, ss.last_stats = result
            ss.analysis_done = True; st.rerun()

    # Dicas
    if not can_run and not ss.analysis_done:
        h1, h2 = st.columns(2)
        with h1:
            if not n_upl:
                st.markdown(
                    '<div style="text-align:center;font-size:12px;color:#7a95ad;padding:8px;'
                    'border:1px dashed rgba(255,255,255,.08);border-radius:8px">'
                    '📂 Faça upload dos PDFs para continuar</div>', unsafe_allow_html=True)
        with h2:
            if not selected_muns:
                st.markdown(
                    '<div style="text-align:center;font-size:12px;color:#7a95ad;padding:8px;'
                    'border:1px dashed rgba(255,255,255,.08);border-radius:8px">'
                    '🏙 Selecione ao menos um município</div>', unsafe_allow_html=True)

    # ── Resultado + Estatísticas ──────────────────────────────────────────────
    if ss.analysis_done and ss.result_zip_bytes:
        st.markdown(f"""
        <div style="background:linear-gradient(135deg,rgba(42,156,107,.1),rgba(42,156,107,.05));
            border:1px solid rgba(42,156,107,.25);border-left:3px solid #2a9c6b;
            border-radius:12px;padding:18px 22px;margin-top:14px">
          <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
            <span style="font-size:20px">✅</span>
            <span style="font-weight:700;color:#4dd8a0;font-size:15px">Análise concluída com sucesso</span>
            <span style="font-family:'IBM Plex Mono',monospace;font-size:11px;color:#2a9c6b;
                background:rgba(42,156,107,.15);border:1px solid rgba(42,156,107,.25);
                border-radius:5px;padding:2px 8px">{ss.result_file_count} arquivo(s)</span>
          </div>
          <div style="font-size:12.5px;color:#7a95ad;line-height:1.6">
            PDFs com <b style="color:#b0c4d8">layout visual ConPrev</b> incluindo
            <b style="color:#b0c4d8">6 relatórios gerenciais</b>:
            Devedor, MAED, Omissões, Processo Fiscal, Validade CND e
            <b style="color:#F29F05">Relatório Unificado</b> (todos os municípios num só PDF).
          </div>
        </div>""", unsafe_allow_html=True)
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        ts = time.strftime("%Y-%m-%d_%Hh%M")
        st.download_button(
            label=f"⬇️  Baixar todos os arquivos  ({ss.result_file_count} arquivo(s) — ZIP)",
            data=ss.result_zip_bytes,
            file_name=f"ConPrev_Restricoes_{ts}.zip",
            mime="application/zip", use_container_width=True)
        if st.button("🔄 Nova análise", key="reset_btn"):
            ss.result_zip_bytes = None; ss.result_file_count = 0
            ss.analysis_done = False; ss.last_stats = None; st.rerun()

        # ── Estatísticas ──────────────────────────────────────────────────────
        if ss.last_stats:
            render_stats(ss.last_stats)

# ── Entry point ───────────────────────────────────────────────────────────────
if not ss.authenticated:
    render_login()
else:
    render_app()
