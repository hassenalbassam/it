#!/usr/bin/env python3
"""Run one central HTTPS server for employees on the company LAN."""
from pathlib import Path
import os,subprocess,socket,re,ssl
root=Path(__file__).resolve().parent
folder=root/'data'/'tls';folder.mkdir(parents=True,exist_ok=True)
addresses=[]
for interface in ('en0','en1','en2'):
 try:
  ip=subprocess.check_output(['/usr/sbin/ipconfig','getifaddr',interface],stderr=subprocess.DEVNULL,text=True).strip()
  if re.fullmatch(r'\d{1,3}(?:\.\d{1,3}){3}',ip) and ip not in addresses:addresses.append(ip)
 except (subprocess.CalledProcessError,FileNotFoundError):pass
if not addresses:raise SystemExit('لم يتم العثور على عنوان الشبكة. اتصل بشبكة الشركة ثم أعد التشغيل.')
hostname=socket.gethostname();hostname=hostname if re.fullmatch(r'[a-zA-Z0-9.-]+',hostname) else 'localhost'
cert=folder/'server.crt';key=folder/'server.key';signature=folder/'addresses.txt';desired='\n'.join(addresses+[hostname])
regenerate=not cert.exists() or not key.exists() or not signature.exists() or signature.read_text()!=desired
if not regenerate:
 try:regenerate=ssl.cert_time_to_seconds(ssl._ssl._test_decode_cert(str(cert))['notAfter'])<__import__('time').time()+86400
 except Exception:regenerate=True
if regenerate:
 config=folder/'openssl.cnf';sans='DNS.1 = localhost\nDNS.2 = '+hostname+'\nIP.1 = 127.0.0.1\n'+''.join('IP.'+str(i+2)+' = '+ip+'\n' for i,ip in enumerate(addresses))
 config.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=Shamara LAN Dashboard\n[ext]\nsubjectAltName=@names\n[names]\n'+sans)
 subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','rsa:3072','-sha256','-nodes','-keyout',str(key),'-out',str(cert),'-days','365','-config',str(config)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);key.chmod(0o600);signature.write_text(desired)
os.environ.update(SHAMARA_HOST='0.0.0.0',SHAMARA_TLS_CERT=str(cert),SHAMARA_TLS_KEY=str(key),SHAMARA_ALLOWED_HOSTS=','.join(addresses+[hostname]))
print('روابط الموظفين داخل الشبكة:',flush=True)
for ip in addresses:print('https://'+ip+':'+os.environ.get('SHAMARA_PORT','8765')+'/',flush=True)
print('أول إعداد للمدير: افتح https://localhost:8765/ على هذا الجهاز.\nالشهادة محلية. على مسؤول الشبكة الوثوق بها على أجهزة الموظفين أو توفير شهادة داخلية معتمدة.\nلا تشارك ملف server.key. أبقِ هذا الجهاز والخادم يعملان.',flush=True)
import server
server.main()
