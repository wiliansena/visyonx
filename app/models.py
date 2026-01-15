from decimal import Decimal
from flask_login import UserMixin
from sqlalchemy.orm import relationship
from app import db
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from datetime import datetime
from sqlalchemy.orm import backref
from app.mixins import EmpresaQueryMixin
from app.utils_datetime import utc_now

from datetime import date, timedelta

 ####   USUÁRIO    ######
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


class Empresa(db.Model):
    __tablename__ = "empresa"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    cnpj = db.Column(db.String(18), unique=True, nullable=True)
    email = db.Column(db.String(255))

    ativa = db.Column(db.Boolean, default=True)
    criada_em = db.Column(db.DateTime, default=utc_now)


class Usuario(UserMixin, EmpresaQueryMixin,db.Model):
    __tablename__ = "usuario"

    id = db.Column(db.Integer, primary_key=True)

    empresa_id = db.Column(
        db.Integer,
        db.ForeignKey("empresa.id"),
        nullable=True   # 👈 MASTER NÃO TEM EMPRESA
    )

    empresa = db.relationship(
        "Empresa",
        backref="usuarios"
    )

    is_master = db.Column(db.Boolean, default=False)  # 👈 CHAVE DO PAINEL MASTER
    is_admin_empresa = db.Column(db.Boolean, default=False)

    nome = db.Column(db.String(100), nullable=False)
    senha_hash = db.Column(db.String(200), nullable=False)

    email = db.Column(db.String(120), unique=True, nullable=False)

    permissoes = db.relationship(
        "Permissao",
        backref="usuario",
        lazy="dynamic",
        cascade="all, delete-orphan"
    )

    def set_password(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def check_password(self, senha):
        return check_password_hash(self.senha_hash, senha)

    @property
    def todas_permissoes(self):
        return {(p.categoria, p.acao) for p in self.permissoes.all()}

    def tem_permissao(self, categoria, acao):
        return (categoria, acao) in self.todas_permissoes

    def pode_trocar_senha(self):
        return self.tem_permissao("trocar_senha", "editar")


class Permissao(EmpresaQueryMixin, db.Model ):
    __tablename__ = "permissao"

    id = db.Column(db.Integer, primary_key=True)

    empresa_id = db.Column(
        db.Integer,
        db.ForeignKey("empresa.id"),
        nullable=False
    )

    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuario.id"),
        nullable=False
    )

    categoria = db.Column(db.String(50), nullable=False)
    acao = db.Column(db.String(20), nullable=False)

    __table_args__ = (
        db.UniqueConstraint(
            "empresa_id",
            "usuario_id",
            "categoria",
            "acao",
            name="unique_permissao_usuario_empresa"
        ),
    )

class LogAcao(EmpresaQueryMixin, db.Model):
    __tablename__ = "log_acao"

    id = db.Column(db.Integer, primary_key=True)

    empresa_id = db.Column(
        db.Integer,
        db.ForeignKey("empresa.id"),
        nullable=False
    )

    usuario_id = db.Column(
        db.Integer,
        db.ForeignKey("usuario.id"),
        nullable=False
    )

    usuario_nome = db.Column(db.String(100), nullable=False)
    acao = db.Column(db.String(255), nullable=False)

    data_hora = db.Column(
        db.DateTime,
        default=utc_now)

    usuario = db.relationship("Usuario")


class LicencaSistema(EmpresaQueryMixin, db.Model):
    __tablename__ = "licenca_sistema"

    id = db.Column(db.Integer, primary_key=True)

    empresa_id = db.Column(
        db.Integer,
        db.ForeignKey("empresa.id"),
        nullable=False
    )
    empresa = db.relationship("Empresa")

    data_inicio = db.Column(db.Date, nullable=False, default=date.today)
    dias_acesso = db.Column(db.Integer, nullable=False, default=1)

    @property
    def data_fim(self):
        return self.data_inicio + timedelta(days=self.dias_acesso)

    @property
    def dias_restantes(self):
        hoje = utc_now().date()
        return max((self.data_fim - hoje).days, 0)

    @property
    def expirado(self):
        return self.dias_restantes <= 0



#### VENDAS #####
class Venda(EmpresaQueryMixin, db.Model):
    __tablename__ = "venda"

    id = db.Column(db.Integer, primary_key=True)

    #MULTIEMPRESA
    empresa_id = db.Column(
        db.Integer,
        db.ForeignKey("empresa.id"),
        nullable=False,
        index=True
    )

    empresa = db.relationship("Empresa")

    # identificação comercial
    representante = db.Column(db.String(150), nullable=False, index=True)
    cliente = db.Column(db.String(150), nullable=False, index=True)
    pedido = db.Column(db.String(50), nullable=False, index=True)

    # localização
    estado = db.Column(db.String(2), nullable=False, index=True)
    municipio = db.Column(db.String(100), nullable=True)

    # informações do pedido
    data_inclusao = db.Column(db.Date, nullable=False, index=True)
    quantidade = db.Column(db.Integer, nullable=False, default=0)
    valor = db.Column(db.Numeric(14, 2), nullable=True, default=0)  # 🔹 adiciona o valor vendido

    # opcional (pode vir de alguns relatórios)
    produto = db.Column(db.String(150), nullable=True)  # descrição/ref se existir
    grupo = db.Column(db.String(100), nullable=True)    # grupo ou categoria do produto
    regiao = db.Column(db.String(100), nullable=True)   # útil p/ agrupar estados ex: nordeste, sudeste...
    
    rede_loja = db.Column(db.String(200), nullable=True)  # NOVO

    def __repr__(self):
        return f"<Venda {self.pedido} - {self.estado} R$ {self.valor}>"


