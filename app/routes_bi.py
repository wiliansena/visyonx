# app/routes_bi.py

from flask import render_template, redirect, url_for, request, flash
from flask_login import login_required

from app import db
from app.models import RefVenda, Venda
from app.forms import VendaForm, ImportarVendasForm
from app.utils_horas import hora_brasilia
from app.utils import requer_permissao

from app.routes import bp  # ← IMPORTA O MESMO BLUEPRINT DO routes.py

 
##### VENDAS  ###

from app.utils import uf_para_regiao
from flask import render_template, request, redirect, url_for, flash, jsonify
from app import db
from app.models import Venda
from app.forms import ImportarVendasForm
from app.utils import requer_permissao, registrar_log
import pandas as pd
from datetime import datetime
import os

@bp.route("/comercial/vendas/importar", methods=["GET", "POST"])
@requer_permissao('comercial', 'criar')
def importar_vendas():
    form = ImportarVendasForm()
    if request.method == "GET" or not form.validate_on_submit():
        return render_template("comercial/vendas_importar.html", form=form)

    f = form.arquivo.data

    # ---------- lê .xls ou .xlsx ----------
    import os, pandas as pd
    from datetime import datetime
    filename = getattr(f, "filename", "") or ""
    ext = os.path.splitext(filename.lower())[1]
    read_kwargs = {}
    if ext == ".xlsx":
        read_kwargs["engine"] = "openpyxl"
    elif ext == ".xls":
        read_kwargs["engine"] = "xlrd"
    df = pd.read_excel(f, **read_kwargs)

    # ---------- cabeçalhos -> nomes do modelo ----------
    mapa = {
        'Representante':'representante','Repres':'representante',
        'Cliente':'cliente',
        'Pedido':'pedido',
        'Estado':'estado','UF':'estado',
        'Municipio':'municipio','Município':'municipio','Cidade':'municipio',
        'Dt. Inc.':'data_inclusao','Dt Inc':'data_inclusao','Data':'data_inclusao',
        'Quantidade':'quantidade','Qtd.':'quantidade','Qtde':'quantidade',
        'Valor':'valor','Total Ped.':'valor',
        'Produto':'produto','Referência':'produto','Descrição':'produto',
        'Grupo':'grupo','Regiao':'regiao','Região':'regiao',
    }
    df.columns = [mapa.get(c, c).strip().lower() for c in df.columns]

    obrig = {'representante','cliente','pedido','estado','data_inclusao'}
    faltam = obrig - set(df.columns)
    if faltam:
        flash(f"Faltam colunas obrigatórias: {', '.join(sorted(faltam))}", "danger")
        return redirect(url_for("routes.importar_vendas"))

    # ---------- helpers ----------
    def to_float_br(v):
        import pandas as pd
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = str(v).strip()
        if s.lower() in ("nan","nat","none",""):
            return None
        try:
            return float(s)
        except:
            pass
        s = s.replace('.', '').replace(',', '.')
        try:
            return float(s)
        except:
            return None

    def parse_data(x):
        if isinstance(x, datetime):
            return x.date()
        try:
            return pd.to_datetime(x, dayfirst=True, errors='coerce').date()
        except Exception:
            return None

    UF_PARA_REGIAO = {
        "AC":"NORTE","AP":"NORTE","AM":"NORTE","PA":"NORTE","RO":"NORTE","RR":"NORTE","TO":"NORTE",
        "AL":"NORDESTE","BA":"NORDESTE","CE":"NORDESTE","MA":"NORDESTE","PB":"NORDESTE",
        "PE":"NORDESTE","PI":"NORDESTE","RN":"NORDESTE","SE":"NORDESTE",
        "DF":"CENTRO-OESTE","GO":"CENTRO-OESTE","MT":"CENTRO-OESTE","MS":"CENTRO-OESTE",
        "ES":"SUDESTE","MG":"SUDESTE","RJ":"SUDESTE","SP":"SUDESTE",
        "PR":"SUL","RS":"SUL","SC":"SUL",
    }

    def uf_limpa(uf):
        import pandas as pd
        if uf is None or (isinstance(uf, float) and pd.isna(uf)):
            return None
        s = str(uf).strip()
        if s.lower() in ("nan",""):
            return None
        return s.upper()[:2]

    # garante colunas opcionais
    for col in ['quantidade','valor','produto','grupo','regiao','municipio']:
        if col not in df.columns:
            df[col] = None

    # ---------- função para detectar Rede de Loja em QUALQUER coluna ----------
    def detectar_rede_loja(row):
        """
        Procura texto contendo 'REDE DE LOJA' em qualquer célula da linha.
        Se achar, extrai o nome da rede na MESMA célula.
        Ex.: 'Rede de Loja: REDE TICO' -> 'REDE TICO'
        """
        for val in row:
            if val is None:
                continue
            s = str(val).strip()
            if not s:
                continue
            up = s.upper()
            if "REDE DE LOJA" in up:
                if ":" in s:
                    nome = s.split(":", 1)[1].strip()
                else:
                    idx = up.find("REDE DE LOJA")
                    nome = s[idx + len("Rede de Loja"):].strip(" :-")
                return nome or None
        return None

    # ---------- IMPORTAÇÃO: rede vale PARA BAIXO ----------
    registros = []
    i = 0
    n = len(df)
    usados_como_qtd = 0
    qtd_inline_ok = 0
    descartadas_sem_data = 0
    descartadas_minimos = 0

    current_rede_loja = None   # 👈 rede atual (vale para as próximas vendas)
    redes_encontradas = 0

    while i < n:
        row = df.iloc[i]

        # 1) LINHA DE CABEÇALHO "REDE DE LOJA"
        rede_detectada = detectar_rede_loja(row)
        if rede_detectada:
            # a partir daqui, todas as vendas até a próxima rede usam esse nome
            current_rede_loja = rede_detectada
            redes_encontradas += 1
            i += 1
            continue  # não é venda, só define a rede

        # 2) LINHA NORMAL (VENDA ou lixo)
        representante = (None if pd.isna(row.get('representante')) else str(row.get('representante')).strip()) or None
        cliente       = (None if pd.isna(row.get('cliente'))       else str(row.get('cliente')).strip()) or None
        pedido        = (None if pd.isna(row.get('pedido'))        else str(row.get('pedido')).strip()) or None
        uf            = uf_limpa(row.get('estado'))
        municipio     = (None if pd.isna(row.get('municipio'))     else str(row.get('municipio')).strip()) or None
        data_inc      = parse_data(row.get('data_inclusao'))

        valor         = to_float_br(row.get('valor'))

        produto       = (None if pd.isna(row.get('produto'))       else str(row.get('produto')).strip()) or None
        grupo         = (None if pd.isna(row.get('grupo'))         else str(row.get('grupo')).strip()) or None

        # --- quantidade na mesma linha ---
        q_inline = to_float_br(row.get('quantidade'))
        quantidade = int(round(q_inline)) if q_inline is not None else None
        if quantidade is not None:
            qtd_inline_ok += 1

        # --- se não veio quantidade, procura até 2 linhas abaixo (mesma lógica antiga) ---
        if quantidade is None:
            for desloc in [1, 2]:
                if i + desloc < n:
                    prox = df.iloc[i + desloc]

                    chaves = ['representante','cliente','pedido','estado','data_inclusao']
                    ch_vazias = all(
                        pd.isna(prox.get(c)) or str(prox.get(c)).strip() == ''
                        for c in chaves
                    )

                    q_next = to_float_br(prox.get('quantidade'))

                    if ch_vazias and (q_next is not None):
                        quantidade = int(round(q_next))
                        usados_como_qtd += 1

                        v_next = to_float_br(prox.get('valor'))
                        if v_next is not None:
                            valor = v_next

                        i += desloc
                        break

        if quantidade is None:
            quantidade = 0
        if valor is None:
            valor = 0.0

        # --- valida mínimos antes de salvar (isso já descarta linhas de total/rodapé) ---
        if not data_inc:
            descartadas_sem_data += 1
            i += 1
            continue
        if not (representante and cliente and pedido and uf):
            descartadas_minimos += 1
            i += 1
            continue

        registro = dict(
            representante=representante,
            cliente=cliente,
            pedido=pedido,
            estado=uf,
            municipio=municipio,
            data_inclusao=data_inc,
            quantidade=quantidade,
            valor=valor,
            produto=produto,
            grupo=grupo,
            regiao=UF_PARA_REGIAO.get(uf),
            rede_loja=current_rede_loja  # 👈 aplica a rede atual (ou None se não tiver)
        )

        registros.append(registro)
        i += 1

    if not registros:
        flash("Nenhum registro válido após análise.", "warning")
        return redirect(url_for("routes.importar_vendas"))

    # ---------- insert ----------
    try:
        objs = [Venda(**r) for r in registros]
        db.session.bulk_save_objects(objs)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f"Erro ao salvar no banco: {e}", "danger")
        return redirect(url_for("routes.importar_vendas"))

    flash(
        f"Importadas {len(registros)} linhas. "
        f"Quantidades inline: {qtd_inline_ok}. "
        f"Quantidades 1-2 linhas abaixo: {usados_como_qtd}. "
        f"Descartadas sem data: {descartadas_sem_data}. "
        f"Descartadas faltando mínimos: {descartadas_minimos}. "
        f"Redes de loja detectadas: {redes_encontradas}.",
        "success"
    )
    return redirect(url_for("routes.dashboard_vendas"))



def _coluna_metrica(metric):
    metric = (metric or 'valor').lower()
    return Venda.quantidade if metric in ('qtd','quantidade') else Venda.valor

#PEGAR A DATA DA ULTIMA IMPORTAÇÃO
def get_last_import_date_vendas():
    return db.session.query(func.max(Venda.data_inclusao)).scalar()

@bp.route("/comercial/vendas/dashboard", methods=["GET"])
@requer_permissao('comercial', 'ver')
def dashboard_vendas():
    data_ini = request.args.get("data_ini")
    data_fim = request.args.get("data_fim")

    last_import_dt_vendas = get_last_import_date_vendas()

    return render_template("comercial/vendas_dashboard.html",
                           data_ini=data_ini, data_fim=data_fim, last_import_dt_vendas=last_import_dt_vendas)

@bp.route("/comercial/vendas/agg_estados")
@requer_permissao('comercial', 'ver')
def agg_estados():
    col = _coluna_metrica(request.args.get("metric"))
    q = db.session.query(Venda.estado, db.func.sum(col).label("total"))
    if request.args.get("data_ini"):
        q = q.filter(Venda.data_inclusao >= request.args.get("data_ini"))
    if request.args.get("data_fim"):
        q = q.filter(Venda.data_inclusao <= request.args.get("data_fim"))
    q = q.group_by(Venda.estado).all()
    return jsonify({uf or "": float(t) for uf, t in q})



@bp.route("/comercial/vendas/agg_representantes")
@requer_permissao('comercial', 'ver')
def agg_representantes():
    metric = request.args.get("metric")
    col = _coluna_metrica(metric)

    estado = request.args.get("estado")
    regiao = request.args.get("regiao")           # 👈 novo
    data_ini = request.args.get("data_ini")
    data_fim = request.args.get("data_fim")

    q = db.session.query(Venda.representante, db.func.sum(col).label("total"))
    if estado:
        q = q.filter(Venda.estado == estado)
    if regiao:
        q = q.filter(Venda.regiao == regiao)      # 👈 novo
    if data_ini:
        q = q.filter(Venda.data_inclusao >= data_ini)
    if data_fim:
        q = q.filter(Venda.data_inclusao <= data_fim)

    q = q.group_by(Venda.representante).order_by(db.desc(db.func.sum(col))).limit(15).all()
    return jsonify([{"representante": r, "total": float(t)} for r, t in q])


