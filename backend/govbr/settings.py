from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Scope = Literal["govbr:read", "govbr:admin"]
READ: Scope = "govbr:read"
ADMIN: Scope = "govbr:admin"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GOVBR_", env_file=(".env", "../.env"), extra="ignore")

    environment: Literal["local", "production"] = "local"
    database_url: SecretStr = SecretStr("postgresql+psycopg://govbr:govbr@127.0.0.1:5432/govbr")
    public_url: str = "http://localhost:8080"
    cgu_key: SecretStr | None = None
    proxy_url: SecretStr | None = None
    ca_bundle: Path | None = None
    time_limit_seconds: Annotated[float, Field(ge=5, le=90)] = 25
    query_concurrency: Annotated[int, Field(ge=1, le=12)] = 5
    requests_per_minute: Annotated[int, Field(ge=5, le=300)] = 45
    history_days: Annotated[int, Field(ge=1, le=365)] = 30
    evidence_days: Annotated[int, Field(ge=1, le=1095)] = 180
    document_max_mib: Annotated[int, Field(ge=1, le=20)] = 10
    # IdP de confiança. O ID token nunca é aceito como access token via uma audiência de cliente.
    oauth_issuer: str | None = None
    oauth_jwks_url: str | None = None
    oauth_audience: str | None = None
    oauth_allowed_subjects: str | None = None
    oauth_algorithms: Literal["RS256", "ES256", "EdDSA"] = "RS256"

    @model_validator(mode="after")
    def secure_configuration(self) -> "Settings":
        self.public_url = self.public_url.rstrip("/")
        url = urlsplit(self.public_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.query
            or url.fragment
            or url.path
        ):
            raise ValueError("GOVBR_PUBLIC_URL precisa ser uma origem HTTP(S), sem caminho")
        if self.environment == "production" and url.scheme != "https":
            raise ValueError("GOVBR_PUBLIC_URL precisa usar HTTPS em produção")
        if url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("HTTP só é permitido no loopback")
        if self.evidence_days < self.history_days:
            raise ValueError("A retenção de evidências deve ser igual ou superior à do histórico")
        if self.oauth_issuer or self.oauth_jwks_url or self.oauth_audience:
            for name, address in (("issuer", self.oauth_issuer), ("jwks_url", self.oauth_jwks_url)):
                parts = urlsplit(address or "")
                if (
                    parts.scheme != "https"
                    or not parts.hostname
                    or parts.username is not None
                    or parts.fragment
                    or parts.query
                ):
                    raise ValueError(f"OAuth {name} precisa ser uma URL HTTPS sem credenciais")
            if self.oauth_audience != f"{self.public_url}/mcp":
                raise ValueError("A audiência OAuth precisa ser a URL pública exata do endpoint /mcp")
            if self.environment == "production" and not self.oauth_allowed_subjects:
                raise ValueError("Defina GOVBR_OAUTH_ALLOWED_SUBJECTS para habilitar OAuth em produção")
        if self.oauth_allowed_subjects:
            self.oauth_allowed_subjects = ",".join(
                v.strip() for v in self.oauth_allowed_subjects.split(",") if v.strip()
            )
            if not self.oauth_allowed_subjects:
                raise ValueError("A lista de usuários OAuth está vazia")
        return self

    @property
    def resource(self) -> str:
        return f"{self.public_url}/mcp"
