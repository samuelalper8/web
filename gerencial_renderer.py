"""
gerencial_renderer.py — Motor Visual ConPrev v3
================================================
Identidade visual completa: navy + amber, badges coloridos,
tabelas financeiras alinhadas em colunas, hierarquia tipográfica
clara, chips de urgência e separadores visuais limpos.

Paleta de design (espelha o Painel CND HTML):
    NAVY   #0B1E33  faixas de município / cabeçalho
    AMBER  #F29F05  acentos, bordas, destaques
    SKY    #2d8fd4  CNPJ, tabela-header, badge DCTFWeb
    GREEN  #2a9c6b  status ok, CND válida
    RED    #d63b3b  devedor, VENCIDA
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

try:
    import fitz
except ImportError:
    fitz = None  # type: ignore[assignment]

# ── Paleta ─────────────────────────────────────────────────────────────────
NAVY     = (0.043, 0.118, 0.200)   # #0B1E33
NAVY_LT  = (0.059, 0.157, 0.255)   # azul mais claro
AMBER    = (0.949, 0.624, 0.020)   # #F29F05
AMBER_LT = (1.000, 0.780, 0.200)   # amber claro para texto
SKY      = (0.176, 0.561, 0.831)   # #2d8fd4
GREEN    = (0.165, 0.612, 0.420)   # #2a9c6b
RED      = (0.839, 0.231, 0.231)   # #d63b3b
WHITE    = (1.0,   1.0,   1.0  )
DARK     = (0.10,  0.16,  0.24 )   # texto principal
MID      = (0.42,  0.50,  0.60 )   # texto secundário
GRAY_ROW = (0.965, 0.972, 0.983)   # linha par
GRAY_SEP = (0.875, 0.900, 0.930)   # linha separadora leve
WHITE_DIM= (0.92,  0.94,  0.97 )   # branco suave para texto em fundos escuros

# Mapeamento tipo_declaracao → cor do badge
_DECL_COLORS: dict[str, tuple] = {
    "DCTFWEB":  SKY,
    "DCTF":     NAVY_LT,
    "SISOBRA":  GREEN,
    "PGFN":     (0.55, 0.19, 0.19),
    "DIRPF":    (0.39, 0.19, 0.55),
    "DEFIS":    (0.19, 0.39, 0.55),
    "DESTDA":   (0.55, 0.39, 0.19),
    "ECF":      (0.19, 0.55, 0.39),
    "EFD":      (0.55, 0.35, 0.19),
    "GFIP":     (0.35, 0.19, 0.55),
    "PGDAS":    (0.19, 0.55, 0.55),
    "REINF":    (0.30, 0.55, 0.19),
    "EFD-REINF":(0.30, 0.55, 0.19),
    "SPED":     (0.45, 0.35, 0.55),
    "GIA-ST":   (0.55, 0.45, 0.19),
}

# Layout A4 paisagem
_W: float   = 841.89
_H: float   = 595.28
_ML: float  = 38.0    # margem esquerda
_MR: float  = 38.0    # margem direita
_HDR: float = 70.0    # altura do cabeçalho
_YBOT: float= _H - 32.0
_CW: float  = _W - _ML - _MR   # largura de conteúdo ≈ 766

_LH  = 16.0   # altura de linha
_LHS = 13.5   # altura de linha pequena
_GAP =  6.0   # espaço extra após item
_GGAP= 12.0   # espaço entre grupos/municípios


# ── Fontes ─────────────────────────────────────────────────────────────────
def _fonts() -> dict[str, str]:
    return {"r": "Helvetica", "b": "Helvetica-Bold"}


# ── Primitivas geométricas ─────────────────────────────────────────────────
def _tw(text: str, fn: str, fs: float) -> float:
    try:
        return fitz.get_text_length(text, fontname=fn, fontsize=fs)
    except Exception:
        return len(text) * fs * 0.56


def _R(x0, y0, x1, y1):
    return fitz.Rect(x0, y0, x1, y1)


def _fill(page, x0, y0, x1, y1, color, radius=None):
    page.draw_rect(_R(x0, y0, x1, y1), color=None, fill=color,
                   width=0, radius=radius)


def _stroke(page, x0, y0, x1, y1, color, width=0.8):
    page.draw_rect(_R(x0, y0, x1, y1), color=color, fill=None, width=width)


def _txt(page, x, y, s, fn, fs, fill=DARK) -> float:
    page.insert_text(fitz.Point(x, y), s, fontname=fn, fontsize=fs, fill=fill)
    return _tw(s, fn, fs)


def _hline(page, x0, y, x1, color=GRAY_SEP, w=0.5):
    page.draw_line(fitz.Point(x0, y), fitz.Point(x1, y), color=color, width=w)


def _vbar(page, x, y0, y1, color=AMBER, w=3.0):
    page.draw_line(fitz.Point(x, y0), fitz.Point(x, y1), color=color, width=w)


def _badge(page, x, y, label, bg, fg=WHITE, fs=8.0, fn="Helvetica-Bold",
           radius=2.5) -> float:
    """Desenha badge colorido arredondado. Retorna largura total."""
    ph, pv = 5.0, 2.5
    tw = _tw(label, fn, fs)
    w = tw + 2 * ph
    h = fs + 2 * pv
    _fill(page, x, y - fs, x + w, y - fs + h, bg, radius=radius)
    page.insert_text(fitz.Point(x + ph, y), label, fontname=fn, fontsize=fs, fill=fg)
    return w + 4.0


# ── Contexto de página ─────────────────────────────────────────────────────
@dataclass
class _Ctx:
    doc:   Any
    page:  Any
    fn:    dict
    titulo: str
    info:   str
    logo:   Path | None
    y:     float = field(default=0.0)
    pnum:  int   = field(default=1)

    @property
    def xl(self) -> float: return _ML
    @property
    def xr(self) -> float: return _W - _MR

    def need(self, h: float) -> None:
        if self.y + h > _YBOT:
            self._flip()

    def _flip(self) -> None:
        self.pnum += 1
        self.page = self.doc.new_page(width=_W, height=_H)
        self.y = _draw_hdr(self.page, self.fn, self.titulo,
                           self.info, self.logo, self.pnum)


# ── Cabeçalho da página ────────────────────────────────────────────────────
def _draw_hdr(page, fn, titulo, info, logo, pnum=1) -> float:
    # Fundo navy degradê simulado com dois rects sobrepostos
    _fill(page, 0, 0, _W, _HDR, NAVY)
    _fill(page, _W * 0.6, 0, _W, _HDR, (0.035, 0.098, 0.175))  # sombra à direita

    # Linha amber no rodapé do cabeçalho
    _fill(page, 0, _HDR - 2.5, _W, _HDR, AMBER)

    logo_end = _ML
    if logo and logo.exists():
        try:
            page.insert_image(_R(_ML, 10, _ML + 90, 10 + 46),
                               filename=str(logo))
            logo_end = _ML + 90 + 14
        except Exception:
            pass

    # Título
    page.insert_text(fitz.Point(logo_end, 32),
                     titulo, fontname=fn["b"], fontsize=15, fill=WHITE)
    # Subtítulo em amber claro
    page.insert_text(fitz.Point(logo_end, 51),
                     info, fontname=fn["r"], fontsize=7.5, fill=AMBER_LT)
    # Nº de página
    pg_txt = f"página {pnum}"
    page.insert_text(
        fitz.Point(_W - _MR - _tw(pg_txt, fn["r"], 8) - 2, 51),
        pg_txt, fontname=fn["r"], fontsize=8, fill=(0.5, 0.62, 0.73))

    return _HDR + 8.0


def _new_ctx(titulo_extra: str, logo: Path | None) -> _Ctx:
    if fitz is None:
        raise RuntimeError("PyMuPDF não instalado.")
    doc = fitz.open()
    fn = _fonts()
    titulo = f"RELATÓRIO GERENCIAL  ·  {titulo_extra}"
    info = (f"Gerado em {time.strftime('%d/%m/%Y às %H:%M')}"
            f"   ·   Fonte: Relatórios de Restrições (RFB / PGFN)")
    page = doc.new_page(width=_W, height=_H)
    y = _draw_hdr(page, fn, titulo, info, logo)
    return _Ctx(doc=doc, page=page, fn=fn, titulo=titulo, info=info, logo=logo, y=y)


# ── Faixa de município ─────────────────────────────────────────────────────
def _mun_strip(ctx: _Ctx, nome: str, total: int = 0) -> None:
    ctx.need(_LH + 16)
    ctx.y += 4
    strip_h = 26.0
    # Fundo navy com borda esquerda amber
    _fill(ctx.page, ctx.xl, ctx.y, ctx.xr, ctx.y + strip_h, NAVY)
    _fill(ctx.page, ctx.xl, ctx.y, ctx.xl + 3, ctx.y + strip_h, AMBER)

    # Nome do município
    _txt(ctx.page, ctx.xl + 10, ctx.y + 17.5,
         nome.upper(), ctx.fn["b"], 11.5, fill=WHITE)

    # Contador de itens (badge compacto)
    if total > 0:
        cnt = f"{total} ocorrência{'s' if total != 1 else ''}"
        cw = _tw(cnt, ctx.fn["r"], 8)
        _fill(ctx.page, ctx.xr - cw - 14, ctx.y + 7,
              ctx.xr - 4, ctx.y + 19,
              (0.09, 0.20, 0.33), radius=3.0)
        _txt(ctx.page, ctx.xr - cw - 9, ctx.y + 16.5,
             cnt, ctx.fn["r"], 8, fill=AMBER_LT)

    ctx.y += strip_h + 4


# ── Cabeçalho de entidade ──────────────────────────────────────────────────
def _entity_hdr(ctx: _Ctx, orgao: str, cnpj: str) -> None:
    ctx.need(30)
    ctx.y += 2
    # Linha vertical amber + fundo suave
    _fill(ctx.page, ctx.xl, ctx.y, ctx.xr, ctx.y + (26 if cnpj else 18),
          (0.97, 0.97, 0.99))
    _vbar(ctx.page, ctx.xl + 1.5, ctx.y, ctx.y + (26 if cnpj else 18))

    _txt(ctx.page, ctx.xl + 9, ctx.y + 12,
         orgao[:88], ctx.fn["b"], 10.0, fill=DARK)
    if cnpj:
        _txt(ctx.page, ctx.xl + 9, ctx.y + 23,
             f"CNPJ:  {cnpj}", ctx.fn["r"], 8.0, fill=SKY)
        ctx.y += 30
    else:
        ctx.y += 22


# ── Helpers monetários ─────────────────────────────────────────────────────
def _fmt(v: Any) -> str:
    if v is None: return "0,00"
    s = str(v).strip()
    if "," in s: return s
    try:
        n = float(s.replace(".", "").replace(",", "."))
        return f"{n:,.2f}".replace(",","X").replace(".","," ).replace("X",".")
    except Exception:
        return s or "0,00"


def _brl(s: Any) -> float:
    try: return float(str(s).replace(".","").replace(",","."))
    except Exception: return 0.0


# ── Item DEVEDOR ───────────────────────────────────────────────────────────
def _devedor_row(ctx: _Ctx, d: dict, alt: bool) -> None:
    ctx.need(40)
    y0 = ctx.y - _LH + 2
    if alt:
        _fill(ctx.page, ctx.xl, y0, ctx.xr, y0 + 38, GRAY_ROW)

    fn, x = ctx.fn, ctx.xl + 6

    # ── Linha 1: código + nome + comp/venc ─────────────────────────────
    cod  = str(d.get("cod",""))
    nome = str(d.get("nome",""))
    comp = str(d.get("comp",""))
    venc = str(d.get("venc",""))

    # Badge de código
    bw = _badge(ctx.page, x, ctx.y, cod, NAVY, WHITE, fs=7.5, fn=fn["b"])

    # Nome do tributo
    max_nome = 52
    nome_disp = (nome[:max_nome] + "…") if len(nome) > max_nome else nome
    _txt(ctx.page, x + bw, ctx.y, nome_disp, fn["r"], 9.0, fill=DARK)

    # Comp + venc à direita
    cv = f"{comp}  ·  Venc. {venc}"
    cw = _tw(cv, fn["r"], 8.0)
    _txt(ctx.page, ctx.xr - cw - 4, ctx.y, cv, fn["r"], 8.0, fill=MID)
    ctx.y += _LH

    # ── Linha 2: tabela financeira compacta ─────────────────────────────
    orig  = _fmt(d.get("orig"))
    dev   = _fmt(d.get("dev"))
    multa = _fmt(d.get("multa"))
    juros = _fmt(d.get("juros"))
    cons  = _fmt(d.get("cons"))
    dev_val = _brl(d.get("dev"))
    residual = d.get("residual", False)

    # Colunas: Original | Devedor | Multa | Juros | Consolidado
    cols = [
        ("Original",    orig,  MID,  False),
        ("Devedor",     dev,   (0.72,0.20,0.20) if dev_val>0 and not residual else MID, True),
        ("Multa",       multa, MID,  False),
        ("Juros",       juros, MID,  False),
        ("Consolidado", cons,  DARK, True),
    ]
    # Larguras proporcionais (total = _CW - 8)
    col_ws = [108, 108, 100, 100, 120]
    xc = x
    for (lbl, val, col, bold), cw in zip(cols, col_ws):
        _txt(ctx.page, xc, ctx.y - 1,
             lbl, fn["r"], 7.0, fill=(0.55, 0.62, 0.70))
        _txt(ctx.page, xc, ctx.y + 8,
             f"R$ {val}", fn["b"] if bold else fn["r"],
             8.5 if bold else 8.0, fill=col)
        xc += cw

    if residual:
        _badge(ctx.page, xc + 4, ctx.y + 8, "RESIDUAL",
               (0.68, 0.58, 0.10), WHITE, fs=7.0, fn=fn["b"])

    ctx.y += _LH + _GAP + 4


# ── Item MAED ──────────────────────────────────────────────────────────────
def _maed_row(ctx: _Ctx, d: dict, alt: bool) -> None:
    ctx.need(50)
    y0 = ctx.y - _LH + 2
    if alt:
        _fill(ctx.page, ctx.xl, y0, ctx.xr, y0 + 48, GRAY_ROW)

    fn, x = ctx.fn, ctx.xl + 6
    situ = str(d.get("situacao","") or "").strip().upper()
    situ_col = (RED if "DEVEDOR" in situ
                else AMBER if "VENCER" in situ
                else GREEN if "PARCEL" in situ
                else SKY)

    # Linha 1: badge situação + código + descrição
    bw = _badge(ctx.page, x, ctx.y, situ or "—", situ_col, WHITE, fs=7.5, fn=fn["b"])
    cod  = str(d.get("cod",""))
    desc = str(d.get("desc", d.get("nome","MAED")))
    label = f"{cod}  —  {desc}"
    _txt(ctx.page, x + bw, ctx.y, label[:72], fn["b"], 9.5, fill=DARK)
    ctx.y += _LH

    # Linha 2: competência / vencimento
    comp = str(d.get("comp",""))
    venc = str(d.get("venc",""))
    _txt(ctx.page, x, ctx.y,
         f"Competência: {comp}     ·     Venc.: {venc}",
         fn["r"], 8.5, fill=MID)
    ctx.y += _LH

    # Linha 3: valores
    orig = _fmt(d.get("orig"))
    dev  = _fmt(d.get("dev"))
    dev_col = (0.72, 0.20, 0.20) if _brl(d.get("dev")) > 0 else MID

    xv = x
    xv += _txt(ctx.page, xv, ctx.y,
               f"Valor original:  R$ {orig}     ·     ",
               fn["r"], 8.5, fill=MID)
    _txt(ctx.page, xv, ctx.y,
         f"Saldo devedor:  R$ {dev}",
         fn["b"], 8.5, fill=dev_col)
    ctx.y += _LH + _GAP + 2


# ── Item OMISSÃO ──────────────────────────────────────────────────────────
def _omissao_row(ctx: _Ctx, d: dict, alt: bool) -> None:
    ctx.need(24)
    y0 = ctx.y - _LH + 2
    if alt:
        _fill(ctx.page, ctx.xl, y0, ctx.xr, y0 + 22, GRAY_ROW)

    fn, x = ctx.fn, ctx.xl + 6
    tipo_decl = str(d.get("tipo_declaracao","") or "").strip().upper()

    if not tipo_decl or tipo_decl in ("NÃO ID.","NAO ID.","NÃO IDENTIFICADO",""):
        badge_col = (0.35, 0.42, 0.55)
        tipo_disp = "OMISSÃO"
    else:
        badge_col = _DECL_COLORS.get(tipo_decl, (0.35, 0.42, 0.55))
        tipo_disp = tipo_decl

    bw = _badge(ctx.page, x, ctx.y, tipo_disp, badge_col, WHITE, fs=7.5, fn=fn["b"])
    per = str(d.get("periodo") or "(período não identificado)").strip()
    _txt(ctx.page, x + bw, ctx.y, f"Período de Apuração:  {per}",
         fn["r"], 9.0, fill=DARK)
    ctx.y += _LH + 2


# ── Item PROCESSO FISCAL ──────────────────────────────────────────────────
def _pf_row(ctx: _Ctx, d: dict, alt: bool) -> None:
    ctx.need(24)
    y0 = ctx.y - _LH + 2
    if alt:
        _fill(ctx.page, ctx.xl, y0, ctx.xr, y0 + 22, GRAY_ROW)

    fn, x = ctx.fn, ctx.xl + 6
    bw = _badge(ctx.page, x, ctx.y, "DEVEDOR", RED, WHITE, fs=7.5, fn=fn["b"])
    proc = str(d.get("processo",""))
    situ = str(d.get("situacao",""))
    _txt(ctx.page, x + bw, ctx.y,
         f"Processo:  {proc}     ·     Situação: {situ}",
         fn["r"], 9.0, fill=DARK)
    ctx.y += _LH + 2


# ── Agrupamento ───────────────────────────────────────────────────────────
def _grupos(itens: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for d in itens:
        k = f"{d.get('orgao','')}\x00{d.get('cnpj','')}"
        if k not in seen:
            seen[k] = {"org": d.get("orgao",""), "cnpj": d.get("cnpj",""), "arr": []}
        seen[k]["arr"].append(d)
    return list(seen.values())


# ── Separador entre municípios ────────────────────────────────────────────
def _sep(ctx: _Ctx) -> None:
    ctx.y += _GGAP / 2
    _hline(ctx.page, ctx.xl, ctx.y, ctx.xr, GRAY_SEP, 0.4)
    ctx.y += _GGAP / 2


# ══════════════════════════════════════════════════════════════════════════════
# Renderers de cada relatório
# ══════════════════════════════════════════════════════════════════════════════

def render_devedores(ocorrencias_por_mun, municipios, ger_dir, logo=None, ts="") -> Path:
    ctx = _new_ctx("DEVEDOR", logo)
    tem = False

    for m in municipios:
        raw = [d for d in ocorrencias_por_mun.get(m,[]) if d.get("tipo")=="DEVEDOR"]
        maed_keys = {
            (str(d.get("cod","")).strip(), str(d.get("comp","")).strip())
            for d in ocorrencias_por_mun.get(m,[]) if d.get("tipo")=="MAED"
        }
        devs = [d for d in raw if not (
            "MAED" in str(d.get("nome","")).upper()
            or "DCTFWEB" in str(d.get("nome","")).upper()
            or str(d.get("cod","")).strip().startswith("5440-01")
            or (str(d.get("cod","")).strip(), str(d.get("comp","")).strip()) in maed_keys
        )]
        if not devs: continue
        tem = True
        if ctx.y > _HDR + 10: _sep(ctx)
        _mun_strip(ctx, m, len(devs))
        for g in _grupos(devs):
            _entity_hdr(ctx, g["org"], g["cnpj"])
            for i, d in enumerate(g["arr"]):
                _devedor_row(ctx, d, alt=(i % 2 == 1))
            ctx.y += _GAP

    if not tem:
        ctx.need(20)
        _txt(ctx.page, ctx.xl, ctx.y,
             "Nenhum DEVEDOR encontrado nos municípios selecionados.",
             ctx.fn["r"], 11, fill=MID)

    out = ger_dir / f"DEVEDO_{ts[:12] or 'R'}.pdf"
    ctx.doc.save(str(out)); ctx.doc.close()
    return out


def render_maeds(ocorrencias_por_mun, municipios, ger_dir, logo=None, ts="") -> Path:
    ctx = _new_ctx("MAED", logo)
    tem = False

    for m in municipios:
        maeds = [d for d in ocorrencias_por_mun.get(m,[]) if d.get("tipo")=="MAED"]
        if not maeds: continue
        tem = True
        if ctx.y > _HDR + 10: _sep(ctx)
        _mun_strip(ctx, m, len(maeds))
        for g in _grupos(maeds):
            _entity_hdr(ctx, g["org"], g["cnpj"])
            for i, d in enumerate(g["arr"]):
                _maed_row(ctx, d, alt=(i % 2 == 1))
            ctx.y += _GAP

    if not tem:
        ctx.need(20)
        _txt(ctx.page, ctx.xl, ctx.y, "Nenhum MAED encontrado.",
             ctx.fn["r"], 11, fill=MID)

    out = ger_dir / f"MAEDS__{ts[:12] or 'R'}.pdf"
    ctx.doc.save(str(out)); ctx.doc.close()
    return out


def render_omissoes(ocorrencias_por_mun, municipios, ger_dir,
                    logo=None, ts="", filtro_decl=None) -> Path:
    ctx = _new_ctx("OMISSÃO", logo)
    tem = False
    filtro_norm = {t.upper() for t in filtro_decl} if filtro_decl else None

    # Legenda dos tipos ativos no cabeçalho da 1ª página (se houver filtro)
    if filtro_norm:
        ctx.need(18)
        lbl = "Filtro ativo:  " + "  ·  ".join(sorted(filtro_norm))
        bw = _badge(ctx.page, ctx.xl, ctx.y, "FILTRO", (0.20, 0.35, 0.55), WHITE, fs=7.5)
        _txt(ctx.page, ctx.xl + bw, ctx.y, lbl, ctx.fn["r"], 8.5, fill=SKY)
        ctx.y += _LH + 4
        _hline(ctx.page, ctx.xl, ctx.y, ctx.xr, SKY, 0.4)
        ctx.y += 8

    for m in municipios:
        omiss = [d for d in ocorrencias_por_mun.get(m,[]) if d.get("tipo")=="OMISSÃO"]
        if filtro_norm:
            omiss = [d for d in omiss
                     if str(d.get("tipo_declaracao","")).upper().strip() in filtro_norm]
        if not omiss: continue
        tem = True
        if ctx.y > _HDR + 10: _sep(ctx)
        _mun_strip(ctx, m, len(omiss))
        for g in _grupos(omiss):
            _entity_hdr(ctx, g["org"], g["cnpj"])
            for i, d in enumerate(g["arr"]):
                _omissao_row(ctx, d, alt=(i % 2 == 1))
            ctx.y += _GAP

    if not tem:
        ctx.need(20)
        msg = "Nenhuma OMISSÃO encontrada"
        if filtro_norm:
            msg += f" para os tipos: {', '.join(sorted(filtro_norm))}"
        _txt(ctx.page, ctx.xl, ctx.y, msg + ".", ctx.fn["r"], 11, fill=MID)

    out = ger_dir / f"OMISSO_{ts[:12] or 'R'}.pdf"
    ctx.doc.save(str(out)); ctx.doc.close()
    return out


def render_processo_fiscal(ocorrencias_por_mun, municipios, ger_dir,
                           logo=None, ts="") -> Path:
    ctx = _new_ctx("PROCESSO FISCAL", logo)
    tem = False

    for m in municipios:
        pfs = [d for d in ocorrencias_por_mun.get(m,[]) if d.get("tipo")=="PROCESSO FISCAL"]
        if not pfs: continue
        tem = True
        if ctx.y > _HDR + 10: _sep(ctx)
        _mun_strip(ctx, m, len(pfs))
        for g in _grupos(pfs):
            _entity_hdr(ctx, g["org"], g["cnpj"])
            for i, d in enumerate(g["arr"]):
                _pf_row(ctx, d, alt=(i % 2 == 1))
            ctx.y += _GAP

    if not tem:
        ctx.need(20)
        _txt(ctx.page, ctx.xl, ctx.y,
             "Nenhum Processo Fiscal (SIEF) DEVEDOR encontrado.",
             ctx.fn["r"], 11, fill=MID)

    out = ger_dir / f"PROCES_{ts[:12] or 'R'}.pdf"
    ctx.doc.save(str(out)); ctx.doc.close()
    return out


def render_validade_cnd(selecionados, ger_dir, logo=None, ts="") -> Path:
    try:
        from relatorio_restricoes_module import _extract_cnd_info_exact, _parse_date_br_to_date
    except ImportError:
        try:
            from relatorio_restricoes_module import _extract_cnd_info_plus as _extract_cnd_info_exact
        except ImportError:
            _extract_cnd_info_exact = None
        def _parse_date_br_to_date(s):
            m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(s or ""))
            if not m: return None
            try: return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except Exception: return None

    ctx  = _new_ctx("VALIDADE DE CND", logo)
    fn   = ctx.fn
    hoje = datetime.now().date()
    tem  = False

    linhas = []
    for p, m in selecionados:
        try:
            cnpj, validade, nome_ent = _extract_cnd_info_exact(p)
        except Exception:
            continue
        if not validade: continue
        dval = _parse_date_br_to_date(validade)
        if dval is None: continue
        dias = (dval - hoje).days
        linhas.append({"entidade":(nome_ent or m).strip(),
                       "cnpj": cnpj or "", "validade": validade, "dias": dias})

    linhas.sort(key=lambda r: r["dias"])

    # Cabeçalho da tabela
    ctx.need(20)
    _fill(ctx.page, ctx.xl, ctx.y - _LH + 3, ctx.xr, ctx.y + 5,
          (0.92, 0.94, 0.97))
    _txt(ctx.page, ctx.xl + 8, ctx.y,
         "SITUAÇÃO", fn["b"], 7.5, fill=(0.40, 0.50, 0.62))
    _txt(ctx.page, ctx.xl + 112, ctx.y,
         "ENTIDADE / CNPJ", fn["b"], 7.5, fill=(0.40, 0.50, 0.62))
    _txt(ctx.page, ctx.xr - 95, ctx.y,
         "VALIDADE", fn["b"], 7.5, fill=(0.40, 0.50, 0.62))
    ctx.y += _LH + 4
    _hline(ctx.page, ctx.xl, ctx.y, ctx.xr, GRAY_SEP, 0.7)
    ctx.y += 4

    for i, r in enumerate(linhas):
        tem = True
        ctx.need(28)
        y0 = ctx.y - _LH + 2

        # Fundo alternado
        if i % 2 == 1:
            _fill(ctx.page, ctx.xl, y0, ctx.xr, y0 + 26, GRAY_ROW)

        dias     = r["dias"]
        validade = r["validade"]
        entidade = r["entidade"]
        cnpj     = r["cnpj"]

        # Chip colorido por urgência
        if dias < 0:
            chip_bg, chip_txt = RED, f"VENCIDA há {abs(dias)}d"
        elif dias == 0:
            chip_bg, chip_txt = RED, "VENCE HOJE"
        elif dias <= 7:
            chip_bg, chip_txt = (0.78, 0.18, 0.18), f"⚠  {dias} dia{'s' if dias != 1 else ''}"
        elif dias <= 30:
            chip_bg, chip_txt = AMBER, f"{dias} dias"
        elif dias <= 90:
            chip_bg, chip_txt = (0.75, 0.60, 0.10), f"{dias} dias"
        else:
            chip_bg, chip_txt = GREEN, f"{dias} dias"

        bw = _badge(ctx.page, ctx.xl + 6, ctx.y,
                    chip_txt, chip_bg, WHITE, fs=7.5, fn=fn["b"])

        # Nome da entidade (linha 1)
        _txt(ctx.page, ctx.xl + 110, ctx.y,
             entidade[:58], fn["b"], 9.0, fill=DARK)

        # Validade à direita
        vw = _tw(validade, fn["r"], 9.0)
        _txt(ctx.page, ctx.xr - vw - 6, ctx.y,
             validade, fn["r"], 9.0, fill=DARK)

        ctx.y += _LH

        # CNPJ (linha 2, recuado)
        if cnpj:
            _txt(ctx.page, ctx.xl + 110, ctx.y,
                 f"CNPJ: {cnpj}", fn["r"], 7.5, fill=SKY)
        ctx.y += 11
        _hline(ctx.page, ctx.xl + 4, ctx.y, ctx.xr - 4, GRAY_SEP, 0.3)
        ctx.y += 4

    if not tem:
        ctx.need(20)
        _txt(ctx.page, ctx.xl, ctx.y,
             "Nenhuma data de validade encontrada nos PDFs selecionados.",
             fn["r"], 11, fill=MID)

    out = ger_dir / f"VALIDA_{ts[:12] or 'R'}.pdf"
    ctx.doc.save(str(out)); ctx.doc.close()
    return out


# ── API pública ────────────────────────────────────────────────────────────
def render_all_gerenciais(ocorrencias_por_mun, municipios, selecionados,
                          ger_dir, logo=None, filtro_decl=None):
    if fitz is None:
        raise RuntimeError("PyMuPDF não instalado.")
    ger_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d%H%M")
    return [
        render_devedores(ocorrencias_por_mun, municipios, ger_dir, logo, ts),
        render_maeds(ocorrencias_por_mun, municipios, ger_dir, logo, ts),
        render_omissoes(ocorrencias_por_mun, municipios, ger_dir, logo, ts,
                        filtro_decl=filtro_decl),
        render_processo_fiscal(ocorrencias_por_mun, municipios, ger_dir, logo, ts),
        render_validade_cnd(selecionados, ger_dir, logo, ts),
    ]


# ══════════════════════════════════════════════════════════════════════════════
# Relatório Unificado — todos os municípios num só PDF
# ══════════════════════════════════════════════════════════════════════════════

def _section_divider(ctx: _Ctx, titulo: str) -> None:
    """Faixa temática (ex.: 'DEVEDOR', 'OMISSÃO') dentro do unificado."""
    ctx.need(_LH + 14)
    ctx.y += 6
    _fill(ctx.page, ctx.xl, ctx.y, ctx.xr, ctx.y + 22, (0.08, 0.18, 0.30))
    _fill(ctx.page, ctx.xl, ctx.y + 20, ctx.xr, ctx.y + 22, AMBER)
    _txt(ctx.page, ctx.xl + 8, ctx.y + 15,
         titulo.upper(), ctx.fn["b"], 10.5, fill=AMBER_LT)
    ctx.y += 28


def render_unificado_municipios(
    ocorrencias_por_mun: dict,
    municipios: list,
    ger_dir: Path,
    logo: Path | None = None,
    ts: str = "",
) -> Path:
    """
    Gera um único PDF com TODOS os municípios e TODOS os tipos de ocorrência
    formatados sequencialmente — o "relatório completo unificado".

    Estrutura por município:
        ▌ Faixa do município (navy)
            └─ DEVEDOR  (se houver)
            └─ MAED     (se houver)
            └─ OMISSÃO  (se houver)
            └─ PROCESSO FISCAL (se houver)
            └─ "Nenhuma ocorrência" (se nada)
    """
    if fitz is None:
        raise RuntimeError("PyMuPDF não instalado.")
    if not ts:
        ts = time.strftime("%Y%m%d%H%M")

    ctx = _new_ctx("RELATÓRIO UNIFICADO · TODOS OS MUNICÍPIOS", logo)
    fn  = ctx.fn
    tem_alguma = False

    for mun in municipios:
        itens = ocorrencias_por_mun.get(mun, [])

        # Filtra DEVEDOR (remove dups de MAED)
        maed_keys = {
            (str(d.get("cod","")).strip(), str(d.get("comp","")).strip())
            for d in itens if d.get("tipo") == "MAED"
        }
        devs = [d for d in itens if d.get("tipo") == "DEVEDOR" and not (
            "MAED" in str(d.get("nome","")).upper()
            or "DCTFWEB" in str(d.get("nome","")).upper()
            or str(d.get("cod","")).strip().startswith("5440-01")
            or (str(d.get("cod","")).strip(), str(d.get("comp","")).strip()) in maed_keys
        )]
        maeds = [d for d in itens if d.get("tipo") == "MAED"]
        omiss = [d for d in itens if d.get("tipo") == "OMISSÃO"]
        pfs   = [d for d in itens if d.get("tipo") == "PROCESSO FISCAL"]

        total = len(devs) + len(maeds) + len(omiss) + len(pfs)
        _mun_strip(ctx, mun, total)
        tem_alguma = True

        if not (devs or maeds or omiss or pfs):
            ctx.need(_LH)
            _txt(ctx.page, ctx.xl + 8, ctx.y,
                 "Nenhuma ocorrência (DEVEDOR / MAED / OMISSÃO / PROCESSO FISCAL).",
                 fn["r"], 9.5, fill=MID)
            ctx.y += _LH + _GAP
            continue

        # ── DEVEDOR ────────────────────────────────────────────────────────
        if devs:
            ctx.need(_LH + 8)
            _txt(ctx.page, ctx.xl + 6, ctx.y,
                 f"DEVEDOR  ({len(devs)} item{'ns' if len(devs)!=1 else ''})",
                 fn["b"], 9.5, fill=(0.65, 0.20, 0.20))
            ctx.y += _LH
            for g in _grupos(devs):
                _entity_hdr(ctx, g["org"], g["cnpj"])
                for i, d in enumerate(g["arr"]):
                    _devedor_row(ctx, d, alt=(i % 2 == 1))
                ctx.y += _GAP
            ctx.y += 2

        # ── MAED ───────────────────────────────────────────────────────────
        if maeds:
            ctx.need(_LH + 8)
            _txt(ctx.page, ctx.xl + 6, ctx.y,
                 f"MAED  ({len(maeds)} item{'ns' if len(maeds)!=1 else ''})",
                 fn["b"], 9.5, fill=(0.55, 0.40, 0.05))
            ctx.y += _LH
            for g in _grupos(maeds):
                _entity_hdr(ctx, g["org"], g["cnpj"])
                for i, d in enumerate(g["arr"]):
                    _maed_row(ctx, d, alt=(i % 2 == 1))
                ctx.y += _GAP
            ctx.y += 2

        # ── OMISSÃO ────────────────────────────────────────────────────────
        if omiss:
            ctx.need(_LH + 8)
            _txt(ctx.page, ctx.xl + 6, ctx.y,
                 f"OMISSÃO  ({len(omiss)} item{'ns' if len(omiss)!=1 else ''})",
                 fn["b"], 9.5, fill=(0.20, 0.40, 0.60))
            ctx.y += _LH
            for g in _grupos(omiss):
                _entity_hdr(ctx, g["org"], g["cnpj"])
                for i, d in enumerate(g["arr"]):
                    _omissao_row(ctx, d, alt=(i % 2 == 1))
                ctx.y += _GAP
            ctx.y += 2

        # ── PROCESSO FISCAL ────────────────────────────────────────────────
        if pfs:
            ctx.need(_LH + 8)
            _txt(ctx.page, ctx.xl + 6, ctx.y,
                 f"PROCESSO FISCAL  ({len(pfs)} item{'ns' if len(pfs)!=1 else ''})",
                 fn["b"], 9.5, fill=(0.50, 0.20, 0.50))
            ctx.y += _LH
            for g in _grupos(pfs):
                _entity_hdr(ctx, g["org"], g["cnpj"])
                for i, d in enumerate(g["arr"]):
                    _pf_row(ctx, d, alt=(i % 2 == 1))
                ctx.y += _GAP
            ctx.y += 2

        # Separador entre municípios
        ctx.y += 4
        _hline(ctx.page, ctx.xl, ctx.y, ctx.xr, (0.82, 0.87, 0.93), 0.6)
        ctx.y += 8

    if not tem_alguma:
        ctx.need(20)
        _txt(ctx.page, ctx.xl, ctx.y,
             "Nenhum município selecionado.", fn["r"], 11, fill=MID)

    out = ger_dir / f"UNIFICADO_{ts[:12] or 'R'}.pdf"
    ctx.doc.save(str(out))
    ctx.doc.close()
    return out