@bp.route("/comercial/vendas/agg_clientes")
@requer_permissao('comercial', 'ver')
def agg_clientes():
    metric = request.args.get("metric")
    col = _coluna_metrica(metric)

    estado    = request.args.get("estado")
    regiao    = request.args.get("regiao")           # já existia
    data_ini  = request.args.get("data_ini")
    data_fim  = request.args.get("data_fim")
    rede_loja = request.args.get("rede_loja")        # 👈 NOVO (opcional)

    q = db.session.query(Venda.cliente, db.func.sum(col).label("total"))
    if estado:
        q = q.filter(Venda.estado == estado)
    if regiao:
        q = q.filter(Venda.regiao == regiao)
    if data_ini:
        q = q.filter(Venda.data_inclusao >= data_ini)
    if data_fim:
        q = q.filter(Venda.data_inclusao <= data_fim)
    if rede_loja:                                     # 👈 NOVO filtro
        q = q.filter(Venda.rede_loja == rede_loja)

    q = (q.group_by(Venda.cliente)
           .order_by(db.desc(db.func.sum(col)))
           .limit(15)
           .all())
    return jsonify([{"cliente": c, "total": float(t)} for c, t in q])


@bp.route("/comercial/vendas/agg_regioes")
@requer_permissao('comercial', 'ver')
def agg_regioes():
    metric = request.args.get("metric")
    col = _coluna_metrica(metric)

    data_ini  = request.args.get("data_ini")
    data_fim  = request.args.get("data_fim")
    rede_loja = (request.args.get("rede_loja") or "").strip()

    q = db.session.query(
        Venda.regiao,
        db.func.sum(col).label("total")
    )

    if data_ini:
        q = q.filter(Venda.data_inclusao >= data_ini)
    if data_fim:
        q = q.filter(Venda.data_inclusao <= data_fim)

    # 👇 NOVO: filtrar pela rede de loja, se vier na URL
    if rede_loja:
        q = q.filter(Venda.rede_loja == rede_loja)

    q = q.group_by(Venda.regiao).all()

    return jsonify([
        {"regiao": reg or "SEM REGIÃO", "total": float(total or 0)}
        for reg, total in q
    ])



@bp.route("/comercial/vendas/rep_ultimos")
@requer_permissao('comercial', 'ver')
def rep_ultimos():
    """Representantes com última venda mais antiga.
       Respeita: estado, regiao, data_ini, data_fim e metric (valor/quantidade)."""
    from datetime import date
    metric = request.args.get("metric")
    col = _coluna_metrica(metric)

    estado  = request.args.get("estado")
    regiao  = request.args.get("regiao")
    data_ini = request.args.get("data_ini")
    data_fim = request.args.get("data_fim")

    q = db.session.query(
        Venda.representante.label("representante"),
        db.func.max(Venda.data_inclusao).label("ultima_data"),
        db.func.sum(col).label("total_periodo")
    )
    if estado:
        q = q.filter(Venda.estado == estado)
    if regiao:
        q = q.filter(Venda.regiao == regiao)
    if data_ini:
        q = q.filter(Venda.data_inclusao >= data_ini)
    if data_fim:
        q = q.filter(Venda.data_inclusao <= data_fim)

    q = (q.group_by(Venda.representante)
           .order_by(db.asc(db.func.max(Venda.data_inclusao)))  # mais antigos primeiro
           .limit(15))

    rows = q.all()
    hoje = date.today()
    out = []
    for rep, ult, tot in rows:
        dias = (hoje - ult).days if ult else None
        out.append({
            "representante": rep,
            "ultima_data": (ult.isoformat() if ult else None),
            "dias_sem_vender": dias,
            "total": float(tot or 0)
        })
    return jsonify(out)



@bp.route("/comercial/vendas/agg_redes_loja")
@requer_permissao('comercial', 'ver')
def agg_redes_loja():
    """
    Top Redes de Loja.
    - ranking baseado em 'metric' (valor/quantidade)
    - sempre retorna também soma de quantidade e valor por rede.
    """

    metric = request.args.get("metric")
    col = _coluna_metrica(metric)

    estado   = request.args.get("estado")
    regiao   = request.args.get("regiao")
    data_ini = request.args.get("data_ini")
    data_fim = request.args.get("data_fim")

    q = db.session.query(
        Venda.rede_loja.label("rede_loja"),
        db.func.sum(col).label("total_metric"),
        db.func.sum(Venda.quantidade).label("total_qtd"),
        db.func.sum(Venda.valor).label("total_valor")
    )

    if estado:
        q = q.filter(Venda.estado == estado)
    if regiao:
        q = q.filter(Venda.regiao == regiao)
    if data_ini:
        q = q.filter(Venda.data_inclusao >= data_ini)
    if data_fim:
        q = q.filter(Venda.data_inclusao <= data_fim)

    # agrupa por rede de loja
    q = (q.group_by(Venda.rede_loja)
           .order_by(db.desc(db.func.sum(col)))
           .limit(20))

    rows = q.all()

    out = []
    for rede, tot_metric, tot_qtd, tot_valor in rows:
        out.append({
            "rede_loja": rede or "SEM REDE",
            "total": float(tot_metric or 0),        # conforme 'metric'
            "total_qtd": float(tot_qtd or 0),       # sempre soma de quantidade
            "total_valor": float(tot_valor or 0),   # sempre soma de valor
        })

    return jsonify(out)


@bp.route("/comercial/vendas/agg_clientes_rede")
@requer_permissao('comercial', 'ver')
def agg_clientes_rede():
    """
    Top clientes por Rede de Loja.
    - Se 'rede_loja' vier nos parâmetros, filtra só aquela rede.
    - Caso contrário, traz os maiores pares (rede, cliente) do período.
    """

    metric = request.args.get("metric")
    col = _coluna_metrica(metric)

    estado    = request.args.get("estado")
    regiao    = request.args.get("regiao")
    data_ini  = request.args.get("data_ini")
    data_fim  = request.args.get("data_fim")
    rede_filtro = request.args.get("rede_loja")  # opcional
    limit     = int(request.args.get("limit", 15))

    q = db.session.query(
        Venda.rede_loja.label("rede_loja"),
        Venda.cliente.label("cliente"),
        db.func.sum(col).label("total_metric"),
        db.func.sum(Venda.quantidade).label("total_qtd"),
        db.func.sum(Venda.valor).label("total_valor")
    )

    if estado:
        q = q.filter(Venda.estado == estado)
    if regiao:
        q = q.filter(Venda.regiao == regiao)
    if data_ini:
        q = q.filter(Venda.data_inclusao >= data_ini)
    if data_fim:
        q = q.filter(Venda.data_inclusao <= data_fim)
    if rede_filtro:
        q = q.filter(Venda.rede_loja == rede_filtro)

    q = (q.group_by(Venda.rede_loja, Venda.cliente)
           .order_by(db.desc(db.func.sum(col)))
           .limit(limit))

    rows = q.all()

    out = []
    for rede, cliente, tot_metric, tot_qtd, tot_valor in rows:
        out.append({
            "rede_loja": rede or "SEM REDE",
            "cliente": cliente or "—",
            "total": float(tot_metric or 0),       # conforme metric
            "total_qtd": float(tot_qtd or 0),      # quantidade
            "total_valor": float(tot_valor or 0),  # valor R$
        })

    return jsonify(out)

@bp.route("/comercial/vendas/rede_ultimas")
@requer_permissao('comercial', 'ver')
def rede_ultimas():
    """
    Redes de loja com última venda mais antiga.
    Respeita: estado, regiao, data_ini, data_fim e metric (valor/quantidade).
    """
    metric = request.args.get("metric")
    col = _coluna_metrica(metric)  # mesma função usada nas outras rotas

    estado   = request.args.get("estado")
    regiao   = request.args.get("regiao")
    data_ini = request.args.get("data_ini")
    data_fim = request.args.get("data_fim")

    # query principal: por rede, última data e total no período
    q = db.session.query(
        Venda.rede_loja.label("rede_loja"),
        func.max(Venda.data_inclusao).label("ultima_data"),
        func.sum(col).label("total_periodo")
    ).filter(Venda.rede_loja.isnot(None))

    if estado:
        q = q.filter(Venda.estado == estado)
    if regiao:
        q = q.filter(Venda.regiao == regiao)
    if data_ini:
        q = q.filter(Venda.data_inclusao >= data_ini)
    if data_fim:
        q = q.filter(Venda.data_inclusao <= data_fim)

    q = (
        q.group_by(Venda.rede_loja)
         .order_by(func.max(Venda.data_inclusao))   # mais antigas primeiro
         .limit(15)
    )

    rows = q.all()
    hoje = date.today()
    out = []

    for rede, ult, tot in rows:
        # 👇 cliente da ÚLTIMA venda da rede (na data 'ult'),
        # escolhendo a maior venda (col desc) naquele dia
        cliente_ult = None
        if ult:
            cliente_ult = (
                db.session.query(Venda.cliente)
                .filter(
                    Venda.rede_loja == rede,
                    Venda.data_inclusao == ult
                )
                .order_by(col.desc())
                .limit(1)
                .scalar()
            )

        dias = (hoje - ult).days if ult else None
        out.append({
            "rede_loja": rede,
            "cliente_ultima_venda": cliente_ult,
            "ultima_data": (ult.isoformat() if ult else None),
            "dias_sem_vender": dias,
            "total": float(tot or 0)     # 👈 total da rede no período, não só a última venda
        })

    return jsonify(out)


### VENDAS MANUAL  ###
UF_PARA_REGIAO = {
    "AC":"NORTE","AP":"NORTE","AM":"NORTE","PA":"NORTE","RO":"NORTE","RR":"NORTE","TO":"NORTE",
    "AL":"NORDESTE","BA":"NORDESTE","CE":"NORDESTE","MA":"NORDESTE","PB":"NORDESTE",
    "PE":"NORDESTE","PI":"NORDESTE","RN":"NORDESTE","SE":"NORDESTE",
    "DF":"CENTRO-OESTE","GO":"CENTRO-OESTE","MT":"CENTRO-OESTE","MS":"CENTRO-OESTE",
    "ES":"SUDESTE","MG":"SUDESTE","RJ":"SUDESTE","SP":"SUDESTE",
    "PR":"SUL","RS":"SUL","SC":"SUL",
}

def _aplicar_filtros_qs(q):
    """Filtros vindos por querystring (?data_ini=...&data_fim=...&estado=... etc.)."""
    data_ini  = request.args.get("data_ini")
    data_fim  = request.args.get("data_fim")
    estado    = request.args.get("estado")
    regiao    = request.args.get("regiao")
    representante = request.args.get("representante")
    cliente   = request.args.get("cliente")
    pedido    = request.args.get("pedido")

    if data_ini: q = q.filter(Venda.data_inclusao >= data_ini)
    if data_fim: q = q.filter(Venda.data_inclusao <= data_fim)
    if estado:   q = q.filter(Venda.estado == estado)
    if regiao:   q = q.filter(Venda.regiao == regiao)
    if representante: q = q.filter(Venda.representante.ilike(f"%{representante}%"))
    if cliente:       q = q.filter(Venda.cliente.ilike(f"%{cliente}%"))
    if pedido:        q = q.filter(Venda.pedido.ilike(f"%{pedido}%"))
    return q

