"""Conservative screenshot intake. Ambiguous inputs are rejected."""
import base64,io,re,subprocess,tempfile,os
from PIL import Image,ImageOps,ImageEnhance
PLAYERS={'jamal murray':'3936299'}
def extract_image(encoded):
 data=base64.b64decode(encoded,validate=True)
 if len(data)>7000000: raise ValueError('Image too large')
 im=Image.open(io.BytesIO(data));im.verify()
 im=Image.open(io.BytesIO(data)).convert('RGB')
 if im.width*im.height>16000000: raise ValueError('Image too large')
 im=ImageEnhance.Contrast(ImageOps.grayscale(im)).enhance(2)
 with tempfile.NamedTemporaryFile(suffix='.png',delete=False) as f:
  path=f.name;im.save(path)
 try:return subprocess.run(['tesseract',path,'stdout','--psm','6'],capture_output=True,text=True,timeout=20,check=True).stdout
 finally:os.unlink(path)
def parse_text(text):
 lower=text.lower()
 matches=[(name,ident) for name,ident in PLAYERS.items() if name in lower]
 if len(matches)!=1:raise ValueError('Player identity unverified')
 if 'points' not in lower:raise ValueError('Market unverified')
 lines=lower.splitlines();values=set()
 for i,line in enumerate(lines):
  if 'points' in line:
   values.update(float(v) for v in re.findall(r'(?<!\d)(\d{1,2}\.5)(?!\d)',' '.join(lines[max(0,i-1):i+2])))
 if len(values)!=1:raise ValueError('Prop line ambiguous')
 return {'athlete_id':matches[0][1],'market':'points','line':values.pop()}
