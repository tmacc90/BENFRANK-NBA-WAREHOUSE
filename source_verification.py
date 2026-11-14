"""Cross-source verification; no mismatched game is silently accepted."""
def compare(primary,secondary):
 a={(r['date'],r.get('opponent','').upper()):r for r in primary}
 b={(r['date'],r.get('opponent','').upper()):r for r in secondary}
 checked=0;disagreements=[];missing=[]
 for key,row in a.items():
  other=b.get(key)
  if other is None:
   missing.append({'date':key[0],'opponent':key[1]});continue
  checked+=1
  for field in ('pts','reb','ast'):
   if row[field]!=other[field]:
    disagreements.append({'date':key[0],'opponent':key[1],'stat':field,'primary':row[field],'secondary':other[field]})
 return {'status':'MATCHED' if checked and not disagreements and not missing else 'PARTIAL_OR_CONFLICT','matched_games':checked,'primary_games':len(a),'secondary_games':len(b),'missing_in_secondary':missing,'disagreements':disagreements}