@bp.route("/comercial/vendas", methods=["GET"])
@requer_permissao('comercial', 'ver')
def listar_vendas():
    q = _aplicar_filtros_qs(Venda.query).order_by(Venda.data_inclusao.desc(), Venda.id.desc())
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    pag = q.paginate(page=page, per_page=per_page, error_out=False)

    # args sem 'page'
    qargs = request.args.to_dict()
    qargs.pop('page', None)

    # monta URLs de navegação
    from flask import url_for
    prev_url = url_for("routes.listar_vendas", **qargs, page=pag.prev_num) if pag.has_prev else None
    next_url = url_for("routes.listar_vendas", **qargs, page=pag.next_num) if pag.has_next else None

    pages = []
    for p in pag.iter_pages(left_edge=1, right_edge=1, left_current=2, right_current=2):
        if p:
            pages.append({
                "num": p,
                "url": url_for("routes.listar_vendas", **qargs, page=p),
                "active": (p == pag.page)
            })
        else:
            pages.append(None)  # separador (reticências)
    return render_template(
        "comercial/listar_vendas.html",
        pag=pag, pages=pages, prev_url=prev_url, next_url=next_url
    )


@bp.route("/comercial/vendas/nova", methods=["GET", "POST"])
@requer_permissao('comercial', 'criar')
def nova_venda():
    form = VendaForm()
    if form.validate_on_submit():
        regiao = form.regiao.data or UF_PARA_REGIAO.get(form.estado.data)
        v = Venda(
            representante=form.representante.data.strip(),
            estado=form.estado.data.strip(),
            municipio=(form.municipio.data or '').strip() or None,
            cliente=form.cliente.data.strip(),
            pedido=form.pedido.data.strip(),
            data_inclusao=form.data_inclusao.data,
            quantidade=form.quantidade.data or 0,
            valor=float(form.valor.data or 0),
            produto=(form.produto.data or '').strip() or None,
            grupo=(form.grupo.data or '').strip() or None,
            regiao=regiao
        )
        db.session.add(v)
        db.session.commit()
        flash("Venda criada com sucesso.", "success")
        return redirect(url_for("routes.listar_vendas"))
    return render_template("comercial/nova_venda.html", form=form)

@bp.route("/comercial/vendas/<int:venda_id>/editar", methods=["GET", "POST"])
@requer_permissao('comercial', 'editar')
def editar_venda(venda_id):
    v = Venda.query.get_or_404(venda_id)
    form = VendaForm(obj=v)
    if form.validate_on_submit():
        v.representante = form.representante.data.strip()
        v.estado        = form.estado.data.strip()
        v.municipio     = (form.municipio.data or '').strip() or None
        v.cliente       = form.cliente.data.strip()
        v.pedido        = form.pedido.data.strip()
        v.data_inclusao = form.data_inclusao.data
        v.quantidade    = form.quantidade.data or 0
        v.valor         = float(form.valor.data or 0)
        v.produto       = (form.produto.data or '').strip() or None
        v.grupo         = (form.grupo.data or '').strip() or None
        v.regiao        = form.regiao.data or UF_PARA_REGIAO.get(v.estado)
        db.session.commit()
        flash("Venda atualizada.", "success")
        return redirect(url_for("routes.listar_vendas"))
    return render_template("comercial/editar_venda.html", form=form, venda=v)

@bp.route("/comercial/vendas/<int:venda_id>/excluir", methods=["POST"])
@requer_permissao('comercial', 'excluir')
def excluir_venda(venda_id):
    v = Venda.query.get_or_404(venda_id)
    db.session.delete(v)
    db.session.commit()
    flash("Venda excluída.", "success")
    return redirect(request.referrer or url_for("routes.listar_vendas"))




# ---------- Importar relatório simples de referências ----------
@bp.route("/comercial/referencias/importar", methods=["GET", "POST"])
@requer_permissao('comercial', 'criar')
def importar_referencias_venda():
    from app.forms import ImportarReferenciasForm
    from app.models import RefVenda
    import pandas as pd, os, re

    form = ImportarReferenciasForm()
    if request.method == "GET" or not form.validate_on_submit():
        return render_template("comercial/referencias_importar.html", form=form)

    f = form.arquivo.data
    if not f or not getattr(f, "filename", ""):
        flash("Selecione um arquivo .xls ou .xlsx.", "danger")
        return redirect(url_for("routes.importar_referencias"))

    ext = os.path.splitext(f.filename.lower())[1]
    read_kwargs = {}
    if ext == ".xlsx": read_kwargs["engine"] = "openpyxl"
    elif ext == ".xls": read_kwargs["engine"] = "xlrd"

    try:
        df = pd.read_excel(f, **read_kwargs)
    except Exception as e:
        flash(f"Erro ao ler planilha: {e}", "danger")
        return redirect(url_for("routes.importar_referencias_venda"))

    # ---- cabeçalhos
    mapa = {
        "Referência":"referencia","Referencia":"referencia","REF":"referencia",
        "Combinação":"combinacao","Combinacao":"combinacao","Descrição":"combinacao",
        "Qtd. Vendida":"quantidade","Quantidade":"quantidade","Qtde":"quantidade",
        "Média Em %":"media_pct","Media Em %":"media_pct","Média %":"media_pct","Media %":"media_pct",
    }
    df.columns = [mapa.get(str(c).strip(), str(c).strip()).lower() for c in df.columns]

    obrig = {"referencia","quantidade"}
    if not obrig.issubset(set(df.columns)):
        faltam = obrig - set(df.columns)
        flash(f"Colunas obrigatórias ausentes: {', '.join(sorted(faltam))}", "danger")
        return redirect(url_for("routes.importar_referencias_venda"))

    # ---- coerções e limpeza
    df["quantidade"] = pd.to_numeric(df["quantidade"], errors="coerce").fillna(0).astype(int)
    if "media_pct" in df.columns:
        df["media_pct"] = pd.to_numeric(df["media_pct"], errors="coerce")

    df["referencia"] = (
        df["referencia"].astype(str)
          .str.replace("\n"," ", regex=False)
          .str.strip()
          .str.rstrip("/")                # remove barra final do relatório
    )
    df = df[df["referencia"] != ""]
    df = df[~df["referencia"].str.contains(r"^senda\s*-", flags=re.I, na=False)]  # remove rodapé
    df = df[df["referencia"].str.contains(r"\.", na=False)]                        # exige ponto
    df = df[df["referencia"].str.contains(r"[A-Za-z]", na=False)]                  # precisa ter letra (evita 67.070)

    # ---- normaliza chave da referência e separa linha/código
    df["ref_key"] = df["referencia"].str.upper()
    df["linha"]   = df["ref_key"].str.split(".", n=1, expand=True)[0]
    df["codigo"]  = df["ref_key"].str.split(".", n=1, expand=True)[1]

    # ---- AGRUPA por referência (somatório de quantidade, 1ª combinação, média opcional)
    agg = (
        df.groupby("ref_key", as_index=False)
          .agg({
              "linha":"first",
              "codigo":"first",
              "referencia":"first",
              "combinacao": lambda s: s.dropna().iloc[0] if not s.dropna().empty else None,
              "quantidade":"sum",
              "media_pct": "mean" if "media_pct" in df.columns else "sum"
          })
    )
    if "media_pct" not in df.columns:
        agg["media_pct"] = None

    # ---- pega referências existentes de uma vez (para contar novas/atualizadas)
    existentes_set = set(
        x[0] for x in db.session.query(RefVenda.referencia)
                                .filter(RefVenda.referencia.in_(agg["ref_key"].tolist()))
                                .all()
    )

    novos = atualizados = 0
    for _, r in agg.iterrows():
        ref_key = r["ref_key"]             # tudo maiúsculo
        linha   = r["linha"]
        codigo  = r["codigo"]
        qtd     = int(r["quantidade"])
        comb    = r["combinacao"] if pd.notna(r["combinacao"]) else None
        pctv    = r["media_pct"]
        pct     = float(pctv) if (pctv is not None and pd.notna(pctv)) else None

        if ref_key in existentes_set:
            v = RefVenda.query.filter_by(referencia=ref_key).first()
            v.linha = linha
            v.codigo = codigo
            v.combinacao = comb
            v.quantidade = qtd
            v.media_pct = pct
            atualizados += 1
        else:
            db.session.add(RefVenda(
                referencia=ref_key,
                linha=linha,
                codigo=codigo,
                combinacao=comb,
                quantidade=qtd,
                media_pct=pct
            ))
            novos += 1

    db.session.commit()
    flash(f"Importação OK: {novos+atualizados} referências (novas: {novos}, atualizadas: {atualizados}).", "success")
    return redirect(url_for("routes.dashboard_vendas"))




# ---------- JSON: Top Referências ----------
@bp.route("/comercial/referencias/top")
@requer_permissao('comercial', 'ver')
def referencias_top():
    lim = request.args.get("limit", 30, type=int)
    lim = max(1, min(lim, 50))
    q = (db.session.query(RefVenda.referencia, RefVenda.quantidade)
         .order_by(RefVenda.quantidade.desc())
         .limit(lim)
        )
    data = [{"referencia": r.referencia, "total": int(r.quantidade or 0)} for r in q.all()]
    return jsonify(data)

# ---------- JSON: Top Linhas (prefixo antes do ponto) ----------
@bp.route("/comercial/referencias/linhas_top")
@requer_permissao('comercial', 'ver')
def referencias_linhas_top():
    lim = request.args.get("limit", 30, type=int)
    lim = max(1, min(lim, 50))
    q = (db.session.query(
            RefVenda.linha.label("linha"),
            db.func.sum(RefVenda.quantidade).label("total"))
         .group_by(RefVenda.linha)
         .order_by(db.desc(db.func.sum(RefVenda.quantidade)))
         .limit(lim)
        )
    data = [{"linha": (r.linha or "—"), "total": int(r.total or 0)} for r in q.all()]
    return jsonify(data)


# --- BI: Painel Avançado (dados do banco) ---
from sqlalchemy import func, desc, and_

from datetime import date, timedelta
from flask import request, render_template
from app.models import Venda, RefVenda
from app.utils_horas import hora_brasilia


# ----------------- Helpers -----------------
def _periodo_padrao():
    hoje = hora_brasilia().date()
    return hoje - timedelta(days=90), hoje


def _filtrar(query, dt_ini, dt_fim, representante, estado, rede_loja=None):
    if dt_ini:
        query = query.filter(Venda.data_inclusao >= dt_ini)
    if dt_fim:
        query = query.filter(Venda.data_inclusao <= dt_fim)
    if representante:
        query = query.filter(Venda.representante == representante)
    if estado:
        query = query.filter(Venda.estado == estado)
    if rede_loja:
        query = query.filter(Venda.rede_loja == rede_loja)
    return query



# PEGAR A DATA DA ULTIMA IMPORTAÇÃO
def get_last_import_date_vendas():
    return db.session.query(func.max(Venda.data_inclusao)).scalar()


def _pct(a, b):
    if b and b != 0:
        return float((a - b) / b * 100)
    return 100.0 if a > 0 else 0.0


