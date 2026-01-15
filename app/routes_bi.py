from datetime import date
import os
from flask import current_app, jsonify, render_template, redirect, url_for, request, flash
from flask_login import current_user, login_required
from sqlalchemy import func
from werkzeug.utils import secure_filename  # 🔹 Para salvar o nome do arquivo corretamente

from app import db
from app.models import Venda
from app.forms import ImportarVendasForm, VendaForm
from app.utils import formatar_data, formatar_moeda, formatar_numero, requer_permissao


from sqlalchemy.exc import IntegrityError

from app import csrf


from app.routes import bp
from app.utils_licenca import requer_licenca_ativa  # ← IMPORTA O MESMO BLUEPRINT DO routes.py

@bp.route("/bi/listar_vendas")
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "ver")
def bi_listar_vendas():

    page = request.args.get("page", 1, type=int)
    per_page = 15

    busca = request.args.get("busca", "").strip()

    query = Venda.query_empresa()

    if busca:
        busca_ilike = f"%{busca}%"
        query = query.filter(
            db.or_(
                Venda.pedido.ilike(busca_ilike),
                Venda.cliente.ilike(busca_ilike),
                Venda.representante.ilike(busca_ilike),
                Venda.produto.ilike(busca_ilike)
            )
        )

    pagination = (
        query
        .order_by(Venda.data_inclusao.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    return render_template(
        "bi/vendas_listar.html",
        vendas=pagination.items,
        pagination=pagination,
        busca=busca
    )

@bp.route("/bi/vendas/nova", methods=["GET", "POST"])
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "criar")
def bi_nova_venda():

    form = VendaForm()

    if form.validate_on_submit():

        venda = Venda(
            empresa_id=current_user.empresa_id,
            representante=form.representante.data,
            cliente=form.cliente.data,
            pedido=form.pedido.data,
            estado=form.estado.data,
            municipio=form.municipio.data,
            data_inclusao=form.data_inclusao.data,
            quantidade=form.quantidade.data,
            valor=form.valor.data,
            produto=form.produto.data,
            grupo=form.grupo.data,
            regiao=form.regiao.data,
            rede_loja=form.rede_loja.data,
        )

        db.session.add(venda)
        db.session.commit()

        flash("Venda cadastrada com sucesso!", "success")
        return redirect(url_for("routes.bi_listar_vendas"))

    return render_template(
        "bi/vendas_form.html",
        form=form
    )

@bp.route("/bi/vendas/<int:id>/editar", methods=["GET", "POST"])
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "editar")
def bi_editar_venda(id):

    venda = (
        Venda.query_empresa()
        .filter_by(id=id)
        .first_or_404()
    )

    form = VendaForm(obj=venda)

    if form.validate_on_submit():

        venda.representante = form.representante.data
        venda.cliente = form.cliente.data
        venda.pedido = form.pedido.data
        venda.estado = form.estado.data
        venda.municipio = form.municipio.data
        venda.data_inclusao = form.data_inclusao.data
        venda.quantidade = form.quantidade.data
        venda.valor = form.valor.data
        venda.produto = form.produto.data
        venda.grupo = form.grupo.data
        venda.regiao = form.regiao.data
        venda.rede_loja = form.rede_loja.data

        db.session.commit()

        flash("Venda atualizada com sucesso!", "success")
        return redirect(url_for("routes.bi_listar_vendas"))

    return render_template(
        "bi/vendas_form.html",
        form=form,
        venda=venda
    )

@bp.route("/bi/vendas/excluir/<int:id>", methods=["POST"])
@login_required
@requer_permissao("comercial", "excluir")
def bi_excluir_venda(id):

    venda = (
        Venda.query_empresa()
        .filter_by(id=id)
        .first_or_404()
    )

    try:
        db.session.delete(venda)
        db.session.commit()
        flash("Venda excluída com sucesso!", "success")

    except IntegrityError:
        db.session.rollback()
        flash(
            "Erro: Não foi possível excluir a venda.",
            "danger"
        )

    return redirect(url_for("routes.bi_listar_vendas"))


from datetime import date, timedelta

def aplicar_filtros_vendas(query):
    hoje = date.today()
    data_padrao_de = hoje - timedelta(days=90)

    data_de = request.args.get("data_de")
    data_ate = request.args.get("data_ate")
    representante = request.args.get("representante")
    uf = request.args.get("uf")
    rede_loja = request.args.get("rede_loja")

    # ======================
    # DATA (PADRÃO BACKEND)
    # ======================
    if not data_de and not data_ate:
        query = query.filter(Venda.data_inclusao >= data_padrao_de)
    else:
        if data_de:
            query = query.filter(Venda.data_inclusao >= data_de)
        if data_ate:
            query = query.filter(Venda.data_inclusao <= data_ate)

    # ======================
    # DEMAIS FILTROS
    # ======================
    if representante:
        query = query.filter(Venda.representante == representante)

    if uf:
        query = query.filter(Venda.estado == uf)

    if rede_loja:
        query = query.filter(Venda.rede_loja == rede_loja)

    return query



@bp.route("/bi/vendas_dashboard")
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "ver")
def bi_vendas_dashboard():
    return render_template("bi/dashboard_vendas.html")

from datetime import date, timedelta
from sqlalchemy import func
from flask import request, jsonify


