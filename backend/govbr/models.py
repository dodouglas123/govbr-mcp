from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints, model_validator

UFS = dict(
    zip(
        "RO AC AM RR PA AP TO MA PI CE RN PB PE AL SE BA MG ES RJ SP PR SC RS MS MT GO DF".split(),
        "11 12 13 14 15 16 17 21 22 23 24 25 26 27 28 29 31 32 33 35 41 42 43 50 51 52 53".split(),
        strict=True,
    )
)
UF_NOMES = dict(
    zip(
        UFS,
        (
            "Rondônia",
            "Acre",
            "Amazonas",
            "Roraima",
            "Pará",
            "Amapá",
            "Tocantins",
            "Maranhão",
            "Piauí",
            "Ceará",
            "Rio Grande do Norte",
            "Paraíba",
            "Pernambuco",
            "Alagoas",
            "Sergipe",
            "Bahia",
            "Minas Gerais",
            "Espírito Santo",
            "Rio de Janeiro",
            "São Paulo",
            "Paraná",
            "Santa Catarina",
            "Rio Grande do Sul",
            "Mato Grosso do Sul",
            "Mato Grosso",
            "Goiás",
            "Distrito Federal",
        ),
        strict=True,
    )
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def cnpj(value: str) -> str:
    if not isinstance(value, str) or not value.isascii():
        raise ValueError("CNPJ inválido")
    value = value.strip().upper()
    if re.fullmatch(r"[A-Z0-9]{2}\.[A-Z0-9]{3}\.[A-Z0-9]{3}/[A-Z0-9]{4}-[0-9]{2}", value):
        value = re.sub(r"[./-]", "", value)
    if not re.fullmatch(r"[A-Z0-9]{12}[0-9]{2}", value) or len(set(value)) == 1:
        raise ValueError("CNPJ precisa ter 14 posições e dígitos verificadores válidos")
    root = value[:12]
    for weights in ((5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2), (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)):
        remainder = sum((ord(char) - 48) * weight for char, weight in zip(root, weights, strict=True)) % 11
        root += str(11 - remainder if remainder >= 2 else 0)
    if root != value:
        raise ValueError("Dígitos verificadores do CNPJ inválidos")
    return value


def uf(value: str) -> str:
    if not isinstance(value, str) or value.upper() not in UFS:
        raise ValueError("UF brasileira inválida")
    return value.upper()


CNPJ = Annotated[str, BeforeValidator(cnpj)]
UF = Annotated[str, BeforeValidator(uf)]
IBGE = Annotated[int, Field(ge=1100000, le=5399999)]
Ano = Annotated[int, Field(ge=1990, le=2100)]
Pagina = Annotated[int, Field(ge=1, le=1000)]
Limite = Annotated[int, Field(ge=1, le=50)]
Codigo = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9_./-]*$")
]
Texto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=200)]
Money = Annotated[Decimal, Field(max_digits=20, decimal_places=4, allow_inf_nan=False)]


class Operation(StrEnum):
    CONTRATOS = "contratos"
    CONTRATO = "contrato"
    ADITIVOS = "aditivos"
    LICITACOES = "licitacoes"
    ATAS = "atas"
    FORNECEDOR = "fornecedor"
    SANCOES = "sancoes"
    DESPESAS = "despesas"
    EMPENHOS = "empenhos"
    LIQUIDACOES = "liquidacoes"
    PAGAMENTOS = "pagamentos"
    TRANSFERENCIAS = "transferencias"
    CONVENIOS = "convenios"
    EMENDAS = "emendas"
    FISCAIS = "fiscais"
    RECEITAS = "receitas"
    ORGAO = "orgao"
    MUNICIPIO = "municipio"
    DOCUMENTOS = "documentos"
    PRECO_MATERIAL = "preco_material"


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fonte: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{1,49}$")] | None = None
    esfera: Annotated[str, StringConstraints(pattern=r"^[FEMD]$")] | None = None
    uf: UF | None = None
    codigo_ibge: IBGE | None = None
    cnpj: CNPJ | None = None
    cnpj_orgao: CNPJ | None = None
    codigo_orgao: Codigo | None = None
    identificador: Codigo | None = None
    texto: Texto | None = None
    data_inicial: date | None = None
    data_final: date | None = None
    ano: Ano | None = None
    periodo: Annotated[int, Field(ge=1, le=12)] | None = None
    modalidade: Annotated[int, Field(ge=1, le=99)] | None = None
    codigo_material: Annotated[int, Field(ge=1, le=9999999)] | None = None
    demonstrativo: Annotated[str, StringConstraints(pattern=r"^(DCA|RREO|RGF)$")] | None = None
    anexo: Texto | None = None
    poder: Annotated[str, StringConstraints(pattern=r"^[ELJMD]$")] | None = None
    periodicidade: Annotated[str, StringConstraints(pattern=r"^[QS]$")] | None = None
    ente_fiscal: Annotated[int, Field(ge=1, le=5399999)] | None = None
    valor_minimo: Money | None = None
    valor_maximo: Money | None = None
    pagina: Pagina = 1
    limite: Limite = 15

    @model_validator(mode="after")
    def validate_filters(self) -> Filters:
        if bool(self.data_inicial) != bool(self.data_final):
            raise ValueError("Informe as duas datas do intervalo")
        if self.data_inicial and self.data_final and self.data_inicial > self.data_final:
            raise ValueError("Data inicial posterior à data final")
        if (
            self.valor_minimo is not None
            and self.valor_maximo is not None
            and self.valor_minimo > self.valor_maximo
        ):
            raise ValueError("Valor mínimo superior ao máximo")
        if self.codigo_ibge:
            prefix = str(self.codigo_ibge)[:2]
            if prefix not in UFS.values() or (self.uf and UFS[self.uf] != prefix):
                raise ValueError("Código IBGE incompatível com a UF")
        if self.codigo_ibge and self.ente_fiscal and self.codigo_ibge != self.ente_fiscal:
            raise ValueError("codigo_ibge e ente_fiscal precisam identificar o mesmo ente")
        return self

    def filtros(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True, exclude={"operacao", "fonte"})


class Query(Filters):
    operacao: Operation


class Record(BaseModel):
    fonte: str
    conjunto: str
    id_original: str
    tipo: str
    titulo: str
    esfera: str | None = None
    uf: str | None = None
    codigo_ibge: int | None = None
    cnpj: str | None = None
    cnpj_orgao: str | None = None
    orgao: str | None = None
    valor: Decimal | None = None
    moeda: str | None = None
    natureza_valor: str | None = None
    data_publicacao: date | None = None
    competencia: str | None = None
    atualizado_na_fonte: str | None = None
    url_oficial: str
    evidencia_id: UUID | None = None
    identificadores: dict[str, str] = Field(default_factory=dict)
    atributos: dict[str, Any] = Field(default_factory=dict)


class SourceResult(BaseModel):
    fonte: str
    estado: str
    registros_recebidos: int = 0
    registros_utilizados: int = 0
    pagina: int
    proxima_pagina: int | None = None
    total_na_fonte: int | None = None
    filtro_local: list[str] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)
    erro: str | None = None
    consultado_em: datetime | None = None
    url_consulta: str | None = None
    cache: bool = False


class Response(BaseModel):
    consulta_id: UUID
    estado: str
    operacao: str
    consultado_em: datetime
    registros: list[Record] = Field(default_factory=list)
    fontes: list[SourceResult] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)
    relacoes: list[dict[str, Any]] = Field(default_factory=list)
    divergencias: list[dict[str, Any]] = Field(default_factory=list)
    calculo: dict[str, Any] | None = None


class PublicError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)
