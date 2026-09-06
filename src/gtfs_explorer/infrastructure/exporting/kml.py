"""Exportación e inspección segura de KML/KMZ para el editor 0.2.0."""

from __future__ import annotations

import io
import math
import re
import stat
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Iterable, cast
from xml.etree import ElementTree as ET

from gtfs_explorer.domain.changesets import EditorCommand, EditorCommandKind, WorkingCopy
from gtfs_explorer.domain.exporting import ExportError, ExportManifest
from gtfs_explorer.infrastructure.exporting.atomic_output import (
    AtomicOutputWriter,
    CancellationCheck,
)

_KML_NS = "http://www.opengis.net/kml/2.2"
_DANGEROUS_XML = re.compile(
    rb"<!\s*(?:DOCTYPE|ENTITY)|\b(?:SYSTEM|PUBLIC|XINCLUDE|NETWORKLINK)\b", re.IGNORECASE
)


class KmlProfile(StrEnum):
    STANDARD_KML = "STANDARD_KML"
    GOOGLE_EARTH = "GOOGLE_EARTH"
    GOOGLE_MY_MAPS = "GOOGLE_MY_MAPS"


class KmlClassification(StrEnum):
    GTFS_EXPLORER_KML = "GTFS_EXPLORER_KML"
    MODIFIED_KML = "MODIFIED_KML"
    UNKNOWN_KML = "UNKNOWN_KML"


class KmlSecurityError(ExportError):
    """KML/KMZ rechazado por seguridad o por no cumplir el contrato."""


@dataclass(frozen=True)
class KmlSecurityLimits:
    max_members: int = 32
    max_compressed_bytes: int = 16 * 1024 * 1024
    max_uncompressed_bytes: int = 64 * 1024 * 1024
    max_expansion_ratio: float = 100.0
    max_xml_bytes: int = 32 * 1024 * 1024
    max_depth: int = 64
    max_attributes_per_element: int = 64
    max_text_bytes: int = 1024 * 1024
    max_points_per_geometry: int = 100_000
    max_features: int = 100_000

    def __post_init__(self) -> None:
        if (
            self.max_members < 1
            or self.max_compressed_bytes < 1
            or self.max_uncompressed_bytes < 1
            or self.max_expansion_ratio < 1
            or self.max_xml_bytes < 1
            or self.max_depth < 1
            or self.max_attributes_per_element < 1
            or self.max_text_bytes < 1
            or self.max_points_per_geometry < 1
            or self.max_features < 1
        ):
            raise ValueError("Los límites KML deben ser positivos y coherentes.")


@dataclass(frozen=True)
class KmlImportPreview:
    classification: KmlClassification
    placemark_count: int
    point_count: int
    line_string_count: int
    metadata_keys: tuple[str, ...]
    features: tuple["KmlFeature", ...] = ()


@dataclass(frozen=True)
class KmlFeature:
    """Geometría KML ya validada, sin HTML ejecutable ni recursos externos."""

    kind: str
    name: str | None
    coordinates: tuple[tuple[float, float], ...]
    metadata: tuple[tuple[str, str], ...]
    description: str | None = None

    @property
    def metadata_dict(self) -> dict[str, str]:
        return dict(self.metadata)


@dataclass(frozen=True)
class KmlImportMapping:
    """Mapeo explícito para KML modificado o desconocido."""

    route_id: str | None = None
    shape_id: str | None = None
    agency_id: str | None = None
    service_id: str | None = None