@bp.route("/bi/api/vendas")
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "ver")
def bi_api_vendas():

    # =====================================================
    # DATAS PADRÃO
    # =====================================================
    hoje = date.today()
    data_padrao_de = hoje - timedelta(days=90)

    data_de = request.args.get("data_de")
    data_ate = request.args.get("data_ate")

    data_de_efetiva = (
        date.fromisoformat(data_de)
        if data_de
        else data_padrao_de
    )

    data_ate_efetiva = (
        date.fromisoformat(data_ate)
        if data_ate
        else hoje
    )

    # =====================================================
    # TAMANHO DO PERÍODO ATUAL
    # =====================================================
    dias_periodo = (data_ate_efetiva - data_de_efetiva).days + 1

    # =====================================================
    # PERÍODO ANTERIOR
    # =====================================================
    data_ate_anterior = data_de_efetiva - timedelta(days=1)
    data_de_anterior = data_ate_anterior - timedelta(days=dias_periodo - 1)

    # =====================================================
    # QUERY BASE – PERÍODO ATUAL
    # =====================================================
    base_query = Venda.query_empresa()
    base_query = aplicar_filtros_vendas(base_query)

    total_qtd_atual, total_valor = (
        base_query
        .with_entities(
            func.coalesce(func.sum(Venda.quantidade), 0),
            func.coalesce(func.sum(Venda.valor), 0)
        )
        .first()
    )

    clientes = (
        base_query
        .with_entities(func.count(func.distinct(Venda.cliente)))
        .scalar()
        or 0
    )
    media_pares_cliente = (
    total_qtd_atual / clientes
    if clientes else 0)


    preco_medio = (total_valor / total_qtd_atual) if total_qtd_atual else 0
    ticket_medio = (total_valor / clientes) if clientes else 0

    # =====================================================
    # QUERY – PERÍODO ANTERIOR (MESMOS FILTROS)
    # =====================================================
    query_anterior = Venda.query_empresa()

    if request.args.get("representante"):
        query_anterior = query_anterior.filter(
            Venda.representante == request.args.get("representante")
        )

    if request.args.get("uf"):
        query_anterior = query_anterior.filter(
            Venda.estado == request.args.get("uf")
        )

    if request.args.get("rede_loja"):
        query_anterior = query_anterior.filter(
            Venda.rede_loja == request.args.get("rede_loja")
        )

    query_anterior = query_anterior.filter(
        Venda.data_inclusao >= data_de_anterior,
        Venda.data_inclusao <= data_ate_anterior
    )

    total_qtd_anterior = (
        query_anterior
        .with_entities(func.coalesce(func.sum(Venda.quantidade), 0))
        .scalar()
    )

    # =====================================================
    # VARIAÇÃO (%)
    # =====================================================
    if total_qtd_anterior > 0:
        quantidade_variacao = (
            (total_qtd_atual - total_qtd_anterior)
            / total_qtd_anterior
        ) * 100
    else:
        quantidade_variacao = None

    # =====================================================
    # TENDÊNCIA MENSAL
    # =====================================================
    tendencia_raw = (
        base_query
        .with_entities(
            func.date_trunc("month", Venda.data_inclusao).label("mes"),
            func.sum(Venda.quantidade).label("quantidade")
        )
        .group_by("mes")
        .order_by("mes")
        .all()
    )

    tendencia = {
        "labels": [t.mes.strftime("%m/%Y") for t in tendencia_raw],
        "values": [int(t.quantidade) for t in tendencia_raw],
    }

    # =====================================================
    # FILTROS (SELECT2)
    # =====================================================
    base_filtros = Venda.query_empresa()

    representantes = (
        base_filtros.with_entities(Venda.representante)
        .filter(Venda.representante.isnot(None))
        .distinct()
        .order_by(Venda.representante)
        .all()
    )

    ufs = (
        base_filtros.with_entities(Venda.estado)
        .filter(Venda.estado.isnot(None))
        .distinct()
        .order_by(Venda.estado)
        .all()
    )

    redes = (
        base_filtros.with_entities(Venda.rede_loja)
        .filter(Venda.rede_loja.isnot(None))
        .distinct()
        .order_by(Venda.rede_loja)
        .all()
    )

    # =====================================================
    # RESPONSE FINAL
    # =====================================================
    return jsonify({
        "kpis": {
            "quantidade": formatar_numero(total_qtd_atual),
            "quantidade_variacao": (
                round(quantidade_variacao, 2)
                if quantidade_variacao is not None
                else None
            ),
            "valor": formatar_moeda(total_valor),
            "preco_medio": formatar_moeda(preco_medio),
            "clientes": formatar_numero(clientes),
            "ticket_medio": formatar_moeda(ticket_medio),
            "media_pares_cliente": round(media_pares_cliente),
        },
        "tendencia": tendencia,
        "filtros": {
            "representantes": [r[0] for r in representantes if r[0]],
            "ufs": [u[0] for u in ufs if u[0]],
            "redes": [r[0] for r in redes if r[0]],
            "data_de": data_de_efetiva.strftime("%Y-%m-%d"),
            "data_ate": data_ate_efetiva.strftime("%Y-%m-%d"),
        }
    })

### RFM LIST

from datetime import date
from sqlalchemy import func
from app.utils import formatar_data


@bp.route("/bi/api/rfm/card")
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "ver")
def bi_api_rfm_card():

    hoje = date.today()

    base = Venda.query_empresa()
    base = aplicar_filtros_vendas(base)

    rows = (
        base.with_entities(
            Venda.cliente,
            func.max(Venda.data_inclusao).label("ultima")
        )
        .group_by(Venda.cliente)
        .all()
    )

    rfm = {
        "ate_30": 0,
        "ate_90": 0,
        "mais_90": 0
    }

    for _, ultima in rows:
        dias = (hoje - ultima).days if ultima else 9999

        if dias <= 30:
            rfm["ate_30"] += 1
        elif dias <= 90:
            rfm["ate_90"] += 1
        else:
            rfm["mais_90"] += 1

    return jsonify(rfm)