# ----------------- Rota do painel -----------------
@bp.route("/comercial/vendas_dashboard_avancado", methods=["GET"])
def vendas_dashboard_avancado():
    # Filtros vindos da tela
    dt_ini_str    = request.args.get("dt_ini", "")
    dt_fim_str    = request.args.get("dt_fim", "")
    representante = request.args.get("representante", "")
    estado        = request.args.get("estado", "")
    rede_loja     = request.args.get("rede_loja", "").strip()   # 👈 NOVO

    # 🔹 Modo de análise: 'qtd' (padrão) ou 'valor'
    modo = request.args.get("modo", "qtd")
    if modo not in ("qtd", "valor"):
        modo = "qtd"

    # coluna métrica base (quantidade ou valor)
    metric_col = Venda.quantidade if modo == "qtd" else Venda.valor
    metric_label = "Quantidade" if modo == "qtd" else "Faturamento (R$)"

    last_import_dt_vendas = get_last_import_date_vendas()

    # Período padrão = hoje (ou o que você quiser), senão usa o informado
    if dt_ini_str and dt_fim_str:
        dt_ini = date.fromisoformat(dt_ini_str)
        dt_fim = date.fromisoformat(dt_fim_str)
    else:
        dt_ini, dt_fim = _periodo_padrao()

    # ================= KPIs por PERÍODO =================
    # Total do período (respeitando filtros da tela)
    q_tot = db.session.query(func.coalesce(func.sum(metric_col), 0.0))
    q_tot = _filtrar(q_tot, dt_ini, dt_fim, representante, estado, rede_loja)
    kpi_periodo = float(q_tot.scalar() or 0.0)

    # Período anterior de MESMO tamanho (para comparação)
    span = (dt_fim - dt_ini).days + 1
    prev_ini = dt_ini - timedelta(days=span)
    prev_fim = dt_ini - timedelta(days=1)

    q_prev = db.session.query(func.coalesce(func.sum(metric_col), 0.0))
    q_prev = _filtrar(q_prev, prev_ini, prev_fim, representante, estado, rede_loja)
    prev_total = float(q_prev.scalar() or 0.0)

    # Variação % vs período anterior de mesmo tamanho
    if prev_total:
        kpi_var_pct = (kpi_periodo - prev_total) / prev_total * 100.0
    else:
        kpi_var_pct = 100.0 if kpi_periodo > 0 else 0.0

    # Ticket médio do período = total / clientes distintos no período
    q_dist = db.session.query(func.count(func.distinct(Venda.cliente)))
    q_dist = _filtrar(q_dist, dt_ini, dt_fim, representante, estado, rede_loja)
    clientes_distintos = int(q_dist.scalar() or 0)
    ticket_medio = (kpi_periodo / clientes_distintos) if clientes_distintos else 0.0

    # 🔹 Preço médio por par = (∑ valor) / (∑ quantidade), sempre em R$/par
    q_sums = db.session.query(
        func.coalesce(func.sum(Venda.valor), 0.0),
        func.coalesce(func.sum(Venda.quantidade), 0)
    )
    q_sums = _filtrar(q_sums, dt_ini, dt_fim, representante, estado, rede_loja)
    total_valor, total_qtd = q_sums.one()
    total_valor = float(total_valor or 0.0)
    total_qtd = int(total_qtd or 0)
    preco_medio_par = (total_valor / total_qtd) if total_qtd > 0 else 0.0

    # ================= Tendência mensal (usa métrica escolhida) =================
    q_tend = db.session.query(
        func.date_trunc('month', Venda.data_inclusao).label("mes"),
        func.coalesce(func.sum(metric_col), 0)
    )
    q_tend = _filtrar(q_tend, dt_ini, dt_fim, representante, estado, rede_loja)
    q_tend = q_tend.group_by("mes").order_by("mes").all()
    tend_labels  = [m[0].date().strftime("%m/%Y") for m in q_tend]
    tend_valores = [float(m[1] or 0) for m in q_tend]

    # ================= Rankings (UF e Representante) =================
    q = db.session.query(Venda.estado, func.coalesce(func.sum(metric_col), 0))
    q = _filtrar(q, dt_ini, dt_fim, representante, estado, rede_loja)
    rank_uf = q.group_by(Venda.estado).order_by(desc(func.sum(metric_col))).limit(15).all()
    rank_uf_labels  = [r[0] for r in rank_uf]
    rank_uf_values  = [float(r[1] or 0) for r in rank_uf]

    q = db.session.query(Venda.representante, func.coalesce(func.sum(metric_col), 0))
    q = _filtrar(q, dt_ini, dt_fim, representante, estado, rede_loja)
    rank_rep = q.group_by(Venda.representante).order_by(desc(func.sum(metric_col))).limit(15).all()
    rank_rep_labels = [r[0] for r in rank_rep]
    rank_rep_values = [float(r[1] or 0) for r in rank_rep]

    # ================= Crescimento / Queda (últimos 30 vs 30 anteriores) =================
    hoje = hora_brasilia().date()
    p1_ini, p1_fim = (hoje - timedelta(days=30), hoje)
    p0_ini, p0_fim = (hoje - timedelta(days=60), hoje - timedelta(days=30))

    q_atual = db.session.query(
        Venda.representante,
        func.coalesce(func.sum(metric_col), 0).label("v")
    )
    q_atual = _filtrar(q_atual, p1_ini, p1_fim, representante, estado, rede_loja)\
                .group_by(Venda.representante).subquery()

    q_ant = db.session.query(
        Venda.representante,
        func.coalesce(func.sum(metric_col), 0).label("v")
    )
    q_ant = _filtrar(q_ant, p0_ini, p0_fim, representante, estado, rede_loja)\
              .group_by(Venda.representante).subquery()

    rows = db.session.query(
        q_atual.c.representante,
        q_atual.c.v.label("atual"),
        func.coalesce(q_ant.c.v, 0).label("anterior")
    ).outerjoin(q_ant, q_ant.c.representante == q_atual.c.representante).all()

    def _pct_safe(a, b):
        a = float(a or 0); b = float(b or 0)
        if b > 0:
            return (a - b) / b * 100.0
        if b == 0:
            if a > 0:
                return 100.0
            return 0.0
        return (a - b) / abs(b) * 100.0

    cresc_all = [
        {"rep": r[0], "pct": _pct_safe(r[1], r[2])}
        for r in rows
    ]

    positivos = [x for x in cresc_all if x["pct"] > 0]
    negativos = [x for x in cresc_all if x["pct"] < 0]

    top_up   = sorted(positivos, key=lambda x: x["pct"], reverse=True)[:15]
    top_down = sorted(negativos, key=lambda x: x["pct"])[:15]

    up_labels   = [x["rep"] for x in top_up]
    up_values   = [round(x["pct"], 2) for x in top_up]

    down_labels = [x["rep"] for x in top_down]
    down_values = [round(x["pct"], 2) for x in top_down]

    # ================= Curva ABC (Top 20 mais vendidas - continua por QUANTIDADE) =================
    refs_all  = RefVenda.query.order_by(RefVenda.quantidade.desc()).all()
    total_all = float(sum((rv.quantidade or 0) for rv in refs_all))

    abc_full = []
    acum = 0.0
    for rv in refs_all:
        qv = float(rv.quantidade or 0)
        acum += qv
        pct_acum       = (acum / total_all * 100) if total_all else 0.0
        pct_individual = (qv   / total_all * 100) if total_all else 0.0
        classe = "A" if pct_acum <= 80 else ("B" if pct_acum <= 95 else "C")
        abc_full.append({
            "referencia": rv.referencia,
            "q": qv,
            "pct_individual": round(pct_individual, 2),
            "pct_acum": round(pct_acum, 2),
            "classe": classe
        })

    refs_top20   = RefVenda.query.order_by(RefVenda.quantidade.desc()).limit(20).all()
    total_top20  = float(sum((rv.quantidade or 0) for rv in refs_top20))
    top20_share  = round((total_top20 / total_all * 100), 2) if total_all else 0.0
    top1_share   = round(((refs_top20[0].quantidade or 0) / total_all * 100), 2) if refs_top20 else 0.0
    info_map     = {x["referencia"]: x for x in abc_full}
    abc_labels    = [rv.referencia for rv in refs_top20]
    abc_valores   = [float(rv.quantidade or 0) for rv in refs_top20]
    abc_acum_pct  = [info_map[rv.referencia]["pct_acum"] for rv in refs_top20]
    abc_indiv_pct = [info_map[rv.referencia]["pct_individual"] for rv in refs_top20]
    abc_classes   = [info_map[rv.referencia]["classe"] for rv in refs_top20]

    # ================= RFM simplificado (resumo) =================
    rfm_rows = db.session.query(
        Venda.cliente,
        func.max(Venda.data_inclusao),
        func.count(Venda.id),
        func.coalesce(func.sum(Venda.valor), 0)
    )
    rfm_rows = _filtrar(rfm_rows, dt_ini, dt_fim, representante, estado, rede_loja)
    rfm_rows = rfm_rows.group_by(Venda.cliente).all()

    hoje_dt = hora_brasilia().date()
    rfm_resumo = {"Ativo": 0, "Risco": 0, "Inativo": 0}
    for _, ultima, _, _ in rfm_rows:
        dias = (hoje_dt - ultima).days if ultima else 9999
        if   dias <= 30: rfm_resumo["Ativo"]   += 1
        elif dias <= 90: rfm_resumo["Risco"]   += 1
        else:            rfm_resumo["Inativo"] += 1

    # ================= Combos de filtros =================
    reps_all = [r[0] for r in db.session.query(Venda.representante).distinct().order_by(Venda.representante).all()]
    ufs_all  = [r[0] for r in db.session.query(Venda.estado).distinct().order_by(Venda.estado).all()]
    redes_all = [r[0] for r in db.session.query(Venda.rede_loja).distinct().order_by(Venda.rede_loja).all()]  # 👈 NOVO

    # ================= Contexto =================
    ctx = dict(
        # filtros
        dt_ini=dt_ini.isoformat(), dt_fim=dt_fim.isoformat(),
        representante_sel=representante, estado_sel=estado,
        rede_loja_sel=rede_loja,              # 👈 NOVO
        reps_all=reps_all, ufs_all=ufs_all,
        redes_all=redes_all,                  # 👈 NOVO

        # modo / rótulo da métrica
        modo=modo,
        metric_label=metric_label,

        # KPIs
        kpi_mes_atual=round(kpi_periodo, 2),
        kpi_var_pct=round(kpi_var_pct, 2),
        ticket_medio=round(ticket_medio, 2),
        preco_medio_par=round(preco_medio_par, 4),

        # Tendência
        tend_labels=tend_labels,
        tend_valores=[round(x, 2) for x in tend_valores],

        # Rankings
        rank_uf_labels=rank_uf_labels,   rank_uf_values=[round(x, 2) for x in rank_uf_values],
        rank_rep_labels=rank_rep_labels, rank_rep_values=[round(x, 2) for x in rank_rep_values],

        # Crescimento/Queda
        up_labels=up_labels, up_values=up_values,
        down_labels=down_values and down_labels, down_values=down_values,

        # ABC
        abc_labels=abc_labels,
        abc_valores=abc_valores,
        abc_acum_pct=abc_acum_pct,
        abc_indiv_pct=abc_indiv_pct,
        abc_classes=abc_classes,
        total_refs=round(total_all, 2),
        top20_share=top20_share,
        top1_share=top1_share,

        # RFM
        rfm_resumo=rfm_resumo,

        # Período comparado
        prev_ini=prev_ini.isoformat(),
        prev_fim=prev_fim.isoformat(),
    )
    return render_template(
        "comercial/vendas_dashboard_avancado.html",
        **ctx,
        last_import_dt_vendas=last_import_dt_vendas
    )





