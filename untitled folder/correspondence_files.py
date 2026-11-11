"""Bounded attachment decoding and safe previews for correspondence books."""
import base64,binascii,hashlib,re,uuid
MAX_FILE_BYTES=20*1024*1024
MAX_BOOK_BYTES=30*1024*1024
MAX_BOOK_FILES=10
PREVIEW_TYPES={'application/pdf','image/png','image/jpeg','image/gif','image/webp'}

def attachment_id(value):
 if not isinstance(value,str) or not value.startswith('ATT-'):raise ValueError('معرف المرفق غير صالح.')
 try:valid=str(uuid.UUID(value[4:]))==value[4:]
 except (ValueError,AttributeError):valid=False
 if not valid:raise ValueError('معرف المرفق غير صالح.')
 return value

def content_type(data):
 if data.startswith(b'%PDF-'):return 'application/pdf'
 if data.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png'
 if data.startswith(b'\xff\xd8\xff'):return 'image/jpeg'
 if data.startswith((b'GIF87a',b'GIF89a')):return 'image/gif'
 if data.startswith(b'RIFF') and data[8:12]==b'WEBP':return 'image/webp'
 return 'application/octet-stream'

def decode_upload(item):
 name=item.get('name','')
 if not isinstance(name,str) or not name or len(name)>240 or any(ord(c)<32 or ord(c)==127 for c in name):raise ValueError('اسم المرفق غير صالح أو طويل جدًا.')
 name=name.replace('\\','/').split('/')[-1].strip()
 if not name or name in {'.','..'}:raise ValueError('اسم المرفق غير صالح.')
 encoded=item.get('data')
 if not isinstance(encoded,str) or len(encoded)>4*((MAX_FILE_BYTES+2)//3):raise ValueError('حجم المرفق يتجاوز 20 ميغابايت.')
 try:data=base64.b64decode(encoded,validate=True)
 except (ValueError,binascii.Error):raise ValueError('تعذر قراءة بيانات المرفق.')
 if not data:raise ValueError('لا يمكن إرفاق ملف فارغ.')
 if len(data)>MAX_FILE_BYTES:raise ValueError('حجم المرفق يتجاوز 20 ميغابايت.')
 return {'id':attachment_id(item.get('id')),'name':name,'contentType':content_type(data),'size':len(data),'sha256':hashlib.sha256(data).hexdigest(),'content':data}