@bp.route("/bi/api/rfm/list")
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "ver")
def bi_rfm_list():

    hoje = date.today()
    status = request.args.get("status")

    base = Venda.query_empresa()
    base = aplicar_filtros_vendas(base)

    rows = (
        base.with_entities(
            Venda.cliente.label("cliente"),
            func.max(Venda.data_inclusao).label("ultima_compra"),
            func.count(Venda.id).label("frequencia"),
            func.coalesce(func.sum(Venda.quantidade), 0).label("total_pares")
        )
        .group_by(Venda.cliente)
        .order_by(func.max(Venda.data_inclusao).desc())
        .all()
    )

    clientes = []

    for cli, ultima, freq, total in rows:
        dias = (hoje - ultima).days if ultima else 9999

        if dias <= 30:
            status_cli = "Ativo"
        elif dias <= 90:
            status_cli = "Risco"
        else:
            status_cli = "Inativo"

        if status == "30" and dias > 30:
            continue
        if status == "90" and not (31 <= dias <= 90):
            continue
        if status == "90p" and dias <= 90:
            continue


        clientes.append({
            "cliente": cli,
            "status": status_cli,
            "ultima_compra": formatar_data(ultima),
            "dias": dias,
            "frequencia": freq,
            "total_pares": total
        })

    # 👉 filtros efetivos (mesmos do dashboard)
    data_de = request.args.get("data_de")
    data_ate = request.args.get("data_ate")

    if not data_de and not data_ate:
        data_de = (hoje - timedelta(days=90))
        data_ate = hoje

    return jsonify({
        "clientes": clientes,
        "filtros": {
            "data_de": formatar_data(data_de),
            "data_ate": formatar_data(data_ate),
            "representante": request.args.get("representante") or "Todos",
            "uf": request.args.get("uf") or "Todas",
            "rede_loja": request.args.get("rede_loja") or "Todas"
        }
    })




from datetime import date, timedelta
from sqlalchemy import func

from datetime import date, timedelta

def get_periodo_efetivo():
    hoje = date.today()

    data_de = request.args.get("data_de")
    data_ate = request.args.get("data_ate")

    if data_de and data_ate:
        return data_de, data_ate

    # padrão backend
    return hoje - timedelta(days=30), hoje

@bp.route("/bi/api/vendas/crescimento")
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "ver")
def bi_api_vendas_crescimento():

    inicio, fim = get_periodo_efetivo()

    base = Venda.query_empresa()
    base = aplicar_filtros_vendas(base)

    rows = (
        base.filter(
            Venda.data_inclusao >= inicio,
            Venda.data_inclusao <= fim
        )
        .with_entities(
            Venda.representante.label("nome"),  # troque por rede_loja se quiser
            func.coalesce(func.sum(Venda.quantidade), 0).label("qtd")
        )
        .group_by(Venda.representante)
        .order_by(func.sum(Venda.quantidade).desc())
        .limit(10)
        .all()
    )

    return jsonify({
        "periodo": {
            "de": inicio,
            "ate": fim
        },
        "dados": [
            {
                "nome": r.nome,
                "valor": int(r.qtd)
            }
            for r in rows if r.nome
        ]
    })

@bp.route("/bi/api/vendas/queda")
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "ver")
def bi_api_vendas_queda():

    inicio, fim = get_periodo_efetivo()

    base = Venda.query_empresa()
    base = aplicar_filtros_vendas(base)

    rows = (
        base.filter(
            Venda.data_inclusao >= inicio,
            Venda.data_inclusao <= fim
        )
        .with_entities(
            Venda.representante.label("nome"),  # ou rede_loja
            func.coalesce(func.sum(Venda.quantidade), 0).label("qtd")
        )
        .group_by(Venda.representante)
        .having(func.sum(Venda.quantidade) > 0)
        .order_by(func.sum(Venda.quantidade).asc())
        .limit(10)
        .all()
    )

    return jsonify({
        "periodo": {
            "de": inicio,
            "ate": fim
        },
        "dados": [
            {
                "nome": r.nome,
                "valor": int(r.qtd)
            }
            for r in rows if r.nome
        ]
    })

from sqlalchemy import func

@bp.route("/bi/api/vendas/top_uf")
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "ver")
def bi_api_vendas_top_uf():

    inicio, fim = get_periodo_efetivo()

    base = Venda.query_empresa()
    base = aplicar_filtros_vendas(base)

    rows = (
        base.filter(
            Venda.data_inclusao >= inicio,
            Venda.data_inclusao <= fim
        )
        .with_entities(
            Venda.estado.label("uf"),
            func.coalesce(func.sum(Venda.quantidade), 0).label("qtd")
        )
        .group_by(Venda.estado)
        .order_by(func.sum(Venda.quantidade).desc())
        .limit(10)
        .all()
    )

    return jsonify({
        "periodo": {
            "de": inicio,
            "ate": fim
        },
        "dados": [
            {
                "uf": r.uf,
                "valor": int(r.qtd)
            }
            for r in rows if r.uf
        ]
    })



##### IMPORTAÇÃO   #####

@bp.route("/comercial/vendas/importar", methods=["GET", "POST"])
@login_required
@requer_licenca_ativa
@requer_permissao('comercial', 'criar')
def importar_vendas():
    form = ImportarVendasForm()
    if request.method == "GET" or not form.validate_on_submit():
        return render_template("bi/vendas_importar.html", form=form)

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

    colunas_esperadas = ['representante', 'estado', 'cliente',
                          'pedido', 'data_inclusao','quantidade','valor']
    
    for c in colunas_esperadas:
        if c not in df.columns:
            flash("Arquivo inválido ou layout diferente do relatório padrão.", "danger")
            return redirect(url_for("routes.importar_vendas"))


    obrig = {'representante','cliente','pedido','estado',
             'data_inclusao','quantidade','valor'}
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

                    if (ch_vazias and q_next is not None and representante and cliente and pedido):
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
            empresa_id=current_user.empresa_id,  # 👈 MULTIEMPRESA
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
            rede_loja=current_rede_loja
        )
        registros.append(registro)
        i += 1

    if not registros:
        flash("Nenhum registro válido após análise.", "warning")
        return redirect(url_for("routes.importar_vendas"))

    # ---------- insert ----------
    try:
        objs = []
        for r in registros:
            objs.append(Venda(**r))

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
    return redirect(url_for("routes.home"))



