"""
restricoes_patches.py — Patches de qualidade + estatísticas + renderer visual
==============================================================================
v4: adiciona compute_stats(), _last_stats e render_unificado_municipios().
"""
from __future__ import annotations
import re, unicodedata
from datetime import date, datetime
from typing import Any

RESIDUAL_THRESHOLD: float = 10.00
_RE_CNPJ = re.compile(r"\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}")
_SITUACAO_MAP = {"0,00":"DEVEDOR","0.00":"DEVEDOR","0":"DEVEDOR","":"(não informada)"}
_DECL_TYPES = ["EFD-REINF","REINF","DCTFWEB","DCTF","SISOBRA","DESTDA","DeSTDA",
               "DEFIS","DIRPF","PGDAS","GIA-ST","GFIP","PGFN","SPED","ECF","EFD"]
_DECL_FILTER: set[str] | None = None
_last_stats: dict | None = None   # resultado da última análise


# ── API pública de filtro ───────────────────────────────────────────────────

def set_decl_filter(tipos):
    global _DECL_FILTER
    _DECL_FILTER = {t.upper().strip() for t in tipos if t.strip()} if tipos else None

def get_decl_filter():
    return _DECL_FILTER

def get_last_stats() -> dict | None:
    return _last_stats


# ── 6. Extração de tipo_declaracao ──────────────────────────────────────────

def extract_tipo_declaracao(raw: str) -> str:
    if not raw: return ""
    up = raw.upper()
    for d in _DECL_TYPES:
        if d.upper() in up: return d.upper()
    m = re.search(r"OMISS[ÃA]O\s*[-–]\s*([A-Z0-9\-]+)", up, re.IGNORECASE)
    if m:
        c = m.group(1).strip()
        if c and len(c) <= 20: return c.upper()
    return ""

def enrich_omissao_tipo_declaracao(itens):
    for it in itens:
        if it.get("tipo") == "OMISSÃO":
            it["tipo_declaracao"] = extract_tipo_declaracao(
                str(it.get("raw") or it.get("desc") or ""))
    return itens


# ── Patches 1-5 ─────────────────────────────────────────────────────────────

def _fp(it):
    tp = it.get("tipo","")
    if tp == "DEVEDOR":
        return "|".join([tp,str(it.get("cnpj","")),str(it.get("cod","")),
                         str(it.get("comp","")),str(it.get("venc",""))])
    if tp == "MAED":
        return "|".join([tp,str(it.get("cnpj","")),str(it.get("cod","")),
                         str(it.get("comp","")),str(it.get("venc",""))])
    if tp == "OMISSÃO":
        p = re.sub(r"\s+"," ",(str(it.get("periodo") or it.get("raw",""))).upper().strip())
        return "|".join([tp,str(it.get("cnpj","")),p])
    if tp == "PROCESSO FISCAL":
        return "|".join([tp,str(it.get("processo",""))])
    return "|".join([tp,str(it.get("cnpj","")),str(it.get("raw",""))[:80]])

def deduplicate_itens(itens):
    seen=set(); r=[]
    for it in itens:
        fp=_fp(it)
        if fp not in seen: seen.add(fp); r.append(it)
    return r

def sanitize_omissao_itens(itens):
    for it in itens:
        if it.get("tipo")=="OMISSÃO": it["periodo"]=_san_per(it.get("periodo"))
    return itens

def _san_per(p):
    if not p: return "(período não identificado)"
    p=p.strip()
    if _RE_CNPJ.search(p) or len(re.sub(r"\D","",p))==14:
        return "(período não identificado)"
    if re.search(r"\b(19|20)\d{2}\b",p) or re.search(
        r"JAN|FEV|MAR|ABR|MAI|JUN|JUL|AGO|SET|OUT|NOV|DEZ",p.upper()) or re.search(r"\d{2}/\d{4}",p):
        return p
    return "(período não identificado)"

def normalize_maed_situacao(itens):
    for it in itens:
        if it.get("tipo")!="MAED": continue
        s=str(it.get("situacao","") or "").strip()
        it["situacao"]=_SITUACAO_MAP.get(s,s) if s in _SITUACAO_MAP else s
    return itens

def _brl(s):
    try: return float(str(s).replace(".","").replace(",","."))
    except: return 0.0

def flag_residual_devedor(itens):
    for it in itens:
        if it.get("tipo")!="DEVEDOR": continue
        v=_brl(it.get("dev")); it["residual"]=(v>0) and (v<RESIDUAL_THRESHOLD)
    return itens

def _norm_nome(s):
    nfkd=unicodedata.normalize("NFKD",s); a=nfkd.encode("ascii","ignore").decode().upper()
    stop={"DE","DO","DA","DOS","DAS","E","EM","NO","NA"}
    return " ".join(t for t in re.split(r"\W+",a) if t and t not in stop)

def detect_cnpj_collision(itens):
    c2n={}
    for it in itens:
        c=str(it.get("cnpj") or "").strip(); n=_norm_nome(str(it.get("orgao") or ""))
        if c and n: c2n.setdefault(c,set()).add(n)
    col={c for c,ns in c2n.items() if len(ns)>1}
    for it in itens: it["cnpj_colisao"]=str(it.get("cnpj") or "").strip() in col
    return itens

