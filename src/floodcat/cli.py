import argparse
import json
from pathlib import Path
from .core.config import load_config
from .core.errors import ModelError, ReviewRequired
from .exposure.loaders import read_csv
from .exposure.validation import summarise_issues
from .services.analysis import analyse
from .hazard.raster import RasterHazard
from .hazard.hotspots import load_hotspots
from .services.data_audit import audit_data
from .services.sensitivity import assumption_sensitivity

def main():
    parser=argparse.ArgumentParser(description='Nairobi flood CAT backend')
    commands=parser.add_subparsers(dest='command',required=True)
    run=commands.add_parser('analyse');run.add_argument('csv');run.add_argument('--output',default='runtime/report.json')
    run.add_argument('--config');run.add_argument('--rasters');run.add_argument('--allow-partial',action='store_true')
    run.add_argument('--hotspots',help='Tag each property with its nearest named hotspot')
    serve=commands.add_parser('serve');serve.add_argument('--port',type=int,default=8000)
    audit=commands.add_parser('audit-data');audit.add_argument('directory',nargs='?',default='data');audit.add_argument('--output')
    sensitivity=commands.add_parser('sensitivity');sensitivity.add_argument('csv');sensitivity.add_argument('--output',default='runtime/sensitivity.json')
    sensitivity.add_argument('--rasters')
    imported=commands.add_parser('import-data');imported.add_argument('--exposure',default='data/exposure_nairobi_with_hazard.csv');imported.add_argument('--hotspots',default='data/nairobi_hotspots_geocoded.csv')
    args=parser.parse_args()
    try:
        if args.command=='serve':
            import uvicorn
            uvicorn.run('floodcat.api.app:create_app',factory=True,host='127.0.0.1',port=args.port)
        elif args.command=='audit-data':
            result=audit_data(args.directory)
            serialized=json.dumps(result,indent=2)+'\n'
            if args.output:
                Path(args.output).parent.mkdir(parents=True,exist_ok=True)
                Path(args.output).write_text(serialized)
            print(serialized,end='')
        elif args.command=='sensitivity':
            provider=RasterHazard(args.rasters).load() if args.rasters else None
            result=assumption_sensitivity(read_csv(args.csv),provider=provider)
            Path(args.output).parent.mkdir(parents=True,exist_ok=True)
            Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
            print(f'Saved {args.output}')
        elif args.command=='import-data':
            from .storage.repository import Repository
            result=Repository().import_starter_data(args.exposure,args.hotspots)
            print(json.dumps(result,indent=2))
        else:
            rows=read_csv(args.csv);config=load_config(args.config)
            hotspots=load_hotspots(args.hotspots) if args.hotspots else ()
            provider=RasterHazard(args.rasters).load() if args.rasters else None
            result=analyse(rows,config,provider,allow_partial=args.allow_partial,hotspots=hotspots)
            Path(args.output).parent.mkdir(parents=True,exist_ok=True)
            Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
            print(f"Saved {args.output}: {result['modelled_count']} properties, KES {result['modelled_tiv_kes']} modelled TIV")
    except ReviewRequired as exc:
        lines=[f"  {g['severity']}: {g['code']} ×{g['count']} — {g['example']}" for g in summarise_issues(exc.issues)]
        parser.exit(2,f'{exc}\n'+'\n'.join(lines)+'\nRe-run with --allow-partial to model the valid records only.\n')
    except (ModelError,OSError,ValueError) as exc:
        parser.exit(2,f'{getattr(exc,"code","input_error")}: {exc}\n')
if __name__=='__main__': main()