###### EMAIL    ##########
from datetime import date, datetime

from flask import current_app, jsonify, request
from sqlalchemy import func

from flask_mail import Message
from app import db, mail
from app.utils import requer_permissao
from app.models import Venda, AlertaInatividadeCliente
from flask_login import current_user

@bp.route("/comercial/rfm_nf_alerta_email", methods=["GET"])
@requer_permissao("comercial", "ver")
def rfm_nf_alerta_email():
    """
    Envia e-mail ao diretor da EMPRESA ATUAL apenas com os NOVOS clientes
    que estão há mais de X dias sem emissão de NOTA FISCAL.

    Fonte correta: NotaFiscal.data_emissao
    """

    # =====================================================
    # EMPRESA ATUAL
    # =====================================================
    empresa_atual = current_user.empresa

    if not empresa_atual:
        return jsonify({
            "status": "erro",
            "mensagem": "Empresa não identificada."
        }), 403

    # =====================================================
    # PARÂMETRO ?dias=
    # =====================================================
    try:
        limite_dias = int(request.args.get("dias", 120))
    except Exception:
        limite_dias = 120

    hoje = date.today()

    # =====================================================
    # ÚLTIMA NOTA FISCAL POR CLIENTE (EMPRESA ATUAL)
    # =====================================================
    rows = (
        NotaFiscal.query_empresa()
        .with_entities(
            NotaFiscal.cliente.label("cliente"),
            func.max(NotaFiscal.data_emissao).label("ultima_data"),
            func.min(NotaFiscal.representante).label("representante")
        )
        .group_by(NotaFiscal.cliente)
        .all()
    )

    clientes_atrasados = []

    for r in rows:
        if not r.ultima_data:
            continue

        dias_sem_comprar = (hoje - r.ultima_data).days

        if dias_sem_comprar > limite_dias:
            clientes_atrasados.append({
                "cliente": r.cliente,
                "ultima_data": r.ultima_data,
                "dias": dias_sem_comprar,
                "representante": r.representante,
            })

    if not clientes_atrasados:
        return jsonify({
            "status": "ok",
            "mensagem": f"Nenhum cliente com mais de {limite_dias} dias sem comprar.",
            "qtd_clientes": 0
        })

    # =====================================================
    # VERIFICA ALERTAS JÁ REGISTRADOS (EMPRESA ATUAL)
    # =====================================================
    clientes_lista = list({c["cliente"] for c in clientes_atrasados})

    alertas_existentes = (
        db.session.query(
            AlertaInatividadeCliente.cliente,
            AlertaInatividadeCliente.ultima_data_venda
        )
        .filter(
            AlertaInatividadeCliente.empresa_id == empresa_atual.id,
            AlertaInatividadeCliente.cliente.in_(clientes_lista)
        )
        .all()
    )

    alertas_set = {(a.cliente, a.ultima_data_venda) for a in alertas_existentes}

    novos_clientes_atrasados = [
        c for c in clientes_atrasados
        if (c["cliente"], c["ultima_data"]) not in alertas_set
    ]

    if not novos_clientes_atrasados:
        return jsonify({
            "status": "ok",
            "mensagem": "Nenhum NOVO cliente entrou na faixa de inatividade desde o último alerta.",
            "qtd_clientes": 0
        })

    # =====================================================
    # CORPO DO E-MAIL
    # =====================================================
    linhas = [
        f"Empresa: {empresa_atual.nome}",
        "",
        f"Clientes com mais de {limite_dias} dias sem emissão de Nota Fiscal:",
        ""
    ]

    for item in novos_clientes_atrasados:
        linhas.append(
            f"- {item['cliente']} (Rep: {item['representante']}) "
            f"há {item['dias']} dias sem comprar "
            f"(última NF em {item['ultima_data'].strftime('%d/%m/%Y')})"
        )

    corpo = "\n".join(linhas)

    destinatario = empresa_atual.email

    if not destinatario:
        return jsonify({
            "status": "erro",
            "mensagem": "Empresa não possui e-mail configurado."
        }), 400

    assunto = (
        f"[ALERTA COMERCIAL] "
        f"{empresa_atual.nome} – Clientes > {limite_dias} dias sem NF"
    )

    # =====================================================
    # ENVIO + REGISTRO
    # =====================================================
    try:
        msg = Message(
            subject=assunto,
            recipients=[destinatario],
            body=corpo,
        )
        mail.send(msg)

        for c in novos_clientes_atrasados:
            alerta = AlertaInatividadeCliente(
                empresa_id=empresa_atual.id,
                cliente=c["cliente"],
                ultima_data_venda=c["ultima_data"],
                data_alerta=datetime.utcnow()
            )
            db.session.add(alerta)

        db.session.commit()

        return jsonify({
            "status": "ok",
            "mensagem": f"E-mail enviado para {destinatario}.",
            "qtd_clientes": len(novos_clientes_atrasados)
        })

    except Exception as e:
        db.session.rollback()
        current_app.logger.exception("[RFM NF ALERTA EMAIL] Erro")

        return jsonify({
            "status": "erro",
            "mensagem": f"Erro ao enviar e-mail ou registrar alertas: {str(e)}"
        }), 500