def apply_all_patches(itens):
    itens=deduplicate_itens(itens)
    itens=sanitize_omissao_itens(itens)
    itens=normalize_maed_situacao(itens)
    itens=enrich_omissao_tipo_declaracao(itens)
    itens=flag_residual_devedor(itens)
    itens=detect_cnpj_collision(itens)
    return itens


# ── Cálculo de estatísticas ──────────────────────────────────────────────────

def compute_stats(ocorrencias_por_mun: dict, selecionados: list) -> dict:
    """
    Computa estatísticas consolidadas de uma análise.

    Estrutura retornada:
    {
      "total_municipios": int,
      "por_municipio": [ {nome, n_dev, v_dev, n_maed, v_maed, n_omiss, n_pf, cnd_dias}, ... ],
      "totais": { v_devedor, v_maed, n_omiss, n_pf, muns_dev, muns_maed, muns_omiss, muns_pf },
      "top_devedores": [ {nome, valor}, ... ] (top 8 por valor consolidado),
      "decl_breakdown": { "DCTF": n, ... },
      "cnd_status": { "vencidas": n, "urgente": n, "atencao": n, "ok": n },
    }
    """
    hoje = datetime.now().date()

    # Extrai validade CND dos PDFs (lazy import)
    cnd_info: dict[str, int] = {}
    try:
        from relatorio_restricoes_module import (
            _extract_cnd_info_exact, _parse_date_br_to_date
        )
        for pdf_path, mun in selecionados:
            try:
                _, validade, _ = _extract_cnd_info_exact(pdf_path)
                if not validade: continue
                d = _parse_date_br_to_date(validade)
                if d: cnd_info[mun] = (d - hoje).days
            except Exception:
                pass
    except Exception:
        pass

    por_mun = []
    totais = {"v_devedor":0.0,"v_maed":0.0,"n_omiss":0,"n_pf":0,
              "muns_dev":0,"muns_maed":0,"muns_omiss":0,"muns_pf":0}
    top_raw: list[tuple[float, str]] = []
    decl_bd: dict[str, int] = {}

    for mun, itens in ocorrencias_por_mun.items():
        devs  = [d for d in itens if d.get("tipo")=="DEVEDOR" and not _is_maed_dup(d)]
        maeds = [d for d in itens if d.get("tipo")=="MAED"]
        omiss = [d for d in itens if d.get("tipo")=="OMISSÃO"]
        pfs   = [d for d in itens if d.get("tipo")=="PROCESSO FISCAL"]

        v_dev  = sum(_brl(d.get("cons") or d.get("dev",0)) for d in devs)
        v_maed = sum(_brl(d.get("dev",0)) for d in maeds)
        n_omiss= len(omiss)
        n_pf   = len(pfs)

        # Breakdown de declaração
        for it in omiss:
            td = str(it.get("tipo_declaracao","") or "").upper().strip() or "NÃO ID."
            decl_bd[td] = decl_bd.get(td,0) + 1

        por_mun.append({
            "nome":    mun,
            "n_dev":   len(devs),
            "v_dev":   v_dev,
            "n_maed":  len(maeds),
            "v_maed":  v_maed,
            "n_omiss": n_omiss,
            "n_pf":    n_pf,
            "cnd_dias": cnd_info.get(mun),
        })

        # Totais
        totais["v_devedor"] += v_dev
        totais["v_maed"]    += v_maed
        totais["n_omiss"]   += n_omiss
        totais["n_pf"]      += n_pf
        if devs:   totais["muns_dev"]   += 1
        if maeds:  totais["muns_maed"]  += 1
        if omiss:  totais["muns_omiss"] += 1
        if pfs:    totais["muns_pf"]    += 1

        if v_dev > 0:
            top_raw.append((v_dev, mun))

    top_raw.sort(reverse=True)
    top_devedores = [{"nome":n,"valor":v} for v,n in top_raw[:10]]

    # CND status
    cnd_status = {"vencidas":0,"urgente":0,"atencao":0,"ok":0}
    for dias in cnd_info.values():
        if dias < 0:      cnd_status["vencidas"] += 1
        elif dias <= 30:  cnd_status["urgente"]  += 1
        elif dias <= 90:  cnd_status["atencao"]  += 1
        else:             cnd_status["ok"]        += 1

    # Ordena por_mun: primeiro os com mais pendências
    por_mun.sort(key=lambda r: -(r["n_dev"]+r["n_maed"]+r["n_omiss"]+r["n_pf"]))

    return {
        "total_municipios": len(ocorrencias_por_mun),
        "por_municipio":    por_mun,
        "totais":           totais,
        "top_devedores":    top_devedores,
        "decl_breakdown":   dict(sorted(decl_bd.items(), key=lambda x:-x[1])),
        "cnd_status":       cnd_status,
    }


