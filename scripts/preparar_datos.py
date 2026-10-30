#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Genera una base estatica por departamento para GitHub Pages.

Descarga y procesa SUNAT en streaming (RUC 20), sin colocar el ZIP en el sitio.
Los datos en data/sunat/*.ndjson.gz se consultan directamente desde el navegador.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import os
import re
import sys
import time
import unicodedata
import zipfile
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
SUNAT_PORTAL = 'https://www.sunat.gob.pe/descargaPRR/mrc137_padron_reducido.html'
SUNAT_URLS = [
    'https://www2.sunat.gob.pe/padron_reducido_ruc.zip',
    'https://www.sunat.gob.pe/descargaPRR/padron_reducido_ruc.zip',
]
PCM_PORTAL = 'https://www.datosabiertos.gob.pe/dataset/entidades-p%C3%BAblicas-registradas-en-el-portal-de-transparencia-est%C3%A1ndar-pte'
PCM_ANTIGUO = '2e7a9e47-456e-4e4a-b2ed-7df44477ee21'
PCM_API = 'https://www.datosabiertos.gob.pe/api/action/datastore/search.json'
UBIGEO_BASE = 'https://raw.githubusercontent.com/RitchieRD/ubigeos-peru-data/main/csv/'
UBIGEO_FILES = ('1_ubigeo_departamentos.csv', '2_ubigeo_provincias.csv', '3_ubigeo_distritos.csv')
NOMBRES_DEP = {
    '01':'AMAZONAS','02':'ANCASH','03':'APURIMAC','04':'AREQUIPA','05':'AYACUCHO',
    '06':'CAJAMARCA','07':'CALLAO','08':'CUSCO','09':'HUANCAVELICA','10':'HUANUCO',
    '11':'ICA','12':'JUNIN','13':'LA LIBERTAD','14':'LAMBAYEQUE','15':'LIMA',
    '16':'LORETO','17':'MADRE DE DIOS','18':'MOQUEGUA','19':'PASCO','20':'PIURA',
    '21':'PUNO','22':'SAN MARTIN','23':'TACNA','24':'TUMBES','25':'UCAYALI',
}
PARTICIONES={'00':'UBIGEO NO IDENTIFICADO',**NOMBRES_DEP}
TIPO_MUNI = 'Municipalidades'
TIPO_REGION = 'Gobiernos regionales'
TIPO_DREM = 'Direcciones regionales de Energia y Minas'
TIPO_MIN = 'Ministerios'
TIPO_PROY = 'Proyectos especiales'
TIPO_OTRAS = 'Otras entidades publicas'
csv.field_size_limit(64 * 1024 * 1024)


def normaliza(s):
    s = unicodedata.normalize('NFKD', str(s or '').strip())
    return re.sub(r'\s+', ' ', ''.join(c for c in s if not unicodedata.combining(c)).upper())


def clasificar(nombre, poder='', publico=False):
    n = normaliza(nombre)
    if re.search(r'\bD\.?R\.?E\.?M\.?\b', n) or re.search(r'(DIRECCION|GERENCIA) REGIONAL DE (ENERGIA Y MINAS|MINAS Y ENERGIA)', n):
        return TIPO_DREM
    if re.search(r'\bPROY(ECTO)?\.? ESP(ECIAL)?\b', n) or 'PROYECTOS ESPECIALES' in n:
        return TIPO_PROY
    if 'MUNICIPALIDAD' in n or 'MUNICIPALIDADES' in normaliza(poder):
        return TIPO_MUNI
    if 'GOBIERNO REGIONAL' in n or n.startswith('REGION ') or 'GOBIERNOS REGIONALES' in normaliza(poder):
        return TIPO_REGION
    if re.search(r'\bMINISTERIO (DE|DEL)\b', n):
        return TIPO_MIN
    return TIPO_OTRAS if publico else ''


def sesion():
    s = requests.Session()
    retry = Retry(total=4, backoff_factor=1.5, status_forcelist=(429,500,502,503,504), allowed_methods={'GET'})
    s.mount('https://', HTTPAdapter(max_retries=retry))
    s.mount('http://', HTTPAdapter(max_retries=retry))
    s.headers['User-Agent'] = 'BuscadorRUC-Pages/1.0 (fuentes oficiales; indice estatitco)'
    return s


def bajar_zip(session, destino):
    destino.parent.mkdir(parents=True,exist_ok=True)
    if destino.exists() and zipfile.is_zipfile(destino):
        print('[SUNAT] Reutilizando ZIP:', destino)
        return destino
    errores = []
    for url in SUNAT_URLS:
        temp = destino.with_suffix('.parcial')
        try:
            print('[SUNAT] Descargando', url, flush=True)
            with session.get(url, stream=True, timeout=(30,180)) as res:
                res.raise_for_status()
                with temp.open('wb') as dest:
                    contador = 0
                    for trozo in res.iter_content(chunk_size=2*1024*1024):
                        if not trozo: continue
                        dest.write(trozo)
                        contador += len(trozo)
                        if contador // (50*1024*1024) != (contador-len(trozo)) // (50*1024*1024):
                            print('[SUNAT] Descargados:',round(contador/1048576),'MB',flush=True)
            if temp.stat().st_size < 10000 or not zipfile.is_zipfile(temp):
                raise RuntimeError('La descarga no es un ZIP valido')
            temp.replace(destino)
            return destino
        except Exception as ex:
            errores.append(f'{url}: {ex}')
            temp.unlink(missing_ok=True)
    raise RuntimeError('No se pudo descargar SUNAT: '+' | '.join(errores))


def campo(row,*nombres):
    norm = {normaliza(k).replace('_',' '): v for k,v in row.items()}
    for k in nombres:
        v = norm.get(normaliza(k).replace('_',' '))
        if v is not None and str(v).strip(): return str(v).strip()
    return ''


def cargar_pcm(session, csv_manual=None):
    if csv_manual:
        with open(csv_manual,'rb') as f: contenido=f.read()
        filas = parse_csv_pcm(contenido)
        return filas,'Archivo PCM aportado'
    errores=[]
    candidatos=[]
    try:
        resp=session.get(PCM_PORTAL,timeout=60);resp.raise_for_status()
        sopa=BeautifulSoup(resp.text,'html.parser')
        for a in sopa.find_all('a',href=True):
            u=urljoin(PCM_PORTAL,a['href'])
            m=re.search(r'/resource/([\da-f-]{20,36})',u,re.I)
            if m:
                txt=normaliza(a.get_text(' ',strip=True))
                score= (20 if 'DSPTE01' in txt else 0)+(10 if 'ENTIDADES' in txt else 0)
                candidatos.append((score,m.group(1),u))
    except Exception as e:
        errores.append('Portal PCM: '+str(e))
    candidatos.sort(reverse=True)
    candidatos.append((0,PCM_ANTIGUO,'https://www.datosabiertos.gob.pe/dataset/lista-de-entidades-del-estado-peruano/resource/'+PCM_ANTIGUO))
    vistos=set()
    for _,rid,pagina in candidatos:
        if rid in vistos:continue
        vistos.add(rid)
        try:
            registros=[];offset=0
            while True:
                r=session.get(PCM_API,params={'resource_id':rid,'limit':1000,'offset':offset},timeout=(25,100))
                r.raise_for_status()
                j=r.json()
                if j.get('success') is False:raise ValueError('Respuesta sin exito')
                contenido=j.get('result',j)
                bloque=contenido.get('records',[])
                if not isinstance(bloque,list):raise ValueError('Registros invalidos')
                registros.extend(bloque)
                offset+=len(bloque)
                if len(bloque)<1000:break
                if offset>200000:raise ValueError('Exceso de filas PCM')
            if registros:
                filas=normalizar_pcm(registros)
                if any(f['ruc'] for f in filas):
                    print(f'[PCM] {len(filas):,} registros: {rid}',flush=True)
                    return filas,pagina
        except Exception as e:
            errores.append('API PCM '+rid+': '+str(e))
        try:
            r=session.get(pagina,timeout=45);r.raise_for_status()
            soup=BeautifulSoup(r.text,'html.parser')
            urls=[]
            for a in soup.find_all('a',href=True):
                u=urljoin(pagina,a['href'])
                if u.lower().endswith('.csv') or '/download' in u.lower():urls.append(u)
            for url in urls[:8]:
                rr=session.get(url,timeout=(25,100));rr.raise_for_status()
                filas=parse_csv_pcm(rr.content)
                if any(f['ruc'] for f in filas):return filas,url
        except Exception as e:
            errores.append('CSV PCM '+rid+': '+str(e))
    print('[PCM] AVISO: No se pudo cargar el directorio. '+' | '.join(errores)[-800:],flush=True)
    return [],''


def parse_csv_pcm(data):
    cadena=None
    for enc in ('utf-8-sig','latin-1'):
        try:
            cadena=data.decode(enc);break
        except UnicodeDecodeError:continue
    if cadena is None:return []
    sep=';' if cadena.splitlines()[0].count(';')>cadena.splitlines()[0].count(',') else ','
    return normalizar_pcm(csv.DictReader(io.StringIO(cadena),delimiter=sep))


def normalizar_pcm(registros):
    resultado=[];seen=set()
    for r in registros:
        if not isinstance(r,dict):continue
        nombre=campo(r,'DSC_INSTITUCION','ENTIDAD','NOMBRE_ENTIDAD','NOMBRE DE ENTIDAD','NOMBRE_INSTITUCION','INSTITUCION','RAZON SOCIAL','NOMBRE')
        if not nombre:continue
        ruc=campo(r,'DSC_RUC','RUC','RUC_ENTIDAD','NUMERO_RUC','NRO_RUC','VC_RUC_ENTIDAD','RUC DE LA ENTIDAD')
        ruc=ruc if re.fullmatch(r'\d{11}',ruc) else ''
        ubigeo=campo(r,'UBIGEO','COD_UBIGEO','CODIGO_UBIGEO','UBIGEO_SEDE_PRINCIPAL','VC_UBIGEO','COD_UBIGEO_SEDE','IDUBIGEOINEI')
        ubigeo=ubigeo.zfill(6) if ubigeo.isdigit() and len(ubigeo)<=6 else ''
        dep=normaliza(campo(r,'DEPARTAMENTO','REGION','DEPARTAMENTO_SEDE'))
        prov=normaliza(campo(r,'PROVINCIA','PROVINCIA_SEDE'))
        dist=normaliza(campo(r,'DISTRITO','DISTRITO_SEDE'))
        clave=(ruc,normaliza(nombre),ubigeo,dep,prov,dist)
        if clave in seen:continue
        seen.add(clave)
        resultado.append({'ruc':ruc,'nombre':nombre,'ubigeo':ubigeo,'departamento':dep,'provincia':prov,'distrito':dist,
            'tipo':clasificar(nombre,campo(r,'PODER','NIVEL_GOBIERNO'),publico=True),'fuente':PCM_PORTAL,
            'identificacion':'Registro de entidad publica PCM',
            'observaciones':('Oficina/unidad sin RUC propio identificado' if not ruc else ''),
            'estado':'','condicion':'','direccion':''})
    return resultado


def cargar_geo(session, JSON_manual=None):
    if JSON_manual:
        return json.loads(Path(JSON_manual).read_text(encoding='utf-8'))
    try:
        docs=[]
        for nombre in UBIGEO_FILES:
            r=session.get(UBIGEO_BASE+nombre,timeout=40);r.raise_for_status()
            text=r.content.decode('utf-8-sig')
            sep=';' if text.splitlines()[0].count(';')>text.splitlines()[0].count(',') else ','
            docs.append(list(csv.DictReader(io.StringIO(text),delimiter=sep)))
        deps={campo(r,'id'):normaliza(campo(r,'departamento')) for r in docs[0]}
        provs={campo(r,'id'):(campo(r,'ubigeo').zfill(4),normaliza(campo(r,'provincia')),deps.get(campo(r,'departamento_id'),'')) for r in docs[1]}
        final={}
        for r in docs[2]:
            c=campo(r,'ubigeo');c=c.zfill(6) if c.isdigit() and len(c)<=6 else ''
            if not c:continue
            _,prov,dep=provs.get(campo(r,'provincia_id'),('','',''))
            dep=dep or NOMBRES_DEP.get(c[:2],'')
            final[c]=[dep,prov,normaliza(campo(r,'distrito'))]
        if len(final)<500:raise ValueError('Catalogo geográfico incompleto: '+str(len(final)))
        print(f'[UBIGEO] {len(final):,} distritos',flush=True)
        return final
    except Exception as e:
        print('[UBIGEO] AVISO: No se pudo descargar: '+str(e),flush=True)
        path=DATA/'ubigeos.json'
        return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def direccion(row):
    parts=[]
    for i in (5,6,8,9,10,11,12,13,14,15):
        if i<len(row) and row[i].strip() not in ('','-','--'):
            parts.append(row[i].strip().replace('\t',' ').replace('\n',' '))
    return ' '.join(parts)[:600]


def procesar_sunat(zip_path, publicas_inferidas, proyectos_base, proyectos_nuevos):
    carpeta=DATA/'sunat';carpeta.mkdir(parents=True,exist_ok=True)
    conteo=Counter();total=0;ruc20=0
    f0=time.monotonic()
    with zipfile.ZipFile(zip_path) as z, ExitStack() as stack:
        files=[f for f in z.infolist() if not f.is_dir() and f.filename.lower().endswith(('.txt','.csv'))]
        if not files: raise RuntimeError('El ZIP SUNAT no contiene un TXT/CSV')
        file=max(files,key=lambda info:info.file_size)
        print(f'[SUNAT] Leyendo {file.filename} ({file.file_size/1048576:,.0f} MB descomprimido)',flush=True)
        w={dep:stack.enter_context(gzip.open(carpeta/(dep+'.ndjson.gz'),'wt',encoding='utf-8',compresslevel=5,newline='\n')) for dep in PARTICIONES}
        with z.open(file) as source,io.TextIOWrapper(source,encoding='latin-1',errors='replace',newline='') as texto:
            reader=csv.reader(texto,delimiter='|',quoting=csv.QUOTE_NONE)
            for row in reader:
                total+=1
                if len(row)<5:continue
                ruc=row[0].strip()
                if not re.fullmatch(r'20\d{9}',ruc):continue
                ruc20+=1
                name=row[1].strip()[:350]; estado=row[2].strip()[:65]; condicion=row[3].strip()[:65]
                ubi=row[4].strip()
                if not re.fullmatch(r'\d{6}',ubi):ubi=''
                dep=ubi[:2] if ubi[:2] in NOMBRES_DEP else '00'
                info=[ruc,name,estado,condicion,ubi,direccion(row)]
                if dep in w:
                    w[dep].write(json.dumps(info,ensure_ascii=False,separators=(',',':'))+'\n')
                    conteo[dep]+=1
                # Capture existing known projects, including those with fiscal domicile outside the referenced dep.
                clase=clasificar(name)
                if clase and clase!=TIPO_PROY and ruc not in publicas_inferidas:
                    publicas_inferidas[ruc]={'ruc':ruc,'nombre':name,'ubigeo':ubi,'departamento':NOMBRES_DEP.get(dep,''),
                        'provincia':'','distrito':'','tipo':clase,'fuente':SUNAT_PORTAL,
                        'identificacion':'Clasificacion ORIENTATIVA por razon social SUNAT',
                        'observaciones':'Nombre compatible con entidad publica, pero no confirmada en directorio PCM.',
                        'estado':estado,'condicion':condicion,'direccion':info[5]}
                es_proyecto=ruc in proyectos_base or clase==TIPO_PROY
                if es_proyecto:
                    base=proyectos_base.get(ruc)
                    if base is None:
                        base={'ruc':ruc,'nombre':name,'departamento':NOMBRES_DEP.get(dep,''),'provincia':'','distrito':'',
                            'tipo':TIPO_PROY,'alias':[], 'fuente':SUNAT_PORTAL,
                            'identificacion':'Candidato por razon social SUNAT, comprobar que sea entidad publica',
                            'observaciones':'Clasificacion automatica por nombre; no prueba que sea entidad estatal.'}
                    else:base=base.copy()
                    base.update({'estado':estado,'condicion':condicion,'ubigeo':ubi,'direccion':info[5],
                        'identificacion':('RUC contrastado con padron SUNAT' if ruc in proyectos_base else base.get('identificacion')),
                        'domicilio_fiscal_departamento':NOMBRES_DEP.get(dep,''),'nombre_sunat':name})
                    proyectos_nuevos[ruc]=base
                if total%2_000_000==0:
                    print(f'[SUNAT] {total:,} registros / {ruc20:,} RUC 20 ({time.monotonic()-f0:.0f}s)',flush=True)
    print(f'[SUNAT] Finalizado: {total:,} lineas, {ruc20:,} RUC 20, {time.monotonic()-f0:.0f}s',flush=True)
    return total,ruc20,conteo


def main():
    parser=argparse.ArgumentParser(description='Prepara una base SUNAT / PCM para GitHub Pages')
    parser.add_argument('--sunat-zip',type=Path,help='ZIP local para pruebas o uso manual')
    parser.add_argument('--publicas-csv',type=Path,help='CSV de entidades PCM local')
    parser.add_argument('--ubigeos-json',type=Path,help='Ubigeos JSON ya generado para pruebas')
    parser.add_argument('--sin-descargas',action='store_true',help='No conectarse a Internet (pruebas)')
    args=parser.parse_args()
    DATA.mkdir(exist_ok=True)
    session=sesion()
    proyectos_base={r['ruc']:r for r in json.loads((DATA/'proyectos_base.json').read_text(encoding='utf-8'))}
    nuevos={}
    avisos=[]
    geo={} if args.sin_descargas and not args.ubigeos_json else cargar_geo(session,args.ubigeos_json)
    (DATA/'ubigeos.json').write_text(json.dumps(geo,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    pcm=[];fuente_pcm=''
    if not args.sin_descargas or args.publicas_csv:
        pcm,fuente_pcm=cargar_pcm(session,args.publicas_csv)
    for p in pcm:
        if p.get('ruc') in proyectos_base or p.get('tipo')==TIPO_PROY:
            ruc=p.get('ruc')
            if ruc:
                rec=proyectos_base.get(ruc,p.copy())
                nuevos[ruc]=rec.copy()
    # SUNAT is mandatory for nationwide company searches. If unavailable, do NOT mark complete.
    total=0;ruc20=0;cuentas=Counter();sunat_ok=False;inferidas={}
    try:
        if args.sunat_zip:zipfile.ZipFile(args.sunat_zip).close();sunat_zip=args.sunat_zip
        elif args.sin_descargas:sunat_zip=None
        else:sunat_zip=bajar_zip(session,ROOT/'_temporal'/'padron_reducido_ruc.zip')
        if sunat_zip:
            total,ruc20,cuentas=procesar_sunat(sunat_zip,inferidas,proyectos_base,nuevos)
            sunat_ok=True
    except Exception as e:
        avisos.append('ERROR: No se proceso SUNAT: '+str(e))
        print('[SUNAT] ERROR:',str(e),file=sys.stderr,flush=True)
        if not args.sin_descargas:
            raise
    if not sunat_ok:avisos.append('Sin padron SUNAT procesado: las empresas no estan disponibles en la web.')
    if not pcm:avisos.append('No se pudo obtener PCM: solo se identifican entidades por denominacion y catalogo de proyectos.')
    if not geo:avisos.append('Sin catalogo de ubigeos: filtros de provincia y distrito no disponibles.')
    # Mantener directorio PCM cuando disponible y enriquecerlo con el estado SUNAT
    # encontrado; completar las entidades reconocidas solo por nombre con nota de cautela.
    todas_publicas=[];pcm_rucs=set()
    for registro in pcm:
        reg=registro.copy()
        if reg['ruc'] and reg['ruc'] in inferidas:
            sunat=inferidas[reg['ruc']]
            reg['estado']=sunat['estado'];reg['condicion']=sunat['condicion'];reg['direccion']=sunat['direccion']
            reg['identificacion']='Directorio PCM; estado contrastado SUNAT'
            reg['observaciones']='Clasificacion oficial por PCM; estado obtenido de SUNAT.'
        todas_publicas.append(reg)
        if reg['ruc']:pcm_rucs.add(reg['ruc'])
    for ruc,registro in inferidas.items():
        if ruc not in pcm_rucs:todas_publicas.append(registro)
    (DATA/'publicas.json').write_text(json.dumps(todas_publicas,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    projects={**proyectos_base,**nuevos}
    # Mark reference-only rows as such; do not claim their status or fiscal address.
    for p in projects.values():
        if not p.get('estado'):
            p['identificacion']=p.get('identificacion') or 'RUC referencial, no contrastado en SUNAT'
            p['observaciones']=p.get('observaciones') or 'Verificar estado fiscal en SUNAT'
    (DATA/'proyectos.json').write_text(json.dumps(sorted(projects.values(),key=lambda r:normaliza(r['nombre'])),ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    manifiesto={
        'version':1,'actualizado':datetime.now(timezone.utc).isoformat(),
        'sunat':{'disponible':sunat_ok,'registros_total':total,'ruc20':ruc20,'fuente':SUNAT_PORTAL},
        'pcm':{'disponible':bool(pcm),'registros':len(pcm),'fuente':fuente_pcm or PCM_PORTAL},
        'ubigeos':{'disponible':len(geo)>500,'distritos':len(geo)},
        'proyectos':len(projects),'publicas_total':len(todas_publicas),'departamentos':{
            dep:{'nombre':name,'archivo':'sunat/'+dep+'.ndjson.gz','registros':cuentas[dep],
                'bytes':(DATA/'sunat'/(dep+'.ndjson.gz')).stat().st_size if sunat_ok else 0}
            for dep,name in PARTICIONES.items()
        } if sunat_ok else {},
        'avisos':avisos
    }
    (DATA/'manifest.json').write_text(json.dumps(manifiesto,ensure_ascii=False,indent=2),encoding='utf-8')
    print('[FIN] Base publicada:',json.dumps({'sunat':sunat_ok,'pcm':len(pcm),'publicas_total':len(todas_publicas),'proyectos':len(projects),'registros20':ruc20},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