#### NOTAS FISCAIS   ####

from flask import (
    render_template, request, redirect,
    url_for, flash, current_app
)
from flask_login import login_required, current_user

from app import db
from app.models import NotaFiscal
from app.utils import allowed_file
from app.utils_uploads import salvar_upload

from decimal import Decimal
from datetime import datetime
from math import isnan
import os
import pandas as pd

from flask import (
    render_template, request, redirect,
    url_for, flash, current_app
)
from flask_login import login_required, current_user

from app import db
from app.models import NotaFiscal
from app.utils import allowed_file
from app.utils_uploads import salvar_upload
from sqlalchemy import text


@bp.route("/importar/nfs", methods=["GET", "POST"])
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "editar")
def importar_notas_fiscais():

    if request.method == "POST":

        # -------------------------
        # valida upload
        # -------------------------
        if "arquivo" not in request.files:
            flash("Nenhum arquivo enviado.", "danger")
            return redirect(request.url)

        arquivo = request.files["arquivo"]

        if arquivo.filename == "":
            flash("Selecione um arquivo.", "warning")
            return redirect(request.url)

        if not allowed_file(arquivo.filename):
            flash("Formato de arquivo inválido.", "danger")
            return redirect(request.url)

        # -------------------------
        # salva arquivo (multiempresa)
        # -------------------------
        caminho_relativo = salvar_upload(
            arquivo,
            subpasta="notas_fiscais"
        )

        if not caminho_relativo:
            flash("Erro ao salvar arquivo.", "danger")
            return redirect(request.url)

        caminho_absoluto = os.path.join(
            current_app.config["UPLOAD_ROOT"],
            caminho_relativo.replace("uploads/", "")
        )

        # -------------------------
        # leitura excel
        # -------------------------
        df = pd.read_excel(
            caminho_absoluto,
            header=None,
            dtype=str
        )

        # -------------------------
        # helpers locais
        # -------------------------
        def clean_pedido(valor):
            if not valor:
                return None

            return (
                str(valor)
                .replace('\r\n', ' ')
                .replace('\n', ' ')
                .replace('\r', ' ')
                .strip()
            )

        def nf_numero_valido(numero: str) -> bool:
            return (
                numero is not None
                and numero.isdigit()
                and numero.startswith("00")
                and len(numero) >= 3
            )

        def clean_str(valor):
            if valor is None:
                return None
            valor = str(valor).strip()
            if not valor or valor.lower() == "nan":
                return None
            return valor

        def parse_date(valor):
            if not valor:
                return None
            valor = str(valor).strip()
            for fmt in ("%d/%m/%Y", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(valor, fmt).date()
                except ValueError:
                    pass
            return None

        def parse_decimal_br(valor):
            if valor is None:
                return None
            try:
                if isinstance(valor, float) and isnan(valor):
                    return None
                valor = str(valor).strip()
                if not valor or valor.lower() == "nan":
                    return None
                if "," in valor:
                    return Decimal(valor.replace(".", "").replace(",", "."))
                return Decimal(valor)
            except Exception:
                return None

        # -------------------------
        # contadores
        # -------------------------
        importadas = 0
        ignoradas = 0
        erros = 0

        # -------------------------
        # loop principal
        # -------------------------
        rede_loja_atual = None

        for idx, row in df.iterrows():
            try:
                primeira_coluna = clean_str(row[0])

                # -------------------------
                # detecta REDE DE LOJA
                # -------------------------
                if primeira_coluna and primeira_coluna.lower().startswith("rede de loja"):
                    rede_loja_atual = primeira_coluna.replace("Rede de Loja:", "").strip()
                    continue

                # -------------------------
                # leitura normal da NF
                # -------------------------
                numero = clean_str(row[0])
                data_emissao = parse_date(row[1])
                serie = clean_str(row[2])
                cfop = clean_str(row[3])
                cliente = clean_str(row[5])
                representante = clean_str(row[6])
                quantidade_raw = clean_str(row[7])
                valor_faturado = parse_decimal_br(row[9])
                codigo_transportadora = clean_str(row[10])
                pedido = clean_pedido(row[12])

                # valida NF
                if not (
                    nf_numero_valido(numero)
                    and valor_faturado is not None
                    and data_emissao
                    and cfop and "." in cfop
                    and cliente
                ):
                    ignoradas += 1
                    continue

                quantidade = int(quantidade_raw.replace(".", "")) if quantidade_raw else 0

                with db.session.no_autoflush:
                    existe = NotaFiscal.query.filter_by(
                        empresa_id=current_user.empresa_id,
                        numero=numero,
                        serie=serie
                    ).first()

                if existe:
                    ignoradas += 1
                    continue

                nf = NotaFiscal(
                    empresa_id=current_user.empresa_id,
                    numero=numero,
                    serie=serie,
                    cfop=cfop,
                    data_emissao=data_emissao,
                    cliente=cliente,
                    representante=representante,
                    quantidade=quantidade,
                    valor_faturado=valor_faturado,
                    codigo_transportadora=codigo_transportadora,
                    pedido=pedido,
                    rede_loja=rede_loja_atual or "Sem Rede de Loja"
                )

                db.session.add(nf)
                importadas += 1

            except Exception as e:
                erros += 1
                db.session.rollback()
                print(f"Erro linha {idx}: {e}")
         ## ver pedido grande #       
        if pedido and len(pedido) > 250:
            print("PEDIDO MUITO GRANDE:", len(pedido))

        db.session.commit()

        flash(
            f"Importação concluída — "
            f"{importadas} importadas, "
            f"{ignoradas} ignoradas, "
            f"{erros} erros.",
            "success"
        )

        return redirect(
            url_for("routes.importar_notas_fiscais")
        )

    return render_template("notas_fiscais/nf_importar.html")


@bp.route("/notas-fiscais")
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "ver")
def listar_notas_fiscais():

    page = request.args.get("page", 1, type=int)

    # filtros
    nf = request.args.get("nf", "").strip()
    data_inicio = request.args.get("data_inicio")
    data_fim = request.args.get("data_fim")
    representante = request.args.get("representante", "").strip()
    rede_loja = request.args.get("rede_loja", "").strip()
    cliente = request.args.get("cliente", "").strip()

    query = NotaFiscal.query.filter_by(
        empresa_id=current_user.empresa_id
    )

    if nf:
        query = query.filter(NotaFiscal.numero.ilike(f"%{nf}%"))

    if representante:
        query = query.filter(
            NotaFiscal.representante.ilike(f"%{representante}%")
        )

    if rede_loja:
        query = query.filter(
            NotaFiscal.rede_loja.ilike(f"%{rede_loja}%")
        )


    if cliente:
        query = query.filter(
            NotaFiscal.cliente.ilike(f"%{cliente}%")
        )

    if data_inicio:
        query = query.filter(
            NotaFiscal.data_emissao >= data_inicio
        )

    if data_fim:
        query = query.filter(
            NotaFiscal.data_emissao <= data_fim
        )

    notas = query.order_by(
        NotaFiscal.data_emissao.desc(),
        NotaFiscal.numero.desc()
    ).paginate(
        page=page,
        per_page=25,
        error_out=False
    )

    return render_template(
        "notas_fiscais/nf_listar.html",
        notas=notas
    )