@dataclass(frozen=True)
class KmlImportProposal:
    """Resultado de clasificar y preparar geometría sin mutar el borrador."""

    preview: KmlImportPreview
    commands: tuple[EditorCommand, ...]
    unresolved: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class WorkingCopyKmlExporter:
    """Exporta geometría y metadatos GTFS de la working copy sin generar Schedule."""

    def __init__(self, *, writer: AtomicOutputWriter | None = None) -> None:
        self._writer = writer or AtomicOutputWriter()

    def write(
        self,
        destination: Path,
        working_copy: WorkingCopy,
        *,
        revision_id: str,
        confirmed: bool,
        route_ids: frozenset[str] | None = None,
        profile: KmlProfile = KmlProfile.STANDARD_KML,
        overwrite: bool = False,
        is_cancelled: CancellationCheck = lambda: False,
    ) -> ExportManifest:
        try:
            profile = KmlProfile(profile)
        except ValueError as error:
            raise ExportError("El perfil KML/KMZ no es válido.") from error
        if not confirmed or not revision_id or revision_id == "draft":
            raise ExportError(
                "No se puede exportar un borrador geoespacial sin confirmar la revisión."
            )
        if working_copy.dirty:
            raise ExportError(
                "No se puede exportar una working copy DIRTY; confirme primero la revisión."
            )
        if revision_id != working_copy.base_revision_id:
            raise ExportError("La exportación debe apuntar a la revisión activa.")
        payload = _working_copy_kml(working_copy, revision_id, route_ids, profile)
        if destination.suffix.casefold() == ".kmz":
            content = _kmz_bytes(payload)
            format_name = "kmz"
        else:
            content = payload
            format_name = "kml"
        return self._writer.write(
            destination,
            (content,),
            overwrite=overwrite,
            is_cancelled=is_cancelled,
            manifest_metadata={"format": format_name, "profile": profile.value},
        )


class SafeKmlReader:
    """Lee solo XML KML local y clasifica su compatibilidad antes de mapearlo."""

    def __init__(self, *, limits: KmlSecurityLimits | None = None) -> None:
        self._limits = limits or KmlSecurityLimits()

    def inspect(self, path: Path) -> KmlImportPreview:
        content = _read_kml_payload(path, self._limits)
        _reject_dangerous_xml(content)
        if len(content) > self._limits.max_xml_bytes:
            raise KmlSecurityError("El XML KML excede el límite de tamaño permitido.")
        try:
            root = ET.fromstring(content)
        except ET.ParseError as error:
            raise KmlSecurityError("El fichero KML no es XML válido y seguro.") from error
        if _local_name(root.tag) != "kml":
            raise KmlSecurityError("El documento no contiene una raíz KML válida.")
        placemarks = [element for element in root.iter() if _local_name(element.tag) == "Placemark"]
        if len(placemarks) > self._limits.max_features:
            raise KmlSecurityError("El KML excede el número máximo de entidades.")
        point_count = 0
        line_count = 0
        metadata: set[str] = set()
        for element, depth in _walk(root):
            if depth > self._limits.max_depth:
                raise KmlSecurityError("El KML excede la profundidad XML permitida.")
            if len(element.attrib) > self._limits.max_attributes_per_element:
                raise KmlSecurityError("Un nodo KML tiene demasiados atributos.")
            if element.text and len(element.text.encode("utf-8")) > self._limits.max_text_bytes:
                raise KmlSecurityError("Un nodo KML contiene demasiado texto.")
        features = _features_from_placemarks(placemarks, self._limits)
        for placemark in placemarks:
            for data in (
                element for element in placemark.iter() if _local_name(element.tag) == "Data"
            ):
                name = data.get("name")
                if name:
                    metadata.add(name)
            points = [
                element
                for element in placemark.iter()
                if _local_name(element.tag) == "Point"
                for child in element
                if _local_name(child.tag) == "coordinates"
            ]
            lines = [
                element
                for element in placemark.iter()
                if _local_name(element.tag) == "LineString"
                for child in element
                if _local_name(child.tag) == "coordinates"
            ]
            point_count += len(points)
            line_count += len(lines)
            for coordinates in (*points, *lines):
                values = _coordinates(coordinates.text or "", self._limits.max_points_per_geometry)
                if len(values) > self._limits.max_points_per_geometry:
                    raise KmlSecurityError("Una geometría KML tiene demasiados puntos.")
        classification = _classify(metadata)
        return KmlImportPreview(
            classification,
            len(placemarks),
            point_count,
            line_count,
            tuple(sorted(metadata)),
            features,
        )

    def read_features(self, path: Path) -> tuple[KmlFeature, ...]:
        """Devuelve solo geometrías locales y metadatos ya saneados."""
        return self.inspect(path).features


