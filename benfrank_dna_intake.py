"""Batch intake. Lines come from user input/OCR or a retained native response.

OCR is conservative: ambiguous cards are retained as rejected inputs, never
assigned a nearby player's line. No uploaded category is silently shortlisted.
"""
import csv
import io
import json
import math
import re
import subprocess
from pathlib import Path

from acquire_history import name_key, team_key
from benfrank_auto_context import schedule, capture_roles, PP_MARKETS, parse_projection_capture
from benfrank_auto_history import PP, now, instant, sha
from benfrank_dna_history import ALIASES, MARKETS


def ocr_screenshots(paths, player_names):
    results, rejected, sources = [], [], []
    market_pattern = r'(Fantasy\s*Score|Pts\s*\+\s*Rebs\s*\+\s*Asts|Pts\s*\+\s*Rebs|Pts\s*\+\s*Asts|Rebs\s*\+\s*Asts|Points|Rebounds|Assists|PRA)'
    for filename in paths:
        path = Path(filename)
        raw = path.read_bytes()
        from PIL import Image
        with Image.open(path) as photo:
            image_height=photo.height
        source = dict(file=path.name,sha256=__import__('hashlib').sha256(raw).hexdigest(),observed_at=now())
        sources.append(source)
        proc = subprocess.run(['tesseract',str(path),'stdout','--psm','11','tsv'],
                              text=True,capture_output=True,timeout=45,check=True)
        groups = {}
        for word in csv.DictReader(io.StringIO(proc.stdout),delimiter='\t'):
            if word.get('text','').strip():
                groups.setdefault((word['block_num'],word['par_num'],word['line_num']),[]).append(word)
        lines = []
        for words in groups.values():
            lines.append(dict(text=' '.join(w['text'] for w in words),left=min(int(w['left']) for w in words),
                top=min(int(w['top']) for w in words),right=max(int(w['left'])+int(w['width']) for w in words),
                bottom=max(int(w['top'])+int(w['height']) for w in words),
                confidence=min(float(w['conf']) for w in words),
                numeric_confidence=min((float(w['conf']) for w in words if re.fullmatch(r'\d+(?:\.\d+)?',w['text'])),default=None)))
        names = []
        for line in lines:
            matches = [n for n in player_names if name_key(line['text']) == name_key(n)]
            if len(matches) == 1:
                names.append(dict(line,player=matches[0]))
        for index, name in enumerate(names):
            # Assign a statistic only inside this card's horizontal band, below
            # this name and before the next name in the same column.
            same_column = [n['top'] for n in names if n['top']>name['top'] and
                           abs(n['left']-name['left'])<100]
            bottom = min(same_column) if same_column else image_height
            region = [l for l in lines if name['bottom']<=l['top']<bottom and
                      l['right']>=name['left']-20 and l['left']<=name['right']+80]
            matches=[]
            for line in region:
                m = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*'+market_pattern+r'\s*',line['text'],re.I)
                if m:
                    matches.append((m.group(1),m.group(2),line))
                else:
                    m = re.fullmatch(market_pattern,line['text'],re.I)
                    if m:
                        adjacent=[l for l in region if re.fullmatch(r'[_\s]*\d+(?:\.\d+)?',l['text']) and
                                  abs(l['top']-line['top'])<100 and abs(l['left']-line['left'])<120]
                        if len(adjacent)==1:
                            numeric=re.search(r'\d+(?:\.\d+)?',adjacent[0]['text']).group(0)
                            number_conf=adjacent[0]['numeric_confidence']
                            matches.append((numeric,m.group(1),dict(line,confidence=min(line['confidence'],number_conf if number_conf is not None else adjacent[0]['confidence']))))
            if len(matches)!=1 or min([name['confidence']]+[m[2]['confidence'] for m in matches])<60:
                rejected.append(dict(player=name['player'],source=source,reason='AMBIGUOUS_OR_LOW_CONFIDENCE_OCR_CARD',candidates=len(matches)))
                continue
            line, label, located = matches[0]
            market = next((v for k,v in PP_MARKETS.items() if name_key(k)==name_key(label)),None)
            market = market or ('pra' if label.upper()=='PRA' else None)
            if market not in MARKETS:
                rejected.append(dict(player=name['player'],source=source,reason='UNSUPPORTED_OCR_MARKET'));continue
            results.append(dict(player=name['player'],market=market,line=float(line),screenshot=source,
                ocr_confidence=min(name['confidence'],located['confidence']),
                line_authority='SCREENSHOT_OCR_LITERAL_LINE',source_url='UPLOADED_SCREENSHOT:'+path.name,
                screenshot_capture_time_verified=False))
        # Keep the full extraction so a missed/unknown name is visible to review.
        source['ocr_lines']=lines
        if not names:
            rejected.append(dict(source=source,reason='NO_UNAMBIGUOUS_ROSTER_PLAYER_NAMES_RECOGNIZED'))
    return dict(props=results,rejected=rejected,screenshots=sources)


