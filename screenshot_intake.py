"""Screenshot text parser backed by the NBA player registry, not a one-player map."""
import base64,io,re,subprocess,tempfile,os
from PIL import Image,ImageOps,ImageEnhance
from player_registry import normalize
MARKET_PATTERNS=[
 ('fantasy_score',r'fantasy\s*(?:score|pts|points)'),
 ('pra',r'(?:pts|points)\s*\+\s*(?:reb|rebounds)\s*\+\s*(?:ast|assists)'),
 ('pr',r'(?:pts|points)\s*\+\s*(?:reb|rebounds)'),
 ('pa',r'(?:pts|points)\s*\+\s*(?:ast|assists)'),
 ('ra',r'(?:reb|rebounds)\s*\+\s*(?:ast|assists)'),
 ('points',r'\b(?:points|pts)\b'),('rebounds',r'\b(?:rebounds|reb)\b'),('assists',r'\b(?:assists|ast)\b')]
def extract_image(encoded):
 data=base64.b64decode(encoded,validate=True)
 if len(data)>7000000:raise ValueError('IMAGE_TOO_LARGE')
 im=Image.open(io.BytesIO(data));im.verify()
 im=Image.open(io.BytesIO(data)).convert('RGB')
 if im.width*im.height>16000000:raise ValueError('IMAGE_TOO_LARGE')
 im=ImageEnhance.Contrast(ImageOps.grayscale(im)).enhance(2)
 with tempfile.NamedTemporaryFile(suffix='.png',delete=False) as f:
  path=f.name;im.save(path)
 try:return subprocess.run(['tesseract',path,'stdout','--psm','6'],capture_output=True,text=True,timeout=20,check=True).stdout
 finally:os.unlink(path)
def parse_text(text,roster):
 lines=[x.strip() for x in text.splitlines() if x.strip()]
 if not lines:raise ValueError('EMPTY_SCREENSHOT_TEXT')
 found=[]
 for player in roster:
  name=normalize(player['name'])
  if len(name)<6:continue
  if any(name in normalize(line) for line in lines):found.append(player)
 unique={p['nba_id']:p for p in found}
 if len(unique)!=1:raise ValueError('PLAYER_NOT_UNIQUELY_IDENTIFIED')
 markets=[]
 for market,pattern in MARKET_PATTERNS:
  for i,line in enumerate(lines):
   if re.search(pattern,line,re.I):
    markets.append((market,i));break
 if not markets:raise ValueError('MARKET_NOT_FOUND')
 market,i=markets[0]
 # The number must appear beside the market, not elsewhere on the screenshot.
 nearby=' '.join(lines[max(0,i-1):min(len(lines),i+2)])
 values=set(float(v) for v in re.findall(r'(?<!\d)(\d{1,3}(?:\.5)?)(?!\d)',nearby))
 values={v for v in values if 0.5<=v<=150}
 if len(values)!=1:raise ValueError('LINE_AMBIGUOUS_CONFIRM_MANUALLY')
 return {'player_name':unique[next(iter(unique))]['name'],'nba_id':next(iter(unique)),'market':market,'line':values.pop(),'intake':'OCR_REQUIRES_CONFIRMATION'}
