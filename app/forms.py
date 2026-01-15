
from decimal import Decimal
from typing import Optional
from flask_wtf import FlaskForm
from wtforms import BooleanField, DateField, DateTimeField, DecimalField, HiddenField, SelectMultipleField, StringField, SubmitField, FloatField, FileField, TextAreaField
from wtforms.validators import DataRequired
from wtforms import SelectField
from flask_wtf import FlaskForm
from wtforms import StringField, FloatField, IntegerField, FileField, FieldList, FormField, SubmitField
from wtforms.validators import DataRequired, NumberRange, Optional, Email
from datetime import date
from wtforms.validators import DataRequired, Length
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField
from wtforms.validators import DataRequired, InputRequired, Length, EqualTo
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import SubmitField
from flask_wtf import FlaskForm

##### STV #####

class LicencaSistemaForm(FlaskForm):
    dias_acesso = IntegerField("Dias_De_Acesso", validators=[DataRequired()])
    submit = SubmitField("Salvar")

class UsuarioForm(FlaskForm):
    nome = StringField('Nome', validators=[DataRequired(), Length(min=3, max=100)])
    senha = PasswordField('Senha', validators=[DataRequired(), Length(min=6, max=100)])
    email = StringField("E-mail",  validators=[DataRequired(), Email(), Length(max=120)])
    confirmar_senha = PasswordField('Confirmar Senha', validators=[DataRequired(), EqualTo('senha', message='As senhas devem coincidir.')])
    submit = SubmitField('Salvar')

from flask_wtf import FlaskForm
from wtforms import (
    StringField, IntegerField, DecimalField, DateField
)
from wtforms.validators import DataRequired, Optional

class VendaForm(FlaskForm):
    representante = StringField("Representante", validators=[DataRequired()])
    cliente = StringField("Cliente", validators=[DataRequired()])
    pedido = StringField("Pedido", validators=[DataRequired()])

    estado = StringField("Estado", validators=[DataRequired()])
    municipio = StringField("Município", validators=[Optional()])

    data_inclusao = DateField("Data", validators=[DataRequired()])
    quantidade = IntegerField("Quantidade", validators=[DataRequired()])
    valor = DecimalField("Valor", places=2, validators=[Optional()])

    produto = StringField("Produto", validators=[Optional()])
    grupo = StringField("Grupo", validators=[Optional()])
    regiao = StringField("Região", validators=[Optional()])
    rede_loja = StringField("Rede / Loja", validators=[Optional()])





class ImportarVendasForm(FlaskForm):
    arquivo = FileField(
        "Planilha de Vendas (.xlsx)",
        validators=[
            FileRequired(message="Selecione um arquivo Excel."),
            FileAllowed(['xlsx', 'xls'], "Somente arquivos Excel são permitidos.")
        ]
    )
    enviar = SubmitField("Importar")