@bp.route("/notas-fiscais/zerar", methods=["POST"])
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "excluir")
def zerar_notas_fiscais():

    # opcional: validar admin
    if not current_user.is_admin_empresa:
        flash("Acesso negado.", "danger")
        return redirect(url_for("routes.listar_notas_fiscais"))

    db.session.execute(
        text("""
            DELETE FROM nota_fiscal
            WHERE empresa_id = :empresa_id
        """),
        {"empresa_id": current_user.empresa_id}
    )
    db.session.commit()

    flash("Notas fiscais apagadas com sucesso.", "success")
    return redirect(url_for("routes.listar_notas_fiscais"))


@bp.route("/bi/notas_fiscais")
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "ver")
def bi_notas_fiscais_dashboard():
    return render_template("bi/dashboard_notas_fiscais.html")


from datetime import date, timedelta
from sqlalchemy import func
from flask import request, jsonify
from datetime import date, timedelta
from sqlalchemy import func
from flask import request, jsonify

@bp.route("/bi/api/notas_fiscais")
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "ver")
def bi_api_notas_fiscais():

    hoje = date.today()
    data_padrao_de = hoje - timedelta(days=90)

    data_de = request.args.get("data_de")
    data_ate = request.args.get("data_ate")

    data_de_efetiva = date.fromisoformat(data_de) if data_de else data_padrao_de
    data_ate_efetiva = date.fromisoformat(data_ate) if data_ate else hoje

    # =====================================================
    # TAMANHO DO PERÍODO
    # =====================================================
    dias_periodo = (data_ate_efetiva - data_de_efetiva).days + 1

    # =====================================================
    # PERÍODO ANTERIOR
    # =====================================================
    data_ate_anterior = data_de_efetiva - timedelta(days=1)
    data_de_anterior = data_ate_anterior - timedelta(days=dias_periodo - 1)

    # =====================================================
    # QUERY BASE – PERÍODO ATUAL
    # =====================================================
    base = (
        NotaFiscal.query_empresa()
        .filter(
            NotaFiscal.data_emissao >= data_de_efetiva,
            NotaFiscal.data_emissao <= data_ate_efetiva
        )
    )

    if request.args.get("representante"):
        base = base.filter(
            NotaFiscal.representante == request.args.get("representante")
        )

    if request.args.get("rede_loja"):
        base = base.filter(
            NotaFiscal.rede_loja == request.args.get("rede_loja")
        )

    total_nf, total_qtd_atual, total_valor = (
        base.with_entities(
            func.count(NotaFiscal.id),
            func.coalesce(func.sum(NotaFiscal.quantidade), 0),
            func.coalesce(func.sum(NotaFiscal.valor_faturado), 0)
        )
        .first()
    )

    clientes = (
        base.with_entities(func.count(func.distinct(NotaFiscal.cliente)))
        .scalar()
        or 0
    )

    ticket_medio_nf = total_valor / total_nf if total_nf else 0
    preco_medio_par = total_valor / total_qtd_atual if total_qtd_atual else 0

    # =====================================================
    # QUERY – PERÍODO ANTERIOR (MESMOS FILTROS)
    # =====================================================
    base_anterior = (
        NotaFiscal.query_empresa()
        .filter(
            NotaFiscal.data_emissao >= data_de_anterior,
            NotaFiscal.data_emissao <= data_ate_anterior
        )
    )

    if request.args.get("representante"):
        base_anterior = base_anterior.filter(
            NotaFiscal.representante == request.args.get("representante")
        )

    if request.args.get("rede_loja"):
        base_anterior = base_anterior.filter(
            NotaFiscal.rede_loja == request.args.get("rede_loja")
        )

    total_qtd_anterior = (
        base_anterior
        .with_entities(func.coalesce(func.sum(NotaFiscal.quantidade), 0))
        .scalar()
    )

    total_valor_anterior = (
        base_anterior
        .with_entities(func.coalesce(func.sum(NotaFiscal.valor_faturado), 0))
        .scalar()
    )


    # =====================================================
    # VARIAÇÃO (%)
    # =====================================================
    if total_qtd_anterior > 0:
        quantidade_variacao = (
            (total_qtd_atual - total_qtd_anterior)
            / total_qtd_anterior
        ) * 100
    else:
        quantidade_variacao = None
    
    if total_valor_anterior > 0:
        valor_variacao = (
            (total_valor - total_valor_anterior)
            / total_valor_anterior
        ) * 100
    else:
        valor_variacao = None


    # =====================================================
    # FILTROS SELECT2
    # =====================================================
    base_filtros = NotaFiscal.query_empresa()

    representantes = (
        base_filtros
        .with_entities(NotaFiscal.representante)
        .filter(NotaFiscal.representante.isnot(None))
        .distinct()
        .order_by(NotaFiscal.representante)
        .all()
    )

    redes = (
        base_filtros
        .with_entities(NotaFiscal.rede_loja)
        .filter(NotaFiscal.rede_loja.isnot(None))
        .distinct()
        .order_by(NotaFiscal.rede_loja)
        .all()
    )

    # =====================================================
    # RESPONSE
    # =====================================================
    return jsonify({
        "kpis": {
            "quantidade_nf": formatar_numero(total_nf),
            "quantidade": formatar_numero(total_qtd_atual),
            "quantidade_variacao": (
                round(quantidade_variacao, 2)
                if quantidade_variacao is not None
                else None
            ),
            "valor_faturado": formatar_moeda(total_valor),
            "valor_variacao": (
                round(valor_variacao, 2)
                if valor_variacao is not None
                else None
            ),
            "clientes": clientes,
            "ticket_medio_nf": formatar_numero(ticket_medio_nf),
            "preco_medio_par": formatar_numero(preco_medio_par),
        },
        "filtros": {
            "data_de": data_de_efetiva.strftime("%Y-%m-%d"),
            "data_ate": data_ate_efetiva.strftime("%Y-%m-%d"),
            "representantes": [
                str(r[0]).strip()
                for r in representantes
                if r[0] and str(r[0]).strip()
            ],
            "redes": [r[0] for r in redes if r[0]],
            "representante": request.args.get("representante") or "",
            "rede_loja": request.args.get("rede_loja") or "",
        }
    })


