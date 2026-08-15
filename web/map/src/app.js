import * as maplibregl from "maplibre-gl";
import {PMTiles, Protocol} from "pmtiles";

// El bridge tipado y la creación de capas pertenecen a tareas posteriores.
// Este contrato mínimo permite cargarlas desde el HTML local sin Node.
window.GTFSExplorerMap = {maplibregl, PMTiles, Protocol};