class KmlGeometryImporter:
    """Prepara cambios de geometría; nunca crea un GTFS completo por inferencia."""

    def __init__(self, reader: SafeKmlReader | None = None) -> None:
        self._reader = reader or SafeKmlReader()

    def propose(
        self,
        path: Path,
        working_copy: WorkingCopy,
        *,
        mapping: KmlImportMapping | None = None,
    ) -> KmlImportProposal:
        preview = self._reader.inspect(path)
        mapping = mapping or KmlImportMapping()
        version_values = {
            feature.metadata_dict.get("gtfs_explorer_version")
            for feature in preview.features
            if feature.metadata_dict.get("gtfs_explorer_version") is not None
        }
        if version_values and version_values != {"0.2.0"}:
            return KmlImportProposal(
                preview,
                (),
                unresolved=(
                    "La metadata KML procede de una versión no compatible; "
                    "revise el mapeo antes de aplicar.",
                ),
            )
        if preview.classification is not KmlClassification.GTFS_EXPLORER_KML and not (
            mapping.route_id or mapping.shape_id
        ):
            return KmlImportProposal(
                preview,
                (),
                unresolved=(
                    "KML sin metadata GTFS: indique explícitamente la ruta y el shape "
                    "antes de aplicar.",
                ),
            )
        commands: list[EditorCommand] = []
        unresolved: list[str] = []
        warnings: list[str] = []
        for feature in preview.features:
            metadata = feature.metadata_dict
            if feature.kind == "Point":
                stop_id = metadata.get("stop_id")
                if stop_id is None:
                    unresolved.append(
                        f"La geometría Point {feature.name or 'sin nombre'} no tiene stop_id."
                    )
                    continue
                key = _find_entity(working_copy, "gtfs_stops", "stop_id", stop_id)
                if key is None:
                    unresolved.append(f"La parada {stop_id} no existe en el borrador.")
                    continue
                before = working_copy.get(key)
                if before is None or not feature.coordinates:
                    continue
                route_ids = _import_route_context(working_copy, key, mapping.route_id)
                if len(route_ids) != 1 or not working_copy.can_edit_route(
                    next(iter(route_ids), "")
                ):
                    unresolved.append(
                        f"La parada {stop_id} no tiene una única ruta activa, editable y "
                        "desbloqueada."
                    )
                    continue
                longitude, latitude = feature.coordinates[0]
                after = dict(before)
                after["stop_lon"], after["stop_lat"] = longitude, latitude
                commands.append(EditorCommand(EditorCommandKind.MOVE_STOP, key, before, after))
            elif feature.kind == "LineString":
                shape_id = metadata.get("shape_id") or mapping.shape_id
                if shape_id is None:
                    unresolved.append(
                        f"La geometría LineString {feature.name or 'sin nombre'} no tiene shape_id."
                    )
                    continue
                shape_keys = tuple(
                    key
                    for key, payload in working_copy.entities.items()
                    if key[0] == "gtfs_shapes" and payload.get("shape_id") == shape_id
                )
                route_ids = set().union(
                    *(working_copy.route_ids_for_entity(key) for key in shape_keys)
                )
                if mapping.route_id is not None:
                    if mapping.route_id not in route_ids:
                        unresolved.append(
                            f"El shape {shape_id} no pertenece a la ruta indicada en el mapeo."
                        )
                        continue
                    route_ids = {mapping.route_id}
                if len(route_ids) != 1 or not working_copy.can_edit_route(
                    next(iter(route_ids), "")
                ):
                    unresolved.append(
                        f"El shape {shape_id} no tiene una única ruta activa, editable y "
                        "desbloqueada."
                    )
                    continue
                commands.extend(_shape_commands(working_copy, shape_id, feature.coordinates))
                if not shape_keys:
                    unresolved.append(f"El shape {shape_id} no existe en el borrador.")
                elif len(shape_keys) != len(feature.coordinates):
                    unresolved.append(
                        f"El shape {shape_id} tiene {len(shape_keys)} vértices y el KML "
                        f"aporta {len(feature.coordinates)}; no se redimensiona automáticamente."
                    )
        if preview.classification is not KmlClassification.GTFS_EXPLORER_KML:
            warnings.append(
                "La geometría KML se importa como propuesta; agencia, servicio, viajes "
                "y horarios no se inventan."
            )
        return KmlImportProposal(preview, tuple(commands), tuple(unresolved), tuple(warnings))

    def apply(self, session: object, proposal: KmlImportProposal) -> tuple[EditorCommand, ...]:
        """Aplica propuestas ya revisadas en un lote transaccional."""
        if proposal.unresolved:
            raise KmlSecurityError("La importación KML tiene entidades sin resolver.")
        apply = getattr(session, "apply", None)
        apply_batch = getattr(session, "apply_batch", None)
        preview_impact = getattr(session, "preview_impact", None)
        if callable(apply_batch):
            result = apply_batch(proposal.commands)
            return tuple(result)
        if not callable(apply) or not callable(preview_impact):
            raise TypeError("La sesión de importación no expone el caso de uso esperado.")
        applied: list[EditorCommand] = []
        for command in proposal.commands:
            impact = preview_impact(command)
            applied.append(apply(command, impact=impact))
        return tuple(applied)


