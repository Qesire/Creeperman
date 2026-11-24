"""Read-only streaming audit matching the supplied official calculator.

Requires normalized input sorted by Python string order. Fails closed if not.
Never writes to the source directory. Python 3.10+; no external packages.
"""
from pathlib import Path
from decimal import Decimal
from collections import Counter
import argparse, hashlib, importlib.util, json, sys, time
sys.dont_write_bytecode = True

def audit(root, out):
    out.mkdir(parents=True, exist_ok=True)
    calcpath = root / 'equivalent_english_domain_calculator/equivalent_english_domains.py'
    spec = importlib.util.spec_from_file_location('official', calcpath)
    calc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(calc)
    weights = calc.load_english_weights(calc.DEFAULT_MODEL)
    model = json.loads(calc.DEFAULT_MODEL.read_text(encoding='utf-8'))
    english_tlds = [str(t).lower() for t,l in zip(model['tld'],model['lang']) if t and l=='eng']
    result = {'baseline': 'merge261121-3', 'method': 'Official normalization and regex; streaming adjacent deduplication after full normalized order validation; EED Decimal aggregation', 'model_sha256': hashlib.sha256(calc.DEFAULT_MODEL.read_bytes()).hexdigest(), 'calculator_sha256': hashlib.sha256(calcpath.read_bytes()).hexdigest(), 'model_english_tld_count': len(weights), 'model_duplicate_english_tlds': {k:v for k,v in Counter(english_tlds).items() if v>1}, 'model_weights_outside_0_1': {k:str(v) for k,v in weights.items() if not 0<=v<=1}, 'years': []}
    for year in range(1996,2002):
        start = time.monotonic()
        path = root / 'merge261121-3' / f'{year}.txt'
        counts = Counter()
        sha = hashlib.sha256()
        previous = None
        lines = nonempty = duplicate = invalid = inversions = 0
        invalid_samples = []
        inversion_samples = []
        with path.open('rb') as f:
            for raw in f:
                sha.update(raw)
                lines += 1
                value = raw.decode('utf-8', errors='replace').strip().lower()
                if not value:
                    continue
                nonempty += 1
                if previous is not None and value < previous:
                    inversions += 1
                    if len(inversion_samples)<5:
                        inversion_samples.append({'line': lines, 'previous':previous, 'current':value})
                if value == previous:
                    duplicate += 1
                    continue
                previous = value
                if calc.HOST_RE.fullmatch(value):
                    counts[value.rsplit('.',1)[-1]] += 1
                else:
                    invalid += 1
                    if len(invalid_samples)<10: invalid_samples.append({'line':lines,'value':value})
        summary = {'year': year, 'bytes':path.stat().st_size, 'sha256':sha.hexdigest(), 'raw_lines': lines, 'nonempty_lines':nonempty, 'adjacent_duplicates':duplicate, 'normalized_order_inversions':inversions, 'inversion_samples':inversion_samples, 'seconds':round(time.monotonic()-start,2)}
        if inversions:
            summary['status'] = 'UNSORTED: unique totals unavailable; perform external sort before counting'
        else:
            total = sum((Decimal(n)*weights.get(t,Decimal(0)) for t,n in counts.items()),Decimal(0))
            unmatched = {t:n for t,n in sorted(counts.items()) if t not in weights}
            summary.update(status='OK', unique_nonempty_records=nonempty-duplicate, unique_valid_domains=sum(counts.values()), invalid_records=invalid, invalid_samples=invalid_samples, model_unmatched_valid_records=sum(unmatched.values()), unmatched_tlds=unmatched, equivalent_english_domains=str(total), minimum_1pct_increment=str(total*Decimal('.01')), preferred_2pct_increment=str(total*Decimal('.02')), tld_counts=dict(sorted(counts.items())))
        result['years'].append(summary)
        (out / 'baseline_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in summary.items() if k not in ('tld_counts', 'unmatched_tlds','invalid_samples','inversion_samples')},ensure_ascii=False),flush=True)
    if all(r['status']=='OK' for r in result['years']):
        total = sum((Decimal(r['equivalent_english_domains']) for r in result['years']),Decimal(0))
        result['core_total'] = {'unique_domain_year_records':sum(r['unique_nonempty_records'] for r in result['years']), 'valid_domain_year_records':sum(r['unique_valid_domains'] for r in result['years']), 'equivalent_english_domains':str(total), 'minimum_1pct_increment':str(total*Decimal('.01')), 'preferred_2pct_increment':str(total*Decimal('.02'))}
        (out / 'baseline_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result['core_total']),flush=True)

if __name__=='__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root',type=Path)
    parser.add_argument('output',type=Path)
    args=parser.parse_args()
    audit(args.root,args.output)
