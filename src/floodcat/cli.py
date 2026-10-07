import argparse
import json
from pathlib import Path
from .core.config import load_config
from .core.errors import ModelError
from .exposure.loaders import read_csv
from .services.analysis import analyse
from .ai.model import HotspotModel
from .ai.training import train
from .hazard.raster import RasterHazard

def main():
    parser=argparse.ArgumentParser(description='Nairobi flood CAT backend')
    commands=parser.add_subparsers(dest='command',required=True)
    run=commands.add_parser('analyse');run.add_argument('csv');run.add_argument('--output',default='runtime/report.json')
    run.add_argument('--config');run.add_argument('--model');run.add_argument('--rasters');run.add_argument('--allow-partial',action='store_true')
    fit=commands.add_parser('train');fit.add_argument('csv');fit.add_argument('--output',required=True);fit.add_argument('--provenance',required=True)
    serve=commands.add_parser('serve');serve.add_argument('--port',type=int,default=8000)
    args=parser.parse_args()
    try:
        if args.command=='serve':
            import uvicorn
            uvicorn.run('floodcat.api.app:create_app',factory=True,host='127.0.0.1',port=args.port)
        elif args.command=='train':
            result=train(args.csv,args.output,args.provenance);print(json.dumps(result['evaluation'],indent=2))
        else:
            rows=read_csv(args.csv);config=load_config(args.config)
            model=HotspotModel.load(args.model) if args.model else None
            if args.rasters:
                with RasterHazard(args.rasters) as provider: result=analyse(rows,config,provider,model,allow_partial=args.allow_partial)
            else: result=analyse(rows,config,model=model,allow_partial=args.allow_partial)
            Path(args.output).parent.mkdir(parents=True,exist_ok=True)
            Path(args.output).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
            print(f"Saved {args.output}: {result['modelled_count']} properties, KES {result['modelled_tiv_kes']} modelled TIV")
    except (ModelError,OSError,ValueError) as exc:
        parser.exit(2,f'{getattr(exc,"code","input_error")}: {exc}\n')
if __name__=='__main__': main()