# ---- helpers ----
def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

def _classifica_status(recency_days: int, ativo_max=30, risco_max=90):
    """
    Regras simples de recência:
      - 0..ativo_max          -> 'Ativo'
      - ativo_max+1..risco_max-> 'Risco'
      - >risco_max            -> 'Inativo'
    """
    if recency_days is None:
        return "Inativo"
    if recency_days <= ativo_max:
        return "Ativo"
    if recency_days <= risco_max:
        return "Risco"
    return "Inativo"


@bp.route("/comercial/rfm_list", methods=["GET"])
def rfm_list():
    from sqlalchemy import func
    from datetime import date

    # filtros
    status        = request.args.get("status", "").strip()         # 'Ativo' | 'Risco' | 'Inativo' | ''
    representante = request.args.get("representante", "").strip()
    estado        = request.args.get("estado", "").strip()
    rede_loja     = request.args.get("rede_loja", "").strip()
    dt_ini        = _parse_date(request.args.get("dt_ini"))
    dt_fim        = _parse_date(request.args.get("dt_fim"))

    # limites de recência (opcionais; defaults 30 / 90)
    ativo_max = int(request.args.get("ativo_max", 30))
    risco_max = int(request.args.get("risco_max", 90))

    # URL de volta (opcional)
    back_url = request.args.get("back", "")

    # 🔹 modo de métrica: 'qtd' (pares) ou 'valor' (R$)
    modo = request.args.get("modo", "valor")
    if modo not in ("qtd", "valor"):
        modo = "valor"

    # base query: já calcula AS DUAS métricas
    q = (
        db.session.query(
            Venda.cliente.label("cliente"),
            func.max(Venda.data_inclusao).label("ultima_data"),
            func.count(Venda.id).label("freq"),  # frequência de pedidos
            func.coalesce(func.sum(Venda.quantidade), 0).label("qtd_total"),
            func.coalesce(func.sum(Venda.valor), 0).label("valor_total"),
        )
    )

    if representante:
        q = q.filter(Venda.representante == representante)
    if estado:
        q = q.filter(Venda.estado == estado)
    if rede_loja:
        q = q.filter(Venda.rede_loja == rede_loja)
    if dt_ini:
        q = q.filter(Venda.data_inclusao >= dt_ini)
    if dt_fim:
        q = q.filter(Venda.data_inclusao <= dt_fim)

    q = q.group_by(Venda.cliente)

    raw = q.all()

    # pós-processo RFM
    hoje = date.today()
    linhas = []
    resumo = {"Ativo": 0, "Risco": 0, "Inativo": 0}

    for r in raw:
        dias = (hoje - r.ultima_data).days if r.ultima_data else None
        st = _classifica_status(dias, ativo_max=ativo_max, risco_max=risco_max)
        resumo[st] = resumo.get(st, 0) + 1

        item = {
            "cliente":      r.cliente,
            "ultima_data":  r.ultima_data,
            "dias":         dias if dias is not None else "-",
            "freq":         int(r.freq or 0),
            "qtd_total":    int(r.qtd_total or 0),          # 🔹 pares
            "valor_total":  float(r.valor_total or 0.0),    # 🔹 R$
            "status":       st,
        }
        linhas.append(item)

    # aplica filtro de status (se informado)
    if status:
        linhas = [x for x in linhas if x["status"] == status]

    # ordenação padrão: maior recência (mais dias sem comprar) primeiro
    linhas.sort(key=lambda x: (x["dias"] if isinstance(x["dias"], int) else 10**9), reverse=True)

    # contexto para template
    ctx = dict(
        linhas=linhas,
        resumo=resumo,
        modo=modo,          # 👈 o template sabe se é qtd ou valor
        filtros=dict(
            status=status,
            representante=representante,
            estado=estado,
            rede_loja=rede_loja,
            dt_ini=dt_ini.isoformat() if dt_ini else "",
            dt_fim=dt_fim.isoformat() if dt_fim else "",
            ativo_max=ativo_max,
            risco_max=risco_max,
        ),
        back_url=back_url,
    )
    return render_template("comercial/rfm_list.html", **ctx)





#### MAIS INDICADORES DE VENDAS ####

