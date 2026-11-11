"""Read the supplied numbering workbook and prepare local material suggestions."""
import hashlib,json,re,zipfile,io,posixpath
from datetime import datetime,date,timedelta
from xml.etree import ElementTree as ET

NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
REL='{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
def normalized(value):
 text=str(value or '').strip().lower().translate(str.maketrans('أإآٱىةؤئ٠١٢٣٤٥٦٧٨٩','اااايهوي0123456789'))
 return re.sub(r'\s+',' ',re.sub(r'[\u064b-\u065f\u0670ـ]','',text)).strip()
def purchase_type(value):
 return normalized(value).replace(' ','') in {'طلبشراء','طلبالشراء','طلبشراي','طلبشرااء','طللبشراء'}
def request_year(value):
 for pattern in ('%Y-%m-%d','%d/%m/%Y','%d-%m-%Y'):
  try:return datetime.strptime(str(value),pattern).year
  except ValueError:pass
 raise ValueError('تاريخ الطلب غير صالح للترقيم.')
def book_date(value):
 text=str(value or '').strip()
 for pattern in ('%Y-%m-%d','%d-%m-%Y','%d/%m/%Y'):
  try:return datetime.strptime(text[:10],pattern).date().isoformat()
  except ValueError:pass
 if re.fullmatch(r'\d+(?:\.\d+)?',text):
  try:return (date(1899,12,30)+timedelta(days=int(float(text)))).isoformat()
  except (ValueError,OverflowError):pass
 return ''
def material_parts(value):
 text=re.sub(r'\s+',' ',str(value or '')).strip(' -،')
 if not text or re.search(r'^(?:سلف[ةه]|صرف مبلغ|\d+\s*(?:الف|ألف|مليون|دينار|دولار))',text):return []
 parts=re.split(r'\s*\+\s*|[\n،;؛]+',str(value))
 result=[]
 for part in parts:
  part=re.sub(r'\s+',' ',part).strip(' -،')
  if not 2<=len(part)<=240:continue
  # Keep the source wording. Quantities and specifications remain editable in the form.
  name=re.sub(r'^\d+\s+(?=\D)','',part).strip()
  name=re.sub(r'\s+عدد\s+[٠-٩0-9]+.*$','',name).strip()
  if name and normalized(name) not in {normalized(item) for item in result}:result.append(name)
 return result[:30]
def read_reference(data,templates):
 with zipfile.ZipFile(io.BytesIO(data)) as archive:
  infos=archive.infolist()
  if len(infos)>5000 or sum(item.file_size for item in infos)>150_000_000:raise ValueError('ملف Excel كبير جدًا.')
  if any(item.flag_bits&1 for item in infos):raise ValueError('الملف محمي بكلمة مرور.')
  shared=[]
  if 'xl/sharedStrings.xml' in archive.namelist():
   shared=[''.join(node.itertext()) for node in ET.fromstring(archive.read('xl/sharedStrings.xml'))]
  workbook=ET.fromstring(archive.read('xl/workbook.xml'))
  links={node.get('Id'):node.get('Target') for node in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels')) if node.get('TargetMode')!='External'}
  aliases={}
  for template in templates:
   for value in [template['name'],template.get('site',''),*template['name'].split('·')]:
    key=normalized(value)
    if key:aliases[key]=template['id']
  known={'مقر الشركة':'shamara','مقر شماره':'shamara','شماره':'shamara','الحرة':'ifc','الحرة الدولية':'ifc','فندق موفنبيك':'movenpick','المستشفى الألماني':'german-iraqi-hospital','مستشفى الألماني':'german-iraqi-hospital','معمل السمنت العربي':'cement-factory'}
  for name,ident in known.items():
   if any(template['id']==ident for template in templates):aliases[normalized(name)]=ident
  rows=[];maxima={};numbers={};ignored=0
  for sheet in workbook.find('s:sheets',NS):
   name=sheet.get('name','')
   target=links.get(sheet.get(REL),'')
   target=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
   if not target.startswith('xl/') or target not in archive.namelist():continue
   root=ET.fromstring(archive.read(target))
   parsed=[]
   for row in root.findall('s:sheetData/s:row',NS):
    values={}
    for cell in row.findall('s:c',NS):
     column=re.sub(r'\d','',cell.get('r',''))
     value=cell.find('s:v',NS)
     if cell.get('t')=='s' and value is not None and value.text:value=shared[int(value.text)]
     elif cell.get('t')=='inlineStr':
      inline=cell.find('s:is',NS);value=''.join(inline.itertext()) if inline is not None else ''
     else:value=(value.text or '') if value is not None else ''
     values[column]=value
    parsed.append((int(row.get('r','0')),values))
   header=next(((index,values) for index,values in parsed[:20] if normalized(values.get('A',''))=='رقم العدد'),None)
   if not header:continue
   cols={normalized(value):key for key,value in header[1].items()}
   kind=cols.get(normalized('عنوان الطلب')) or cols.get(normalized('نوع الطلب'))
   detail=cols.get(normalized('التفاصيل'))
   if not kind or not detail:raise ValueError('لم أجد عمودي عنوان الطلب والتفاصيل.')
   for index,values in parsed:
    if index<=header[0]:continue
    raw=str(values.get('A','')).strip().translate(str.maketrans('٠١٢٣٤٥٦٧٨٩','0123456789'))
    if not re.fullmatch(r'\d+(?:\.0+)?',raw):
     if any(values.values()):ignored+=1
     continue
    number=int(float(raw))
    if not 0<number<1000000000:continue
    when=book_date(values.get(cols.get(normalized('التاريخ'),'G'),''))
    year=int(name) if re.fullmatch(r'20\d\d',name) else int(when[:4]) if when else None
    if year is None:ignored+=1;continue
    maxima[year]=max(maxima.get(year,0),number)
    numbers[(year,number)]=numbers.get((year,number),0)+1
    if not purchase_type(values.get(kind,'')):continue
    item={'year':year,'number':str(number),'requester':str(values.get('B','')).strip(),'fromDepartment':str(values.get('C','')).strip(),'toDepartment':str(values.get('D','')).strip(),'title':str(values.get(kind,'')).strip(),'details':str(values.get(detail,'')).strip(),'date':when}
    item['key']=hashlib.sha256(json.dumps(item,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:32]
    item.update(sheet=name,row=index,company=aliases.get(normalized(item['toDepartment']),''))
    rows.append(item)
  if not maxima:raise ValueError('لم أجد أعدادًا صالحة في ملف Excel.')
  if not rows:raise ValueError('لم أجد طلبات شراء في عمود عنوان الطلب.')
  duplicates=[{'year':year,'number':number,'count':count} for (year,number),count in numbers.items() if count>1]
  return {'rows':rows,'maxima':maxima,'duplicates':duplicates,'ignored':ignored,'sha256':hashlib.sha256(data).hexdigest()}
