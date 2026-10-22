"""Interfaz de línea de comandos."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from pydantic import ValidationError

from sensormon import __version__
from sensormon.config import Settings, StorageConfig, load_settings
from sensormon.runtime import run_collector, run_dashboard, run_embedded, run_simulator
from sensormon.simulator.runner import parse_fault_token
from sensormon.storage.sqlite import SqliteStore
from sensormon.util import setup_logging

app = typer.Typer(
    help="Monitorización de sensores IoT sobre MQTT.",
    no_args_is_help=True,
)


def _version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def cli(
    log_level: str = typer.Option("INFO", "--log-level", help="DEBUG, INFO, WARNING o ERROR"),
    version: bool = typer.Option(
        False,
        "--version",
        help="Muestra la versión y sale",
        callback=_version,
        is_eager=True,
    ),
) -> None:
    """Monitorización de sensores IoT sobre MQTT."""

    del version
    try:
        setup_logging(log_level)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc


def _load(
    config: Path | None,
    *,
    db: Path | None = None,
    host: str | None = None,
    port: int | None = None,
    faults: list[str] | None = None,
) -> Settings:
    try:
        settings = load_settings(config)
    except (FileNotFoundError, ValueError, ValidationError) as exc:
        typer.secho(f"Configuración inválida: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc

    updates: dict[str, object] = {}
    if db is not None:
        updates["storage"] = StorageConfig(path=str(db))
    if host is not None or port is not None:
        api_updates: dict[str, object] = {}
        if host is not None:
            api_updates["host"] = host
        if port is not None:
            api_updates["port"] = port
        updates["api"] = settings.api.model_copy(update=api_updates)
    try:
        if faults:
            parsed = [parse_fault_token(item) for item in faults]
            updates["simulator"] = settings.simulator.model_copy(
                update={"faults": [*settings.simulator.faults, *parsed]}
            )
        if updates:
            settings = settings.model_copy(update=updates)
    except (ValueError, ValidationError) as exc:
        typer.secho(f"Configuración inválida: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc
    return settings


def _apply_mqtt(settings: Settings, mqtt_host: str | None, mqtt_port: int | None) -> Settings:
    if mqtt_host is None and mqtt_port is None:
        return settings
    updates: dict[str, object] = {}
    if mqtt_host is not None:
        updates["host"] = mqtt_host
    if mqtt_port is not None:
        updates["port"] = mqtt_port
    try:
        mqtt = settings.mqtt.model_copy(update=updates)
        return settings.model_copy(update={"mqtt": mqtt})
    except ValidationError as exc:
        typer.secho(f"Broker inválido: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from exc


def _transport(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in {"mqtt", "memory"}:
        typer.secho("El transporte debe ser mqtt o memory", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    return value


@app.command()
def simulate(
    config: Path | None = typer.Option(None, "--config", "-c", help="Fichero YAML"),
    transport: str | None = typer.Option(
        None, "--transport", "-t", help="mqtt o memory. memory no necesita broker"
    ),
    duration: float | None = typer.Option(None, "--duration", help="Segundos antes de salir"),
    fault: list[str] = typer.Option(
        [],
        "--fault",
        help="Avería dispositivo:metrica:tipo:magnitud[:inicio[:duracion]]",
    ),
    mqtt_host: str | None = typer.Option(None, "--mqtt-host", help="Host del broker"),
    mqtt_port: int | None = typer.Option(None, "--mqtt-port", help="Puerto del broker"),
) -> None:
    """Publica telemetría de sensores virtuales."""

    settings = _apply_mqtt(
        _load(config, faults=fault),
        mqtt_host,
        mqtt_port,
    )
    chosen = _transport(transport) or ("mqtt" if settings.mqtt.enabled else "memory")
    run_simulator(settings, transport=chosen, duration=duration)


@app.command()
def collect(
    config: Path | None = typer.Option(None, "--config", "-c", help="Fichero YAML"),
    transport: str | None = typer.Option(None, "--transport", "-t", help="mqtt o memory"),
    duration: float | None = typer.Option(None, "--duration", help="Segundos antes de salir"),
    db: Path | None = typer.Option(None, "--db", help="Ruta SQLite"),
    mqtt_host: str | None = typer.Option(None, "--mqtt-host"),
    mqtt_port: int | None = typer.Option(None, "--mqtt-port"),
) -> None:
    """Valida lecturas, las guarda y emite alertas."""

    settings = _apply_mqtt(_load(config, db=db), mqtt_host, mqtt_port)
    chosen = _transport(transport) or ("mqtt" if settings.mqtt.enabled else "memory")
    run_collector(settings, transport=chosen, duration=duration)


def _serve(
    config: Path | None,
    host: str | None,
    port: int | None,
    embedded: bool,
    duration: float | None,
    db: Path | None,
    faults: list[str] | None = None,
) -> None:
    if faults and not embedded:
        typer.secho("--fault solo aplica junto con --embedded", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    settings = _load(config, db=db, host=host, port=port, faults=faults or [])
    if embedded:
        run_embedded(
            settings,
            host=settings.api.host,
            port=settings.api.port,
            duration=duration,
            log_level="info",
        )
        return
    run_dashboard(
        settings,
        host=settings.api.host,
        port=settings.api.port,
        duration=duration,
        log_level="info",
    )


@app.command()
def serve(
    config: Path | None = typer.Option(None, "--config", "-c", help="Fichero YAML"),
    host: str | None = typer.Option(None, "--host", help="Interfaz de escucha"),
    port: int | None = typer.Option(None, "--port", help="Puerto HTTP"),
    embedded: bool = typer.Option(
        False,
        "--embedded",
        help="Simulador, colector y panel en un proceso, sin broker",
    ),
    duration: float | None = typer.Option(
        None, "--duration", help="Detiene el proceso tras N segundos"
    ),
    db: Path | None = typer.Option(None, "--db", help="Ruta SQLite"),
    fault: list[str] = typer.Option(
        [],
        "--fault",
        help="En modo embebido: dispositivo:metrica:tipo:magnitud[:inicio[:duracion]]",
    ),
) -> None:
    """Sirve el API y el panel web."""

    _serve(config, host, port, embedded, duration, db, fault)


@app.command("dashboard")
def dashboard(
    config: Path | None = typer.Option(None, "--config", "-c", help="Fichero YAML"),
    host: str | None = typer.Option(None, "--host", help="Interfaz de escucha"),
    port: int | None = typer.Option(None, "--port", help="Puerto HTTP"),
    embedded: bool = typer.Option(
        False,
        "--embedded",
        help="Simulador, colector y panel en un proceso, sin broker",
    ),
    duration: float | None = typer.Option(None, "--duration"),
    db: Path | None = typer.Option(None, "--db", help="Ruta SQLite"),
    fault: list[str] = typer.Option(
        [],
        "--fault",
        help="En modo embebido: dispositivo:metrica:tipo:magnitud[:inicio[:duracion]]",
    ),
) -> None:
    """Alias de serve."""

    _serve(config, host, port, embedded, duration, db, fault)


def _open_cli_store(config: Path | None, db: Path | None) -> SqliteStore:
    settings = _load(config, db=db)
    return SqliteStore(settings.storage.path)


@app.command()
def devices(
    config: Path | None = typer.Option(None, "--config", "-c", help="Fichero YAML"),
    db: Path | None = typer.Option(None, "--db", help="Ruta SQLite"),
    as_json: bool = typer.Option(False, "--json", help="Salida JSON"),
) -> None:
    """Lista los dispositivos vistos por el colector."""

    store = _open_cli_store(config, db)
    try:
        store.init()
        rows = store.list_devices()
    finally:
        store.close()
    if as_json:
        payload = [
            {
                "device_id": row.device_id,
                "location": row.location,
                "last_seen": row.last_seen.isoformat() if row.last_seen else None,
                "sensors": row.sensors,
                "reading_count": row.reading_count,
            }
            for row in rows
        ]
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if not rows:
        typer.echo("No hay dispositivos registrados.")
        return
    typer.echo(f"{'Dispositivo':<16} {'Ubicación':<32} {'Sensores':<28} Lecturas")
    for row in rows:
        location = row.location or "-"
        sensors = ",".join(row.sensors) or "-"
        typer.echo(f"{row.device_id:<16} {location:<32} {sensors:<28} {row.reading_count}")


@app.command()
def alerts(
    config: Path | None = typer.Option(None, "--config", "-c", help="Fichero YAML"),
    db: Path | None = typer.Option(None, "--db", help="Ruta SQLite"),
    device: str | None = typer.Option(None, "--device", help="Filtra por dispositivo"),
    severity: str | None = typer.Option(None, "--severity", help="info, warning o critical"),
    limit: int = typer.Option(20, "--limit", min=1, max=500),
    as_json: bool = typer.Option(False, "--json", help="Salida JSON"),
) -> None:
    """Lista alertas almacenadas."""

    if severity is not None and severity not in {"info", "warning", "critical"}:
        typer.secho("La severidad debe ser info, warning o critical", fg=typer.colors.RED, err=True)
        raise typer.Exit(2)
    store = _open_cli_store(config, db)
    try:
        store.init()
        rows = store.list_alerts(device_id=device, severity=severity, limit=limit)
    finally:
        store.close()
    if as_json:
        typer.echo(
            json.dumps(
                [row.model_dump(mode="json") for row in rows],
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if not rows:
        typer.echo("No hay alertas.")
        return
    for row in rows:
        stamp = row.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        typer.echo(
            f"{stamp}  {row.severity:<8}  {row.device_id:<14} {row.metric.value:<12} "
            f"{row.detector:<18} {row.value:8.2f}  {row.message}"
        )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
