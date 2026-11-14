"""Paste-friendly verified game-log intake; CSV files optional.
Accepted columns: date, pts/points, reb/rebounds, ast/assists, opponent, min.
Never invent missing box-score values. Input must be reviewed against source URL.
"""
import csv,io,json,re,datetime
ALIASES={'date':'date','game_date':'date','pts':'pts','points':'pts','reb':'reb','rebounds':'reb','ast':'ast','assists':'ast','opp':'opponent','opponent':'opponent','min':'min','minutes':'min'}
def parse_pasted_logs(text,source_url='',season=None):
 if not isinstance(text,str) or len(text)>500000:raise ValueError('INVALID_PASTED_TEXT')
 lines=[s.strip() for s in text.splitlines() if s.strip()]
 if not lines:raise ValueError('EMPTY_GAME_LOG_TEXT')
 # Supports CSV, tab separated, and Markdown tables pasted from free websites.
 lines=[s for s in lines if not re.match(r'^\\|?\\s*:?-{2,}',s)]
 if lines[0].startswith('|'):
  lines=[','.join(c.strip() for c in s.strip('|').split('|')) for s in lines]
 elif '\t' in lines[0]:
  lines=[s.replace('\t',',') for s in lines]
 reader=csv.DictReader(io.StringIO('\n'.join(lines)))
 if not reader.fieldnames:raise ValueError('MISSING_HEADER')
 headers={h:ALIASES.get(h.strip().lower()) for h in reader.fieldnames if h}
 if not {'date','pts','reb','ast'}<=set(headers.values()):raise ValueError('REQUIRED_COLUMNS_DATE_PTS_REB_AST')
 rows=[];seen=set()
 for raw in reader:
  r={canonical:(value or '').strip() for original,value in raw.items() if original in headers for canonical in [headers[original]] if canonical}
  if not all(r.get(k) for k in ('date','pts','reb','ast')):continue
  try:
   date=datetime.date.fromisoformat(r['date'][:10]).isoformat()
   vals={k:float(r[k]) for k in ('pts','reb','ast')}
   if any(v<0 or not v.is_integer() for v in vals.values()):continue
  except (ValueError,TypeError):continue
  if date in seen:raise ValueError('DUPLICATE_DATE_REQUIRES_REVIEW_'+date)
  seen.add(date)
  row={'date':date,'event_id':'PASTE_'+date,'opponent':r.get('opponent','').upper(),'source':'WEB_PASTE','source_url':source_url}
  row.update(vals)
  if r.get('min'):
   try:row['min']=float(r['min'])
   except ValueError:pass
  if season:row['season']=season
  rows.append(row)
 if not rows:raise ValueError('NO_VALID_GAME_ROWS')
 return sorted(rows,key=lambda r:r['date'])