def _features_from_placemarks(
    placemarks: list[ET.Element], limits: KmlSecurityLimits
) -> tuple[KmlFeature, ...]:
    features: list[KmlFeature] = []
    for placemark in placemarks:
        metadata: dict[str, str] = {}
        for data in (item for item in placemark.iter() if _local_name(item.tag) == "Data"):
            name = data.get("name")
            if not name:
                continue
            value = next(
                (child.text or "" for child in data if _local_name(child.tag) == "value"),
                "",
            )
            metadata[name] = value
        name = next(
            (element.text for element in placemark if _local_name(element.tag) == "name"),
            None,
        )
        description = next(
            (
                "".join(element.itertext())
                for element in placemark
                if _local_name(element.tag) == "description"
            ),
            None,
        )
        geometry = next(
            (
                element
                for element in placemark.iter()
                if _local_name(element.tag) in {"Point", "LineString"}
            ),
            None,
        )
        if geometry is None:
            continue
        coordinates_node = next(
            (child for child in geometry if _local_name(child.tag) == "coordinates"),
            None,
        )
        if coordinates_node is None:
            continue
        coordinates = _coordinates(coordinates_node.text or "", limits.max_points_per_geometry)
        features.append(
            KmlFeature(
                _local_name(geometry.tag),
                None if name is None else name.strip() or None,
                coordinates,
                tuple(sorted(metadata.items())),
                None if description is None else description.strip() or None,
            )
        )
    return tuple(features)


def _find_entity(
    working_copy: WorkingCopy, table: str, field: str, value: str
) -> tuple[str, str] | None:
    return next(
        (
            key
            for key, payload in working_copy.entities.items()
            if key[0] == table and str(payload.get(field)) == value
        ),
        None,
    )


def _import_route_context(
    working_copy: WorkingCopy,
    entity_key: tuple[str, str],
    mapped_route_id: str | None,
) -> set[str]:
    route_ids = set(working_copy.route_ids_for_entity(entity_key))
    if mapped_route_id is not None:
        if route_ids and mapped_route_id not in route_ids:
            return set()
        route_ids = {mapped_route_id}
    return route_ids


def _shape_commands(
    working_copy: WorkingCopy,
    shape_id: str,
    coordinates: tuple[tuple[float, float], ...],
) -> tuple[EditorCommand, ...]:
    points = [
        (key, payload)
        for key, payload in working_copy.entities.items()
        if key[0] == "gtfs_shapes" and payload.get("shape_id") == shape_id
    ]
    points.sort(key=lambda item: _number(item[1].get("shape_pt_sequence")))
    result: list[EditorCommand] = []
    for (key, before), (longitude, latitude) in zip(points, coordinates, strict=False):
        after = dict(before)
        after["shape_pt_lon"], after["shape_pt_lat"] = longitude, latitude
        result.append(EditorCommand(EditorCommandKind.MOVE_SHAPE_POINT, key, before, after))
    return tuple(result)