from datetime import date, timedelta
from flask import request

def base_nf_filtradas_bi():
    hoje = date.today()

    data_de = request.args.get("data_de")
    data_ate = request.args.get("data_ate")

    data_de = date.fromisoformat(data_de) if data_de else hoje - timedelta(days=90)
    data_ate = date.fromisoformat(data_ate) if data_ate else hoje

    base = (
        NotaFiscal.query_empresa()
        .filter(
            NotaFiscal.data_emissao >= data_de,
            NotaFiscal.data_emissao <= data_ate
        )
    )

    if request.args.get("representante"):
        base = base.filter(
            NotaFiscal.representante == request.args.get("representante")
        )

    if request.args.get("rede_loja"):
        base = base.filter(
            NotaFiscal.rede_loja == request.args.get("rede_loja")
        )

    return base, data_de, data_ate

@bp.route("/bi/api/notas-fiscais/rfm/cards")
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "ver")
def bi_nf_rfm_cards():

    hoje = date.today()
    base, _, _ = base_nf_filtradas_bi()

    rows = (
        base.with_entities(
            NotaFiscal.cliente,
            func.max(NotaFiscal.data_emissao).label("ultima_compra")
        )
        .group_by(NotaFiscal.cliente)
        .all()
    )

    rfm = {
        "ate_30": 0,
        "ate_90": 0,
        "mais_90": 0
    }

    for _, ultima in rows:
        dias = (hoje - ultima).days if ultima else 9999

        if dias <= 30:
            rfm["ate_30"] += 1
        elif dias <= 90:
            rfm["ate_90"] += 1
        else:
            rfm["mais_90"] += 1

    return jsonify(rfm)

@bp.route("/bi/api/notas-fiscais/rfm/clientes")
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "ver")
def bi_nf_rfm_clientes():

    hoje = date.today()
    status = request.args.get("status")  # "30" | "90" | "90p"

    base, data_de, data_ate = base_nf_filtradas_bi()

    rows = (
        base.with_entities(
            NotaFiscal.cliente.label("cliente"),
            func.max(NotaFiscal.data_emissao).label("ultima_compra"),
            func.count(NotaFiscal.id).label("pedidos"),
            func.coalesce(func.sum(NotaFiscal.quantidade), 0).label("total_pares")
        )
        .group_by(NotaFiscal.cliente)
        .order_by(func.max(NotaFiscal.data_emissao).desc())
        .all()
    )

    clientes = []

    for cli, ultima, pedidos, total in rows:
        dias = (hoje - ultima).days if ultima else 9999

        if dias <= 30:
            status_cli = "Ativo"
        elif dias <= 90:
            status_cli = "Risco"
        else:
            status_cli = "Inativo"

        # 🎯 filtro por faixa
        if status == "30" and dias > 30:
            continue
        if status == "90" and not (31 <= dias <= 90):
            continue
        if status == "90p" and dias <= 90:
            continue

        clientes.append({
            "cliente": cli,
            "status": status_cli,
            "ultima_compra": formatar_data(ultima),
            "dias": dias,
            "pedidos": pedidos,
            "total_pares": int(total)
        })

    return jsonify({
        "clientes": clientes,
        "filtros": {
            "data_de": formatar_data(data_de),
            "data_ate": formatar_data(data_ate),
            "representante": request.args.get("representante") or "Todos",
            "rede_loja": request.args.get("rede_loja") or "Todas"
        }
    })

from datetime import date, timedelta
from sqlalchemy import func, case

