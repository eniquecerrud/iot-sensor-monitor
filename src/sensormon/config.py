"""Configuración YAML con prioridad de variables de entorno."""

from __future__ import annotations

import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from sensormon.models import DEVICE_ID_RE, Metric

_CONFIG_PATH: ContextVar[Path | None] = ContextVar("sensormon_config_path", default=None)

FaultKind = Literal["spike", "stuck", "bias", "dropout"]


class MqttConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    client_id: str = "sensormon"
    keepalive: int = 60
    topic_root: str = "sensors"

    @field_validator("port")
    @classmethod
    def _port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("el puerto MQTT debe estar entre 1 y 65535")
        return value

    @field_validator("topic_root")
    @classmethod
    def _root(cls, value: str) -> str:
        if not value or "/" in value or any(ch in value for ch in "+#"):
            raise ValueError("topic_root debe ser un solo nivel sin comodines")
        return value


class StorageConfig(BaseModel):
    path: str = "data/sensormon.db"


class SensorConfig(BaseModel):
    baseline: float
    noise: float = 0.1
    drift: float = 0.0
    reversion: float = 0.08
    unit: str = Field(min_length=1, max_length=32)
    diurnal_amplitude: float = 0.0
    cycle_period_seconds: float = 300.0
    min_value: float | None = None
    max_value: float | None = None

    @field_validator("noise", "diurnal_amplitude")
    @classmethod
    def _non_negative(cls, value: float) -> float:
        if value < 0:
            raise ValueError("el valor no puede ser negativo")
        return value

    @field_validator("reversion")
    @classmethod
    def _reversion(cls, value: float) -> float:
        if value < 0:
            raise ValueError("reversion no puede ser negativa")
        return value

    @field_validator("cycle_period_seconds")
    @classmethod
    def _period(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("cycle_period_seconds debe ser positivo")
        return value


class DeviceConfig(BaseModel):
    id: str
    location: str | None = None
    sensors: dict[str, SensorConfig]

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not DEVICE_ID_RE.fullmatch(value):
            raise ValueError(f"id de dispositivo inválido: {value}")
        return value

    @field_validator("sensors")
    @classmethod
    def _sensors(cls, value: dict[str, SensorConfig]) -> dict[str, SensorConfig]:
        if not value:
            raise ValueError("el dispositivo necesita al menos un sensor")
        for key in value:
            Metric(key)
        return value


class FaultConfig(BaseModel):
    device_id: str
    metric: str | None = None
    kind: FaultKind
    magnitude: float = 0.0
    start_after: float = 0.0
    duration: float = 10.0

    @field_validator("device_id")
    @classmethod
    def _device_id(cls, value: str) -> str:
        if not DEVICE_ID_RE.fullmatch(value):
            raise ValueError(f"device_id inválido: {value}")
        return value

    @field_validator("metric")
    @classmethod
    def _metric(cls, value: str | None) -> str | None:
        if value is None or value == "*":
            return None
        Metric(value)
        return value

    @field_validator("start_after", "duration")
    @classmethod
    def _times(cls, value: float) -> float:
        if value < 0:
            raise ValueError("los tiempos de la avería no pueden ser negativos")
        return value

    @model_validator(mode="after")
    def _duration_positive(self) -> FaultConfig:
        if self.duration <= 0:
            raise ValueError("duration debe ser mayor que cero")
        return self


class SimulatorConfig(BaseModel):
    interval_seconds: float = 1.0
    seed: int | None = 7
    devices: list[DeviceConfig] = Field(default_factory=list)
    faults: list[FaultConfig] = Field(default_factory=list)

    @field_validator("interval_seconds")
    @classmethod
    def _interval(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("interval_seconds debe ser positivo")
        return value


class ThresholdRule(BaseModel):
    min: float | None = None
    max: float | None = None
    critical_min: float | None = None
    critical_max: float | None = None

    @model_validator(mode="after")
    def _order(self) -> ThresholdRule:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min no puede ser mayor que max")
        if (
            self.critical_min is not None
            and self.critical_max is not None
            and self.critical_min > self.critical_max
        ):
            raise ValueError("critical_min no puede ser mayor que critical_max")
        return self


class ZScoreConfig(BaseModel):
    enabled: bool = True
    window: int = 30
    threshold: float = 3.5
    min_samples: int = 12

    @model_validator(mode="after")
    def _check(self) -> ZScoreConfig:
        if self.window < 2:
            raise ValueError("zscore.window debe ser >= 2")
        if self.min_samples < 2 or self.min_samples > self.window:
            raise ValueError("zscore.min_samples debe estar entre 2 y window")
        if self.threshold <= 0:
            raise ValueError("zscore.threshold debe ser positivo")
        return self


class EwmaConfig(BaseModel):
    enabled: bool = True
    alpha: float = 0.25
    threshold: float = 3.5
    min_samples: int = 8

    @model_validator(mode="after")
    def _check(self) -> EwmaConfig:
        if not 0 < self.alpha <= 1:
            raise ValueError("ewma.alpha debe estar en (0, 1]")
        if self.min_samples < 2:
            raise ValueError("ewma.min_samples debe ser >= 2")
        if self.threshold <= 0:
            raise ValueError("ewma.threshold debe ser positivo")
        return self


class IsolationForestConfig(BaseModel):
    enabled: bool = False
    window: int = 40
    contamination: float = 0.05
    min_samples: int = 30
    refit_every: int = 10
    random_state: int = 0
    n_estimators: int = 80

    @model_validator(mode="after")
    def _check(self) -> IsolationForestConfig:
        if self.window < 10:
            raise ValueError("isolation_forest.window debe ser >= 10")
        if self.min_samples < 10 or self.min_samples > self.window:
            raise ValueError("isolation_forest.min_samples debe estar entre 10 y window")
        if not 0 < self.contamination <= 0.5:
            raise ValueError("contamination debe estar en (0, 0.5]")
        if self.refit_every < 1:
            raise ValueError("refit_every debe ser >= 1")
        if self.n_estimators < 10:
            raise ValueError("n_estimators debe ser >= 10")
        return self


class DetectionConfig(BaseModel):
    cooldown_seconds: float = 15.0
    thresholds: dict[str, ThresholdRule] = Field(default_factory=dict)
    zscore: ZScoreConfig = Field(default_factory=ZScoreConfig)
    ewma: EwmaConfig = Field(default_factory=EwmaConfig)
    isolation_forest: IsolationForestConfig = Field(default_factory=IsolationForestConfig)

    @field_validator("cooldown_seconds")
    @classmethod
    def _cooldown(cls, value: float) -> float:
        if value < 0:
            raise ValueError("cooldown_seconds no puede ser negativo")
        return value

    @field_validator("thresholds")
    @classmethod
    def _metrics(cls, value: dict[str, ThresholdRule]) -> dict[str, ThresholdRule]:
        for key in value:
            Metric(key)
        return value


class NotifierConfig(BaseModel):
    type: Literal["console", "webhook"]
    enabled: bool = True
    url: str | None = None
    timeout_seconds: float = 3.0

    @field_validator("timeout_seconds")
    @classmethod
    def _timeout(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("timeout_seconds debe ser positivo")
        return value


class ApiConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000

    @field_validator("port")
    @classmethod
    def _port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("el puerto del API debe estar entre 1 y 65535")
        return value


class Settings(BaseSettings):
    """Configuración efectiva.

    Orden de prioridad (de mayor a menor): argumentos del constructor,
    variables `SENSOR_*` y el fichero YAML.
    """

    model_config = SettingsConfigDict(
        env_prefix="SENSOR_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    mqtt: MqttConfig = Field(default_factory=MqttConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    simulator: SimulatorConfig = Field(default_factory=SimulatorConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    notifiers: list[NotifierConfig] = Field(
        default_factory=lambda: [NotifierConfig(type="console")]
    )
    api: ApiConfig = Field(default_factory=ApiConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


class YamlConfigSettingsSource(PydanticBaseSettingsSource):
    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return None, "", False

    def __call__(self) -> dict[str, Any]:
        return read_yaml_config()


def resolve_config_path(explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return explicit
    env = os.environ.get("SENSOR_CONFIG")
    if env:
        return Path(env)
    default = Path("config/default.yaml")
    if default.is_file():
        return default
    return None


def read_yaml_config() -> dict[str, Any]:
    path = resolve_config_path(_CONFIG_PATH.get())
    if path is None:
        return {}
    if not path.is_file():
        raise FileNotFoundError(f"No existe el fichero de configuración: {path}")
    with path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"La configuración debe ser un mapa YAML: {path}")
    return loaded


def load_settings(config: Path | None = None, **overrides: Any) -> Settings:
    token = _CONFIG_PATH.set(config)
    try:
        return Settings(**overrides)
    finally:
        _CONFIG_PATH.reset(token)