def _working_copy_kml(
    working_copy: WorkingCopy,
    revision_id: str,
    route_ids: frozenset[str] | None,
    profile: KmlProfile,
) -> bytes:
    entities = working_copy.entities
    selected_routes = route_ids or frozenset(
        str(payload["route_id"])
        for key, payload in entities.items()
        if key[0] == "gtfs_routes" and payload.get("route_id") is not None
    )
    selected_trips = {
        str(payload["trip_id"]): payload
        for key, payload in entities.items()
        if key[0] == "gtfs_trips"
        and payload.get("route_id") in selected_routes
        and payload.get("trip_id") is not None
    }
    route_by_trip = {
        trip_id: str(payload["route_id"])
        for trip_id, payload in selected_trips.items()
        if payload.get("route_id") is not None
    }
    routes = {
        str(payload["route_id"]): payload
        for key, payload in entities.items()
        if key[0] == "gtfs_routes" and payload.get("route_id") is not None
    }
    shape_ids = {
        payload.get("shape_id") for payload in selected_trips.values() if payload.get("shape_id")
    }
    stop_ids: set[object] = {
        payload.get("stop_id")
        for key, payload in entities.items()
        if key[0] == "gtfs_stop_times" and payload.get("trip_id") in selected_trips
    }
    stop_metadata: dict[str, dict[str, object]] = {
        str(stop_time.get("stop_id")): stop_time
        for key, stop_time in entities.items()
        if key[0] == "gtfs_stop_times"
        and stop_time.get("stop_id") is not None
        and str(stop_time.get("trip_id")) in route_by_trip
    }
    stop_route_ids = {
        str(stop_id): route_by_trip.get(str(stop_metadata.get(str(stop_id), {}).get("trip_id")))
        for stop_id in stop_ids
    }
    root = ET.Element(f"{{{_KML_NS}}}kml")
    document = ET.SubElement(root, f"{{{_KML_NS}}}Document")
    ET.SubElement(document, f"{{{_KML_NS}}}name").text = "GTFS Explorer 0.2.0"
    style_id = "gtfsRouteLine-" + profile.value.casefold()
    style = ET.SubElement(document, f"{{{_KML_NS}}}Style", id=style_id)
    line_style = ET.SubElement(style, f"{{{_KML_NS}}}LineStyle")
    ET.SubElement(line_style, f"{{{_KML_NS}}}color").text = (
        "ff0055ff" if profile is not KmlProfile.GOOGLE_MY_MAPS else "ff3366cc"
    )
    ET.SubElement(line_style, f"{{{_KML_NS}}}width").text = (
        "4" if profile is not KmlProfile.GOOGLE_MY_MAPS else "3"
    )
    for shape_id in sorted(str(value) for value in shape_ids if value is not None):
        coordinates = _shape_coordinates(entities, shape_id)
        if not coordinates:
            continue
        placemark = _placemark(document, "Shape " + shape_id)
        shape_routes = sorted(
            route_by_trip[trip_id]
            for trip_id, trip in selected_trips.items()
            if trip.get("shape_id") == shape_id and trip_id in route_by_trip
        )
        _data(
            placemark,
            {
                "shape_id": shape_id,
                "route_id": shape_routes[0] if shape_routes else None,
                "route_ids": ",".join(shape_routes),
                "route_short_name": (
                    routes.get(shape_routes[0], {}).get("route_short_name")
                    if shape_routes
                    else None
                ),
                "route_long_name": (
                    routes.get(shape_routes[0], {}).get("route_long_name") if shape_routes else None
                ),
                "agency_id": (
                    routes.get(shape_routes[0], {}).get("agency_id") if shape_routes else None
                ),
                "revision_id": revision_id,
                "gtfs_explorer_version": "0.2.0",
                "kml_profile": profile.value,
            },
        )
        ET.SubElement(placemark, f"{{{_KML_NS}}}styleUrl").text = f"#{style_id}"
        line = ET.SubElement(placemark, f"{{{_KML_NS}}}LineString")
        ET.SubElement(line, f"{{{_KML_NS}}}tessellate").text = "1"
        ET.SubElement(line, f"{{{_KML_NS}}}coordinates").text = " ".join(coordinates)
    for key, payload in sorted(entities.items()):
        if key[0] != "gtfs_stops" or payload.get("stop_id") not in stop_ids:
            continue
        latitude, longitude = payload.get("stop_lat"), payload.get("stop_lon")
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
            continue
        placemark = _placemark(document, str(payload.get("stop_name") or payload.get("stop_id")))
        _data(
            placemark,
            {
                "stop_id": payload.get("stop_id"),
                "stop_name": payload.get("stop_name"),
                "route_id": stop_route_ids.get(str(payload.get("stop_id"))),
                "route_short_name": routes.get(
                    stop_route_ids.get(str(payload.get("stop_id"))) or "",
                    {},
                ).get("route_short_name"),
                "route_long_name": routes.get(
                    stop_route_ids.get(str(payload.get("stop_id"))) or "",
                    {},
                ).get("route_long_name"),
                "agency_id": routes.get(
                    stop_route_ids.get(str(payload.get("stop_id"))) or "",
                    {},
                ).get("agency_id"),
                "stop_sequence": stop_metadata.get(str(payload.get("stop_id")), {}).get(
                    "stop_sequence"
                ),
                "revision_id": revision_id,
                "gtfs_explorer_version": "0.2.0",
                "kml_profile": profile.value,
            },
        )
        point = ET.SubElement(placemark, f"{{{_KML_NS}}}Point")
        ET.SubElement(point, f"{{{_KML_NS}}}coordinates").text = f"{longitude},{latitude},0"
    ET.register_namespace("", _KML_NS)
    return cast(bytes, ET.tostring(root, encoding="utf-8", xml_declaration=True))