@bp.route("/bi/api/notas-fiscais/top-crescimento")
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "ver")
def bi_nf_top_crescimento():

    data_de = date.fromisoformat(request.args.get("data_de"))
    data_ate = date.fromisoformat(request.args.get("data_ate"))

    dias = (data_ate - data_de).days + 1
    data_ate_ant = data_de - timedelta(days=1)
    data_de_ant = data_ate_ant - timedelta(days=dias - 1)

    grupo = request.args.get("grupo", "representante")
    metrica = request.args.get("metrica", "pares")

    campo_grupo = (
        NotaFiscal.representante
        if grupo == "representante"
        else NotaFiscal.rede_loja
    )

    campo_valor = (
        NotaFiscal.quantidade
        if metrica == "pares"
        else NotaFiscal.valor_faturado
    )

    # ===============================
    # PERÍODO ATUAL
    # ===============================
    atual = (
        NotaFiscal.query_empresa()
        .filter(NotaFiscal.data_emissao.between(data_de, data_ate))
        .with_entities(
            campo_grupo.label("nome"),
            func.sum(campo_valor).label("atual")
        )
        .group_by(campo_grupo)
        .subquery()
    )

    # ===============================
    # PERÍODO ANTERIOR
    # ===============================
    anterior = (
        NotaFiscal.query_empresa()
        .filter(NotaFiscal.data_emissao.between(data_de_ant, data_ate_ant))
        .with_entities(
            campo_grupo.label("nome"),
            func.sum(campo_valor).label("anterior")
        )
        .group_by(campo_grupo)
        .subquery()
    )

    # ===============================
    # VARIAÇÃO (REGRA DE BI)
    # ===============================
    variacao = case(
        # não existia antes → crescimento total
        (func.coalesce(anterior.c.anterior, 0) == 0, 1.0),
        else_=(
            (atual.c.atual - anterior.c.anterior)
            / anterior.c.anterior
        )
    ).label("variacao")

    # ===============================
    # QUERY FINAL
    # ===============================
    query = (
        db.session.query(
            atual.c.nome,
            atual.c.atual,
            func.coalesce(anterior.c.anterior, 0).label("anterior"),
            variacao
        )
        .outerjoin(anterior, atual.c.nome == anterior.c.nome)
        .filter(atual.c.nome.isnot(None))
        .filter(atual.c.atual > 0)  # 🔥 essencial
        .order_by(db.desc(variacao))
        .limit(20)
        .all()
    )

    # ===============================
    # SERIALIZAÇÃO
    # ===============================
    dados = [
        {
            "nome": r.nome,
            "atual": float(r.atual),
            "anterior": float(r.anterior),
            "percentual": round(r.variacao * 100, 2)
        }
        for r in query
        if r.variacao > 0
    ][:10]

    return jsonify({"dados": dados})


from datetime import date, timedelta
from sqlalchemy import func, case

@bp.route("/bi/api/notas-fiscais/top-queda")
@login_required
@requer_licenca_ativa
@requer_permissao("comercial", "ver")
def bi_nf_top_queda():

    data_de = date.fromisoformat(request.args.get("data_de"))
    data_ate = date.fromisoformat(request.args.get("data_ate"))

    dias = (data_ate - data_de).days + 1
    data_ate_ant = data_de - timedelta(days=1)
    data_de_ant = data_ate_ant - timedelta(days=dias - 1)

    grupo = request.args.get("grupo", "representante")
    metrica = request.args.get("metrica", "pares")

    campo_grupo = (
        NotaFiscal.representante
        if grupo == "representante"
        else NotaFiscal.rede_loja
    )

    campo_valor = (
        NotaFiscal.quantidade
        if metrica == "pares"
        else NotaFiscal.valor_faturado
    )

    # ===============================
    # PERÍODO ATUAL
    # ===============================
    atual = (
        NotaFiscal.query_empresa()
        .filter(NotaFiscal.data_emissao.between(data_de, data_ate))
        .with_entities(
            campo_grupo.label("nome"),
            func.sum(campo_valor).label("atual")
        )
        .group_by(campo_grupo)
        .subquery()
    )

    # ===============================
    # PERÍODO ANTERIOR
    # ===============================
    anterior = (
        NotaFiscal.query_empresa()
        .filter(NotaFiscal.data_emissao.between(data_de_ant, data_ate_ant))
        .with_entities(
            campo_grupo.label("nome"),
            func.sum(campo_valor).label("anterior")
        )
        .group_by(campo_grupo)
        .subquery()
    )

    # ===============================
    # VARIAÇÃO (QUEDA REAL)
    # ===============================
    variacao = case(
        # se não existia antes, não existe "queda"
        (func.coalesce(anterior.c.anterior, 0) == 0, None),
        else_=(
            (atual.c.atual - anterior.c.anterior)
            / anterior.c.anterior
        )
    ).label("variacao")

    # ===============================
    # QUERY FINAL
    # ===============================
    query = (
        db.session.query(
            atual.c.nome,
            atual.c.atual,
            func.coalesce(anterior.c.anterior, 0).label("anterior"),
            variacao
        )
        .outerjoin(anterior, atual.c.nome == anterior.c.nome)
        .filter(atual.c.nome.isnot(None))
        .filter(variacao.isnot(None))
        .filter(variacao < 0)
        .order_by(variacao)
        .limit(20)
        .all()
    )

    # ===============================
    # SERIALIZAÇÃO
    # ===============================
    dados = [
        {
            "nome": r.nome,
            "atual": float(r.atual),
            "anterior": float(r.anterior),
            "percentual": round(r.variacao * 100, 2)
        }
        for r in query
    ][:10]

    return jsonify({"dados": dados})