##### NOTA FISCAL   #######
class NotaFiscal(EmpresaQueryMixin, db.Model):
    __tablename__ = "nota_fiscal"

    id = db.Column(db.Integer, primary_key=True)

    # MULTIEMPRESA
    empresa_id = db.Column(
        db.Integer,
        db.ForeignKey("empresa.id"),
        nullable=False,
        index=True
    )
    empresa = db.relationship("Empresa")

    # Identificação da NF
    numero = db.Column(db.String(20), nullable=False, index=True)
    serie = db.Column(db.String(10), nullable=True, index=True)
    cfop = db.Column(db.String(10), nullable=True, index=True)

    # Datas
    data_emissao = db.Column(db.Date, nullable=False, index=True)

    # Comercial
    cliente = db.Column(db.String(200), nullable=False, index=True)
    representante = db.Column(db.String(150), nullable=True, index=True)
    pedido = db.Column(db.Text, nullable=True, index=True)

    # Quantitativos
    quantidade = db.Column(db.Integer, nullable=True)
    valor_faturado = db.Column(db.Numeric(14, 2), nullable=False)

    # 🚚 COD DE TRANSPORTE
    codigo_transportadora = db.Column(db.String(20), nullable=True)
    # REDE DE LOJA AGRUPAR
    rede_loja = db.Column(db.String(150), index=True)


    # Controle
    created_at = db.Column(
        db.DateTime,
        server_default=db.func.now()
    )

    __table_args__ = (
        db.UniqueConstraint(
            "empresa_id", "numero", "serie",
            name="uq_nf_empresa_numero_serie"
        ),
    )

    def __repr__(self):
        return (
            f"<NF {self.numero}/{self.serie} "
            f"{self.cliente} "
            f"Fat: {self.valor_faturado} "
            f"Transp: {self.valor_transporte}>"
        )


class Colaborador(db.Model):
    __tablename__ = "colaborador"

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(50), unique=True, index=True, nullable=False)
    nome = db.Column(db.String(255), nullable=False)
    nome_fantasia = db.Column(db.String(255))
    ativo = db.Column(db.Boolean, default=True)



#### FINANCEIRO   ###
class FinanceiroTitulo(EmpresaQueryMixin, db.Model):
    __tablename__ = "financeiro_titulo"

    id             = db.Column(db.Integer, primary_key=True)

    #MULTIEMPRESA
    empresa_id = db.Column(
        db.Integer,
        db.ForeignKey("empresa.id"),
        nullable=False,
        index=True
    )

    empresa = db.relationship("Empresa")

    empresa_nome   = db.Column(db.String(120))
    cliente        = db.Column(db.String(180))
    representante  = db.Column(db.String(120))
    especie        = db.Column(db.String(80))
    numero_doc     = db.Column(db.String(120), nullable=False)  # chave natural
    emissao        = db.Column(db.Date)
    vencimento     = db.Column(db.Date)
    liquidacao     = db.Column(db.Date)                         # quando quitou
    valor          = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    saldo          = db.Column(db.Numeric(14, 2), nullable=False, default=0)
    conta_bancaria = db.Column(db.String(120))
    banco          = db.Column(db.String(120))

    __table_args__ = (
        db.Index("ix_fin_tit_vencimento", "vencimento"),
        db.Index("ix_fin_tit_cliente", "cliente"),
        db.Index("ix_fin_tit_representante", "representante"),
        db.UniqueConstraint(
            "empresa_nome", "numero_doc", "emissao", "vencimento", "valor",
            name="uq_fin_titulo_emp_doc_emis_venc_valor"
        ),

    )

    @property
    def situacao(self) -> str:
        try:
            return "ABERTO" if (self.saldo or 0) > 0 else "LIQUIDADO"
        except Exception:
            return "ABERTO"
    

class AlertaInatividadeCliente(EmpresaQueryMixin, db.Model):
    __tablename__ = "alerta_inatividade_cliente"

    id = db.Column(db.Integer, primary_key=True)
    #MULTIEMPRESA
    empresa_id = db.Column(
        db.Integer,
        db.ForeignKey("empresa.id"),
        nullable=False,
        index=True
    )

    empresa = db.relationship("Empresa")
    cliente = db.Column(db.String(150), nullable=False, index=True)
    ultima_data_venda = db.Column(db.Date, nullable=False)
    data_alerta = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)