def _placemark(document: ET.Element, name: str) -> ET.Element:
    placemark = ET.SubElement(document, f"{{{_KML_NS}}}Placemark")
    ET.SubElement(placemark, f"{{{_KML_NS}}}name").text = name
    return placemark


def _data(placemark: ET.Element, values: dict[str, object]) -> None:
    extended = ET.SubElement(placemark, f"{{{_KML_NS}}}ExtendedData")
    for name, value in sorted(values.items()):
        if value is None:
            continue
        data = ET.SubElement(extended, f"{{{_KML_NS}}}Data", name=name)
        ET.SubElement(data, f"{{{_KML_NS}}}value").text = str(value)


def _shape_coordinates(
    entities: dict[tuple[str, str], dict[str, object]], shape_id: object
) -> tuple[str, ...]:
    points = [
        payload
        for key, payload in entities.items()
        if key[0] == "gtfs_shapes" and payload.get("shape_id") == shape_id
    ]
    points.sort(key=lambda payload: _number(payload.get("shape_pt_sequence")))
    result: list[str] = []
    for payload in points:
        latitude, longitude = payload.get("shape_pt_lat"), payload.get("shape_pt_lon")
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
            continue
        if not (
            math.isfinite(float(latitude))
            and math.isfinite(float(longitude))
            and -90 <= float(latitude) <= 90
            and -180 <= float(longitude) <= 180
        ):
            continue
        result.append(f"{float(longitude):.8f},{float(latitude):.8f},0")
    return tuple(result)


