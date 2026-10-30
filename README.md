# Buscador RUC Perú — sitio web para GitHub Pages

Página estática en **HTML + JavaScript**: no requiere un servidor Python ni API privada para que los visitantes consulten la información. Las fuentes oficiales se procesan por **GitHub Actions** y se convierten en archivos comprimidos por departamento.

## Publicar en GitHub Pages

1. Crea un repositorio en GitHub (p. ej. `buscador-ruc-peru`) y súbele el **contenido completo de esta carpeta**, incluidos `index.html`, `data/`, `scripts/` y `.github/workflows/publicar.yml`. No subas solo el archivo ZIP sin extraer.
2. En el repositorio, abre **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. En **Actions**, selecciona **Actualizar padron y publicar web → Run workflow** (rama `main`). También se ejecuta al subir cambios a `main` y cada lunes.
4. Una vez que termine correctamente, abre la URL indicada en **Settings → Pages** (habitualmente `https://TU-USUARIO.github.io/buscador-ruc-peru/`).
5. La primera ejecución **descarga el padrón oficial comprimido de SUNAT** (centenares de MB), lo procesa en el runner de GitHub y publica únicamente los **RUC de personas jurídicas (RUC 20) divididos por departamento**. El visitante no tiene que descargar el padrón ni instalar Python.

**Importante:** el primer acceso a la web antes de completar la acción solo muestra un catálogo **referencial y no exhaustivo** de proyectos especiales. El aviso en la parte superior especifica si el índice SUNAT está disponible. No interpretes un registro referencial como RUC activo confirmado. Si Actions falla, examina el log del trabajo, especialmente la descarga de SUNAT o del PCM.

## Qué incluye

- Búsqueda por departamento, provincia y distrito (campos opcionales), con filtro de razón social o RUC.
- Modos: públicas, empresas, ambas; tipos: municipalidades, gobiernos regionales, DREM, ministerios, proyectos especiales, otras entidades y empresas.
- Proyectos especiales: lista referencial inicial, enriquecida con SUNAT cuando existe su RUC en el padrón. Ejemplos: Pasto Grande, Chira-Piura, Olmos-Tinajones, PECH Chavimochic, PET Tacna.
- Exportación a **Excel `.xlsx`** (hojas Resumen, Proyectos, Públicas, Empresas, Sin RUC y Fuentes) y CSV, hecha íntegramente en el navegador, sin librerías externas.
- Navegación responsive en celular y PC. Fecha de actualización y grado de verificación de cada RUC.
- Datos fuente divididos en `data/sunat/01.ndjson.gz` a `data/sunat/25.ndjson.gz` para descargar solo la ubicación consultada.

## Fuentes

- SUNAT: https://www.sunat.gob.pe/descargaPRR/mrc137_padron_reducido.html
- PCM (PTE): https://www.datosabiertos.gob.pe/dataset/entidades-p%C3%BAblicas-registradas-en-el-portal-de-transparencia-est%C3%A1ndar-pte
- Ubigeos auxiliares: https://github.com/RitchieRD/ubigeos-peru-data
- Los RUC de los proyectos de referencia incluyen una URL de la fuente documental por fila en `data/proyectos_base.json`.

## Limitaciones importantes

- **No hay consulta SUNAT en vivo.** El índice es una fotografía de la última actualización exitosa.
- El padrón reducido proporciona domicilio **fiscal**, no necesariamente el lugar de operación; no se incluyen locales anexos en esta primera versión web.
- El modo empresas identifica personas jurídicas cuyos RUC empiezan en `20`. **No incluye RUC 10** de personas naturales con negocio ni otros números; esto mantiene el mismo criterio de la versión Python anterior.
- PCM puede omitir unidades ejecutoras y proyectos; las coincidencias por nombre no confirman que la organización sea estatal.
- En un navegador se retienen **máximo 250 000 filas** por consulta para evitar bloqueos de memoria. Si la selección supera ese número, la web lo advierte y la exportación es **parcial**: reduce la búsqueda a un departamento o provincia.
- Un proyecto especial puede compartir el RUC de su entidad adscrita. Una referencia departamental no es una dirección fiscal.
- GitHub Pages recomienda no superar aproximadamente 1 GB de sitio publicado ni sus límites de ancho de banda; el generador evita subir el ZIP original, solo archivos comprimidos por departamento. Si el sitio sobrepasa esos límites, alojar el índice en otro servicio de datos (storage/CDN) es más apropiado.
- Se requiere navegador reciente con soporte `DecompressionStream` para consultas empresariales. La exportación XLSX tiene una implementación compatible con Excel/LibreOffice que no depende de CDN.

## Desarrollo local (sin descargar SUNAT)

Ejecuta un servidor HTTP en la carpeta:

```bash
python -m http.server 8000
```

Abre http://localhost:8000. El catálogo de proyectos base se puede consultar sin descargar los datos masivos.

## Preparar datos desde la computadora (opcional)

```bash
python -m pip install requests beautifulsoup4
python scripts/preparar_datos.py
```

Si ya tienes el ZIP SUNAT descargado, puedes reutilizarlo sin volverlo a bajar:

```bash
python scripts/preparar_datos.py --sunat-zip "C:\\ruta\\padron_reducido_ruc.zip"
```

También puedes proporcionar un CSV PCM `--publicas-csv` o un JSON de ubigeos `--ubigeos-json`. Se requiere internet para fuentes no proporcionadas. Luego debes subir el directorio `data` procesado o usar GitHub Actions; cuidado con el tamaño de los archivos si haces commits normales.

## Ubigeos y resolución de la ubicación

La web utiliza la codificación de seis dígitos de la SUNAT y un catálogo de ubigeos por departamento, provincia y distrito. El campo Departamento puede quedar en **Todos**, la provincia y distrito pueden quedar vacíos. La dirección usada es la fiscal, salvo que el registro indique que su ubicación procede de PCM o es referencial.

## Garantías de calidad

La herramienta no inventa RUC, no lee datos privados y muestra la fuente. El proceso masivo debe completarse exitosamente antes de señalar la búsqueda empresarial como habilitada. El estado ACTIVO no se afirma en proyectos sin contraste SUNAT. Los datos de PCM son best-effort y el sitio advierte cuando faltan.

## Cómo agregar proyectos especiales adicionales

Edita `data/proyectos_base.json` en el repositorio. Cada registro debe incluir como mínimo `ruc` (11 dígitos), `nombre`, `departamento` y `fuente` (URL documental). Mantén `identificacion` y `observaciones` indicando si es **referencia documental**. No uses un RUC supuesto. Tras guardar los cambios, vuelve a ejecutar el flujo de GitHub Actions para actualizar `data/proyectos.json` con el nuevo catálogo y contrastarlo con SUNAT.