def _is_maed_dup(d: dict) -> bool:
    txt = f" {d.get('nome','')} {d.get('raw','')} ".upper()
    cod = str(d.get("cod","")).strip()
    return ("MAED" in txt or "DCTFWEB" in txt or cod.startswith("5440-01"))


# ── Monkey-patch principal ───────────────────────────────────────────────────

def patch_analisar_restricoes() -> None:
    """Envolve analisar_restricoes com patches de qualidade + renderer visual + stats."""
    import relatorio_restricoes_module as _mod
    if getattr(_mod,"_patches_applied",False): return

    _orig_extract = _mod._extract_itens_pdf
    def _patched_extract(pdf_path):
        itens = _orig_extract(pdf_path)
        itens = sanitize_omissao_itens(itens)
        itens = normalize_maed_situacao(itens)
        itens = enrich_omissao_tipo_declaracao(itens)
        itens = flag_residual_devedor(itens)
        return itens
    _mod._extract_itens_pdf = _patched_extract

    _orig = _mod.analisar_restricoes
    def _patched(base_dir, municipios_escolhidos, incluir_subpastas, out_root, log_cb):
        global _last_stats
        result = _orig(base_dir, municipios_escolhidos, incluir_subpastas, out_root, log_cb)
        out_dir = result[0]
        log_cb("🎨 Gerando layout visual e estatísticas…")
        try:
            raw_dir = out_dir / "Relatórios de Restrições"
            ger_dir = out_dir / "Relatórios Gerenciais"
            logo    = _mod._find_logo_auto()
            ocorrencias = {m:[] for m in municipios_escolhidos}
            selecionados = []
            for pdf in sorted(raw_dir.glob("*.pdf")):
                if pdf.stem.upper().startswith("RESTRICOES_UNIFICADO"): continue
                nome_norm = _mod.normalizar(pdf.stem)
                for m in municipios_escolhidos:
                    if _mod.corresponde_municipio(nome_norm, _mod.normalizar(m)):
                        ocorrencias[m].extend(_mod._extract_itens_pdf(pdf))
                        selecionados.append((pdf, m))
                        break
            for m in municipios_escolhidos:
                ocorrencias[m] = deduplicate_itens(ocorrencias[m])
            all_itens = [i for lst in ocorrencias.values() for i in lst]
            detect_cnpj_collision(all_itens)

            # Estatísticas
            _last_stats = compute_stats(ocorrencias, selecionados)

            # Gera relatórios gerenciais visuais
            for old in ger_dir.glob("*.pdf"):
                try: old.unlink()
                except: pass
            from gerencial_renderer import render_all_gerenciais, render_unificado_municipios
            render_all_gerenciais(
                ocorrencias_por_mun=ocorrencias,
                municipios=municipios_escolhidos,
                selecionados=selecionados,
                ger_dir=ger_dir, logo=logo,
                filtro_decl=_DECL_FILTER,
            )

            # Relatório unificado (todos municípios num só PDF)
            render_unificado_municipios(
                ocorrencias_por_mun=ocorrencias,
                municipios=municipios_escolhidos,
                ger_dir=ger_dir, logo=logo,
            )

            log_cb("✅ Layout visual e estatísticas gerados.")
        except Exception as exc:
            log_cb(f"[AVISO] Renderer falhou (layout padrão mantido): {exc}")
        return result
    _mod.analisar_restricoes = _patched
    _mod._patches_applied = True


if __name__ == "__main__":
    s=[
        {"tipo":"DEVEDOR","cnpj":"01.131.713/0001-57","cod":"1162-01","comp":"01/2026",
         "venc":"20/02/2026","dev":"439,11","orig":"439,11","cons":"465,23","orgao":"MUN CERES"},
        {"tipo":"DEVEDOR","cnpj":"01.131.713/0001-57","cod":"1162-01","comp":"01/2026",
         "venc":"20/02/2026","dev":"439,11","orig":"439,11","cons":"465,23","orgao":"MUN CERES"},
        {"tipo":"OMISSÃO","cnpj":"10.0/0001","periodo":"CNPJ:10.0","raw":"OMISSÃO - DCTF","orgao":"F"},
        {"tipo":"MAED","cnpj":"01.2/0001","cod":"3676","comp":"01/2025","venc":"09/02/2026",
         "orig":"3368,43","dev":"3368,43","situacao":"0,00","orgao":"MUN JARAGUA"},
        {"tipo":"DEVEDOR","cnpj":"28.0/0001","cod":"1162","comp":"06/2025","venc":"18/07/2025",
         "dev":"1,03","orig":"100,00","cons":"1,32","orgao":"FME ITAPACI"},
    ]
    p=apply_all_patches(s)
    print(f"Original:{len(s)} → Patcheado:{len(p)}")
    for it in p:
        fl=[f for f in ["RESIDUAL" if it.get("residual") else "",
            "COL" if it.get("cnpj_colisao") else "",
            f"D={it.get('tipo_declaracao','')}" if it.get("tipo_declaracao") else ""] if f]
        print(f"  [{it['tipo']:16}] situ={it.get('situacao',''):12} per={it.get('periodo',''):30} {' '.join(fl)}")