def resolve_batch(store, config):
    day=config['game_date']; games=schedule(store,day)
    upcoming=[g for g in games if instant(g['tipoff_utc'])>instant(now()) and g['status'].get('state')=='pre']
    if not upcoming:raise ValueError('NO_VERIFIED_FUTURE_GAMES')
    if config['mode']=='native_category_test':
        # QA uses actual available native lines, never invented test thresholds.
        raw,meta=store.fetch(PP,'PRIZEPICKS_NATIVE_PUBLIC')
        board,audit=parse_projection_capture(raw,meta,games,max_props=10000,max_games=30,
            all_requested=True, schedule_tolerance_seconds=900)
        board=[p for p in board if p['player']==config['test_player'] and p['market'] in MARKETS]
        # Reject ambiguous multiple native offers within the same market.
        counts={m:sum(p['market']==m for p in board) for m in MARKETS}
        board=[p for p in board if counts[p['market']]==1]
        if not board:raise ValueError('NO_NATIVE_STANDARD_EIGHT_CATEGORY_TEST_PLAYER_LINES')
        sources=capture_roles(store,sorted({p[k] for p in board for k in ('team','opponent')}),day)
        if config.get('screenshots'):
            extra,extra_audit,_=resolve_batch(store,dict(config,mode='uploaded_props',props=[],
                teams=sorted({p[k] for p in board for k in ('team','opponent')})))
            board.extend(extra)
            audit['screenshot_extraction']=extra_audit['screenshot_extraction']
            audit['rejected']=extra_audit['rejected']
        return board,dict(audit,selected=len(board),source_route='LIVE_NATIVE_EIGHT_CATEGORY_QA',rejected=audit.get('rejected',[])),sources
    supplied=config.get('props',[])
    hints={team_key(p[k]) for p in supplied for k in ('team','opponent') if p.get(k)}
    hints.update(team_key(t) for t in config.get('teams',[]))
    if not hints and config.get('screenshots'):
        # Team abbreviations narrow acquisition only. Player/opponent identity
        # still has to match the actual future schedule and sourced depth.
        codes={g[k] for g in upcoming for k in ('home','away')}
        for path in config['screenshots']:
            proc=subprocess.run(['tesseract',str(path),'stdout','--psm','11'],text=True,capture_output=True,timeout=45,check=True)
            tokens=set(re.findall(r'\b[A-Z]{2,4}\b',proc.stdout))
            hints.update(codes & tokens)
    lookup=[g for g in upcoming if not hints or bool(hints & {g['home'],g['away']})]
    teams=sorted({g[k] for g in lookup for k in ('home','away')})
    sources,injury,identities=capture_roles(store,teams,day)
    extraction = ocr_screenshots(config.get('screenshots',[]),list(identities.values())) if config.get('screenshots') else None
    if extraction:supplied=[*supplied,*extraction['props']]
    board=[];rejected=list(extraction['rejected']) if extraction else []
    captured=now()
    for index,p in enumerate(supplied):
        try:
            p=dict(p);market=ALIASES.get(p.get('market'),p.get('market')); line=p.get('line')
            if market not in MARKETS or type(line) not in (int,float) or not math.isfinite(line) or not 0<=line<=10000:
                raise ValueError('UNSUPPORTED_MARKET_OR_NONFINITE_EXACT_LINE')
            matches=[]
            for g in upcoming:
                for team,opponent in ((g['home'],g['away']),(g['away'],g['home'])):
                    if p.get('team') and team_key(p['team'])!=team:continue
                    if p.get('opponent') and team_key(p['opponent'])!=opponent:continue
                    for item in sources['depths'].get(team,{}).get('players',{}).values():
                        if name_key(item['player'])==name_key(p.get('player','')):matches.append((g,team,opponent,item))
            if len(matches)!=1:raise ValueError('NO_UNIQUE_PLAYER_GAME_OPPONENT_FROM_CURRENT_ROSTER:'+str(len(matches)))
            game,team,opponent,item=matches[0]
            board.append(dict(p,player=item['player'],market=market,line=line,team=team,opponent=opponent,
                espn_player_id=item['id'],game_date=day,game_id=game['game_id'],tipoff_utc=game['tipoff_utc'],
                espn_event_id=game['espn_event_id'],platform='PrizePicks' if p.get('screenshot') else 'USER_SUPPLIED',
                line_authority=p.get('line_authority','EXACT_USER_LINE_NOT_NATIVE_RECHECKED'),
                source_url=p.get('source_url','USER_UPLOADED_PROP_MANIFEST'),source_sha256=sha(p),
                line_capture_utc=captured,native_platform_line_capture_utc=None,
                snapshot_id='batch_'+sha([p,index,captured])[:24]))
        except Exception as error:
            rejected.append(dict(input=p,index=index,status='BLOCKED',timestamp=now(),exact_blocker=str(error)))
    return board,dict(games=games,selected=len(board),submitted=len(supplied),rejected=rejected,
                      screenshot_extraction=extraction,source_route='ALL_UPLOADED_PROPS_NO_SHORTLIST'),(sources,injury,identities)