def _kmz_bytes(kml: bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        info = zipfile.ZipInfo("doc.kml", date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, kml)
    return output.getvalue()


def _read_kml_payload(path: Path, limits: KmlSecurityLimits) -> bytes:
    if not path.is_file():
        raise KmlSecurityError("El fichero KML/KMZ no existe.")
    if path.suffix.casefold() != ".kmz":
        try:
            content = path.read_bytes()
        except OSError as error:
            raise KmlSecurityError("No se ha podido leer el fichero KML.") from error
        if len(content) > limits.max_xml_bytes:
            raise KmlSecurityError("El XML KML excede el límite de tamaño permitido.")
        return content
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > limits.max_members:
                raise KmlSecurityError("El KMZ contiene demasiados miembros.")
            compressed = sum(info.compress_size for info in infos)
            uncompressed = sum(info.file_size for info in infos)
            if (
                compressed > limits.max_compressed_bytes
                or uncompressed > limits.max_uncompressed_bytes
            ):
                raise KmlSecurityError("El KMZ excede los límites de tamaño.")
            if (not compressed and uncompressed) or (
                compressed and uncompressed / compressed > limits.max_expansion_ratio
            ):
                raise KmlSecurityError("El KMZ excede el ratio de expansión permitido.")
            candidates: list[str] = []
            for info in infos:
                _validate_zip_member(info)
                if not info.is_dir() and info.filename.casefold().endswith(".kml"):
                    candidates.append(info.filename)
            if len(candidates) != 1:
                raise KmlSecurityError("El KMZ debe contener exactamente un KML local.")
            content = archive.read(candidates[0])
    except (OSError, zipfile.BadZipFile) as error:
        raise KmlSecurityError("El KMZ no es un contenedor local válido.") from error
    if len(content) > limits.max_xml_bytes:
        raise KmlSecurityError("El XML KML excede el límite de tamaño permitido.")
    return content


def _validate_zip_member(info: zipfile.ZipInfo) -> None:
    path = info.filename.replace("\\", "/")
    pure = Path(path)
    parts = path.split("/")
    if info.is_dir() and parts and parts[-1] == "":
        parts.pop()
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in parts):
        raise KmlSecurityError("El KMZ contiene una ruta interna no segura.")
    mode = (info.external_attr >> 16) & 0o170000
    if mode and mode != stat.S_IFREG and mode != stat.S_IFDIR:
        raise KmlSecurityError("El KMZ contiene un miembro que no es un fichero regular.")


def _reject_dangerous_xml(content: bytes) -> None:
    if _DANGEROUS_XML.search(content):
        raise KmlSecurityError("El KML contiene DTD, entidades, XInclude o enlaces de red.")


def _walk(root: ET.Element) -> Iterable[tuple[ET.Element, int]]:
    pending: list[tuple[ET.Element, int]] = [(root, 0)]
    while pending:
        element, depth = pending.pop()
        yield element, depth
        pending.extend((child, depth + 1) for child in reversed(list(element)))


def _coordinates(value: str, max_points: int) -> tuple[tuple[float, float], ...]:
    result: list[tuple[float, float]] = []
    for index, token in enumerate(value.split()):
        if index >= max_points:
            raise KmlSecurityError("Una geometría KML excede el límite de puntos.")
        parts = token.split(",")
        if len(parts) < 2:
            raise KmlSecurityError("Una coordenada KML no tiene longitud y latitud.")
        try:
            longitude, latitude = float(parts[0]), float(parts[1])
        except ValueError as error:
            raise KmlSecurityError("Una coordenada KML no es numérica.") from error
        if not (
            math.isfinite(longitude)
            and math.isfinite(latitude)
            and -180 <= longitude <= 180
            and -90 <= latitude <= 90
        ):
            raise KmlSecurityError("Una coordenada KML queda fuera de WGS84.")
        result.append((longitude, latitude))
    return tuple(result)


def _classify(metadata: set[str]) -> KmlClassification:
    if "gtfs_explorer_version" in metadata:
        return KmlClassification.GTFS_EXPLORER_KML
    if metadata & {"route_id", "shape_id", "stop_id", "agency_id", "stop_sequence"}:
        return KmlClassification.MODIFIED_KML
    return KmlClassification.UNKNOWN_KML


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else float("inf")
