# === VERSÃO CORRIGIDA: separação por CNPJ/ENTIDADE (RPPS, Câmara, etc.) ===

# ===== Helpers: CNPJ lookup + resolvedores =====
_CNPJ_LOOKUP_CACHE = {}

def _cnpj_digits(s: str) -> str:
    import re
    return re.sub(r"\D","", str(s or ""))[:14]

def _cnpj_lookup_online(cnpj_in: str) -> str:
    """Nome do CNPJ via BrasilAPI (urllib, sem dependências externas). Aceita CNPJ mascarado."""
    try:
        import os, json, urllib.request
        if os.environ.get("CONPREV_CNPJ_LOOKUP","1") == "0":
            return ""
        d = _cnpj_digits(cnpj_in)
        if len(d) != 14:
            return ""
        if d in _CNPJ_LOOKUP_CACHE:
            return _CNPJ_LOOKUP_CACHE[d]
        req = urllib.request.Request(
            f"https://brasilapi.com.br/api/cnpj/v1/{d}",
            headers={"User-Agent":"conprev-app"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8","ignore"))
                nome = (data.get("razao_social") or data.get("nome_fantasia") or "").strip()
                if nome:
                    _CNPJ_LOOKUP_CACHE[d] = nome
                    return nome
        return ""
    except Exception:
        return ""

def _is_noise_label(s: str) -> bool:
    u = (s or "").upper()
    if not u: return True
    bad = ("PÁGINA","PAGINA","RECEITA","MINIST","SECRETARIA","PROCURADORIA",
           "DIAGNÓSTICO","DIAGNOSTICO","FISCAL","INFORMAÇÕES","INFORMACOES",
           "AUTOR PEDIDO","CONTRATANTE","CNPJ:","UA DE DOMIC","ARF","RFB",
           "EMITIDA CONSIDERANDO","LIBERAÇÃO","LIBERACAO","UA DE DOMICÍLIO",
           "ENTE FEDERATIVO RESPONSÁVEL","ENTE FEDERATIVO RESPONSAVEL")
    import re
    if any(b in u for b in bad): return True
    if re.search(r"\d", u): return True
    return False

def _resolve_name_prefer_cnpj(label: str, cnpj_masked: str) -> str:
    """Sempre tenta o NOME pelo CNPJ primeiro; se falhar, usa o label."""
    nm = _cnpj_lookup_online(cnpj_masked)
    return nm or (label or "")

def _resolve_if_noise(label: str, cnpj_masked: str) -> str:
    """Se o label for ruído, substitui pelo nome do CNPJ; caso contrário mantém."""
    if _is_noise_label(label or ""):
        return _resolve_name_prefer_cnpj(label, cnpj_masked)
    return label or _cnpj_lookup_online(cnpj_masked) or ""


def _fallback_scan_processo_fiscal(lines, itens, pdf_path, current_org=None, current_cnpj=None):
    """
    Varredura: PROCESSO FISCAL (SIEF) com situação DEVEDOR.
    - Procura nº de processo (4–6 dígitos no 1º bloco).
    - Verifica "DEVEDOR" **em janela curta** (linha, anterior e próxima).
    - Exclui qualquer ocorrência com hífen após DEVEDOR ou com palavras de blacklist.
    """
    import re
    proc_re = re.compile(r'(?:^|\b)(\d{4,6}\.\d{3}\.\d{3}/\d{4}-\d{2})(?:\b|$)')
    seen = set(x.get("processo") for x in itens if x.get("tipo") == "PROCESSO FISCAL")
    NEG_BLACKLIST = ("AJUIZ", "NEGOCIAD", "SUSPENS", "JULG", "MANIFESTA", "AJUIZAVEL", "IMPUGNAC", "CREDITO", "SISPAR")

    for idx, raw in enumerate(lines):
        m = proc_re.search(raw or "")
        if not m:
            continue
        proc = m.group(1)
        if proc in seen:
            continue

        # janela curta: linha atual + anterior + próxima
        prev_l = (lines[idx-1] if idx-1 >= 0 else "") or ""
        next_l = (lines[idx+1] if idx+1 < len(lines) else "") or ""
        janela = (prev_l + " " + raw + " " + next_l).upper()

        # Regras de aceitação
        if "DEVEDOR" not in janela:
            continue
        # "DEVEDOR" puro (sem hífen logo após)
        if re.search(r'\bDEVEDOR\b-', janela):
            continue
        # Blacklist
        if any(tok in janela for tok in NEG_BLACKLIST):
            continue
        # Evitar CNPJ: 14 dígitos no match
        only_digits = re.sub(r'\D', '', proc)
        if len(only_digits) == 14:
            continue

        cnpj_display = _mask_cnpj_digits(current_cnpj) if current_cnpj else ""
        org_display  = _resolve_if_noise(current_org or "", cnpj_display) or "CNPJ do Município (sede)"
        itens.append({
            "tipo": "PROCESSO FISCAL",
            "processo": proc,
            "situacao": "DEVEDOR",
            "orgao": org_display,
            "cnpj": cnpj_display,
            "src": pdf_path.stem
        })
        seen.add(proc)

# ===== Fim helpers =====

# relatorio_restricoes_module.py — v1
# Análise de Relatórios de Restrições (RFB/PGFN) por município
# - Lê PDFs de "relatórios de restrição" e extrai linhas que contenham
#   "DEVEDOR", "MAED" ou "OMISSÃO" (case-insensitive).
# - Permite selecionar municípios (checkbox), copiar os PDFs encontrados
#   para uma pasta "Análise de Restrições", gerar um PDF Unificado,
#   gerar um TXT geral e um TXT por município, e um PDF por município
#   com cabeçalho (logo ConPrev) no mesmo estilo do módulo de FPM.
#
# Requisitos:
#   venv\\Scripts\\python.exe -m pip install PyMuPDF==1.24.11 PyPDF2==3.0.1
#
# Observação: Lista de municípios e matching de nomes baseada na mesma
# abordagem do módulo de FPM.

import os, re, time, unicodedata, shutil, difflib
from pathlib import Path
import tkinter as tk
_DLG_SINGLETON = None
_DLG_SINGLETON_ROOT = None
from tkinter import filedialog, messagebox

_missing = []
try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None
    _missing.append("PyMuPDF (pacote 'PyMuPDF')")
try:
    from PyPDF2 import PdfMerger
except Exception:
    PdfMerger = None
    _missing.append("PyPDF2")

def _warn_missing(parent):
    if not _missing:
        return False
    msg = (
        "Dependências ausentes:\n  - " + "\n  - ".join(_missing) +
        "\n\nInstale no venv do app:\nvenv\\Scripts\\python.exe -m pip install PyMuPDF==1.24.11 PyPDF2==3.0.1"
    )
    messagebox.showerror("Dependências ausentes", msg, parent=parent)
    return True

# --------- Municípios com filtro por UF ---------
MUNICIPIOS_POR_UF = {
    "GO": [
  "Amaralina",
  "Baliza",
  "Barro Alto",
  "Bela Vista de Goiás",
  "Brazabrantes",
  "Buriti Alegre",
  "Caiapônia",
  "Catalão",
  "Campinaçu",
  "Ceres",
  "Córrego do Ouro",
  "Corumba de Goiás",
  "Cristalina",
  "Crixás",
  "Edéia",
  "Goiás",
  "Goiatuba",
  "Hidrolina",
  "Itaberaí",
  "Itapaci",
  "Jaraguá",
  "Montes Claros de Goiás",
  "Nerópolis",
  "Novo Gama",
  "Paranaiguara",
  "Perolândia",
  "Pilar de Goiás",
  "Piranhas",
  "Rianápolis",
  "Rio Quente",
  "Serranópolis",
  "São Francisco de Goiás",
  "São Luís Montes Belos",
  "Teresina de Goiás",
  "Trindade",
  "Uirapuru"
],
    "TO": [
  "Aguiarnópolis",
  "Almas",
  "Bandeirantes do Tocantins",
  "Barra do Ouro",
  "Brejinho de Nazaré",
  "Cristalândia",
  "Goianorte",
  "Guaraí",
  "Jaú do Tocantins",
  "Lajeado",
  "Maurilândia do Tocantins",
  "Natividade",
  "Palmeiras do Tocantins",
  "Palmeirópolis",
  "Paraíso do Tocantins",
  "Paranã",
  "Pedro Afonso",
  "Peixe",
  "Santa Maria do Tocantins",
  "Santa Rita do Tocantins",
  "São Valério",
  "Silvanópolis"
],
    "MS": [
  "Alcinópolis",
  "Anastácio",
  "Chapadão do Sul",
  "Coxim",
  "Iguatemi",
  "Japorã",
  "Jaraguari",
  "Sete Quedas",
  "Sonora",
  "Tacuru"
],
}
MUNICIPIOS_ALL = [m for uf in ("GO","TO","MS") for m in MUNICIPIOS_POR_UF[uf]]
def normalizar(s: str) -> str:
    t = unicodedata.normalize("NFKD", str(s))
    return t.encode("ascii", "ignore").decode().lower().strip()


# --- Canonicalização para matching robusto de municípios ---
_STOPWORDS_MUN = {"de","da","do","das","dos","municipio","municipio de","municipio do","municipio da","camara","câmara","prefeitura","municipal"}

def _canon_mun(s: str) -> str:
    """Remove acentos, pontuação, stopwords ('de','da','do',...), e junta tokens sem espaços para comparação tolerante."""
    if s is None:
        return ""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii","ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    tokens = [t for t in s.split() if t and t not in _STOPWORDS_MUN]
    return "".join(tokens)

def _tokens_mun(s: str) -> set:
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii","ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return {t for t in s.split() if t and t not in _STOPWORDS_MUN}

def corresponde_municipio(base_norm: str, mun_norm: str) -> bool:
    """
    Matching tolerante entre nomes de município e nomes de arquivo:
    - Ignora 'de/da/do/das/dos', 'Câmara', 'Prefeitura', etc. (tratado em _canon_mun / _tokens_mun)
    - Tolera ausência/presença de 'de' (ex.: 'São Luís Montes Belos' vs 'São Luís de Montes Belos')
    - Tolera pequenos erros de digitação via similaridade (difflib)
    - Evita especificamente confundir a cidade de "Goiás" com municípios "de Goiás"
      (ex.: "São Francisco de Goiás").
    """
    # Regra especial para a cidade "Goiás":
    # - só considera correspondência quando o nome base, após remoção de stopwords,
    #   não traz outros termos relevantes além de "goias" (admitindo apenas o prefixo "go").
    if mun_norm == "goias":
        tok_b = _tokens_mun(base_norm)
        if "goias" not in tok_b:
            return False
        extras_permitidos = {"go"}
        significativos = {t for t in tok_b if t != "goias" and t not in extras_permitidos}
        if significativos:
            # Ex.: "sao francisco goias" -> {"sao","francisco"} => NÃO é a cidade de Goiás
            return False
        return True

    # Comparações canônicas (heurísticas originais)
    cb = _canon_mun(base_norm)
    cm = _canon_mun(mun_norm)
    if not cb or not cm:
        return False

    # Substring canônica direta
    if cm in cb:
        return True

    # Todos os tokens do município presentes no nome base (ordem flexível)
    tok_m = _tokens_mun(mun_norm)
    tok_b = _tokens_mun(base_norm)
    if tok_m and tok_m.issubset(tok_b):
        return True

    # Similaridade (fuzzy) — tolera erros leves de digitação
    ratio = difflib.SequenceMatcher(None, cm, cb).ratio()
    if ratio >= 0.90:
        return True

    # Fallback: regex antigo (mantido por compatibilidade)
    padrao = r'(^|[-_().\s])' + re.escape(mun_norm) + r'([-_().\s]|$)'
    return re.search(padrao, base_norm) is not None


def listar_pdfs(base: Path, sub=True):
    return list(base.rglob("*.pdf")) if sub else list(base.glob("*.pdf"))

# ---------- util ----------
def _find_logo_auto():
    env = os.environ.get("CONPREV_LOGO", "").strip()
    if env and Path(env).exists():
        return Path(env)

    here = Path(__file__).resolve().parent
    prioridade = here / "Arquivos" / "Logo Conprev" / "logo_conprev.png"
    if prioridade.exists():
        return prioridade

    var_dirs = [
        here / "Arquivos" / "Logo Conprev",
        here / "Arquivos" / "logo conprev",
        here / "Arquivos" / "Logo_Conprev",
        here / "Arquivos",
        here,
    ]
    padroes = ["logo_conprev*.png", "logo*conprev*.png", "logo*.png"]
    for d in var_dirs:
        if d.exists():
            for pattern in padroes:
                for p in d.glob(pattern):
                    if p.suffix.lower() == ".png" and p.is_file():
                        return p

    for sub in ["assets","imgs","images","_assets","_imgs"]:
        d = here / sub
        if d.exists():
            for p in d.glob("logo*.png"):
                if p.is_file():
                    return p
    return None

def _register_fonts(doc):
    fonts = {"regular": "Helvetica", "bold": "Helvetica-Bold"}
    try:
        from pathlib import Path as _P
        import os as _os
        win = _P(_os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        arial = win / "arial.ttf"
        arialbd = win / "arialbd.ttf"
        if arial.exists():
            fonts["regular"] = doc.insert_font(file=str(arial))
        if arialbd.exists():
            fonts["bold"] = doc.insert_font(file=str(arialbd))
    except Exception:
        pass
    return fonts



def _sanitize_filename(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^A-Za-z0-9._ -]", "", s).strip()
    s = s.replace("  ", " ")
    return s

def _unique_dir(root: Path, base_name: str) -> Path:
    out = root / base_name
    if not out.exists() or not any(out.iterdir()):
        out.mkdir(parents=True, exist_ok=True); 
        return out
    out = root / f"{base_name} - {time.strftime('%Y-%m-%d_%Hh%M')}"
    out.mkdir(parents=True, exist_ok=True); 
    return out

def _unique_path(dst: Path) -> Path:
    if not dst.exists(): 
        return dst
    stem, suf, n = dst.stem, dst.suffix, 2
    while True:
        cand = dst.with_name(f"{stem} ({n}){suf}")
        if not cand.exists(): 
            return cand
        n += 1

# ---------- Render PDF (cabecalho similar ao FPM) ----------

def _draw_header(page, logo_path: Path, titulo: str, info: str, fonts):
    W, H = page.rect.width, page.rect.height
    margin = 36
    y = margin

    # Logo + título + info
    logo_w, logo_h = 130, 60
    if logo_path and logo_path.exists():
        try:
            img_rect = fitz.Rect(margin, y, margin+logo_w, y+logo_h)
            page.insert_image(img_rect, filename=str(logo_path))
        except Exception:
            logo_w = 0

    text_x = margin + (logo_w + 12)
    page.insert_text((text_x, y+16), titulo, fontname=fonts["bold"], fontsize=16, fill=(0,0,0))
    page.insert_text((text_x, y+36), info,   fontname=fonts["regular"], fontsize=10, fill=(0,0,0))

    # Linha separadora
    y_sep = y + max(logo_h, 60) + 16
    page.draw_line((margin, y_sep), (W-margin, y_sep), color=(0,0,0), width=0.7)

    # Retorna somente x_left (margin) e y logo abaixo da linha
    y = y_sep + 16
    x_mun   = margin
    x_topic = margin
    x_obs   = margin
    return y, x_mun, x_topic, x_obs

def _render_rel_pdf(rows, out_file: Path, titulo_extra: str, logo_path: Path):
    doc = fitz.open()
    fonts = _register_fonts(doc)
    A4 = fitz.paper_rect("a4")
    page = doc.new_page(width=A4.height, height=A4.width)

    titulo   = f"RELATÓRIO DE RESTRIÇÕES {titulo_extra}"
    info     = f"Gerado em {time.strftime('%d/%m/%Y %H:%M')}  ·  Fonte: Relatórios de Restrições (RFB/PGFN)"

    y, x_mun, x_topic, x_obs = _draw_header(page, logo_path, titulo, info, fonts)
    y_bottom = A4.height - 40
    line_h = 18

    if not rows:
        page.insert_text((x_mun, y+6), "Sem ocorrências de DEVEDOR/MAED/OMISSÃO.", 
                         fontname=fonts["regular"], fontsize=12, fill=(0,0,0))
    else:
        for (m, tipo, linha) in rows:
            if y > y_bottom:
                page = doc.new_page(width=A4.height, height=A4.width)
                y, x_mun, x_topic, x_obs = _draw_header(page, logo_path, titulo, info, fonts)
            page.insert_text((x_mun,   y), m,    fontname=fonts["regular"], fontsize=11)
            page.insert_text((x_topic, y), tipo, fontname=fonts["bold"],    fontsize=11)
            page.insert_text((x_obs,   y), linha[:110], fontname=fonts["regular"], fontsize=10)
            y += line_h

    doc.save(str(out_file))
    doc.close()
    return out_file


# ---------- 
# === Helpers: Validade de CND (nome completo + parsing + cor) ==================
from datetime import datetime, date

def _parse_date_br_to_date(s: str):
    """Converte 'dd/mm/aaaa' para date; tolera strings com outros textos."""
    import re as _re
    if not s:
        return None
    m = _re.search(r"(\d{2})/(\d{2})/(\d{4})", str(s))
    if not m:
        return None
    try:
        d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return date(y, mth, d)
    except Exception:
        return None

def _extract_cnd_info_plus(pdf_path: Path):
    """
    Retorna (cnpj_masked, validade_dd/mm/aaaa, nome_entidade_legivel).

    Estratégia para o NOME:
      1) 'CNPJ: <cnpj> - <NOME>' (evita rótulos: 'Ente Federativo Responsável', 'Dados Cadastrais', etc.)
      2) Linhas fortes do topo, ignorando ruídos (INTEGRA CONTADOR, RECEITA, PGFN, etc.)
      3) Fallback 'Município: <CIDADE>' -> 'MUNICÍPIO DE <CIDADE>'
    """
    cnpj = ""
    validade = ""
    nome = ""
    try:
        import fitz, re as _re
        with fitz.open(str(pdf_path)) as doc:
            texto = []
            for i, pg in enumerate(doc):
                if i > 1:
                    break
                texto.append(pg.get_text())
            big = "\n".join(texto)

        # CNPJ
        m_cnpj = _re.search(r"CNPJ[:\s]*([0-9\.\-\/]{8,20})", big, flags=_re.I)
        if m_cnpj:
            cnpj = _mask_cnpj_digits(m_cnpj.group(1))

        # Validade
        m_val = _re.search(r"(DATA\s*DE\s*VALIDADE|VALIDADE)[:\s]*([0-9]{2}/[0-9]{2}/[0-9]{4})", big, flags=_re.I)
        if m_val:
            validade = m_val.group(2)

        # Nome pelo padrão 'CNPJ: ... - NOME'
        m_nome_dash = _re.search(
            r"CNPJ[:\s]*[0-9\.\-\/]{14,18}\s*[-–—]\s*([^\n]+)",
            big, flags=_re.I
        )
        if m_nome_dash:
            cand = m_nome_dash.group(1).strip()
            if not _re.search(r"Ente\s+Federativo|Respons[aá]vel|Dados\s+Cadastrais|Matriz|Filial|Unidade|UA\s+de\s+domic|C[oó]digo\s+da\s+UA", cand, flags=_re.I):
                nome = cand

        # Nome por linha forte (evita ruídos/headers)
        if not nome:
            linhas = [ln.strip() for ln in big.splitlines() if ln.strip()]
            def _bad(l):
                u = l.upper()
                if len(u) < 5: return True
                bad_subs = (
                    "INTEGRA CONTADOR", "MINIST", "RECEITA", "PROCURADORIA", "PGFN",
                    "RFB", "INFORMA", "PÁGINA", "PAGINA", "AUTOR PEDIDO", "CONTRATANTE",
                    "CÓDIGO DA UA", "UA DE DOMIC", "DADOS CADASTRAIS", "CERTIDÃO EMITIDA",
                    "CERTIDAO EMITIDA"
                )
                if any(b in u for b in bad_subs): return True
                return False
            for l in linhas[:80]:
                if not _bad(l):
                    nome = l; break

        # Fallback Município:
        if not nome:
            m_mun = _re.search(r"Munic[ií]pio\s*:\s*([^\n]+)", big, flags=_re.I)
            if m_mun:
                nome = "MUNICÍPIO DE " + m_mun.group(1).strip()

        nome = _re.sub(r"\s+", " ", nome or "").strip()
    except Exception:
        pass
    return cnpj, validade, nome

def _extract_cnd_info_exact(pdf_path: Path):
    """
    Extrai exatamente destes campos no PDF (1ª página, com fallback 2ª):

      - Linha de topo:  CNPJ: <número> - <NOME COMPLETO>
        -> pega o NOME COMPLETO (ex.: MUNICIPIO DE TRINDADE)

      - CNPJ do **ENTE FEDERATIVO RESPONSÁVEL**
        -> prioriza a linha "CNPJ: xx.xxx.xxx/xxxx-xx - Ente Federativo Responsável"
           (e equivalentes sem acento), porque o PDF costuma trazer antes o
           "Autor pedido" (procurador) e "Contratante" no cabeçalho.

      - 'Data de Validade: dd/mm/aaaa'

    Retorna (cnpj_masked, validade_str, nome_alvo).
    """
    cnpj = ""
    validade = ""
    nome = ""
    try:
        import fitz, re as _re

        # Lê até 2 primeiras páginas (suficiente para cabeçalho + validade)
        with fitz.open(str(pdf_path)) as doc:
            texto_paginas = []
            for i, pg in enumerate(doc):
                if i > 1:
                    break
                texto_paginas.append(pg.get_text())
            big = "\n".join(texto_paginas)

        # 1) Nome na linha de topo: "CNPJ: 01.217.538 - MUNICIPIO DE TRINDADE"
        m_nome = _re.search(
            r"(?im)^\s*CNPJ\s*:\s*([0-9\.\-\/]{8,18})\s*[-–—]\s*([^\n]+)$",
            big
        )
        if m_nome:
            cand = m_nome.group(2).strip()
            if not _re.search(r"Ente\s+Federativo|Respons[aá]vel|Dados\s+Cadastrais|Matriz|Filial|Unidade|UA\s+de\s+domic|C[oó]digo\s+da\s+UA", cand, flags=_re.I):
                nome = cand

        # 2) Data de Validade
        m_val = _re.search(r"(?im)Data\s*de\s*Validade\s*:\s*([0-9]{2}/[0-9]{2}/[0-9]{4})", big)
        if m_val:
            validade = m_val.group(1)

        # 3) CNPJ do Ente Federativo Responsável (não pegar Autor pedido)
        linhas = [ln.strip() for ln in big.splitlines() if ln.strip()]

        def _is_header_noise_line(ln: str) -> bool:
            u = (ln or "").upper()
            return ("AUTOR PEDIDO" in u) or ("CONTRATANTE" in u)

        # a) linha com "Ente Federativo Responsável"
        for ln in linhas[:200]:
            u = ln.upper()
            if ("ENTE FEDERATIVO" in u) and ("RESPONS" in u) and ("CNPJ" in u):
                m = _re.search(r"(?<!\d)(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})(?!\d)", ln)
                if m:
                    cnpj = m.group(1)
                    break

        # b) após "Dados Cadastrais da Matriz"
        if not cnpj:
            idx_dc = None
            for i, ln in enumerate(linhas[:300]):
                if "DADOS CADASTRAIS DA MATRIZ" in ln.upper():
                    idx_dc = i
                    break
            if idx_dc is not None:
                # prioriza a linha que menciona ENTE FEDERATIVO
                for ln in linhas[idx_dc: idx_dc + 60]:
                    if _is_header_noise_line(ln):
                        continue
                    u = ln.upper()
                    if ("CNPJ" in u) and ("ENTE" in u) and ("FEDERATIVO" in u):
                        m = _re.search(r"(?<!\d)(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})(?!\d)", ln)
                        if m:
                            cnpj = m.group(1)
                            break
                if not cnpj:
                    # primeiro CNPJ completo logo após o bloco, ignorando autor/contratante
                    for ln in linhas[idx_dc: idx_dc + 60]:
                        if _is_header_noise_line(ln):
                            continue
                        m = _re.search(r"(?<!\d)(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})(?!\d)", ln)
                        if m:
                            cnpj = m.group(1)
                            break

        # c) fallback: primeiro CNPJ completo fora do header de autor/contratante
        if not cnpj:
            for ln in linhas[:250]:
                if _is_header_noise_line(ln):
                    continue
                m = _re.search(r"(?<!\d)(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})(?!\d)", ln)
                if m:
                    cnpj = m.group(1)
                    break

        # 4) Fallback para nome: "Município: <nome>"
        if not nome:
            m_mun = _re.search(r"(?im)^\s*Munic[ií]pio\s*:\s*([^\n]+)$", big)
            if m_mun:
                nome = m_mun.group(1).strip()

        nome = _re.sub(r"\s+", " ", nome or "").strip()
        cnpj = _mask_cnpj_digits(cnpj) if cnpj else ""
    except Exception:
        pass

    return cnpj, validade, nome

def _cnd_days_color_tuple(days: int):
    """>90 verde; 31..90 amarelo; 1..30 laranja; <=0 vermelho"""
    if days is None:
        return (0, 0, 0)
    if days > 90:
        return (0.05, 0.55, 0.15)
    if days > 30:
        return (0.95, 0.75, 0.08)
    if days > 0:
        return (1.00, 0.45, 0.00)
    return (0.90, 0.12, 0.12)
# ==============================================================================
# Extração robusta por linhas (usa get_text("dict") com offsets) ----------

def _mask_cnpj_digits(s: str) -> str:
    d = re.sub(r"\D", "", str(s or ""))[:14]
    if len(d) != 14:
        return s or ""
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"

def _extract_itens_pdf(pdf_path: Path):
    """Extrai itens (DEVEDOR/MAED/OMISSÃO). Para OMISSÃO: captura Período e órgão/CNPJ do cabeçalho."""
    itens = []
    try:
        with fitz.open(str(pdf_path)) as doc:
            # Construir mapa CNPJ -> Órgão (linha após 'CNPJ ... vinculado')
            try:
                import re as _re
                _txt_all = []
                for _pg in doc:
                    _txt_all.append(_pg.get_text())
                _big = "\n".join(_txt_all)
                header_map = {}
                for _m in _re.finditer(r"CNPJ:\s*([\d\./\-]{14,20}).{0,160}?vinculado.*?\n([^\n]+)", _big, flags=_re.I):
                    _cn = _re.sub(r"\D", "", _m.group(1))[:14]
                    header_map[_cn] = " ".join(_m.group(2).split())
            except Exception:
                header_map = {}
            current_cnpj = None
            current_org  = None  # persiste entre páginas
            for page in doc:
                pf_inside = False
                pf_prev_proc = None
                pf_prev_loc = None
                d = page.get_text("dict")
                lines = []
                for block in d.get("blocks", []):
                    for line in block.get("lines", []):
                        text = "".join(span.get("text","") for span in line.get("spans", []))
                        text = " ".join(text.split())
                        if text:
                            lines.append(text)

                i = 0
                while i < len(lines):
                    t = lines[i]
                    U = t.upper()

                    # Cabeçalho de CNPJ + nome do órgão (mesma linha ou linha seguinte)
                    if "CNPJ" in U:
                        # Ignorar CNPJ de 'Autor pedido/Contratante' (não é o devedor do relatório)
                        if any(k in U for k in ["AUTOR PEDIDO", "CONTRATANTE"]):
                            i += 1
                            continue
                        m = re.search(r"CNPJ[:\s]*([0-9\.\-\/]{8,20})(?:\s*-\s*(.+))?", t, flags=re.I)
                        if m:
                            current_cnpj = re.sub(r"\D", "", m.group(1))
                            name_inline = (m.group(2) or "").strip()
                            name_inline = re.sub(r"\s*-?\s*CNPJ.*$", "", name_inline, flags=re.I).strip()
                            if name_inline and not re.search(r"\d", name_inline):
                                current_org = name_inline
                            else:
                                # procurar nas próximas linhas o nome do estabelecimento (só se ainda não tivermos um nome bom)
                                if not (current_org and not _is_noise_label(current_org)):
                                    for j in range(1, 5):
                                        if i + j >= len(lines): break
                                        nxt = lines[i + j].strip()
                                        if ":" in nxt:
                                            continue
                                        up  = nxt.upper()
                                        if any(k in up for k in ["MINISTÉRIO","RECEITA FEDERAL","SECRETARIA","PROCURADORIA","INFORMAÇÕES DE APOIO","INFORMACOES DE APOIO","PÁGINA","PAGINA","AUTOR PEDIDO","CONTRATANTE"]):
                                            continue
                                        if len(nxt) >= 5 and not re.search(r"\d", nxt):
                                            current_org = nxt
                                            break
                            # Se for bloco "vinculado..." (ou similares), o header_map tende a ter o NOME correto do devedor
                            if current_cnpj and isinstance(header_map, dict) and current_cnpj in header_map:
                                nm = (header_map.get(current_cnpj) or "").strip()
                                nm = re.sub(r"\s*-?\s*CNPJ.*$", "", nm, flags=re.I).strip()
                                if nm and not _is_noise_label(nm):
                                    current_org = nm

                        i += 1
                        continue

                    # DEVEDOR (igual)
                    if U == "DEVEDOR":
                        try:
                            if pf_inside:
                                i += 1
                                continue
                        except NameError:
                            pass
                        try:
                            cod_nome = lines[i-8]
                            comp = lines[i-7]; venc = lines[i-6]; orig = lines[i-5]
                            dev  = lines[i-4]; multa= lines[i-3]; juros= lines[i-2]; cons = lines[i-1]
                            if " - " in cod_nome:
                                cod, nome = cod_nome.split(" - ", 1)
                            else:
                                parts = cod_nome.split()
                                cod, nome = (parts[0], " ".join(parts[1:])) if parts else ("","")
                            itens.append({"tipo":"DEVEDOR","cod":cod,"nome":nome,"comp":comp,"venc":venc,"orig":orig,"dev":dev,"multa":multa,"juros":juros,"cons":cons,"orgao": _resolve_if_noise(current_org or "", _mask_cnpj_digits(current_cnpj) if current_cnpj else ""), "cnpj": (_mask_cnpj_digits(current_cnpj) if current_cnpj else ""), "src":pdf_path.stem})
                        except Exception:
                            itens.append({"tipo":"DEVEDOR","raw":t,"orgao": _resolve_if_noise(current_org or "", _mask_cnpj_digits(current_cnpj) if current_cnpj else ""), "cnpj": (_mask_cnpj_digits(current_cnpj) if current_cnpj else ""), "src":pdf_path.stem})
                        i += 1
                        continue

                    # MAED (igual)
                    if "MAED" in U:
                        try:
                            pa_ou_comp = lines[i+1]; venc = lines[i+2]; orig = lines[i+3]; dev  = lines[i+4]; situ = lines[i+5]
                            cod = t.split(" - ")[0].strip()
                            desc = t.split(" - ", 1)[1].strip() if " - " in t else "MAED"
                            if re.match(r"\d{2}/\d{2}/\d{4}$", pa_ou_comp):
                                comp = f"{pa_ou_comp[3:5]}/{pa_ou_comp[6:10]}"
                            else:
                                comp = pa_ou_comp
                            itens.append({"tipo":"MAED","cod":cod,"desc":desc,"comp":comp,"venc":venc,"orig":orig,"dev":dev,"situacao":situ.strip(),"orgao": (header_map.get(re.sub(r"\D","", current_cnpj or "")[:14], "") or current_org or ""), "cnpj": (_mask_cnpj_digits(current_cnpj) if current_cnpj else ""), "src": pdf_path.stem})
                        except Exception:
                            itens.append({"tipo":"MAED","raw":t,"src":pdf_path.stem,"orgao": (header_map.get(re.sub(r"\D","", current_cnpj or "")[:14], "") or current_org or ""), "cnpj": (_mask_cnpj_digits(current_cnpj) if current_cnpj else "")})
                        i += 1
                        continue

                    
                    # ---------- PROCESSO FISCAL (SIEF) ----------
                    # Entrar no bloco quando encontrar o cabeçalho
                    if ("PENDÊNCIA - PROCESSO FISCAL" in U) or ("PENDENCIA - PROCESSO FISCAL" in U) or ("PROCESSO FISCAL (SIEF)" in U):
                        pf_inside = True
                        pf_prev_proc = None
                        pf_prev_loc  = None
                        i += 1
                        continue

                    # Se achar, fora do modo bloco, uma linha única com nº de processo + DEVEDOR, captura direto
                    m_proc_inline = re.search(r"(?:\\b|^)(\\d{1,5}\\.\\d{3}\\.\\d{3}/\\d{4}-\\d{2})(?:\\b|$)", t)
                    if (m_proc_inline and "DEVEDOR" in U and not pf_inside):
                        cnpj_display = _mask_cnpj_digits(current_cnpj) if current_cnpj else ""
                        org_display  = _resolve_if_noise(current_org or "", cnpj_display) or "CNPJ do Município (sede)"
                        itens.append({"tipo":"PROCESSO FISCAL","processo": m_proc_inline.group(1),"situacao":"DEVEDOR","orgao": org_display,"cnpj": cnpj_display,"src": pdf_path.stem})
                        i += 1
                        continue

                    # Sair do bloco ao detectar outra pendência
                    if ("PENDÊNCIA -" in U or "PENDENCIA -" in U) and ("PROCESSO FISCAL" not in U):
                        pf_inside = False
                        pf_prev_proc = None
                        pf_prev_loc  = None

                    # Se dentro do bloco, capturar processo, localização e situação (DEVEDOR)
                    if pf_inside:
                        # Ignorar cabeçalhos de colunas
                        if U.strip() in ("PROCESSO","SITUAÇÃO","LOCALIZAÇÃO") or "PROCESSO SITUAÇÃO LOCALIZAÇÃO" in U:
                            i += 1
                            continue

                        # nº do processo
                        m_proc = re.search(r"(?:\\b|^)(\\d{1,5}\\.\\d{3}\\.\\d{3}/\\d{4}-\\d{2})(?:\\b|$)", t)
                        if m_proc:
                            pf_prev_proc = m_proc.group(1)
                            i += 1
                            continue

                        # Localização
                        m_loc = re.search(r"LOCALIZA[ÇC][ÃA]O[:\\s\\-]*(.+)$", U)
                        if m_loc:
                            try:
                                pf_prev_loc = lines[i].split(":",1)[1].strip()
                            except Exception:
                                pf_prev_loc = (m_loc.group(1) or "").strip()
                            i += 1
                            continue

                        # Situação: DEVEDOR
                        status_norm = _normalize_status_pf(U)
                        if ("DEVEDOR" in status_norm):
                            proc = pf_prev_proc

                            # Se não tiver processo ainda, procurar ao redor
                            if not proc:
                                # anteriores
                                for k in range(1, 10):
                                    idx = i - k
                                    if idx < 0: break
                                    m_prev = re.search(r"(?:\\b|^)(\\d{1,5}\\.\\d{3}\\.\\d{3}/\\d{4}-\\d{2})(?:\\b|$)", lines[idx])
                                    if m_prev:
                                        proc = m_prev.group(1)
                                        break
                                # seguintes
                                if not proc:
                                    for k in range(1, 10):
                                        idx = i + k
                                        if idx >= len(lines): break
                                        m_next = re.search(r"(?:\\b|^)(\\d{1,5}\\.\\d{3}\\.\\d{3}/\\d{4}-\\d{2})(?:\\b|$)", lines[idx])
                                        if m_next:
                                            proc = m_next.group(1)
                                            break

                            if proc:
                                cnpj_display = _mask_cnpj_digits(current_cnpj) if current_cnpj else ""
                                org_display  = _resolve_if_noise(current_org or "", cnpj_display) or "CNPJ do Município (sede)"
                                itens.append({
                                    "tipo": "PROCESSO FISCAL",
                                    "processo": proc,
                                    "situacao": "DEVEDOR",
                                    "localizacao": pf_prev_loc or "",
                                    "orgao": org_display,
                                    "cnpj": cnpj_display,
                                    "src": pdf_path.stem
                                })
                                pf_prev_proc = None
                                pf_prev_loc  = None
                                i += 1
                                continue
# OMISSÃO com período + órgão/CNPJ
                    if "OMISS" in U:
                        periodo = None
                        months = "JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ"
                        for k in range(1, 7):
                            if i + k >= len(lines): break
                            look = lines[i + k].strip()
                            up   = look.upper()
                            if "PERÍODO" in up or "PERIODO" in up:
                                continue
                            if re.search(rf"\b(19|20)\d{{2}}\b", up) or re.search(rf"\b({months})\b", up) or re.search(r"\d{2}/\d{4}", up):
                                periodo = look
                                break
                        cnpj_display = _mask_cnpj_digits(current_cnpj) if current_cnpj else ""
                        org_display = _resolve_if_noise(current_org or "", cnpj_display) or "CNPJ do Município (sede)"

                        itens.append({"tipo":"OMISSÃO","raw":t,"periodo":periodo or "","orgao":org_display,"cnpj":cnpj_display,"src":pdf_path.stem})
                        i += 1
                        continue

                    i += 1
    except Exception as e:
        itens.append({"tipo":"ERRO","raw":f"[ERRO AO LER] {pdf_path.name}: {e}","src":pdf_path.stem})
    
    # Fallback: se não capturou PF pelo bloco formal, tenta varredura por nº de processo + "DEVEDOR"
    try:
        _fallback_scan_processo_fiscal(lines, itens, pdf_path, current_org, current_cnpj)
    except Exception:
        pass
    return itens

# ---------- Núcleo ----------
TOKENS = ["DEVEDOR", "MAED", "OMISSÃO", "OMISSAO"]

# ---------- Parsing helpers (formatação "bonitinha") ----------
_num_pt = r"[\d\.\,]+"  # numero pt-BR


def _parse_devedor(linha: str):
    """
    Formato típico (linha única extraída do PDF):
      '3703-01 - PASEP 06/2025 25/07/2025 9.396,81 9.396,81 1.333,40 202,97 10.933,18 DEVEDOR'
    """
    s = " ".join(linha.split())
    m = re.search(
        rf"^(?P<cod>\d{{4}}-\d{{2}})\s*-\s*(?P<nome>.+?)\s+"
        rf"(?P<comp>\d{{2}}/\d{{4}})\s+(?P<venc>\d{{2}}/\d{{2}}/\d{{4}})\s+"
        rf"(?P<orig>{_num_pt})\s+(?P<dev>{_num_pt})\s+(?P<multa>{_num_pt})\s+(?P<juros>{_num_pt})\s+(?P<cons>{_num_pt})\s+DEVEDOR$",
        s, flags=re.IGNORECASE
    )
    if not m:
        return None
    return {
        "tipo": "DEVEDOR",
        "cod": m.group("cod"),
        "nome": m.group("nome"),
        "comp": m.group("comp"),
        "venc": m.group("venc"),
        "orig": m.group("orig"),
        "dev": m.group("dev"),
        "multa": m.group("multa"),
        "juros": m.group("juros"),
        "cons": m.group("cons"),
    }

def _parse_maed(linha: str):
    """
    Formato típico (linha única extraída do PDF):
      '5440-01 - MAED - DCTFWEB 01/08/2025 16/09/2025 500,00 500,00 A VENCER'
    A 1ª data é o período de apuração (pegamos MM/AAAA como competência).
    """
    s = " ".join(linha.split())
    m = re.search(
        rf"^(?P<cod>\d{{4}}-\d{{2}})\s*-\s*MAED(?:\s*-\s*DCTFWEB)?\s+"
        rf"(?P<pa>\d{{2}}/\d{{2}}/\d{{4}})\s+(?P<venc>\d{{2}}/\d{{2}}/\d{{4}})\s+"
        rf"(?P<orig>{_num_pt})\s+(?P<dev>{_num_pt})\s+(?P<situacao>[A-ZÇÃ\s]+)$",
        s, flags=re.IGNORECASE
    )
    if not m:
        # Variante: já vem '08/2025 16/09/2025 500,00 500,00 A VENCER'
        m2 = re.search(
            rf"^(?P<cod>\d{{4}}-\d{{2}})\s*-\s*MAED(?:\s*-\s*DCTFWEB)?\s+"
            rf"(?P<comp>\d{{2}}/\d{{4}})\s+(?P<venc>\d{{2}}/\d{{2}}/\d{{4}})\s+"
            rf"(?P<orig>{_num_pt})\s+(?P<dev>{_num_pt})\s+(?P<situacao>[A-ZÇÃ\s]+)$",
            s, flags=re.IGNORECASE
        )
        if not m2:
            return None
        comp = m2.group("comp")
        return {
            "tipo": "MAED",
            "cod": m2.group("cod"),
            "comp": comp,
            "venc": m2.group("venc"),
            "orig": m2.group("orig"),
            "dev": m2.group("dev"),
            "situacao": m2.group("situacao").strip(),
        }
    pa = m.group("pa")  # dd/mm/aaaa
    comp = f"{pa[3:5]}/{pa[6:10]}"
    return {
        "tipo": "MAED",
        "cod": m.group("cod"),
        "comp": comp,
        "venc": m.group("venc"),
        "orig": m.group("orig"),
        "dev": m.group("dev"),
        "situacao": m.group("situacao").strip(),
    }

def _fmt_money(v) -> str:
    """Formata valor em string pt-BR de forma resiliente."""
    if v is None:
        return "0,00"
    s = str(v).strip()
    if not s:
        return "0,00"
    if "," in s and any(ch.isdigit() for ch in s):
        return s
    try:
        num = float(s.replace(".", "").replace(",", "."))
        s = f"{num:,.2f}"
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
        return s
    except Exception:
        return s



def _format_txt_bloco(municipio: str, src_name: str, itens_struct: list) -> str:
    """
    Bloco textual do município no padrão dos exemplos do Klayton.
    Regras:
      - Título: ***{Municipio (UF)}*** ( UF vem do prefixo do arquivo fonte, ex.: "GO - Município - ..." )
      - MAED: cabeçalho "MAED – DCTFWeb", quebra de linha, "Competência: MM/AAAA • Venc.: DD/MM/AAAA",
              "Valor original: R$ X • Saldo devedor: R$ Y • Situação: Z".
      - DEVEDOR: cada linha em duas linhas: 
          "####-## – NOME — MM/AAAA (Venc. DD/MM/AAAA)"
          "Original: R$ ... • Devedor: R$ ... • Multa: R$ ... • Juros: R$ ... • Consolidado: R$ ... ."
      - Inserir o nome do arquivo fonte (sem .pdf) entre blocos, como nos exemplos.
      - Se NÃO houver MAED e NÃO houver OMISSÃO, após DEVEDOR mostrar: 
          "OMISSÃO / MAED: não aparecem no relatório de {Municipio} além das pendências acima em DEVEDOR."
      - Caso contrário, imprimir blocos "OMISSÃO:" ou "OMISSÃO: não há no relatório." separadamente.
    """
    # Detecta UF a partir do nome do arquivo (ex.: "GO - Município - X")
    uf = ""
    if src_name:
        prefix = src_name.split(" - ")[0].strip()
        if len(prefix) == 2:
            uf = f" ({prefix})"
    title = f"***{municipio}{uf}***"
    lines = [title, ""]

    maeds = [d for d in itens_struct if d.get("tipo") == "MAED"]
    devs  = [d for d in itens_struct if d.get("tipo") == "DEVEDOR"]
    omiss = [d for d in itens_struct if d.get("tipo") == "OMISSÃO"]



    # Deduplica: remove DEVEDOR que é MAED vencido (mesmo cod+comp ou textual)
    if maeds and devs:
        maed_keys = set()
        for it in maeds:
            cod_k = (str(it.get("cod") or "").strip(), str(it.get("comp") or "").strip())
            maed_keys.add(cod_k)
        def _looks_like_maed(d):
            txt = f"{d.get('nome','')} {d.get('raw','')} {d.get('cod','')}".upper()
            cod = (d.get('cod') or '').strip()
            return ("MAED" in txt) or ("DCTFWEB" in txt) or cod.startswith("5440-01")
        devs = [d for d in devs if not _looks_like_maed(d) and ((str(d.get('cod') or '').strip(), str(d.get('comp') or '').strip()) not in maed_keys)]

    # Deduplica: remove DEVEDOR que é MAED vencido (mesmo cod+comp ou textual)
    if maeds and devs:
        maed_keys = set()
        for it in maeds:
            cod_k = (str(it.get("cod") or "").strip(), str(it.get("comp") or "").strip())
            maed_keys.add(cod_k)
        def _looks_like_maed(d):
            txt = f"{d.get('nome','')} {d.get('raw','')} {d.get('cod','')}".upper()
            cod = (d.get('cod') or '').strip()
            return ("MAED" in txt) or ("DCTFWEB" in txt) or cod.startswith("5440-01")
        devs = [d for d in devs if not _looks_like_maed(d) and ((str(d.get('cod') or '').strip(), str(d.get('comp') or '').strip()) not in maed_keys)]

    # MAED
    if maeds:
        for d in maeds:
            lines += ["", "", "", "**MAED**",
                f"{d.get('cod','')} - {d.get('desc', d.get('nome', 'MAED'))}",
                f"Competência: {d.get('comp','')} • Venc.: {d.get('venc','')}",
                f"Valor original: R$ {_fmt_money(d.get('orig',''))} • Saldo devedor: R$ {_fmt_money(d.get('dev',''))} • Situação: {str(d.get('situacao','')).strip().title().replace('Devedor','DEVEDOR')} ",
                ""
            ]
        if src_name:
            lines += [src_name, "", ""]

    # DEVEDOR
    if devs:
        lines += ["", "", "", "**DEVEDOR**"]

        # Agrupa por órgão/CNPJ (ex.: Câmara vs RPPS vs sede)
        grupos = {}
        for d in devs:
            cnpj = str(d.get("cnpj","") or "")
            org  = _resolve_name_prefer_cnpj(d.get("orgao","") or "", cnpj)
            key  = (org.strip(), cnpj.strip())
            grupos.setdefault(key, [])
            grupos[key].append(d)

        for (org, cnpj), arr in sorted(grupos.items(), key=lambda kv: (kv[0][0].upper(), kv[0][1])):
            if cnpj:
                lines.append(f"- {org} (CNPJ: {cnpj})")
            else:
                lines.append(f"- {org} (CNPJ do Município)")

            for d in arr:
                lines.append(f"{d.get('cod','')} – {d.get('nome','')} — {d.get('comp','')} (Venc. {d.get('venc','')})")
                lines.append(f"Original: R$ {_fmt_money(d.get('orig',0))} • Devedor: R$ {_fmt_money(d.get('dev',0))} • Multa: R$ {_fmt_money(d.get('multa',0))} • Juros: R$ {_fmt_money(d.get('juros',0))} • Consolidado: R$ {_fmt_money(d.get('cons',0))}. ")
                lines.append("")

        if src_name and not maeds:
            lines += [src_name, "", ""]

    # OMISSÃO
    if not maeds and not omiss and devs:
        # frase combinada, igual ao exemplo de Pilar
        lines += ["", "", "", f"**OMISSÃO / MAED**: não aparecem no relatório de {municipio.split(' (')[0]} além das pendências acima em DEVEDOR.", "", ""]
    else:
        if omiss:
            lines += ["", "", "", "**OMISSÃO**:"]
            _cnpj_head = str(omiss[0].get("cnpj","") or "")
            _org_head  = _resolve_name_prefer_cnpj(omiss[0].get("orgao","") or "", _cnpj_head)
            if _cnpj_head:
                lines.append(f"- {_org_head} (CNPJ: {_cnpj_head})")
            for d in omiss:
                lines.append(f"- {d.get('raw','OMISSÃO')}")
            lines.append("")
        else:
            lines += ["", "", "", "**OMISSÃO**: não há no relatório.", "", ""]

    return "\n\n".join(lines).strip() + "\n"




def _format_pdf_bloco(doc, page, fonts, x_left, y_top, municipio: str, src_name: str, itens_struct: list, logo_path: Path, titulo: str, info: str):
    LINE_GAP = 18
    TOPIC_GAP = 36
    y = y_top
    margin = x_left

    def ensure_space(gap=LINE_GAP):
        nonlocal page, y, margin
        if y + gap > page.rect.height - 40:
            page = doc.new_page(width=page.rect.width, height=page.rect.height)
            y2, x_mun, _, _ = _draw_header(page, logo_path, titulo, info, fonts)
            margin = x_mun
            y = y2
            page.insert_text((margin, y), str(municipio), fontname=fonts["bold"], fontsize=13, fill=(0,0,0))
            y += LINE_GAP

    def write(text, bold=False, size=11, gap=LINE_GAP):
        nonlocal y
        ensure_space(gap)
        page.insert_text((margin, y), str(text), fontname=fonts["bold" if bold else "regular"], fontsize=size, fill=(0,0,0))
        y += gap

    def topic_title(title: str):
        """Título do tópico em negrito, com ':' e sem espaço extra."""
        nonlocal y
        ensure_space(LINE_GAP)
        page.insert_text((margin, y), title.rstrip(':').upper() + ":", fontname=fonts["bold"], fontsize=11, fill=(0,0,0))
        y += LINE_GAP  # desce para o texto imediatamente abaixo

    def topic_empty_line():
        """Texto padrão quando o tópico não possui itens, em uma nova linha."""
        nonlocal y
        ensure_space(LINE_GAP)
        page.insert_text((margin, y), "Não há no relatório.", fontname=fonts["regular"], fontsize=11, fill=(0,0,0))
        y += TOPIC_GAP  # espaço antes do próximo tópico

    # Cabeçalho do município
    write(f"{municipio}", bold=True, size=13, gap=LINE_GAP)

    # Particiona itens
    maeds = [d for d in itens_struct if d.get("tipo")=="MAED"]
    devs  = [d for d in itens_struct if d.get("tipo")=="DEVEDOR"]
    omiss = [d for d in itens_struct if d.get("tipo")=="OMISSÃO"]

    # ---------- MAED ----------
    topic_title("MAED")
    if maeds:
        grupos = {}
        for d in maeds:
            key = ((d.get("orgao") or "") + "|" + (d.get("cnpj") or "")).strip("|")
            grupos.setdefault(key, {"org": d.get("orgao") or "", "cnpj": d.get("cnpj") or "", "arr": []})
            grupos[key]["arr"].append(d)
        for _, g in grupos.items():
            cnpj_txt = f" (CNPJ: {g['cnpj']})" if g["cnpj"] else " (CNPJ do Município)"
            write(f"- {_resolve_name_prefer_cnpj(g['org'], g['cnpj'])}{cnpj_txt}", bold=True, gap=LINE_GAP)  # NOME + CNPJ em negrito
            for d in g["arr"]:
                write(f"· {d.get('cod', '')} - {d.get('desc', d.get('nome', 'MAED'))}", gap=LINE_GAP)
                write(f"· Competência: {d.get('comp', '')} · Venc.: {d.get('venc', '')}", gap=LINE_GAP)
                write(f"  Valor original: R$ {_fmt_money(d.get('orig', ''))} · Saldo devedor: R$ {_fmt_money(d.get('dev', ''))} · Situação: {str(d.get('situacao', '')).strip()}", gap=LINE_GAP)
        y += TOPIC_GAP
    else:
        topic_empty_line()

    # ---------- DEVEDOR ----------
    # filtro forte: remover do DEVEDOR todos que sejam MAED/DCTFWeb
    try:
        # mapa simples de competências dos MAED (02/2024 etc.)
        _maed_months = set(str(x.get('comp','')).strip() for x in maeds)
        _devs_filtrados = []
        for _d in devs:
            _cod = str(_d.get('cod') or '').strip()
            _txt = (' ' + ' '.join([str(_d.get(k) or '') for k in ('nome','descricao','raw')]) + ' ').lower()
            _comp = str(_d.get('comp') or '').strip()
            _eh_maed = False
            if _cod.startswith('5440-01'):
                _eh_maed = True
            if (' maed ' in _txt) or (' dctfweb ' in _txt) or ('maed - dctfweb' in _txt):
                _eh_maed = True
            # se a competência do DEVEDOR casar com uma competência MAED (mesmo mês/ano)
            if _comp and _comp[-7:] in _maed_months:
                _eh_maed = True
            if not _eh_maed:
                _devs_filtrados.append(_d)
        devs = _devs_filtrados
    except Exception:
        pass

    # deduplicar: remover do DEVEDOR os itens que representam MAED/DCTFWeb já listados em MAED
    try:
        maed_keys = set()
        for d in maeds:
            k = (str(d.get('cod') or '').strip(), str(d.get('comp') or '').strip(), str(d.get('venc') or '').strip())
            maed_keys.add(k)
        def _is_maed_like(dev):
            cod = (dev.get('cod') or '').strip()
            nome = (dev.get('nome') or '').upper()
            raw  = (dev.get('raw') or '').upper()
            comp = str(dev.get('comp') or '').strip()
            venc = str(dev.get('venc') or '').strip()
            if cod.startswith('5440-01'):  # código típico de MAED
                return True
            if ('MAED' in nome) or ('DCTFWEB' in nome) or ('MAED' in raw) or ('DCTFWEB' in raw):
                return True
            if (cod, comp, venc) in maed_keys:
                return True
            if (cod, comp, '') in maed_keys or ('', comp, venc) in maed_keys:
                return True
            return False
        devs = [d for d in devs if not _is_maed_like(d)]
    except Exception:
        pass

    topic_title("DEVEDOR")
    if devs:
        grupos = {}
        for d in devs:
            key = ((d.get("orgao") or "") + "|" + (d.get("cnpj") or "")).strip("|")
            grupos.setdefault(key, {"org": d.get("orgao") or "", "cnpj": d.get("cnpj") or "", "arr": []})
            grupos[key]["arr"].append(d)

        for _, g in sorted(grupos.items(), key=lambda kv: (_resolve_name_prefer_cnpj(kv[1]["org"], kv[1]["cnpj"]).upper(), kv[1]["cnpj"])):
            cnpj_txt = f" (CNPJ: {g['cnpj']})" if g["cnpj"] else " (CNPJ do Município)"
            write(f"- {_resolve_name_prefer_cnpj(g['org'], g['cnpj'])}{cnpj_txt}", bold=True, gap=LINE_GAP)
            for d in g["arr"]:
                write(f"{d.get('cod','')} – {d.get('nome','')} — {d.get('comp','')} (Venc. {d.get('venc','')})", gap=LINE_GAP)
                write(f"Original: R$ {_fmt_money(d.get('orig',''))} · Devedor: R$ {_fmt_money(d.get('dev',''))} · Multa: R$ {_fmt_money(d.get('multa',''))} · Juros: R$ {_fmt_money(d.get('juros',''))} · Consolidado: R$ {_fmt_money(d.get('cons',''))}. ", gap=LINE_GAP)
        y += TOPIC_GAP
    else:
        topic_empty_line()


    # ---------- PROCESSO FISCAL ----------
    topic_title("PROCESSO FISCAL")
    pf = [d for d in itens_struct if d.get("tipo")=="PROCESSO FISCAL"]
    if pf:
        grupos = {}
        for d in pf:
            key = ((d.get("orgao") or "") + "|" + (d.get("cnpj") or "")).strip("|")
            grupos.setdefault(key, {"org": d.get("orgao") or "", "cnpj": d.get("cnpj") or "", "arr": []})
            grupos[key]["arr"].append(d)
        for _, g in grupos.items():
            cnpj_txt = f" (CNPJ: {g['cnpj']})" if g["cnpj"] else " (CNPJ do Município)"
            write(f"- {_resolve_name_prefer_cnpj(g['org'], g['cnpj'])}{cnpj_txt}", bold=True, gap=LINE_GAP)
            for it in g["arr"]:
                write(f"· Processo: {it.get('processo','')} · Situação: {it.get('situacao','')}", gap=LINE_GAP)
        y += TOPIC_GAP
    else:
        topic_empty_line()

    # ---------- OMISSÃO ----------
    topic_title("OMISSÃO")
    if omiss:
        grupos = {}
        for d in omiss:
            key = ((d.get("orgao") or "") + "|" + (d.get("cnpj") or "")).strip("|")
            grupos.setdefault(key, {"org": d.get("orgao") or "", "cnpj": d.get("cnpj") or "", "arr": []})
            grupos[key]["arr"].append(d)
        for _, g in grupos.items():
            cnpj_txt = f" (CNPJ: {g['cnpj']})" if g["cnpj"] else " (CNPJ do Município)"
            write(f"- {_resolve_name_prefer_cnpj(g['org'], g['cnpj'])}{cnpj_txt}", bold=True, gap=LINE_GAP)  # NOME + CNPJ em negrito
            for it in g["arr"]:
                per = (it.get('periodo') or '').strip()
                write(f"· Período de Apuração: {per if per else '(não identificado)'}", gap=LINE_GAP)
        y += TOPIC_GAP
    else:
        topic_empty_line()

    return page
def _iter_ocorrencias_pdf(pdf_path: Path):
    """Retorna lista de strings (linhas) do PDF que contêm os tokens desejados."""
    out = []
    try:
        with fitz.open(str(pdf_path)) as doc:
            for page in doc:
                pf_inside = False
                pf_prev_proc = None
                pf_prev_loc = None
                texto = page.get_text("text")
                for raw in texto.splitlines():
                    U = raw.upper()
                    if any(t in U for t in TOKENS):
                        linha = " ".join(raw.split())
                        out.append(linha)
    except Exception as e:
        out.append(f"[ERRO AO LER] {pdf_path.name}: {e}")
    return out

def analisar_restricoes(base_dir: Path, municipios_escolhidos, incluir_subpastas: bool, out_root: Path, log_cb):
    """Fluxo principal:
       - Seleciona PDFs onde o nome contém o município
       - Copia para pasta de saída
       - Gera UNIFICADO.pdf
       - Gera TXT geral e TXT por município
       - Gera PDF por município (com cabeçalho/logo)
    """
    if PdfMerger is None or fitz is None:
        raise RuntimeError("Dependências ausentes: instale PyMuPDF e PyPDF2.")

    out_dir = _unique_dir(out_root, "Análise de Restrições")

    # subpastas padronizadas
    raw_dir = out_dir / "Relatórios de Restrições"
    analyzed_dir = out_dir / "Relatórios Analisados"
    raw_dir.mkdir(parents=True, exist_ok=True)
    analyzed_dir.mkdir(parents=True, exist_ok=True)

    # 1) selecionar PDFs por município
    log_cb("Escaneando PDFs...")
    selecionados = []
    mnorm = {m: normalizar(m) for m in municipios_escolhidos}
    for p in listar_pdfs(base_dir, incluir_subpastas):
        nome = normalizar(p.stem)
        for m_disp, m_norm in mnorm.items():
            if corresponde_municipio(nome, m_norm):
                selecionados.append((p, m_disp)); break
    if not selecionados:
        raise RuntimeError("Nenhum PDF correspondente aos municípios selecionados foi encontrado.")

    # 2) copiar individuais
    log_cb(f"Copiando {len(selecionados)} PDFs selecionados...")
    copiados = []
    for p, _ in selecionados:
        dst = _unique_path(raw_dir / p.name)
        try:
            shutil.copy2(p, dst); copiados.append(dst)
        except Exception as e:
            log_cb(f"[AVISO] Falha ao copiar: {p.name} ({e})")

    # 3) unificado
    log_cb("Gerando PDF unificado...")
    unificado = raw_dir  / "RESTRICOES_Unificado.pdf"
    merger = PdfMerger()
    for p in sorted(copiados, key=lambda x: normalizar(x.stem)):
        try:
            merger.append(str(p))
        except Exception as e:
            log_cb(f"[AVISO] Falha ao anexar no unificado: {p.name} ({e})")
    merger.write(str(unificado)); merger.close()

    # 4) extrair ocorrências por município (preservando src)
    log_cb("Extraindo ocorrências (DEVEDOR/MAED/OMISSÃO)...")
    ocorrencias_por_mun = {m: [] for m in municipios_escolhidos}
    fontes_por_mun = {m: None for m in municipios_escolhidos}
    for p, m in selecionados:
        itens_pdf = _extract_itens_pdf(p)
        if not fontes_por_mun[m]:
            fontes_por_mun[m] = p.stem
        for item in itens_pdf:
            ocorrencias_por_mun[m].append(item)

    # 5) TXT geral + TXT por município + PDFs por município (formato bonitinho)

    logo_final = _find_logo_auto()
    txt_geral = analyzed_dir / f"RELATORIO_RESTRICOES_{time.strftime('%Y-%m-%d_%Hh%M')}.txt"
    with open(txt_geral, "w", encoding="utf-8") as f:
        tem_algo = False
        for m in municipios_escolhidos:
            itens = ocorrencias_por_mun.get(m, [])
            src   = fontes_por_mun.get(m) or ""
            bloco = _format_txt_bloco(m, src, itens)
            f.write(bloco.strip() + "\n\n")
            if itens: tem_algo = True
        if not tem_algo:
            f.write("Nenhuma ocorrência (DEVEDOR/MAED/OMISSÃO) encontrada nos PDFs selecionados.\n")

    txts_por_mun = []
    pdfs_por_mun = []
    for m in municipios_escolhidos:
        itens = ocorrencias_por_mun.get(m, [])
        src   = fontes_por_mun.get(m) or ""
        # PDF por município (texto formatado)
        pdf_m = analyzed_dir / f"RELATORIO_RESTRICOES_{_sanitize_filename(m.replace(' ','_'))}.pdf"
        # Render em PDF
        doc = fitz.open()
        fonts = _register_fonts(doc)
        A4 = fitz.paper_rect("a4")
        page = doc.new_page(width=A4.height, height=A4.width)
        titulo = f"RELATÓRIO DE RESTRIÇÕES · {m}"
        info   = f"Gerado em {time.strftime('%d/%m/%Y %H:%M')}  ·  Fonte: Relatórios de Restrições (RFB/PGFN)"
        y, x_mun, x_topic, x_obs = _draw_header(page, _find_logo_auto(), titulo, info, fonts)
        _format_pdf_bloco(doc, page, fonts, x_mun, y, f"{m}", src, itens, _find_logo_auto(), titulo, info)
        doc.save(str(pdf_m)); doc.close()
        pdfs_por_mun.append(pdf_m)

    
    
    
    # 6) Relatórios Gerenciais (consolidados por tópico) — em PDF com logo (v4: margens, quebras e keep-together)
    try:
        ger_dir = out_dir / "Relatórios Gerenciais"
        ger_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime('%Y-%m-%d_%Hh%M')
        logo_path = _find_logo_auto()

        def _new_doc(titulo_extra: str):
            doc = fitz.open()
            fonts = _register_fonts(doc)
            A4 = fitz.paper_rect("a4")
            # Paisagem
            page = doc.new_page(width=A4.height, height=A4.width)
            titulo = f"RELATÓRIO GERENCIAL · {titulo_extra}"
            info   = f"Gerado em {time.strftime('%d/%m/%Y %H:%M')}  ·  Fonte: Relatórios de Restrições (RFB/PGFN)"
            y, x_l, _, _ = _draw_header(page, logo_path, titulo, info, fonts)
            # Margem inferior respeitando orientação da página
            y_bottom = page.rect.height - 36
            return doc, page, fonts, x_l, y, y_bottom, titulo, info

        def _new_page_with_header(doc, page, fonts, titulo, info):
            page = doc.new_page(width=page.rect.width, height=page.rect.height)
            y, x_l, _, _ = _draw_header(page, _find_logo_auto(), titulo, info, fonts)
            y_bottom = page.rect.height - 36
            return page, x_l, y, y_bottom

        # Pequena ajuda para checar espaço necessário (em linhas)
        def _need(doc, page, fonts, x_l, y, y_bottom, titulo, info, lines_needed, line_h):
            if y + lines_needed*line_h > y_bottom:
                page, x_l, y, y_bottom = _new_page_with_header(doc, page, fonts, titulo, info)
            return page, x_l, y, y_bottom

        # ---------- MAEDS (PDF) ----------
        maed_pdf = ger_dir / f"MAEDS_TODOS_{ts}.pdf"
        doc, page, fonts, x_l, y, y_bottom, titulo_hdr, info_hdr = _new_doc("MAED")
        tem_maed = False
        LINE = 18; GAP = 24

        for m in municipios_escolhidos:
            maeds = [d for d in ocorrencias_por_mun.get(m, []) if (d.get("tipo") == "MAED")]
            if not maeds:
                continue
            tem_maed = True
            # Município
            page, x_l, y, y_bottom = _need(doc, page, fonts, x_l, y, y_bottom, titulo_hdr, info_hdr, 1, LINE)
            page.insert_text((x_l, y), f"{m}", fontname=fonts["bold"], fontsize=13); y += LINE

            # Agrupar por órgão/CNPJ
            grupos = {}
            for d in maeds:
                k = ((d.get("orgao") or "") + "|" + (d.get("cnpj") or "")).strip("|")
                grupos.setdefault(k, {"org": d.get("orgao") or "", "cnpj": d.get("cnpj") or "", "arr": []})
                grupos[k]["arr"].append(d)

            for _, g in grupos.items():
                # Título do órgão
                g_title = f"- {_resolve_name_prefer_cnpj(g['org'], g['cnpj'])} " + (f"(CNPJ: {g['cnpj']})" if g["cnpj"] else "(CNPJ do Município)")
                page, x_l, y, y_bottom = _need(doc, page, fonts, x_l, y, y_bottom, titulo_hdr, info_hdr, 1, LINE)
                page.insert_text((x_l, y), g_title, fontname=fonts["bold"], fontsize=11); y += LINE

                for d in g["arr"]:
                    # Cada item usa 3 linhas -> manter junto
                    if y + 3*LINE > y_bottom:
                        page, x_l, y, y_bottom = _new_page_with_header(doc, page, fonts, titulo_hdr, info_hdr)
                        # Repetir contexto
                        page.insert_text((x_l, y), f"{m}", fontname=fonts["bold"], fontsize=13); y += LINE
                        page.insert_text((x_l, y), g_title, fontname=fonts["bold"], fontsize=11); y += LINE
                    page.insert_text((x_l, y), f"· {d.get('cod', '')} - {d.get('desc', d.get('nome', 'MAED'))}", fontname=fonts["regular"], fontsize=11); y += LINE
                    page.insert_text((x_l, y), f"· Competência: {d.get('comp', '')} · Venc.: {d.get('venc', '')}", fontname=fonts["regular"], fontsize=11); y += LINE
                    page.insert_text((x_l, y), f"  Valor original: R$ {_fmt_money(d.get('orig', ''))} · Saldo devedor: R$ {_fmt_money(d.get('dev', ''))} · Situação: {str(d.get('situacao', '')).strip()}", fontname=fonts["regular"], fontsize=11); y += LINE
            y += GAP
        if not tem_maed:
            page.insert_text((x_l, y), "Nenhum MAED encontrado nos municípios selecionados.", fontname=fonts["regular"], fontsize=12); y += LINE
        doc.save(str(maed_pdf)); doc.close()

        # ---------- OMISSÕES (PDF) ----------
        omiss_pdf = ger_dir / f"OMISSOES_TODAS_{ts}.pdf"
        doc, page, fonts, x_l, y, y_bottom, titulo_hdr, info_hdr = _new_doc("OMISSÃO")
        tem_omiss = False
        LINE = 18; GAP = 24

        for m in municipios_escolhidos:
            omiss = [d for d in ocorrencias_por_mun.get(m, []) if (d.get("tipo") == "OMISSÃO")]
            if not omiss:
                continue
            tem_omiss = True
            page, x_l, y, y_bottom = _need(doc, page, fonts, x_l, y, y_bottom, titulo_hdr, info_hdr, 1, LINE)
            page.insert_text((x_l, y), f"{m}", fontname=fonts["bold"], fontsize=13); y += LINE

            grupos = {}
            for d in omiss:
                k = ((d.get("orgao") or "") + "|" + (d.get("cnpj") or "")).strip("|")
                grupos.setdefault(k, {"org": d.get("orgao") or "", "cnpj": d.get("cnpj") or "", "arr": []})
                grupos[k]["arr"].append(d)

            for _, g in grupos.items():
                g_title = f"- {_resolve_name_prefer_cnpj(g['org'], g['cnpj'])} " + (f"(CNPJ: {g['cnpj']})" if g["cnpj"] else "(CNPJ do Município)")
                page, x_l, y, y_bottom = _need(doc, page, fonts, x_l, y, y_bottom, titulo_hdr, info_hdr, 1, LINE)
                page.insert_text((x_l, y), g_title, fontname=fonts["bold"], fontsize=11); y += LINE

                for d in g["arr"]:
                    if y + 1*LINE > y_bottom:
                        page, x_l, y, y_bottom = _new_page_with_header(doc, page, fonts, titulo_hdr, info_hdr)
                        page.insert_text((x_l, y), f"{m}", fontname=fonts["bold"], fontsize=13); y += LINE
                        page.insert_text((x_l, y), g_title, fontname=fonts["bold"], fontsize=11); y += LINE
                    per = (d.get('periodo') or '').strip() or "(período não identificado)"
                    page.insert_text((x_l, y), f"· Período de Apuração: {per}", fontname=fonts["regular"], fontsize=11); y += LINE
            y += GAP
        if not tem_omiss:
            page.insert_text((x_l, y), "Nenhuma OMISSÃO encontrada nos municípios selecionados.", fontname=fonts["regular"], fontsize=12); y += LINE
        doc.save(str(omiss_pdf)); doc.close()

        
        # ---------- PROCESSO FISCAL (PDF) ----------
        pf_pdf = ger_dir / f"PROCESSO_FISCAL_TODOS_{ts}.pdf"
        doc, page, fonts, x_l, y, y_bottom, titulo_hdr, info_hdr = _new_doc("PROCESSO FISCAL")
        tem_pf = False
        LINE = 18; GAP = 24

        for m in municipios_escolhidos:
            pf = [d for d in ocorrencias_por_mun.get(m, []) if (d.get("tipo") == "PROCESSO FISCAL")]
            if not pf:
                continue
            tem_pf = True
            page, x_l, y, y_bottom = _need(doc, page, fonts, x_l, y, y_bottom, titulo_hdr, info_hdr, 1, LINE)
            page.insert_text((x_l, y), f"{m}", fontname=fonts["bold"], fontsize=13); y += LINE

            grupos = {}
            for d in pf:
                k = ((d.get("orgao") or "") + "|" + (d.get("cnpj") or "")).strip("|")
                grupos.setdefault(k, {"org": d.get("orgao") or "", "cnpj": d.get("cnpj") or "", "arr": []})
                grupos[k]["arr"].append(d)

            for _, g in grupos.items():
                g_title = f"- {_resolve_name_prefer_cnpj(g['org'], g['cnpj'])}"
                page, x_l, y, y_bottom = _need(doc, page, fonts, x_l, y, y_bottom, titulo_hdr, info_hdr, 1, LINE)
                page.insert_text((x_l, y), g_title, fontname=fonts["bold"], fontsize=11); y += LINE

                for d in g["arr"]:
                    if y + 1*LINE > y_bottom:
                        page, x_l, y, y_bottom = _new_page_with_header(doc, page, fonts, titulo_hdr, info_hdr)
                        page.insert_text((x_l, y), f"{m}", fontname=fonts["bold"], fontsize=13); y += LINE
                        page.insert_text((x_l, y), g_title, fontname=fonts["bold"], fontsize=11); y += LINE
                    page.insert_text((x_l, y), f"· Processo: {d.get('processo','')} · Situação: {d.get('situacao','')}", fontname=fonts["regular"], fontsize=11); y += LINE
            y += GAP

        if not tem_pf:
            page.insert_text((x_l, y), "Nenhum Processo Fiscal (SIEF) com situação DEVEDOR encontrado.", fontname=fonts["regular"], fontsize=12); y += LINE
        doc.save(str(pf_pdf)); doc.close()


        # ---------- DEVEDORES (PDF) ----------
        dev_pdf = ger_dir / f"DEVEDORES_TODOS_{ts}.pdf"
        doc, page, fonts, x_l, y, y_bottom, titulo_hdr, info_hdr = _new_doc("DEVEDOR")
        tem_dev = False
        LINE = 18; GAP = 24

        for m in municipios_escolhidos:
            devs = [d for d in ocorrencias_por_mun.get(m, []) if (d.get("tipo") == "DEVEDOR")]

            # aplicar o mesmo filtro que remove MAED/DCTFWeb dos devedores
            try:
                maeds = [d for d in ocorrencias_por_mun.get(m, []) if (d.get('tipo') == 'MAED')]
                _maed_months = set(str(x.get('comp','')).strip() for x in maeds)
                _devs_filtrados = []
                for _d in devs:
                    _cod = str(_d.get('cod') or '').strip()
                    _txt = (' ' + ' '.join([str(_d.get(k) or '') for k in ('nome','descricao','raw')]) + ' ').lower()
                    _comp = str(_d.get('comp') or '').strip()
                    _eh_maed = False
                    if _cod.startswith('5440-01'):
                        _eh_maed = True
                    if (' maed ' in _txt) or (' dctfweb ' in _txt) or ('maed - dctfweb' in _txt):
                        _eh_maed = True
                    if _comp and _comp[-7:] in _maed_months:
                        _eh_maed = True
                    if not _eh_maed:
                        _devs_filtrados.append(_d)
                devs = _devs_filtrados
            except Exception:
                pass

            if not devs:
                continue
            tem_dev = True

            # Município
            page, x_l, y, y_bottom = _need(doc, page, fonts, x_l, y, y_bottom, titulo_hdr, info_hdr, 1, LINE)
            page.insert_text((x_l, y), f"{m}", fontname=fonts["bold"], fontsize=13); y += LINE

            # AGRUPAR POR (ÓRGÃO + CNPJ) — evita misturar Câmara/RPPS/Prefeitura
            grupos = {}
            for d in devs:
                k = ((d.get("orgao") or "") + "|" + (d.get("cnpj") or "")).strip("|")
                grupos.setdefault(k, {"org": d.get("orgao") or "", "cnpj": d.get("cnpj") or "", "arr": []})
                grupos[k]["arr"].append(d)

            # ordem estável: primeiro por nome, depois por CNPJ
            grupos_ordenados = sorted(
                grupos.values(),
                key=lambda g: ((_resolve_name_prefer_cnpj(g.get("org",""), g.get("cnpj","")) or "").upper(), (g.get("cnpj","") or ""))
            )

            for g in grupos_ordenados:
                g_cnpj = str(g.get("cnpj") or "").strip()
                g_org  = _resolve_name_prefer_cnpj(str(g.get("org") or "").strip(), g_cnpj)

                if g_cnpj:
                    g_title = f"- {g_org} (CNPJ: {g_cnpj})"
                else:
                    g_title = f"- {g_org} (CNPJ do Município)"

                page, x_l, y, y_bottom = _need(doc, page, fonts, x_l, y, y_bottom, titulo_hdr, info_hdr, 1, LINE)
                page.insert_text((x_l, y), g_title, fontname=fonts["bold"], fontsize=11); y += LINE

                for d in g["arr"]:
                    # cada item usa 2 linhas -> manter junto
                    if y + 2*LINE > y_bottom:
                        page, x_l, y, y_bottom = _new_page_with_header(doc, page, fonts, titulo_hdr, info_hdr)
                        # repetir contexto
                        page.insert_text((x_l, y), f"{m}", fontname=fonts["bold"], fontsize=13); y += LINE
                        page.insert_text((x_l, y), g_title, fontname=fonts["bold"], fontsize=11); y += LINE

                    page.insert_text(
                        (x_l, y),
                        f"{d.get('cod','')} – {d.get('nome','')} — {d.get('comp','')} (Venc. {d.get('venc','')})",
                        fontname=fonts["regular"], fontsize=11
                    ); y += LINE
                    page.insert_text(
                        (x_l, y),
                        f"Original: R$ {_fmt_money(d.get('orig',0))} · Devedor: R$ {_fmt_money(d.get('dev',0))} · Multa: R$ {_fmt_money(d.get('multa',0))} · Juros: R$ {_fmt_money(d.get('juros',0))} · Consolidado: R$ {_fmt_money(d.get('cons',0))}.",
                        fontname=fonts["regular"], fontsize=11
                    ); y += LINE

            y += GAP

        if not tem_dev:
            page.insert_text((x_l, y), "Nenhum DEVEDOR encontrado nos municípios selecionados (após filtrar MAED/DCTFWeb).", fontname=fonts["regular"], fontsize=12); y += LINE
        doc.save(str(dev_pdf)); doc.close()
# ---------- VALIDADE DE CND (PDF) ----------
        cnd_pdf = ger_dir / f"VALIDADE_CND_{ts}.pdf"
        doc, page, fonts, x_l, y, y_bottom, titulo_hdr, info_hdr = _new_doc("VALIDADE DE CND")
        LINE = 18; GAP = 28
        hoje = datetime.now().date()

        # Coleta linhas e ordena: mais vencido -> menos vencido
        linhas = []
        for p, m in selecionados:
            cnpj, validade, nome_entidade = _extract_cnd_info_exact(p)
            if not validade:
                continue
            dval = _parse_date_br_to_date(validade)
            dias = (dval - hoje).days if dval else None
            if dias is None:
                continue
            linhas.append({
                "municipio": (nome_entidade or m).strip(),
                "cnpj": cnpj or "-",
                "validade": validade,
                "dias": dias
            })

        # Ordena por dias (vencidos primeiro), mantendo consistência visual
        linhas.sort(key=lambda r: (r["dias"] is None, r["dias"]))

        tem_cnd = False
        for r in linhas:
            tem_cnd = True
            municipio = r["municipio"]
            cnpj = r["cnpj"]
            validade = r["validade"]
            dias = r["dias"]

            # Cada item usa 2 linhas: manter junto na mesma página
            if y + 2*LINE > y_bottom:
                page, x_l, y, y_bottom = _new_page_with_header(doc, page, fonts, titulo_hdr, info_hdr)

            # Linha 1: Nome / Estabelecimento + CNPJ (em negrito, estilo gerencial)
            head = f"- {municipio}"
            if cnpj and cnpj != "-":
                head += f" (CNPJ: {cnpj})"
            page.insert_text((x_l, y), head, fontname=fonts["bold"], fontsize=11); y += LINE

            # Linha 2: Validade + Dias (com cor existente)
            cor = _cnd_days_color_tuple(dias)
            if dias > 0:
                msg = f"{dias} dia{'s' if dias != 1 else ''}"
            elif dias == 0:
                msg = "VENCE HOJE"
            else:
                msg = f"VENCIDA há {abs(dias)} dia{'s' if abs(dias) != 1 else ''}"

            # "Validade: dd/mm/aaaa · Dias: <msg>" (aplicando cor somente no texto de dias)
            page.insert_text((x_l, y), f"  Validade: {validade} · Dias: ", fontname=fonts["regular"], fontsize=11)
            # Escreve os dias com a cor
            page.insert_text((x_l + 220, y), msg, fontname=fonts["bold"], fontsize=11, fill=cor)
            y += GAP

        if not tem_cnd:
            page.insert_text((x_l, y), "Nenhuma 'Data de Validade' encontrada nos PDFs selecionados.", fontname=fonts["regular"], fontsize=12); y += LINE

        doc.save(str(cnd_pdf)); doc.close()
    
        log_cb("Relatórios Gerenciais (PDF) gerados com sucesso.")
    except Exception as e:
        log_cb(f"[AVISO] Falha ao gerar Relatórios Gerenciais (PDF): {e}")

    except Exception as e:
        log_cb(f"[AVISO] Falha ao gerar Relatórios Gerenciais (PDF): {e}")

    log_cb(f"Concluído. Pasta de saída:\n{out_dir}")
    return out_dir, unificado, txt_geral, txts_por_mun, pdfs_por_mun


# ---------- Janela (dialog) ----------
class AnaliseRestricoesDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Análise de Relatório de Restrições (seleção por município)")
        self.configure(bg="#e6e2db"); self.resizable(True, True)
        try:
            if master is not None:
                self.transient(master); self.grab_set()
        except Exception:
            pass
        if _warn_missing(self): self.destroy(); return
        self.base_var = tk.StringVar()
        self.out_var  = tk.StringVar()
        self.sub_var  = tk.BooleanVar(value=True)
        self.mun_vars = {}
        self._build_ui()

    def _build_ui(self):
        pad = dict(padx=10, pady=8)

        # Pasta base
        f1 = tk.Frame(self, bg="#e6e2db"); f1.pack(fill="x", **pad)
        tk.Label(f1, text="Pasta base (onde estão os PDFs):", bg="#e6e2db").pack(side="left")
        tk.Entry(f1, textvariable=self.base_var).pack(side="left", fill="x", expand=True, padx=8)
        tk.Button(f1, text="Selecionar...", command=self._sel_base, bg="#12233a", fg="white").pack(side="left")

        # Pasta saída
        f2 = tk.Frame(self, bg="#e6e2db"); f2.pack(fill="x", **pad)
        tk.Label(f2, text="Pasta de saída (onde salvar):", bg="#e6e2db").pack(side="left")
        tk.Entry(f2, textvariable=self.out_var).pack(side="left", fill="x", expand=True, padx=8)
        tk.Button(f2, text="Selecionar...", command=self._sel_out, bg="#12233a", fg="white").pack(side="left")

        # Opções
        f3 = tk.Frame(self, bg="#e6e2db"); f3.pack(fill="x", **pad)
        tk.Checkbutton(f3, text="Incluir subpastas", variable=self.sub_var, bg="#e6e2db").pack(anchor="w")

        # Filtro por UF
        fuf = tk.Frame(self, bg="#e6e2db"); fuf.pack(fill="x", **pad)
        tk.Label(fuf, text="Filtrar por UF:", bg="#e6e2db").pack(side="left")
        self.uf_var = tk.StringVar(value="GO")
        for uf in ("GO","TO","MS"):
            tk.Radiobutton(fuf, text=uf, variable=self.uf_var, value=uf, bg="#e6e2db",
                           command=self._refresh_municipios).pack(side="left", padx=6)

        # Grade dinâmica
        self.fm = tk.Frame(self, bg="#e6e2db"); self.fm.pack(fill="both", expand=True, **pad)

        # BooleanVars para todos (mantém seleção ao alternar UF)
        self.mun_vars = {}
        for _uf, lista in MUNICIPIOS_POR_UF.items():
            for m in lista:
                if m not in self.mun_vars:
                    self.mun_vars[m] = tk.BooleanVar(value=False)

        # Botões de seleção
        fb = tk.Frame(self, bg="#e6e2db"); fb.pack(fill="x", **pad)
        tk.Button(fb, text="Selecionar todos (UF)", command=self._sel_all).pack(side="left")
        tk.Button(fb, text="Limpar seleção (UF)", command=self._clear).pack(side="left", padx=6)

        # Log
        fl = tk.Frame(self, bg="#e6e2db"); fl.pack(fill="both", expand=True, **pad)
        self.txt = tk.Text(fl, height=3); self.txt.pack(fill="both", expand=True)

        # Ações
        ff = tk.Frame(self, bg="#e6e2db"); ff.pack(fill="x", **pad)
        tk.Button(ff, text="Gerar Relatório (PDF/TXT)", command=self._go, bg="#f57c00", fg="white").pack(side="left", padx=4)
        tk.Button(ff, text="Fechar", command=self.destroy).pack(side="left", padx=8)

        self.minsize(980, 680)
        self._refresh_municipios()

    def _log(self, msg): self.txt.insert("end", str(msg)+"\n"); self.txt.see("end"); self.update_idletasks()
    def _sel_base(self):
        d = filedialog.askdirectory(title="Selecione a pasta base (com os relatórios de restrições)", parent=self, mustexist=True)
        if d:
            self.base_var.set(d)
            try: self.lift(); self.focus_force()
            except Exception: pass
    def _sel_out(self):
        d = filedialog.askdirectory(title="Selecione a pasta onde salvar (será criada 'Análise de Restrições')", parent=self)
        if d:
            self.out_var.set(d)
            try: self.lift(); self.focus_force()
            except Exception: pass
    def _sel_all(self):
        # Seleciona todos da UF atual
        current = MUNICIPIOS_POR_UF.get(self.uf_var.get(), [])
        for m in current:
            if m in self.mun_vars:
                self.mun_vars[m].set(True)
    def _clear(self):
        # Limpa seleção da UF atual
        current = MUNICIPIOS_POR_UF.get(self.uf_var.get(), [])
        for m in current:
            if m in self.mun_vars:
                self.mun_vars[m].set(False)
    def _refresh_municipios(self):
        """Repovoa o grid de checkboxes conforme a UF atual, mantendo seleções."""
        # Limpa o frame
        for w in list(self.fm.winfo_children()):
            try:
                w.destroy()
            except Exception:
                pass
        uf = self.uf_var.get().strip() if hasattr(self, 'uf_var') else 'GO'
        lista = MUNICIPIOS_POR_UF.get(uf, [])
        self._current_muns = list(lista)
        cols = 4
        for i, m in enumerate(lista):
            var = self.mun_vars.get(m)
            if var is None:
                var = self.mun_vars[m] = tk.BooleanVar(value=False)
            r, c = divmod(i, cols)
            tk.Checkbutton(self.fm, text=m, variable=var, bg="#e6e2db").grid(row=r, column=c, sticky="w", padx=8, pady=3)
        try:
            self.lift(); self.focus_force()
        except Exception:
            pass

    def _go(self):
        base = self.base_var.get().strip()
        if not base: messagebox.showwarning("Atenção","Selecione a pasta base.",parent=self); return
        base = Path(base)
        if not base.is_dir(): messagebox.showerror("Erro", f"Pasta inválida:\n{base}", parent=self); return
        out_root = Path(self.out_var.get().strip() or base)
        if not out_root.exists():
            try: out_root.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                messagebox.showerror("Erro", f"Não foi possível criar a pasta de saída:\n{out_root}\n{e}", parent=self); return
        municipios = [m for m,v in self.mun_vars.items() if v.get()]
        if not municipios: messagebox.showwarning("Atenção","Selecione ao menos um município.",parent=self); return

        self.txt.delete("1.0","end")
        self._log(f"Base: {base}"); self._log(f"Saída: {out_root}")
        self._log(f"Municípios: {', '.join(municipios)}"); self._log("Rodando análise...")
        try:
            pasta, unif, txt_geral, txts_muns, pdfs_muns = analisar_restricoes(base, municipios, self.sub_var.get(), out_root, self._log)
        except Exception as e:
            messagebox.showerror("Erro", f"Falha na geração:\n{e}", parent=self); return

        self._log("Concluído.")
        if messagebox.askyesno("Concluído", f"Arquivos gerados em:\n{pasta}\n\nAbrir a pasta agora?", parent=self):
            try:
                os.startfile(str(pasta))
            except Exception:
                pass


def open_relatorio_restricoes_dialog(master):
    """Abre a janela de análise como singleton (apenas uma instância)."""
    global _DLG_SINGLETON, _DLG_SINGLETON_ROOT
    try:
        # Se já existe e está viva, só traz para frente
        if _DLG_SINGLETON is not None and _DLG_SINGLETON.winfo_exists():
            try:
                _DLG_SINGLETON.deiconify(); _DLG_SINGLETON.lift(); _DLG_SINGLETON.focus_force()
            except Exception:
                pass
            return _DLG_SINGLETON

        # Criar root oculto se master não foi passado
        created_root = False
        root = master
        if root is None:
            root = tk.Tk()
            root.withdraw()
            created_root = True
            _DLG_SINGLETON_ROOT = root

        dlg = AnaliseRestricoesDialog(root)

        # garante foco e torna singleton
        _DLG_SINGLETON = dlg
        try:
            dlg.lift(); dlg.focus_force()
        except Exception:
            pass

        # Ao fechar, limpa singleton e eventualmente fecha root oculto
        def _on_close():
            global _DLG_SINGLETON, _DLG_SINGLETON_ROOT
            try:
                dlg.destroy()
            finally:
                _DLG_SINGLETON = None
                if created_root and _DLG_SINGLETON_ROOT is not None:
                    try:
                        _DLG_SINGLETON_ROOT.destroy()
                    except Exception:
                        pass
                    _DLG_SINGLETON_ROOT = None

        try:
            dlg.protocol("WM_DELETE_WINDOW", _on_close)
        except Exception:
            pass

        return dlg
    except Exception as e:
        # Falha inesperada: se criamos root, tente derrubar para não travar
        if _DLG_SINGLETON_ROOT is not None:
            try:
                _DLG_SINGLETON_ROOT.destroy()
            except Exception:
                pass
            _DLG_SINGLETON_ROOT = None
        raise