# /comercial/vendas/indicadores_base
@bp.route("/comercial/vendas/indicadores_base")
@requer_permissao('comercial','ver')
def indicadores_base():
    from sqlalchemy import distinct
    from datetime import date

    data_ini = request.args.get("dt_ini")
    data_fim = request.args.get("dt_fim")
    estado   = request.args.get("estado")
    rep      = request.args.get("representante")
    rede     = request.args.get("rede_loja")    # 👈 NOVO

    # chave = código antes do " - " (ex.: "7.954")
    cliente_key = func.split_part(Venda.cliente, ' - ', 1)

    # base por cliente (key), com última compra e frequência no período
    q = db.session.query(
        func.upper(func.trim(cliente_key)).label("cli_key"),
        func.count(Venda.id).label("freq"),
        func.max(Venda.data_inclusao).label("ultima")
    )
    if data_ini: q = q.filter(Venda.data_inclusao >= data_ini)
    if data_fim: q = q.filter(Venda.data_inclusao <= data_fim)
    if estado:   q = q.filter(Venda.estado == estado)
    if rep:      q = q.filter(Venda.representante == rep)
    if rede:     q = q.filter(Venda.rede_loja == rede)   # 👈 NOVO

    q = q.group_by("cli_key").all()

    hoje = date.today()
    base_total   = len(q)
    clientes_novos = 0
    recompra       = 0
    ativos_60d     = 0
    inativos_60d   = 0
    gaps_aprox     = []

    # primeira compra histórica (fora do filtro de período — mantém como estava)
    keys = [row[0] for row in q]
    prim_hist = dict(
        db.session.query(
            func.upper(func.trim(func.split_part(Venda.cliente, ' - ', 1))).label("cli_key"),
            func.min(Venda.data_inclusao)
        ).filter(func.upper(func.trim(func.split_part(Venda.cliente, ' - ', 1))).in_(keys))
         .group_by("cli_key").all()
    )

    for cli_key, freq, ultima in q:
        if data_ini and prim_hist.get(cli_key) and str(prim_hist[cli_key]) >= str(data_ini):
            clientes_novos += 1

        if (freq or 0) > 1:
            recompra += 1
            dias = (hoje - ultima).days if ultima else None
            if dias is not None and (freq-1) > 0:
                gaps_aprox.append(max(1, dias // (freq-1)))

        dias_sem      = (hoje - ultima).days if ultima else 9999
        if dias_sem <= 60:  ativos_60d += 1
        else:               inativos_60d += 1

    taxa_recompra = (recompra / base_total * 100) if base_total else 0.0
    churn         = (inativos_60d / base_total * 100) if base_total else 0.0
    gap_medio     = (sum(gaps_aprox)/len(gaps_aprox)) if gaps_aprox else None

    return jsonify({
        "base_total": base_total,
        "clientes_novos": clientes_novos,
        "taxa_recompra_pct": round(taxa_recompra,2),
        "churn_pct": round(churn,2),
        "gap_medio_dias": round(gap_medio,1) if gap_medio is not None else None,
        "ativos_60d": ativos_60d,
        "inativos_60d": inativos_60d
    })


#### FINANCEIRO ###
# --- BI FINANCEIRO ------------------------------------------------------------

from sqlalchemy import func, case, and_, cast, Float, Integer, text
from datetime import date, datetime, timedelta  # ✅ precisa do timedelta

def _parse_date(s: str):
    """Aceita 'YYYY-MM-DD' ou 'DD/MM/YYYY'. Retorna date|None."""
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except Exception:
        pass
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except Exception:
        return None


#PEGAR A DATA DA ULTIMA IMPORTAÇÃO
def get_last_import_date_emissao():
    return db.session.query(func.max(FinanceiroTitulo.emissao)).scalar()

@bp.route("/financeiro/financeiro_dashboard", methods=["GET"])
@requer_permissao("financeiro", "ver")
def financeiro_dashboard():
    """
    Sem filtros: Recebido/Atraso/Tendência usam TODAS as liquidações;
    demais KPIs/Gráficos usam o estado atual (hoje).
    Com filtros (dt_ini/dt_fim): Recebido/Atraso/Tendência consideram o intervalo de liquidação.
    'A vencer (7 dias)' sempre conta a partir de HOJE.
    """

    last_import_date_emissao = get_last_import_date_emissao()
    # ---------------- Filtros ----------------
    dt_ini = _parse_date(request.args.get("dt_ini", ""))
    dt_fim = _parse_date(request.args.get("dt_fim", ""))

    # 👉 Padrão: mês atual quando ambos vazios
    if not dt_ini and not dt_fim:
        hoje = date.today()
        primeiro = hoje.replace(day=1)
        proximo_mes = (primeiro.replace(day=28) + timedelta(days=4)).replace(day=1)
        dt_fim = proximo_mes - timedelta(days=1)
        dt_ini = primeiro
    # (não reatribuímos dt_ini/dt_fim de novo!)

    # ---------------- Constantes de data (hoje / +7d) ----------------
    hoje_sql = func.current_date()
    mais7_sql = func.current_date() + text("interval '7 day'")

    # ---------------- KPIs (independentes de filtro) ----------------
    total_aberto = (
        db.session.query(func.coalesce(func.sum(FinanceiroTitulo.saldo), 0.0))
        .filter(FinanceiroTitulo.saldo > 0)
        .scalar() or 0.0
    )

    total_vencido = (
        db.session.query(func.coalesce(func.sum(FinanceiroTitulo.saldo), 0.0))
        .filter(FinanceiroTitulo.saldo > 0,
                FinanceiroTitulo.vencimento < hoje_sql)
        .scalar() or 0.0
    )

    total_a_vencer_7 = (
        db.session.query(func.coalesce(func.sum(FinanceiroTitulo.saldo), 0.0))
        .filter(FinanceiroTitulo.saldo > 0,
                FinanceiroTitulo.vencimento >= hoje_sql,
                FinanceiroTitulo.vencimento <= mais7_sql)
        .scalar() or 0.0
    )

    # --- LISTAS P/ MODAIS -------------------------------------------------
    # dias vencidos = (hoje - vencimento), dias restantes = (vencimento - hoje)
    dias_vencidos = cast((func.current_date() - FinanceiroTitulo.vencimento), Integer)
    dias_restantes = cast((FinanceiroTitulo.vencimento - func.current_date()), Integer)

    # VENCIDOS EM ABERTO
    vencidos_list = (
        db.session.query(
            FinanceiroTitulo.cliente,
            FinanceiroTitulo.numero_doc,
            FinanceiroTitulo.vencimento,
            FinanceiroTitulo.saldo.label("valor_aberto"),
            dias_vencidos.label("dias")
        )
        .filter(
            FinanceiroTitulo.saldo > 0,
            FinanceiroTitulo.vencimento < func.current_date()
        )
        .order_by(FinanceiroTitulo.vencimento.asc())
        .limit(2000)
        .all()
    )

    # A VENCER (próximos 7 dias)
    a_vencer_list = (
        db.session.query(
            FinanceiroTitulo.cliente,
            FinanceiroTitulo.numero_doc,
            FinanceiroTitulo.vencimento,
            FinanceiroTitulo.saldo.label("valor_aberto"),
            dias_restantes.label("dias")
        )
        .filter(
            FinanceiroTitulo.saldo > 0,
            FinanceiroTitulo.vencimento >= func.current_date(),
            FinanceiroTitulo.vencimento <= (func.current_date() + text("interval '7 day'")),
        )
        .order_by(FinanceiroTitulo.vencimento.asc())
        .limit(2000)
        .all()
    )


    # ---------------- Recebido no período (filtrado por liquidação) ----------
    rec_q = db.session.query(
        func.coalesce(func.sum(FinanceiroTitulo.valor - FinanceiroTitulo.saldo), 0.0)
    ).filter(FinanceiroTitulo.liquidacao.isnot(None))
    if dt_ini:
        rec_q = rec_q.filter(FinanceiroTitulo.liquidacao >= dt_ini)
    if dt_fim:
        rec_q = rec_q.filter(FinanceiroTitulo.liquidacao <= dt_fim)
    total_recebido = rec_q.scalar() or 0.0

    # ---------------- Atraso médio (dias) — liquidados -----------------------
    atraso_q = db.session.query(
        func.avg(cast((FinanceiroTitulo.liquidacao - FinanceiroTitulo.vencimento), Float))
    ).filter(FinanceiroTitulo.liquidacao.isnot(None))
    if dt_ini:
        atraso_q = atraso_q.filter(FinanceiroTitulo.liquidacao >= dt_ini)
    if dt_fim:
        atraso_q = atraso_q.filter(FinanceiroTitulo.liquidacao <= dt_fim)
    atraso_medio = round(float(atraso_q.scalar() or 0.0), 1)

    # ---------------- Aging (saldo em aberto por faixa) ----------------------
    dias_atraso = cast((hoje_sql - FinanceiroTitulo.vencimento), Integer)
    dias_pos = func.greatest(dias_atraso, 0)
    aging_row = db.session.query(
        func.sum(case(
            (and_(FinanceiroTitulo.saldo > 0, FinanceiroTitulo.vencimento >= hoje_sql),
             FinanceiroTitulo.saldo), else_=0)).label("a_vencer"),
        func.sum(case(
            (and_(FinanceiroTitulo.saldo > 0, FinanceiroTitulo.vencimento < hoje_sql, dias_pos <= 15),
             FinanceiroTitulo.saldo), else_=0)).label("d0_15"),
        func.sum(case(
            (and_(FinanceiroTitulo.saldo > 0, dias_pos > 15, dias_pos <= 30),
             FinanceiroTitulo.saldo), else_=0)).label("d16_30"),
        func.sum(case(
            (and_(FinanceiroTitulo.saldo > 0, dias_pos > 30, dias_pos <= 60),
             FinanceiroTitulo.saldo), else_=0)).label("d31_60"),
        func.sum(case(
            (and_(FinanceiroTitulo.saldo > 0, dias_pos > 60, dias_pos <= 90),
             FinanceiroTitulo.saldo), else_=0)).label("d61_90"),
        func.sum(case(
            (and_(FinanceiroTitulo.saldo > 0, dias_pos > 90),
             FinanceiroTitulo.saldo), else_=0)).label("d90p"),
    ).one()

    aging_labels = ["A vencer", "0–15", "16–30", "31–60", "61–90", "90+"]
    aging_values = [float(aging_row.a_vencer or 0.0), float(aging_row.d0_15 or 0.0),
                    float(aging_row.d16_30 or 0.0), float(aging_row.d31_60 or 0.0),
                    float(aging_row.d61_90 or 0.0), float(aging_row.d90p or 0.0)]

    # ---------------- Top Devedores (saldo vencido) --------------------------
    top_rows = (
        db.session.query(
            FinanceiroTitulo.cliente,
            func.coalesce(func.sum(FinanceiroTitulo.saldo), 0.0).label("vencido"),
        )
        .filter(FinanceiroTitulo.saldo > 0,
                FinanceiroTitulo.vencimento < hoje_sql)
        .group_by(FinanceiroTitulo.cliente)
        .order_by(text("vencido DESC"))
        .limit(15)
        .all()
    )
    top_dev_labels = [r[0] or "—" for r in top_rows]
    top_dev_values = [float(r[1] or 0.0) for r in top_rows]

    # ---------------- Tendência (por mês de liquidação) ----------------------
    tend_q = db.session.query(
        func.date_trunc("month", FinanceiroTitulo.liquidacao).label("mes"),
        func.coalesce(func.sum(FinanceiroTitulo.valor - FinanceiroTitulo.saldo), 0.0).label("recebido")
    ).filter(FinanceiroTitulo.liquidacao.isnot(None))
    if dt_ini:
        tend_q = tend_q.filter(FinanceiroTitulo.liquidacao >= dt_ini)
    if dt_fim:
        tend_q = tend_q.filter(FinanceiroTitulo.liquidacao <= dt_fim)
    rec_rows = tend_q.group_by("mes").order_by("mes").all()
    tend_labels = [(r[0].date().strftime("%m/%Y") if hasattr(r[0], "date") else r[0].strftime("%m/%Y")) for r in rec_rows]
    tend_valores = [float(r[1] or 0.0) for r in rec_rows]

    # ---------------- Classe por atraso (clientes) ---------------------------
    classe_q = db.session.query(
        FinanceiroTitulo.cliente,
        func.avg(cast((FinanceiroTitulo.liquidacao - FinanceiroTitulo.vencimento), Float)).label("atraso_medio"),
    ).filter(FinanceiroTitulo.liquidacao.isnot(None))
    if dt_ini:
        classe_q = classe_q.filter(FinanceiroTitulo.liquidacao >= dt_ini)
    if dt_fim:
        classe_q = classe_q.filter(FinanceiroTitulo.liquidacao <= dt_fim)
    classe_rows = classe_q.group_by(FinanceiroTitulo.cliente).all()

    clientes_classe, classe_counts = [], {"Ótimo":0,"Bom":0,"Regular":0,"Alerta":0,"Ruim":0}
    for cli, atras in classe_rows:
        atras = float(atras or 0.0)
        if atras <= 0:   classe = "Ótimo"
        elif atras <= 5: classe = "Bom"
        elif atras <=10: classe = "Regular"
        elif atras <=20: classe = "Alerta"
        else:            classe = "Ruim"
        clientes_classe.append({"cliente": cli or "—", "atraso_medio": round(atras, 1), "classe": classe})
        classe_counts[classe] += 1

    # ---------------- Contexto ----------------
    ctx = dict(
        dt_ini=dt_ini.isoformat() if dt_ini else "",
        dt_fim=dt_fim.isoformat() if dt_fim else "",
        total_aberto=round(float(total_aberto), 2),
        total_vencido=round(float(total_vencido), 2),
        total_a_vencer_7=round(float(total_a_vencer_7), 2),
        total_recebido=round(float(total_recebido), 2),
        atraso_medio=atraso_medio,
        aging_labels=aging_labels,
        aging_values=[round(x, 2) for x in aging_values],
        top_dev_labels=top_dev_labels,
        top_dev_values=[round(x, 2) for x in top_dev_values],
        tend_labels=tend_labels,
        tend_valores=[round(x, 2) for x in tend_valores],
        classe_counts=classe_counts,
        clientes_classe=clientes_classe,
        vencidos_list=vencidos_list,
        a_vencer_list=a_vencer_list,
    )
    return render_template("financeiro/financeiro_dashboard.html",
                            **ctx, last_import_date_emissao=last_import_date_emissao)






# ===================== Importação (CSV/XLSX) ======================

# --- IMPORTAÇÃO FINANCEIRO ----------------------------------------------------
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from werkzeug.utils import secure_filename
from datetime import datetime, date
import pandas as pd
import io, os, re

from app import db
from app.models import FinanceiroTitulo  # seu modelo
from app.utils import allowed_file, requer_permissao

def _norm_col(s: str) -> str:
    """normaliza nome de coluna: minúsculo, troca espaços/acentos por _"""
    s = (s or "").strip()
    s = s.lower()
    s = re.sub(r"\s+", "_", s)
    s = s.replace("ç", "c").replace("ã","a").replace("á","a").replace("â","a") \
         .replace("é","e").replace("ê","e").replace("í","i").replace("ó","o") \
         .replace("ô","o").replace("ú","u").replace("õ","o")
    return s

def _parse_date_cell(val):
    """Converte célula para date (None se inválido). Aceita dd/mm/yyyy, yyyy-mm-dd e datetime excel/pandas."""
    if pd.isna(val) or val == "":
        return None
    # já é datetime/date?
    if isinstance(val, (datetime, date)):
        return val.date() if isinstance(val, datetime) else val
    txt = str(val).strip()
    # tenta ISO
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(txt, fmt).date()
        except Exception:
            pass
    # tenta BR
    for fmt in ("%d/%m/%Y", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(txt, fmt).date()
        except Exception:
            pass
    # tenta pandas (com coerce)
    try:
        dt = pd.to_datetime(txt, dayfirst=True, errors="coerce")
        if pd.isna(dt):
            return None
        return dt.date()
    except Exception:
        return None

def _parse_num(val):
    """Converte números com vírgula/ponto. Retorna float ou 0.0."""
    if pd.isna(val) or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    txt = str(val).strip()
    # remove separador de milhar e troca vírgula decimal por ponto
    txt = txt.replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except Exception:
        return 0.0

@bp.route("/financeiro/importar_titulos", methods=["GET", "POST"])
@requer_permissao('financeiro', 'editar')
def financeiro_importar():
    if request.method == "GET":
        # tela simples de upload (usa o layout que vc preferir)
        return render_template("financeiro/financeiro_importar.html")

    # POST
    f = request.files.get("arquivo")
    if not f or f.filename == "":
        flash("Selecione um arquivo.", "warning")
        return redirect(url_for("routes.financeiro_importar"))

    filename = secure_filename(f.filename)
    if not allowed_file(filename):
        flash("Extensão não permitida. Use CSV, XLS ou XLSX.", "danger")
        return redirect(url_for("routes.financeiro_importar"))

    ext = os.path.splitext(filename)[1].lower()

    try:
        # lê para memória para evitar problemas de caminho
        buf = f.read()
        if not buf:
            flash("Arquivo vazio.", "warning")
            return redirect(url_for("routes.financeiro_importar"))

        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(buf), sep=None, engine="python")  # detecta ; ou ,
        else:
            # xlsx/xls
            df = pd.read_excel(io.BytesIO(buf))  # openpyxl/xlrd conforme instalado

        # normaliza nomes
        orig_cols = list(df.columns)
        df.columns = [_norm_col(c) for c in df.columns]

        # mapeamento mínimo obrigatório
        required = [
            "empresa","cliente","representante","especie","numero_doc",
            "emissao","vencimento","liquidacao","valor","saldo","conta_bancaria","banco"
        ]
        # alguns ERPs exportam 'salto'/'restante' – você pode adaptar aqui:
        aliases = {"saldo": ["saldo","restante","valor_aberto","aberto"]}
        for key, al in aliases.items():
            if key not in df.columns:
                for a in al:
                    if a in df.columns:
                        df.rename(columns={a: key}, inplace=True)
                        break

        missing = [c for c in required if c not in df.columns]
        if missing:
            flash(f"Colunas ausentes: {', '.join(missing)}. Detectadas: {', '.join(df.columns)}", "danger")
            # loga no console para debug
            current_app.logger.warning(f"[IMPORT FIN] Colunas originais: {orig_cols}")
            return redirect(url_for("routes.financeiro_importar"))

        # parse datas e números
        for col in ["emissao", "vencimento", "liquidacao"]:
            df[col] = df[col].apply(_parse_date_cell)
        for col in ["valor", "saldo"]:
            df[col] = df[col].apply(_parse_num)

        # limpa linhas totalmente vazias (pelo menos cliente e numero_doc)
        df = df.dropna(how="all")
        df = df[df["cliente"].astype(str).str.strip() != ""]
        df = df[df["numero_doc"].astype(str).str.strip() != ""]

        if df.empty:
            flash("Nenhuma linha válida encontrada após limpeza.", "warning")
            return redirect(url_for("routes.financeiro_importar"))

        # imprime amostra no console
        sample = df.head(3).to_dict(orient="records")
        current_app.logger.info(f"[IMPORT FIN] Colunas normalizadas: {list(df.columns)}")
        current_app.logger.info(f"[IMPORT FIN] Primeiras linhas: {sample}")

        # grava
        to_add = []
        linhas = 0
        for _, r in df.iterrows():
            def _txt(v):
                """Converte para string segura (aceita números, None, etc)."""
                if pd.isna(v):
                    return ""
                return str(v).strip()

            t = FinanceiroTitulo(
                empresa=_txt(r.get("empresa")),
                cliente=_txt(r.get("cliente")),
                representante=_txt(r.get("representante")),
                especie=_txt(r.get("especie")),
                numero_doc=_txt(r.get("numero_doc")),
                emissao=r.get("emissao"),
                vencimento=r.get("vencimento"),
                liquidacao=r.get("liquidacao"),  # pode ser None
                valor=float(r.get("valor") or 0.0),
                saldo=float(r.get("saldo") or 0.0),
                conta_bancaria=_txt(r.get("conta_bancaria")),
                banco=_txt(r.get("banco")),
            )
            to_add.append(t)

        if not to_add:
            flash("Arquivo processado, mas não havia linhas válidas para salvar.", "warning")
            return redirect(url_for("routes.financeiro_importar"))

        db.session.bulk_save_objects(to_add)
        db.session.commit()

        flash(f"Importação concluída: {linhas} linha(s) processadas e salvas.", "success")
        return redirect(url_for("routes.financeiro_dashboard"))

    except Exception as e:
        current_app.logger.exception("[IMPORT FIN] Falha ao importar")
        flash(f"Erro ao importar: {e}", "danger")
        return redirect(url_for("routes.financeiro_importar"))

@bp.route("/financeiro/importar/modelo.csv", methods=["GET"])
@requer_permissao('financeiro', 'ver')
def financeiro_importar_modelo():
    """
    Gera um modelo de planilha para importação do BI Financeiro.

    Usa ; (ponto-e-vírgula) como separador, que é o padrão do Excel em PT-BR.
    O import continua funcionando porque o read_csv está com sep=None.
    """
    # cabeçalho na ordem esperada
    csv_lines = [
        "empresa;cliente;representante;especie;numero_doc;emissao;vencimento;liquidacao;valor;saldo;conta_bancaria;banco",
        # exemplos de linhas (opcionais)
        "MINHA EMPRESA;CLIENTE A;REP 1;BOLETO;12345;01/11/2025;15/11/2025;;1.234,56;1.234,56;Conta 123;BANCO X",
        "MINHA EMPRESA;CLIENTE B;REP 2;DUPLICATA;12346;02/11/2025;12/11/2025;13/11/2025;2.345,67;0,00;Conta 456;BANCO Y",
    ]

    from flask import Response
    return Response(
        "\n".join(csv_lines),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=modelo_financeiro.csv"}
    )




# --- ZERAR DADOS BI ----------------------------------------------------------
from sqlalchemy import text
from flask import redirect, url_for, flash, request
from app import db, csrf
from app.utils import requer_permissao

# Ajuste aqui se os nomes forem diferentes:
BI_FINANCEIRO_TABLES = [
       FinanceiroTitulo.__tablename__,         # -> FinanceiroTitulo.__tablename__
]

# Para o BI comercial (2 arquivos importados)
BI_COMERCIAL_TABLES = [
    Venda.__tablename__,                    # tabela de vendas importadas
    RefVenda.__tablename__,                 # tabela de referencias/itens importados
]

def _truncate_tables(table_names: list[str]):
    # Usa aspas duplas pra preservar nomes snake_case minúsculos no Postgres
    for t in table_names:
        db.session.execute(text(f'TRUNCATE TABLE "{t}" RESTART IDENTITY CASCADE'))
    db.session.commit()

@bp.route("/financeiro/zerar", methods=["POST"])
@requer_permissao("financeiro", "editar")
def bi_financeiro_zerar():
    # proteção extra: exige confirmação vinda do modal
    confirm = request.form.get("confirm", "").strip().upper()
    if confirm != "ZERAR":
        flash("Confirmação inválida. Digite ZERAR para prosseguir.", "warning")
        return redirect(url_for("routes.listar_titulos"))

    try:
        _truncate_tables(BI_FINANCEIRO_TABLES)
        flash("BI Financeiro zerado com sucesso.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Falha ao zerar BI Financeiro: {e}", "danger")
    return redirect(url_for("routes.listar_titulos"))

@bp.route("/comercial/zerar", methods=["POST"])
@requer_permissao("comercial", "editar")
def bi_comercial_zerar():
    confirm = request.form.get("confirm", "").strip().upper()
    if confirm != "ZERAR":
        flash("Confirmação inválida. Digite ZERAR para prosseguir.", "warning")
        return redirect(url_for("routes.listar_vendas"))  # ajuste o endpoint

    try:
        _truncate_tables(BI_COMERCIAL_TABLES)
        flash("BI Comercial zerado com sucesso.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Falha ao zerar BI Comercial: {e}", "danger")
    return redirect(url_for("routes.listar_vendas"))      # ajuste o endpoint



def _aplicar_filtros_titulos(q):
    """Filtros vindos por querystring (?data_ini=...&data_fim=...&estado=... etc.)."""
    data_ini  = request.args.get("emissao")
    data_fim  = request.args.get("emissao")
    representante = request.args.get("representante")
    cliente   = request.args.get("cliente")

    if data_ini: q = q.filter(FinanceiroTitulo.emissao >= data_ini)
    if data_fim: q = q.filter(FinanceiroTitulo.emissao <= data_fim)
    if representante: q = q.filter(FinanceiroTitulo.representante.ilike(f"%{representante}%"))
    if cliente:       q = q.filter(FinanceiroTitulo.cliente.ilike(f"%{cliente}%"))
    return q

@bp.route("/financeiro/titulos_abertos", methods=["GET"])
@requer_permissao('comercial', 'ver')
def listar_titulos():
    q = _aplicar_filtros_titulos(FinanceiroTitulo.query).order_by(FinanceiroTitulo.vencimento.desc(), FinanceiroTitulo.id.desc())
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    pag = q.paginate(page=page, per_page=per_page, error_out=False)

    # args sem 'page'
    qargs = request.args.to_dict()
    qargs.pop('page', None)

    # monta URLs de navegação
    from flask import url_for
    prev_url = url_for("routes.listar_titulos", **qargs, page=pag.prev_num) if pag.has_prev else None
    next_url = url_for("routes.listar_titulos", **qargs, page=pag.next_num) if pag.has_next else None

    pages = []
    for p in pag.iter_pages(left_edge=1, right_edge=1, left_current=2, right_current=2):
        if p:
            pages.append({
                "num": p,
                "url": url_for("routes.listar_titulos", **qargs, page=p),
                "active": (p == pag.page)
            })
        else:
            pages.append(None)  # separador (reticências)
    return render_template(
        "financeiro/listar_titulos.html",
        pag=pag, pages=pages, prev_url=prev_url, next_url=next_url
    )


#### EMAIL   ####

from flask import current_app, jsonify
from flask_mail import Message
from app import mail

@bp.route("/teste_email", methods=["GET"])
def teste_email():
    try:
        msg = Message(
            subject="Teste de e-mail sysPCP",
            recipients=[current_app.config.get("ALERTA_RFM_EMAIL")]
        )
        msg.body = "Se você recebeu este e-mail, o Flask-Mail está configurado corretamente."
        mail.send(msg)
        return jsonify({"status": "ok", "mensagem": "E-mail de teste enviado!"})
    except Exception as e:
        current_app.logger.exception("[TESTE_EMAIL] Erro ao enviar")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


from datetime import date, datetime

from flask import current_app, jsonify, request
from sqlalchemy import func

from flask_mail import Message
from app import db, mail
from app.utils import requer_permissao
from app.models import Venda, AlertaInatividadeCliente

@bp.route("/comercial/rfm_alerta_email", methods=["GET"])
@requer_permissao('comercial', 'ver')
def rfm_alerta_email():
    """
    Envia um e-mail apenas com os NOVOS clientes que passaram a ter
    mais de N dias sem comprar (padrão 120 dias).

    Lógica:
      1) Calcula a última data de compra de cada cliente.
      2) Verifica quantos dias está sem comprar.
      3) Compara com a tabela AlertaInatividadeCliente para ver se
         esse cliente com essa mesma última_data_venda já foi alertado.
      4) Envia e-mail apenas dos que ainda não foram avisados.
      5) Registra um alerta para cada um na tabela.
    """

    # 1) parâmetro ?dias= (se não vier, assume 120)
    try:
        limite_dias = int(request.args.get("dias", 120))
    except Exception:
        limite_dias = 120

    hoje = date.today()

    # 2) Query: última data de compra por cliente + representante
    #    (representante aqui é só para aparecer na mensagem)
    q = (
        db.session.query(
            Venda.cliente.label("cliente"),
            func.max(Venda.data_inclusao).label("ultima_data"),
            func.min(Venda.representante).label("representante")  # pega 1 representante
        )
        .group_by(Venda.cliente)
    )

    rows = q.all()

    # Lista com todos que estão hoje acima do limite de dias
    clientes_atrasados = []
    for r in rows:
        if not r.ultima_data:
            continue

        dias_sem_comprar = (hoje - r.ultima_data).days
        if dias_sem_comprar > limite_dias:
            clientes_atrasados.append(
                {
                    "cliente": r.cliente,
                    "ultima_data": r.ultima_data,
                    "dias": dias_sem_comprar,
                    "representante": r.representante,
                }
            )

    if not clientes_atrasados:
        return jsonify(
            {
                "status": "ok",
                "mensagem": f"Nenhum cliente com mais de {limite_dias} dias sem comprar.",
                "qtd_clientes": 0
            }
        )

    # 3) Verifica na tabela de alertas quais já foram avisados
    #    Chave de controle: (cliente, ultima_data_venda)
    clientes_lista = list({c["cliente"] for c in clientes_atrasados})

    alertas_existentes = (
        db.session.query(
            AlertaInatividadeCliente.cliente,
            AlertaInatividadeCliente.ultima_data_venda
        )
        .filter(AlertaInatividadeCliente.cliente.in_(clientes_lista))
        .all()
    )

    alertas_set = {(a.cliente, a.ultima_data_venda) for a in alertas_existentes}

    novos_clientes_atrasados = [
        c for c in clientes_atrasados
        if (c["cliente"], c["ultima_data"]) not in alertas_set
    ]

    # Se não houver nenhum novo cliente atrasado, não manda e-mail
    if not novos_clientes_atrasados:
        return jsonify({
            "status": "ok",
            "mensagem": "Nenhum NOVO cliente entrou na faixa de atraso desde o último alerta.",
            "qtd_clientes": 0
        })

    # 4) Monta corpo do e-mail
    linhas = [
        f"Novos clientes com mais de {limite_dias} dias sem comprar:",
        ""
    ]
    for item in novos_clientes_atrasados:
        linhas.append(
            f"- {item['cliente']} (Rep: {item['representante']}) "
            f"está há {item['dias']} dias sem comprar "
            f"(última compra em {item['ultima_data'].strftime('%d/%m/%Y')})."
        )

    corpo = "\n".join(linhas)

    destinatario = current_app.config.get(
        "ALERTA_RFM_EMAIL",
        "wilian.senna@gmail.com"
    )

    assunto = f"[ALERTA COMERCIAL PVC] Novos clientes > {limite_dias} dias sem comprar"

    # 5) Envia o e-mail e registra os alertas
    try:
        msg = Message(
            subject=assunto,
            recipients=[destinatario],
            body=corpo,
        )
        mail.send(msg)

        # Registra um alerta para cada cliente enviado
        for c in novos_clientes_atrasados:
            alerta = AlertaInatividadeCliente(
                cliente=c["cliente"],
                ultima_data_venda=c["ultima_data"],
                data_alerta=datetime.utcnow()
            )
            db.session.add(alerta)

        db.session.commit()

        return jsonify(
            {
                "status": "ok",
                "mensagem": f"E-mail enviado para {destinatario}.",
                "qtd_clientes": len(novos_clientes_atrasados),
            }
        )
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("[RFM ALERTA EMAIL] Falha ao enviar e/ou registrar alertas")
        return jsonify(
            {
                "status": "erro",
                "mensagem": f"Erro ao enviar e-mail ou salvar alertas: {e}",
            }
        ), 500


#### BI 3 ####


# Se já tiver essas helpers definidas em outro lugar, PODE APAGAR estas versões
def _parse_date_bi3(s: str):
    """Converte 'YYYY-MM-DD' ou vazio em date ou None."""
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except Exception:
        return None


def _coluna_metrica(metric: str):
    """
    'valor' -> Venda.valor
    'quantidade' -> Venda.quantidade
    """
    metric = (metric or "").lower()
    if metric == "quantidade":
        return Venda.quantidade
    return Venda.valor


def _get_last_import_date_vendas():
    return db.session.query(func.max(Venda.data_inclusao)).scalar()


@bp.route("/comercial/vendas_dashboard_rede", methods=["GET"])
@requer_permissao("comercial", "ver")
def vendas_dashboard_rede():
    """
    Tela principal do BI III (Rede / Cliente).
    Toda a lógica pesada vem por AJAX (JSON) abaixo.
    """
    last_import_dt_vendas = _get_last_import_date_vendas()

    # Deixa os filtros iniciais vazios (ou você pode colocar defaults)
    ctx = dict(
        data_ini=request.args.get("data_ini", "") or "",
        data_fim=request.args.get("data_fim", "") or "",
        metric=request.args.get("metric", "valor") or "valor",
        estado_sel=request.args.get("estado", "") or "",
        rede_loja_sel=request.args.get("rede_loja", "") or "",
        last_import_dt_vendas=last_import_dt_vendas,
    )
    return render_template("comercial/vendas_dashboard_rede.html", **ctx)


# ---------- Aggregations JSON ----------

@bp.route("/comercial/bi3/agg_redes", methods=["GET"])
@requer_permissao("comercial", "ver")
def bi3_agg_redes():
    """
    Retorna redes de loja agregadas por valor ou quantidade.

    - Sem parâmetro ?all=1  -> TOP 10 (para o card / gráfico)
    - Com parâmetro ?all=1  -> TODAS as redes (para preencher o select)
    Filtros: data_ini, data_fim, estado.
    """
    metric = request.args.get("metric", "valor")
    col = _coluna_metrica(metric)

    data_ini = _parse_date_bi3(request.args.get("data_ini"))
    data_fim = _parse_date_bi3(request.args.get("data_fim"))
    estado = (request.args.get("estado") or "").strip()
    all_flag = request.args.get("all")  # qualquer valor já indica "trazer todas"

    q = db.session.query(
        Venda.rede_loja,
        func.coalesce(func.sum(col), 0).label("total"),
        func.count(func.distinct(Venda.cliente)).label("clientes"),
    )

    if data_ini:
        q = q.filter(Venda.data_inclusao >= data_ini)
    if data_fim:
        q = q.filter(Venda.data_inclusao <= data_fim)
    if estado:
        q = q.filter(Venda.estado == estado)

    q = q.group_by(Venda.rede_loja).order_by(func.sum(col).desc())

    # Top 10 só quando NÃO for chamada com ?all=1
    if not all_flag:
        q = q.limit(10)

    rows = q.all()

    res = []
    for rede, total, clientes in rows:
        res.append(
            {
                # aqui devolvemos o valor cru do banco (pode ser None)
                "rede_loja": rede,
                "total": float(total or 0),
                "clientes": int(clientes or 0),
            }
        )
    return jsonify(res)



@bp.route("/comercial/bi3/agg_clientes", methods=["GET"])
@requer_permissao("comercial", "ver")
def bi3_agg_clientes():
    """
    Top Clientes agregados por rede (opcional).
    Filtros: data_ini, data_fim, estado, rede_loja.
    """
    metric = request.args.get("metric", "valor")
    col = _coluna_metrica(metric)

    data_ini = _parse_date_bi3(request.args.get("data_ini"))
    data_fim = _parse_date_bi3(request.args.get("data_fim"))
    estado = (request.args.get("estado") or "").strip()
    rede_loja = (request.args.get("rede_loja") or "").strip()

    q = db.session.query(
        Venda.cliente,
        func.coalesce(func.sum(col), 0).label("total"),
    )

    if data_ini:
        q = q.filter(Venda.data_inclusao >= data_ini)
    if data_fim:
        q = q.filter(Venda.data_inclusao <= data_fim)
    if estado:
        q = q.filter(Venda.estado == estado)
    if rede_loja:
        q = q.filter(Venda.rede_loja == rede_loja)

    q = (
        q.group_by(Venda.cliente)
         .order_by(func.sum(col).desc())
         .limit(10)
         .all()
    )

    res = [{"cliente": c, "total": float(t or 0)} for c, t in q]
    return jsonify(res)


@bp.route("/comercial/bi3/rede_ultimas", methods=["GET"])
@requer_permissao("comercial", "ver")
def bi3_rede_ultimas():
    """
    Redes de loja com última venda mais antiga (para achar redes 'paradas').
    Filtros: data_ini, data_fim, estado.
    """
    metric = request.args.get("metric", "valor")
    col = _coluna_metrica(metric)

    data_ini = _parse_date_bi3(request.args.get("data_ini"))
    data_fim = _parse_date_bi3(request.args.get("data_fim"))
    estado = (request.args.get("estado") or "").strip()

    q = db.session.query(
        Venda.rede_loja.label("rede_loja"),
        func.max(Venda.data_inclusao).label("ultima_data"),
        func.coalesce(func.sum(col), 0).label("total"),
    )

    if data_ini:
        q = q.filter(Venda.data_inclusao >= data_ini)
    if data_fim:
        q = q.filter(Venda.data_inclusao <= data_fim)
    if estado:
        q = q.filter(Venda.estado == estado)

    q = q.group_by(Venda.rede_loja).all()

    hoje = date.today()
    linhas = []
    for rede, ultima, total in q:
        if ultima:
            dias = (hoje - ultima).days
        else:
            dias = None
        linhas.append(
            {
                "rede_loja": rede or "SEM REDE",
                "ultima_data": ultima.isoformat() if ultima else None,
                "dias_sem_vender": dias,
                "total": float(total or 0),
            }
        )

    # Ordena por maior tempo sem vender
    linhas.sort(
        key=lambda x: (x["dias_sem_vender"] if x["dias_sem_vender"] is not None else -1),
        reverse=True,
    )
    return jsonify(linhas)


@bp.route("/comercial/bi3/clientes_ultimos", methods=["GET"])
@requer_permissao("comercial", "ver")
def bi3_clientes_ultimos():
    """
    Clientes com última venda mais antiga DENTRO de uma Rede (opcional).
    Se rede_loja não vier, considera todos os clientes.
    """
    metric = request.args.get("metric", "valor")
    col = _coluna_metrica(metric)

    data_ini = _parse_date_bi3(request.args.get("data_ini"))
    data_fim = _parse_date_bi3(request.args.get("data_fim"))
    estado = (request.args.get("estado") or "").strip()
    rede_loja = (request.args.get("rede_loja") or "").strip()

    q = db.session.query(
        Venda.cliente.label("cliente"),
        func.max(Venda.data_inclusao).label("ultima_data"),
        func.coalesce(func.sum(col), 0).label("total"),
    )

    if data_ini:
        q = q.filter(Venda.data_inclusao >= data_ini)
    if data_fim:
        q = q.filter(Venda.data_inclusao <= data_fim)
    if estado:
        q = q.filter(Venda.estado == estado)
    if rede_loja:
        q = q.filter(Venda.rede_loja == rede_loja)

    q = q.group_by(Venda.cliente).all()

    hoje = date.today()
    linhas = []
    for cliente, ultima, total in q:
        if ultima:
            dias = (hoje - ultima).days
        else:
            dias = None
        linhas.append(
            {
                "cliente": cliente,
                "ultima_data": ultima.isoformat() if ultima else None,
                "dias_sem_vender": dias,
                "total": float(total or 0),
            }
        )

    # Ordena por maior tempo sem vender
    linhas.sort(
        key=lambda x: (x["dias_sem_vender"] if x["dias_sem_vender"] is not None else -1),
        reverse=True,
    )
    return jsonify(linhas)

def _get_last_import_date_vendas():
    return db.session.query(func.max(Venda.data_inclusao)).scalar()


@bp.route("/comercial/vendas/dashboard_master", methods=["GET"])
@requer_permissao("comercial", "ver")
def vendas_dashboard_master():
    """
    BI Master – painel unificado de vendas.
    """
    last_import_dt_vendas = _get_last_import_date_vendas()

    hoje = date.today()
    dt_ini_default = hoje - timedelta(days=30)

    dt_ini = request.args.get("dt_ini") or dt_ini_default.isoformat()
    dt_fim = request.args.get("dt_fim") or hoje.isoformat()

    ctx = dict(
      last_import_dt_vendas=last_import_dt_vendas,
      dt_ini=dt_ini,
      dt_fim=dt_fim,
      representante_sel=request.args.get("representante", "") or "",
      estado_sel=request.args.get("estado", "") or "",
      metric=request.args.get("metric", "valor") or "valor",
      rede_loja_sel=request.args.get("rede_loja", "") or "",
    )
    return render_template("comercial/vendas_dashboard_master.html", **ctx)