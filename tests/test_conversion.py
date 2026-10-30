"""Smoke tests for the SUNAT/PCM converter; run with Python 3.10+."""
import csv
import gzip
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from shutil import copytree

BASE=Path(__file__).resolve().parents[1]

class TestGeneration(unittest.TestCase):
    def test_sunat_and_pcm_fixture(self):
        with tempfile.TemporaryDirectory() as td:
            td=Path(td)
            (td/'scripts').mkdir();(td/'data').mkdir()
            (td/'scripts'/'preparar_datos.py').write_bytes((BASE/'scripts'/'preparar_datos.py').read_bytes())
            (td/'data'/'proyectos_base.json').write_bytes((BASE/'data'/'proyectos_base.json').read_bytes())
            data=[
                ['20519923182','PROYECTO ESPECIAL REGIONAL PASTO GRANDE','ACTIVO','HABIDO','180101','AV','CENTRAL','-','-','123','-','-','-','-','-','-'],
                ['20170639520','PROYECTO ESPECIAL RECURSOS HIDRICOS DE TACNA','ACTIVO','HABIDO','230101','AV','CENTRAL','-','-','123','-','-','-','-','-','-'],
                ['20100000001','EMPRESA DE PRUEBA TACNA S.A.C.','ACTIVO','HABIDO','230101','JR','TACNA','-','-','120','-','-','-','-','-','-'],
                ['20100000002','MUNICIPALIDAD PROVINCIAL DE TACNA','ACTIVO','HABIDO','230101','JR','TACNA','-','-','15','-','-','-','-','-','-'],
                ['20100000003','EMPRESA NO ACTIVA TACNA S.A.C.','BAJA','NO HABIDO','230101','AV','','-','-','40','-','-','-','-','-','-'],
            ]
            with zipfile.ZipFile(td/'sunat.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
                txt='RUC|NOMBRE O RAZON SOCIAL|ESTADO|CONDICION|UBIGEO|DIRECCION\n'+'\n'.join('|'.join(r) for r in data)
                z.writestr('padron_reducido_ruc.txt',txt.encode('latin-1'))
            geo={'180101':['MOQUEGUA','MARISCAL NIETO','MOQUEGUA'],'230101':['TACNA','TACNA','TACNA']}
            (td/'geo.json').write_text(json.dumps(geo))
            with (td/'pcm.csv').open('w',encoding='utf-8',newline='') as f:
                w=csv.writer(f);w.writerow(['RUC','ENTIDAD','DEPARTAMENTO','PROVINCIA','DISTRITO','UBIGEO']);
                w.writerow(['20100000002','MUNICIPALIDAD PROVINCIAL DE TACNA','TACNA','TACNA','TACNA','230101'])
            cmd=[sys.executable,str(td/'scripts'/'preparar_datos.py'),'--sin-descargas','--sunat-zip',str(td/'sunat.zip'),
                 '--publicas-csv',str(td/'pcm.csv'),'--ubigeos-json',str(td/'geo.json')]
            proc=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=35)
            self.assertEqual(proc.returncode,0,(proc.stdout,proc.stderr))
            mf=json.loads((td/'data'/'manifest.json').read_text())
            self.assertTrue(mf['sunat']['disponible'])
            self.assertEqual(mf['sunat']['ruc20'],5)
            self.assertEqual(mf['departamentos']['23']['registros'],4)
            proyectos=json.loads((td/'data'/'proyectos.json').read_text())
            self.assertEqual(next(r for r in proyectos if r['ruc']=='20519923182')['estado'],'ACTIVO')
            with gzip.open(td/'data'/'sunat'/'23.ndjson.gz','rt',encoding='utf8') as f:
                result=[json.loads(line) for line in f]
            self.assertEqual(len(result),4)
            self.assertEqual(result[0][0],'20170639520')
            pcm=json.loads((td/'data'/'publicas.json').read_text())
            self.assertEqual(pcm[0]['tipo'],'Municipalidades')

if __name__=='__main__':unittest.main()
